"""Idempotent local demo data. Never used when SEED is false."""

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.domain import Role, clinic_now
from app.models import Clinic, Department, Doctor, Patient, UserAccount, WeeklySchedule
from app.security import hash_password
from app.services.slots import SlotService
from app.cache import InMemorySlotCache


DEMO_PASSWORD = {
    "admin@arogyadesk.local": "Admin@12345",
    "reception@arogyadesk.local": "Reception@12345",
    "doctor@arogyadesk.local": "Doctor@12345",
    "patient@arogyadesk.local": "Patient@12345",
}


def seed_demo(db: Session, settings: Settings) -> None:
    if db.scalar(select(Clinic).where(Clinic.name == "CityCare OPD")):
        return
    now = datetime.now(timezone.utc)
    admin = _user(db, settings, "admin@arogyadesk.local", "Arogya Admin", Role.ADMIN, now)
    reception = _user(
        db, settings, "reception@arogyadesk.local", "Lakshmi Reception", Role.RECEPTIONIST, now
    )
    doctor_user = _user(
        db, settings, "doctor@arogyadesk.local", "Dr. Meera Iyer", Role.DOCTOR, now
    )
    patient_user = _user(
        db, settings, "patient@arogyadesk.local", "Asha Rao", Role.PATIENT, now
    )
    db.flush()
    clinic = Clinic(
        name="CityCare OPD",
        city="Hyderabad",
        address="12 Lake View Road, Madhapur, Hyderabad",
        phone="04040001234",
        created_at=now,
    )
    db.add(clinic)
    db.flush()
    general = Department(clinic_id=clinic.id, name="General Medicine", code="GM")
    db.add(general)
    db.add(Department(clinic_id=clinic.id, name="Paediatrics", code="PED"))
    db.flush()
    doctor = Doctor(
        user_id=doctor_user.id,
        department_id=general.id,
        registration_number="MCI-TS-20481",
        consultation_fee_paise=50000,
        active=True,
    )
    db.add(doctor)
    db.add(Patient(user_id=patient_user.id, gender="FEMALE"))
    db.flush()
    for day in range(1, 7):
        db.add(
            WeeklySchedule(
                doctor_id=doctor.id,
                day_of_week=day,
                start_time=time(9, 0),
                end_time=time(12, 0),
                slot_minutes=15,
            )
        )
    db.flush()
    today = clinic_now().date()
    SlotService(db, InMemorySlotCache(settings.cache_ttl_seconds)).generate(
        admin.id, doctor.id, today, today + timedelta(days=6)
    )
    db.flush()
    _ = reception


def _user(db, settings, email, name, role, now) -> UserAccount:
    user = UserAccount(
        email=email,
        password_hash=hash_password(DEMO_PASSWORD[email], settings.password_iterations),
        full_name=name,
        phone=None,
        role=role,
        enabled=True,
        created_at=now,
    )
    db.add(user)
    return user
