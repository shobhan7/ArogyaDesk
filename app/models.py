from datetime import date, datetime, time

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UserAccount(Base):
    __tablename__ = "user_account"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    role: Mapped[str] = mapped_column(String(32), index=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Clinic(Base):
    __tablename__ = "clinic"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    city: Mapped[str] = mapped_column(String(80))
    address: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    departments: Mapped[list["Department"]] = relationship(back_populates="clinic")


class Department(Base):
    __tablename__ = "department"
    __table_args__ = (UniqueConstraint("clinic_id", "code", name="uq_department_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinic.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(16))
    clinic: Mapped[Clinic] = relationship(back_populates="departments")
    doctors: Mapped[list["Doctor"]] = relationship(back_populates="department")


class Doctor(Base):
    __tablename__ = "doctor"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_account.id"), unique=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("department.id"), index=True)
    registration_number: Mapped[str] = mapped_column(String(40), unique=True)
    consultation_fee_paise: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(default=True)
    user: Mapped[UserAccount] = relationship()
    department: Mapped[Department] = relationship(back_populates="doctors")


class Patient(Base):
    __tablename__ = "patient"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_account.id"), unique=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(16), nullable=True)
    blood_group: Mapped[str | None] = mapped_column(String(8), nullable=True)
    user: Mapped[UserAccount] = relationship()


class WeeklySchedule(Base):
    __tablename__ = "weekly_schedule"
    __table_args__ = (
        UniqueConstraint(
            "doctor_id", "day_of_week", "start_time", name="uq_schedule_block"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctor.id"), index=True)
    day_of_week: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    slot_minutes: Mapped[int] = mapped_column(Integer)


class AppointmentSlot(Base):
    __tablename__ = "appointment_slot"
    __table_args__ = (
        UniqueConstraint(
            "doctor_id", "slot_date", "start_time", name="uq_slot_doctor_date_start"
        ),
        Index("idx_slot_doctor_date_status", "doctor_id", "slot_date", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctor.id"))
    slot_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, default=1)
    doctor: Mapped[Doctor] = relationship()


class Appointment(Base):
    __tablename__ = "appointment"
    __table_args__ = (
        Index("idx_appointment_patient", "patient_id", "status"),
        Index("idx_appointment_doctor", "doctor_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("appointment_slot.id"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id"))
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctor.id"))
    status: Mapped[str] = mapped_column(String(24))
    token_number: Mapped[int] = mapped_column(Integer)
    booked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    day_guard: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    slot: Mapped[AppointmentSlot] = relationship()
    patient: Mapped[Patient] = relationship()
    doctor: Mapped[Doctor] = relationship()


class QueueToken(Base):
    __tablename__ = "queue_token"
    __table_args__ = (
        UniqueConstraint(
            "doctor_id", "queue_date", "token_number", name="uq_token_number"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointment.id"), unique=True
    )
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctor.id"), index=True)
    queue_date: Mapped[date] = mapped_column(Date)
    token_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    appointment: Mapped[Appointment] = relationship()


class Encounter(Base):
    __tablename__ = "encounter"

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointment.id"), unique=True
    )
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctor.id"))
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id"))
    clinical_notes: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    items: Mapped[list["PrescriptionItem"]] = relationship(back_populates="encounter")


class PrescriptionItem(Base):
    __tablename__ = "prescription_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    encounter_id: Mapped[int] = mapped_column(ForeignKey("encounter.id"), index=True)
    medicine_name: Mapped[str] = mapped_column(String(160))
    dosage: Mapped[str] = mapped_column(String(80))
    duration_days: Mapped[int] = mapped_column(Integer)
    instructions: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encounter: Mapped[Encounter] = relationship(back_populates="items")


class Invoice(Base):
    __tablename__ = "invoice"

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointment.id"), unique=True
    )
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id"), index=True)
    amount_paise: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice")


class Payment(Base):
    __tablename__ = "payment"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoice.id"), index=True)
    amount_paise: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(24))
    reference_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    invoice: Mapped[Invoice] = relationship(back_populates="payments")


class OutboxEvent(Base):
    __tablename__ = "outbox_event"
    __table_args__ = (Index("idx_outbox_unpublished", "published_at", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(String(40))
    aggregate_id: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(60))
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(Integer, unique=True)
    event_type: Mapped[str] = mapped_column(String(60))
    payload: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditEntry(Base):
    __tablename__ = "audit_entry"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
