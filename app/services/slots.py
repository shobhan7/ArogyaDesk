from datetime import date, datetime, timedelta

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.cache import SlotCache
from app.domain import SlotStatus, clinic_now, combine_slot
from app.errors import bad_request, not_found
from app.models import AppointmentSlot, Doctor, WeeklySchedule
from app.schemas import GenerateSlotsOut, ScheduleBlockIn, ScheduleBlockOut, SlotOut
from app.services.catalog import write_audit


class SlotService:
    def __init__(self, db: Session, cache: SlotCache):
        self.db = db
        self.cache = cache

    def replace_schedule(
        self, actor_id: int, doctor_id: int, blocks: list[ScheduleBlockIn]
    ) -> list[ScheduleBlockOut]:
        self._require_doctor(doctor_id)
        if not blocks:
            raise bad_request("A schedule needs at least one block")
        for block in blocks:
            if block.start_time >= block.end_time:
                raise bad_request("Schedule start time must be before the end time")
        self.db.query(WeeklySchedule).filter(WeeklySchedule.doctor_id == doctor_id).delete()
        saved: list[WeeklySchedule] = []
        for block in blocks:
            row = WeeklySchedule(
                doctor_id=doctor_id,
                day_of_week=block.day_of_week,
                start_time=block.start_time,
                end_time=block.end_time,
                slot_minutes=block.slot_minutes,
            )
            self.db.add(row)
            saved.append(row)
        self.db.flush()
        write_audit(
            self.db, actor_id, "SCHEDULE_REPLACED", "doctor", doctor_id, f"{len(saved)} blocks"
        )
        return [
            ScheduleBlockOut(
                id=row.id,
                doctor_id=row.doctor_id,
                day_of_week=row.day_of_week,
                start_time=row.start_time,
                end_time=row.end_time,
                slot_minutes=row.slot_minutes,
            )
            for row in saved
        ]

    def generate(self, actor_id: int, doctor_id: int, start: date, end: date) -> GenerateSlotsOut:
        self._require_doctor(doctor_id)
        if end < start:
            raise bad_request("The end date cannot be before the start date")
        if (end - start).days > 31:
            raise bad_request("Generate at most 31 days of slots at a time")
        created = 0
        skipped = 0
        day = start
        touched: set[date] = set()
        while day <= end:
            blocks = self.db.scalars(
                select(WeeklySchedule).where(
                    WeeklySchedule.doctor_id == doctor_id,
                    WeeklySchedule.day_of_week == day.isoweekday(),
                )
            ).all()
            for block in blocks:
                cursor = datetime.combine(day, block.start_time)
                stop = datetime.combine(day, block.end_time)
                step = timedelta(minutes=block.slot_minutes)
                while cursor + step <= stop:
                    slot_end = cursor + step
                    exists = self.db.scalar(
                        select(AppointmentSlot.id).where(
                            AppointmentSlot.doctor_id == doctor_id,
                            AppointmentSlot.slot_date == day,
                            AppointmentSlot.start_time == cursor.time(),
                        )
                    )
                    if exists:
                        skipped += 1
                    else:
                        self.db.add(
                            AppointmentSlot(
                                doctor_id=doctor_id,
                                slot_date=day,
                                start_time=cursor.time(),
                                end_time=slot_end.time(),
                                status=SlotStatus.OPEN,
                                version=1,
                            )
                        )
                        created += 1
                        touched.add(day)
                    cursor = slot_end
            day += timedelta(days=1)
        self.db.flush()
        for touched_day in touched:
            self._evict_after_commit(doctor_id, touched_day)
        write_audit(
            self.db,
            actor_id,
            "SLOTS_GENERATED",
            "doctor",
            doctor_id,
            f"created={created} skipped={skipped}",
        )
        return GenerateSlotsOut(created=created, skipped=skipped)

    def open_slots(self, doctor_id: int, day: date) -> list[SlotOut]:
        self._require_doctor(doctor_id)
        payload = self.cache.get_or_load(doctor_id, day, lambda: self._load_open(doctor_id, day))
        return [SlotOut.model_validate(item) for item in payload]

    def _load_open(self, doctor_id: int, day: date) -> list[dict]:
        now = clinic_now()
        rows = self.db.scalars(
            select(AppointmentSlot)
            .where(
                AppointmentSlot.doctor_id == doctor_id,
                AppointmentSlot.slot_date == day,
                AppointmentSlot.status == SlotStatus.OPEN,
            )
            .order_by(AppointmentSlot.start_time)
        ).all()
        visible = []
        for row in rows:
            if combine_slot(row.slot_date, row.start_time) <= now:
                continue
            visible.append(
                {
                    "id": row.id,
                    "doctor_id": row.doctor_id,
                    "slot_date": row.slot_date.isoformat(),
                    "start_time": row.start_time.isoformat(),
                    "end_time": row.end_time.isoformat(),
                    "status": row.status,
                }
            )
        return visible

    def _require_doctor(self, doctor_id: int) -> Doctor:
        doctor = self.db.get(Doctor, doctor_id)
        if not doctor or not doctor.active:
            raise not_found("Doctor not found")
        return doctor

    def _evict_after_commit(self, doctor_id: int, day: date) -> None:
        cache = self.cache

        def _clear(_session) -> None:
            cache.evict(doctor_id, day)

        event.listen(self.db, "after_commit", _clear, once=True)
