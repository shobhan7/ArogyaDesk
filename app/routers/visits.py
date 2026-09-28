from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db, require
from app.domain import Role
from app.errors import forbidden, not_found
from app.models import Patient, UserAccount
from app.schemas import (
    AppointmentOut,
    AuditOut,
    BookIn,
    CacheStatsOut,
    CancelIn,
    EncounterIn,
    EncounterOut,
    InvoiceOut,
    PaymentIn,
    QueueEntryOut,
)
from app.services.appointments import AppointmentService
from app.services.clinical import BillingService, EncounterService, QueueService
from app.models import AuditEntry

router = APIRouter(prefix="/api/v1", tags=["Visits"])


def _appointments(request: Request, db: Session) -> AppointmentService:
    return AppointmentService(db, request.app.state.cache, request.app.state.settings)


@router.get("/patients/me")
def my_patient(user: UserAccount = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != Role.PATIENT:
        raise forbidden("Only a patient account has a patient profile")
    patient = db.scalar(select(Patient).where(Patient.user_id == user.id))
    if not patient:
        raise not_found("Patient profile not found")
    return {"patientId": patient.id, "fullName": user.full_name}


@router.post("/appointments", response_model=AppointmentOut, status_code=201)
def book(
    body: BookIn,
    request: Request,
    user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _appointments(request, db).book(user, body.slot_id, body.patient_id)


@router.post("/appointments/{appointment_id}/cancel", response_model=AppointmentOut)
def cancel(
    appointment_id: int,
    body: CancelIn,
    request: Request,
    user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _appointments(request, db).cancel(user, appointment_id, body.reason)


@router.post("/appointments/{appointment_id}/check-in", response_model=AppointmentOut)
def check_in(
    appointment_id: int,
    request: Request,
    user: UserAccount = Depends(require(Role.RECEPTIONIST, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    return _appointments(request, db).check_in(user, appointment_id)


@router.post("/appointments/{appointment_id}/no-show", response_model=AppointmentOut)
def no_show(
    appointment_id: int,
    request: Request,
    user: UserAccount = Depends(require(Role.RECEPTIONIST, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    return _appointments(request, db).mark_no_show(user, appointment_id)


@router.get("/appointments/{appointment_id}", response_model=AppointmentOut)
def get_appointment(
    appointment_id: int,
    request: Request,
    user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _appointments(request, db).get(user, appointment_id)


@router.get("/patients/{patient_id}/appointments", response_model=list[AppointmentOut])
def list_appointments(
    patient_id: int,
    request: Request,
    user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _appointments(request, db).list_for_patient(user, patient_id)


@router.get("/doctors/{doctor_id}/queue", response_model=list[QueueEntryOut])
def queue(
    doctor_id: int,
    day: date,
    user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return QueueService(db).list_queue(user, doctor_id, day)


@router.post("/doctors/{doctor_id}/queue/next", response_model=QueueEntryOut)
def call_next(
    doctor_id: int,
    day: date,
    user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return QueueService(db).call_next(user, doctor_id, day)


@router.post("/appointments/{appointment_id}/encounter", response_model=EncounterOut, status_code=201)
def complete_encounter(
    appointment_id: int,
    body: EncounterIn,
    user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return EncounterService(db).complete(user, appointment_id, body)


@router.get("/appointments/{appointment_id}/invoice", response_model=InvoiceOut)
def get_invoice(
    appointment_id: int,
    user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return BillingService(db).get_for_appointment(user, appointment_id)


@router.post("/invoices/{invoice_id}/payments", response_model=InvoiceOut, status_code=201)
def pay(
    invoice_id: int,
    body: PaymentIn,
    user: UserAccount = Depends(require(Role.RECEPTIONIST, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    return BillingService(db).pay(user, invoice_id, body)


@router.get("/admin/cache-stats", response_model=CacheStatsOut)
def cache_stats(
    request: Request,
    _: UserAccount = Depends(require(Role.ADMIN)),
):
    return request.app.state.cache.stats()


@router.get("/admin/audit", response_model=list[AuditOut])
def audit(
    _: UserAccount = Depends(require(Role.ADMIN)),
    db: Session = Depends(get_db),
    limit: int = 20,
):
    safe_limit = min(max(limit, 1), 100)
    rows = db.scalars(select(AuditEntry).order_by(AuditEntry.id.desc()).limit(safe_limit)).all()
    return [
        AuditOut(
            id=row.id,
            actor_id=row.actor_id,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            detail=row.detail,
            created_at=row.created_at,
        )
        for row in rows
    ]
