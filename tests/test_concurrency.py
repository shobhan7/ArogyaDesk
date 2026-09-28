import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from app.domain import Role, SlotStatus, clinic_now
from app.errors import AppError
from app.models import (
    Appointment,
    AppointmentSlot,
    Clinic,
    Department,
    Doctor,
    Patient,
    UserAccount,
)
from app.outbox import RecordingPublisher, consume_notification, relay_pending
from app.security import hash_password
from app.services.appointments import AppointmentService
from app.models import OutboxEvent


def _seed_race(app):
    db = app.state.session_factory()
    now = datetime.now(timezone.utc)
    iterations = app.state.settings.password_iterations
    admin = UserAccount(
        email="admin@example.com",
        password_hash=hash_password("Password@1", iterations),
        full_name="Admin",
        phone=None,
        role=Role.ADMIN,
        enabled=True,
        created_at=now,
    )
    patient_user = UserAccount(
        email="asha@example.com",
        password_hash=hash_password("Patient@123", iterations),
        full_name="Asha Rao",
        phone=None,
        role=Role.PATIENT,
        enabled=True,
        created_at=now,
    )
    db.add_all([admin, patient_user])
    db.flush()
    clinic = Clinic(
        name="CityCare OPD",
        city="Hyderabad",
        address="12 Lake View Road",
        phone=None,
        created_at=now,
    )
    db.add(clinic)
    db.flush()
    department = Department(clinic_id=clinic.id, name="General Medicine", code="GM")
    db.add(department)
    db.flush()
    doctor_user = UserAccount(
        email="meera@example.com",
        password_hash=hash_password("Doctor@123", iterations),
        full_name="Dr. Meera Iyer",
        phone=None,
        role=Role.DOCTOR,
        enabled=True,
        created_at=now,
    )
    db.add(doctor_user)
    db.flush()
    doctor = Doctor(
        user_id=doctor_user.id,
        department_id=department.id,
        registration_number="MCI-TS-20481",
        consultation_fee_paise=50000,
        active=True,
    )
    db.add(doctor)
    patient = Patient(user_id=patient_user.id)
    db.add(patient)
    db.flush()
    slot_day = (clinic_now() + timedelta(days=4)).date()
    slot = AppointmentSlot(
        doctor_id=doctor.id,
        slot_date=slot_day,
        start_time=datetime.strptime("10:00", "%H:%M").time(),
        end_time=datetime.strptime("10:15", "%H:%M").time(),
        status=SlotStatus.OPEN,
        version=1,
    )
    db.add(slot)
    db.commit()
    ids = {
        "patient_user_id": patient_user.id,
        "patient_id": patient.id,
        "doctor_id": doctor.id,
        "slot_id": slot.id,
        "slot_date": slot_day.isoformat(),
    }
    db.close()
    return ids


def _cache_timing(app, doctor_id: int, day: date) -> dict:
    cache = app.state.cache

    def loader():
        session = app.state.session_factory()
        try:
            rows = session.scalars(
                select(AppointmentSlot).where(
                    AppointmentSlot.doctor_id == doctor_id,
                    AppointmentSlot.slot_date == day,
                    AppointmentSlot.status == SlotStatus.OPEN,
                )
            ).all()
            return [{"id": row.id} for row in rows]
        finally:
            session.close()

    cold = []
    for _ in range(100):
        cache.evict(doctor_id, day)
        started = time.perf_counter()
        cache.get_or_load(doctor_id, day, loader)
        cold.append((time.perf_counter() - started) * 1000)
    warm = []
    for _ in range(100):
        started = time.perf_counter()
        cache.get_or_load(doctor_id, day, loader)
        warm.append((time.perf_counter() - started) * 1000)

    def average(samples: list[float]) -> float:
        return round(sum(samples) / len(samples), 3)

    return {"cold": average(cold), "warm": average(warm)}


def test_only_one_parallel_booking_wins(app):
    ids = _seed_race(app)
    attempts = 16

    def attempt():
        db = app.state.session_factory()
        try:
            for _ in range(4):
                try:
                    actor = db.get(UserAccount, ids["patient_user_id"])
                    AppointmentService(db, app.state.cache, app.state.settings).book(
                        actor, ids["slot_id"], ids["patient_id"]
                    )
                    db.commit()
                    return "ok"
                except AppError as exc:
                    db.rollback()
                    return str(exc.status_code)
                except Exception as exc:
                    db.rollback()
                    if exc.__class__.__name__ == "OperationalError":
                        continue
                    return exc.__class__.__name__
            return "locked"
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        results = list(pool.map(lambda _: attempt(), range(attempts)))

    db = app.state.session_factory()
    try:
        successes = results.count("ok")
        stored = db.scalar(
            select(func.count()).select_from(Appointment).where(Appointment.slot_id == ids["slot_id"])
        )
        slot = db.get(AppointmentSlot, ids["slot_id"])
        unpublished = db.scalar(
            select(func.count()).select_from(OutboxEvent).where(OutboxEvent.published_at.is_(None))
        )
        timing = _cache_timing(app, ids["doctor_id"], date.fromisoformat(ids["slot_date"]))
    finally:
        db.close()

    payload = {
        "attempts": attempts,
        "successes": successes,
        "conflicts": results.count("409"),
        "results": results,
        "storedAppointments": stored,
        "slotStatus": slot.status,
        "unpublishedOutbox": unpublished,
        "coldMs": timing["cold"],
        "warmMs": timing["warm"],
    }
    Path(__file__).resolve().parents[1].joinpath("measured-results.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    print("MEASURED_RACE " + json.dumps({k: payload[k] for k in payload if k != "results"}))
    assert successes == 1, payload
    assert stored == 1
    assert slot.status == SlotStatus.BOOKED
    assert unpublished == 1


def test_outbox_relay_is_idempotent(app):
    ids = _seed_race(app)
    db = app.state.session_factory()
    try:
        actor = db.get(UserAccount, ids["patient_user_id"])
        AppointmentService(db, app.state.cache, app.state.settings).book(
            actor, ids["slot_id"], ids["patient_id"]
        )
        publisher = RecordingPublisher()
        sent = relay_pending(db, publisher)
        db.commit()
        assert sent == 1
        assert len(publisher.messages) == 1
        payload = publisher.messages[0][1]
        assert consume_notification(db, payload) is True
        assert consume_notification(db, payload) is False
        db.commit()
        assert relay_pending(db, publisher) == 0
    finally:
        db.close()
