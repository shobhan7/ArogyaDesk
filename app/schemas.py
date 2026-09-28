from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, EmailStr, Field


def to_camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part.capitalize() for part in tail)


class APIModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        ser_json_by_alias=True,
    )


class RegisterIn(APIModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    phone: str | None = Field(default=None, max_length=20)


class LoginIn(APIModel):
    email: EmailStr
    password: str


class TokenOut(APIModel):
    token: str
    token_type: str = "Bearer"
    expires_in_seconds: int
    user_id: int
    full_name: str
    email: EmailStr
    role: str


class MeOut(APIModel):
    user_id: int
    full_name: str
    email: EmailStr
    role: str


class ClinicIn(APIModel):
    name: str = Field(min_length=2, max_length=160)
    city: str = Field(min_length=2, max_length=80)
    address: str = Field(min_length=4, max_length=255)
    phone: str | None = Field(default=None, max_length=20)


class ClinicOut(ClinicIn):
    id: int


class DepartmentIn(APIModel):
    name: str = Field(min_length=2, max_length=120)
    code: str = Field(min_length=2, max_length=16)


class DepartmentOut(DepartmentIn):
    id: int
    clinic_id: int


class StaffIn(APIModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    phone: str | None = Field(default=None, max_length=20)
    role: str
    department_id: int | None = None
    registration_number: str | None = Field(default=None, max_length=40)
    consultation_fee_paise: int | None = Field(default=None, ge=0)


class DoctorOut(APIModel):
    id: int
    user_id: int
    full_name: str
    department_id: int
    registration_number: str
    consultation_fee_paise: int
    active: bool


class StaffOut(APIModel):
    user_id: int
    full_name: str
    email: EmailStr
    role: str
    doctor: DoctorOut | None = None


class ScheduleBlockIn(APIModel):
    day_of_week: int = Field(ge=1, le=7)
    start_time: time
    end_time: time
    slot_minutes: int = Field(ge=5, le=60)


class ScheduleIn(APIModel):
    blocks: list[ScheduleBlockIn]


class ScheduleBlockOut(ScheduleBlockIn):
    id: int
    doctor_id: int


class GenerateSlotsIn(APIModel):
    from_date: date
    to_date: date


class GenerateSlotsOut(APIModel):
    created: int
    skipped: int


class SlotOut(APIModel):
    id: int
    doctor_id: int
    slot_date: date
    start_time: time
    end_time: time
    status: str


class BookIn(APIModel):
    slot_id: int
    patient_id: int


class CancelIn(APIModel):
    reason: str = Field(min_length=3, max_length=255)


class AppointmentOut(APIModel):
    id: int
    slot_id: int
    patient_id: int
    doctor_id: int
    doctor_name: str
    slot_date: date
    start_time: time
    end_time: time
    status: str
    token_number: int
    booked_at: datetime
    cancel_reason: str | None = None


class QueueEntryOut(APIModel):
    token_number: int
    token_status: str
    appointment_id: int
    appointment_status: str
    patient_id: int
    patient_name: str


class PrescriptionIn(APIModel):
    medicine_name: str = Field(min_length=2, max_length=160)
    dosage: str = Field(min_length=2, max_length=80)
    duration_days: int = Field(ge=1, le=90)
    instructions: str | None = Field(default=None, max_length=255)


class EncounterIn(APIModel):
    clinical_notes: str = Field(min_length=2, max_length=2000)
    items: list[PrescriptionIn] = Field(min_length=1, max_length=12)


class PrescriptionOut(PrescriptionIn):
    id: int


class EncounterOut(APIModel):
    id: int
    appointment_id: int
    doctor_id: int
    patient_id: int
    clinical_notes: str
    created_at: datetime
    items: list[PrescriptionOut]


class PaymentIn(APIModel):
    amount_paise: int = Field(ge=1)
    method: str
    reference_code: str | None = Field(default=None, max_length=64)


class PaymentOut(APIModel):
    id: int
    amount_paise: int
    method: str
    reference_code: str | None
    paid_at: datetime


class InvoiceOut(APIModel):
    id: int
    appointment_id: int
    patient_id: int
    amount_paise: int
    paid_paise: int
    remaining_paise: int
    status: str
    issued_at: datetime
    payments: list[PaymentOut]


class CacheStatsOut(APIModel):
    hits: int
    misses: int
    backend: str


class AuditOut(APIModel):
    id: int
    actor_id: int | None
    action: str
    entity_type: str
    entity_id: int | None
    detail: str | None
    created_at: datetime
