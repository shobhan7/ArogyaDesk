from datetime import datetime, timedelta, timezone

from sqlalchemy import event, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.cache import SlotCache
from app.config import Settings
from app.domain import (
    AppointmentStatus,
    QueueStatus,
    Role,
    SlotStatus,
    clinic_now,
    combine_slot,
)
from app.errors import bad_request, conflict, forbidden, not_found
from app.models import (
    Appointment,
    AppointmentSlot,
    Doctor,
    Patient,
    QueueToken,
    UserAccount,
)
from app.outbox import enqueue
from app.schemas import AppointmentOut
from app.services.catalog import write_audit


class AppointmentService:
    def __init__(self, db: Session, cache: SlotCache, settings: Settings):
        self.db = db
        self.cache = cache
        self.settings = settings

    def book(self, actor: UserAccount, slot_id: int, patient_id: int) -> AppointmentOut:
        patient = self.db.get(Patient, patient_id)
        if not patient:
            raise not_found("Patient not found")
        self._assert_can_book(actor, patient)
        slot = self.db.get(AppointmentSlot, slot_id)
        if not slot:
            raise not_found("Slot not found")
        if combine_slot(slot.slot_date, slot.start_time) <= clinic_now():
            raise conflict("This slot has already started")

        claimed = self.db.execute(
            update(AppointmentSlot)
            .where(
                AppointmentSlot.id == slot_id,
                AppointmentSlot.status == SlotStatus.OPEN,
            )
            .values(status=SlotStatus.BOOKED, version=AppointmentSlot.version + 1)
        )
        if claimed.rowcount != 1:
            raise conflict("Slot is not open")
        self.db.expire_all()
        slot = self.db.get(AppointmentSlot, slot_id)

        duplicate = self.db.scalar(
            select(Appointment.id).where(
                Appointment.patient_id == patient.id,
                Appointment.doctor_id == slot.doctor_id,
                Appointment.status.in_(AppointmentStatus.ACTIVE),
                Appointment.slot_id.in_(
                    select(AppointmentSlot.id).where(
                        AppointmentSlot.slot_date == slot.slot_date,
                        AppointmentSlot.doctor_id == slot.doctor_id,
                    )
                ),
            )
        )
        if duplicate:
            raise conflict("This patient already has an active appointment with the doctor on that day")

        token_number = self._next_token(slot.doctor_id, slot.slot_date)
        appointment = Appointment(
            slot_id=slot.id,
            patient_id=patient.id,
            doctor_id=slot.doctor_id,
            status=AppointmentStatus.BOOKED,
            token_number=token_number,
            booked_at=datetime.now(timezone.utc),
            cancel_reason=None,
            day_guard=f"{patient.id}:{slot.doctor_id}:{slot.slot_date.isoformat()}",
        )
        self.db.add(appointment)
        try:
            self.db.flush()
        except IntegrityError:
            raise conflict(
                "This patient already has an active appointment with the doctor on that day"
            ) from None
        self.db.add(
            QueueToken(
                appointment_id=appointment.id,
                doctor_id=slot.doctor_id,
                queue_date=slot.slot_date,
                token_number=token_number,
                status=QueueStatus.WAITING,
            )
        )
        doctor = self.db.get(Doctor, slot.doctor_id)
        enqueue(
            self.db,
            "appointment",
            appointment.id,
            "AppointmentBooked",
            {
                "appointmentId": appointment.id,
                "slotId": slot.id,
                "doctorId": slot.doctor_id,
                "patientId": patient.id,
                "tokenNumber": token_number,
                "slotDate": slot.slot_date.isoformat(),
            },
        )
        write_audit(
            self.db,
            actor.id,
            "APPOINTMENT_BOOKED",
            "appointment",
            appointment.id,
            f"token {token_number}",
        )
        self._evict_after_commit(slot.doctor_id, slot.slot_date)
        return self._view(appointment, slot, doctor.user.full_name)

    def cancel(self, actor: UserAccount, appointment_id: int, reason: str) -> AppointmentOut:
        appointment = self._require(appointment_id)
        slot = appointment.slot
        self._assert_can_cancel(actor, appointment, slot)
        if appointment.status not in (AppointmentStatus.BOOKED, AppointmentStatus.CHECKED_IN):
            raise conflict("This appointment can no longer be cancelled")
        appointment.status = AppointmentStatus.CANCELLED
        appointment.cancel_reason = reason.strip()
        appointment.day_guard = None
        token = self._token_for(appointment.id)
        token.status = QueueStatus.SKIPPED
        self._release_slot(slot)
        enqueue(
            self.db,
            "appointment",
            appointment.id,
            "AppointmentCancelled",
            {"appointmentId": appointment.id, "slotId": slot.id, "reason": appointment.cancel_reason},
        )
        write_audit(self.db, actor.id, "APPOINTMENT_CANCELLED", "appointment", appointment.id, reason)
        self.db.flush()
        return self._view(appointment, slot, appointment.doctor.user.full_name)

    def check_in(self, actor: UserAccount, appointment_id: int) -> AppointmentOut:
        if actor.role not in (Role.RECEPTIONIST, Role.ADMIN):
            raise forbidden("Only reception or an admin can check a patient in")
        appointment = self._require(appointment_id)
        if appointment.status != AppointmentStatus.BOOKED:
            raise conflict("Only a booked appointment can be checked in")
        appointment.status = AppointmentStatus.CHECKED_IN
        write_audit(self.db, actor.id, "PATIENT_CHECKED_IN", "appointment", appointment.id, "")
        self.db.flush()
        return self._view(appointment, appointment.slot, appointment.doctor.user.full_name)

    def mark_no_show(self, actor: UserAccount, appointment_id: int) -> AppointmentOut:
        if actor.role not in (Role.RECEPTIONIST, Role.ADMIN):
            raise forbidden("Only reception or an admin can mark a no-show")
        appointment = self._require(appointment_id)
        if appointment.status not in (AppointmentStatus.BOOKED, AppointmentStatus.CHECKED_IN):
            raise conflict("This appointment cannot be marked as a no-show")
        appointment.status = AppointmentStatus.NO_SHOW
        appointment.day_guard = None
        token = self._token_for(appointment.id)
        token.status = QueueStatus.SKIPPED
        self._release_slot(appointment.slot)
        enqueue(
            self.db,
            "appointment",
            appointment.id,
            "AppointmentNoShow",
            {"appointmentId": appointment.id},
        )
        write_audit(self.db, actor.id, "NO_SHOW", "appointment", appointment.id, "")
        self.db.flush()
        return self._view(appointment, appointment.slot, appointment.doctor.user.full_name)

    def get(self, actor: UserAccount, appointment_id: int) -> AppointmentOut:
        appointment = self._require(appointment_id)
        self._assert_can_view(actor, appointment)
        return self._view(appointment, appointment.slot, appointment.doctor.user.full_name)

    def list_for_patient(self, actor: UserAccount, patient_id: int) -> list[AppointmentOut]:
        patient = self.db.get(Patient, patient_id)
        if not patient:
            raise not_found("Patient not found")
        if actor.role == Role.PATIENT and patient.user_id != actor.id:
            raise forbidden("Patients can view only their own appointments")
        if actor.role == Role.DOCTOR:
            raise forbidden("Use the doctor queue to see today's patients")
        rows = self.db.scalars(
            select(Appointment)
            .where(Appointment.patient_id == patient_id)
            .order_by(Appointment.booked_at.desc())
        ).all()
        return [self._view(row, row.slot, row.doctor.user.full_name) for row in rows]

    def _release_slot(self, slot: AppointmentSlot) -> None:
        if combine_slot(slot.slot_date, slot.start_time) > clinic_now():
            slot.status = SlotStatus.OPEN
        else:
            slot.status = SlotStatus.BLOCKED
        slot.version += 1
        self._evict_after_commit(slot.doctor_id, slot.slot_date)

    def _next_token(self, doctor_id: int, day) -> int:
        current = self.db.scalar(
            select(func.max(QueueToken.token_number)).where(
                QueueToken.doctor_id == doctor_id,
                QueueToken.queue_date == day,
            )
        )
        return int(current or 0) + 1

    def _assert_can_book(self, actor: UserAccount, patient: Patient) -> None:
        if actor.role == Role.PATIENT:
            if patient.user_id != actor.id:
                raise forbidden("Patients can book only for themselves")
            return
        if actor.role not in (Role.RECEPTIONIST, Role.ADMIN):
            raise forbidden("Only a patient, reception, or an admin can book")

    def _assert_can_cancel(self, actor: UserAccount, appointment: Appointment, slot: AppointmentSlot) -> None:
        if actor.role == Role.PATIENT:
            if appointment.patient.user_id != actor.id:
                raise forbidden("Patients can cancel only their own appointments")
            if appointment.status != AppointmentStatus.BOOKED:
                raise conflict("Reception must handle this appointment")
            cutoff = combine_slot(slot.slot_date, slot.start_time) - timedelta(
                hours=self.settings.cancel_cutoff_hours
            )
            if clinic_now() > cutoff:
                raise conflict("The cancellation window for this slot has closed")
            return
        if actor.role not in (Role.RECEPTIONIST, Role.ADMIN):
            raise forbidden("You cannot cancel this appointment")

    def _assert_can_view(self, actor: UserAccount, appointment: Appointment) -> None:
        if actor.role in (Role.ADMIN, Role.RECEPTIONIST):
            return
        if actor.role == Role.PATIENT and appointment.patient.user_id == actor.id:
            return
        if actor.role == Role.DOCTOR and appointment.doctor.user_id == actor.id:
            return
        raise forbidden("You cannot view this appointment")

    def _require(self, appointment_id: int) -> Appointment:
        appointment = self.db.get(Appointment, appointment_id)
        if not appointment:
            raise not_found("Appointment not found")
        return appointment

    def _token_for(self, appointment_id: int) -> QueueToken:
        token = self.db.scalar(
            select(QueueToken).where(QueueToken.appointment_id == appointment_id)
        )
        if not token:
            raise not_found("Queue token not found")
        return token

    def _evict_after_commit(self, doctor_id: int, day) -> None:
        cache = self.cache

        def _clear(_session) -> None:
            cache.evict(doctor_id, day)

        event.listen(self.db, "after_commit", _clear, once=True)

    @staticmethod
    def _view(appointment: Appointment, slot: AppointmentSlot, doctor_name: str) -> AppointmentOut:
        return AppointmentOut(
            id=appointment.id,
            slot_id=slot.id,
            patient_id=appointment.patient_id,
            doctor_id=appointment.doctor_id,
            doctor_name=doctor_name,
            slot_date=slot.slot_date,
            start_time=slot.start_time,
            end_time=slot.end_time,
            status=appointment.status,
            token_number=appointment.token_number,
            booked_at=appointment.booked_at,
            cancel_reason=appointment.cancel_reason,
        )
