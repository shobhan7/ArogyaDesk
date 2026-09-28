from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import AppointmentStatus, InvoiceStatus, PaymentMethod, QueueStatus, Role, clinic_now
from app.errors import bad_request, conflict, forbidden, not_found
from app.models import (
    Appointment,
    Doctor,
    Encounter,
    Invoice,
    Patient,
    Payment,
    PrescriptionItem,
    QueueToken,
    UserAccount,
)
from app.outbox import enqueue
from app.schemas import (
    EncounterIn,
    EncounterOut,
    InvoiceOut,
    PaymentIn,
    PaymentOut,
    PrescriptionOut,
    QueueEntryOut,
)
from app.services.catalog import write_audit


class QueueService:
    def __init__(self, db: Session):
        self.db = db

    def list_queue(self, actor: UserAccount, doctor_id: int, day: date) -> list[QueueEntryOut]:
        doctor = self._doctor(doctor_id)
        if actor.role == Role.DOCTOR and doctor.user_id != actor.id:
            raise forbidden("Doctors can view only their own queue")
        if actor.role == Role.PATIENT:
            raise forbidden("Patients cannot view the clinic queue")
        rows = self.db.scalars(
            select(QueueToken)
            .where(QueueToken.doctor_id == doctor_id, QueueToken.queue_date == day)
            .order_by(QueueToken.token_number)
        ).all()
        result = []
        for token in rows:
            appointment = token.appointment
            result.append(
                QueueEntryOut(
                    token_number=token.token_number,
                    token_status=token.status,
                    appointment_id=appointment.id,
                    appointment_status=appointment.status,
                    patient_id=appointment.patient_id,
                    patient_name=appointment.patient.user.full_name,
                )
            )
        return result

    def call_next(self, actor: UserAccount, doctor_id: int, day: date) -> QueueEntryOut:
        doctor = self._doctor(doctor_id)
        if actor.role != Role.DOCTOR or doctor.user_id != actor.id:
            raise forbidden("Only the assigned doctor can call the next patient")
        tokens = self.db.scalars(
            select(QueueToken)
            .where(
                QueueToken.doctor_id == doctor_id,
                QueueToken.queue_date == day,
                QueueToken.status == QueueStatus.WAITING,
            )
            .order_by(QueueToken.token_number)
        ).all()
        chosen = None
        for token in tokens:
            if token.appointment.status == AppointmentStatus.CHECKED_IN:
                chosen = token
                break
        if not chosen:
            raise not_found("No checked-in patient is waiting")
        chosen.status = QueueStatus.CALLED
        chosen.appointment.status = AppointmentStatus.IN_CONSULT
        write_audit(self.db, actor.id, "PATIENT_CALLED", "appointment", chosen.appointment_id, f"token {chosen.token_number}")
        self.db.flush()
        appointment = chosen.appointment
        return QueueEntryOut(
            token_number=chosen.token_number,
            token_status=chosen.status,
            appointment_id=appointment.id,
            appointment_status=appointment.status,
            patient_id=appointment.patient_id,
            patient_name=appointment.patient.user.full_name,
        )

    def _doctor(self, doctor_id: int) -> Doctor:
        doctor = self.db.get(Doctor, doctor_id)
        if not doctor or not doctor.active:
            raise not_found("Doctor not found")
        return doctor


class EncounterService:
    def __init__(self, db: Session):
        self.db = db

    def complete(self, actor: UserAccount, appointment_id: int, body: EncounterIn) -> EncounterOut:
        appointment = self.db.get(Appointment, appointment_id)
        if not appointment:
            raise not_found("Appointment not found")
        if actor.role != Role.DOCTOR or appointment.doctor.user_id != actor.id:
            raise forbidden("Only the consulting doctor can close this visit")
        if appointment.status != AppointmentStatus.IN_CONSULT:
            raise conflict("The patient must be in consultation before notes are saved")
        now = datetime.now(timezone.utc)
        encounter = Encounter(
            appointment_id=appointment.id,
            doctor_id=appointment.doctor_id,
            patient_id=appointment.patient_id,
            clinical_notes=body.clinical_notes.strip(),
            created_at=now,
        )
        self.db.add(encounter)
        self.db.flush()
        items = []
        for item in body.items:
            row = PrescriptionItem(
                encounter_id=encounter.id,
                medicine_name=item.medicine_name.strip(),
                dosage=item.dosage.strip(),
                duration_days=item.duration_days,
                instructions=item.instructions,
            )
            self.db.add(row)
            items.append(row)
        self.db.flush()
        invoice = Invoice(
            appointment_id=appointment.id,
            patient_id=appointment.patient_id,
            amount_paise=appointment.doctor.consultation_fee_paise,
            status=InvoiceStatus.DUE,
            issued_at=now,
        )
        self.db.add(invoice)
        token = self.db.scalar(select(QueueToken).where(QueueToken.appointment_id == appointment.id))
        if token:
            token.status = QueueStatus.DONE
        appointment.status = AppointmentStatus.COMPLETED
        appointment.day_guard = None
        enqueue(
            self.db,
            "encounter",
            encounter.id,
            "EncounterCompleted",
            {"appointmentId": appointment.id, "encounterId": encounter.id, "invoicePaise": invoice.amount_paise},
        )
        write_audit(self.db, actor.id, "ENCOUNTER_COMPLETED", "encounter", encounter.id, "")
        self.db.flush()
        return EncounterOut(
            id=encounter.id,
            appointment_id=encounter.appointment_id,
            doctor_id=encounter.doctor_id,
            patient_id=encounter.patient_id,
            clinical_notes=encounter.clinical_notes,
            created_at=encounter.created_at,
            items=[
                PrescriptionOut(
                    id=row.id,
                    medicine_name=row.medicine_name,
                    dosage=row.dosage,
                    duration_days=row.duration_days,
                    instructions=row.instructions,
                )
                for row in items
            ],
        )


class BillingService:
    def __init__(self, db: Session):
        self.db = db

    def get_for_appointment(self, actor: UserAccount, appointment_id: int) -> InvoiceOut:
        invoice = self.db.scalar(select(Invoice).where(Invoice.appointment_id == appointment_id))
        if not invoice:
            raise not_found("Invoice not found")
        self._assert_can_view(actor, invoice)
        return self._view(invoice)

    def pay(self, actor: UserAccount, invoice_id: int, body: PaymentIn) -> InvoiceOut:
        if actor.role not in (Role.RECEPTIONIST, Role.ADMIN):
            raise forbidden("Only reception or an admin can record a payment")
        if body.method not in PaymentMethod.ALL:
            raise bad_request("Payment method must be CASH, UPI, or CARD")
        invoice = self.db.get(Invoice, invoice_id)
        if not invoice:
            raise not_found("Invoice not found")
        if invoice.status != InvoiceStatus.DUE:
            raise conflict("This invoice is not awaiting payment")
        paid = sum(payment.amount_paise for payment in invoice.payments)
        remaining = invoice.amount_paise - paid
        if body.amount_paise > remaining:
            raise bad_request("Payment is larger than the remaining balance")
        self.db.add(
            Payment(
                invoice_id=invoice.id,
                amount_paise=body.amount_paise,
                method=body.method,
                reference_code=body.reference_code,
                paid_at=datetime.now(timezone.utc),
            )
        )
        self.db.flush()
        self.db.refresh(invoice)
        if sum(payment.amount_paise for payment in invoice.payments) >= invoice.amount_paise:
            invoice.status = InvoiceStatus.PAID
        enqueue(
            self.db,
            "invoice",
            invoice.id,
            "PaymentRecorded",
            {"invoiceId": invoice.id, "amountPaise": body.amount_paise, "status": invoice.status},
        )
        write_audit(self.db, actor.id, "PAYMENT_RECORDED", "invoice", invoice.id, body.method)
        self.db.flush()
        return self._view(invoice)

    def _assert_can_view(self, actor: UserAccount, invoice: Invoice) -> None:
        if actor.role in (Role.ADMIN, Role.RECEPTIONIST):
            return
        patient = self.db.get(Patient, invoice.patient_id)
        if actor.role == Role.PATIENT and patient and patient.user_id == actor.id:
            return
        raise forbidden("You cannot view this invoice")

    @staticmethod
    def _view(invoice: Invoice) -> InvoiceOut:
        payments = [
            PaymentOut(
                id=payment.id,
                amount_paise=payment.amount_paise,
                method=payment.method,
                reference_code=payment.reference_code,
                paid_at=payment.paid_at,
            )
            for payment in invoice.payments
        ]
        paid = sum(payment.amount_paise for payment in payments)
        return InvoiceOut(
            id=invoice.id,
            appointment_id=invoice.appointment_id,
            patient_id=invoice.patient_id,
            amount_paise=invoice.amount_paise,
            paid_paise=paid,
            remaining_paise=max(invoice.amount_paise - paid, 0),
            status=invoice.status,
            issued_at=invoice.issued_at,
            payments=payments,
        )
