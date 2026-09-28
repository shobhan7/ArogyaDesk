from datetime import date, datetime, time, timedelta, timezone

# India Standard Time does not observe daylight saving.
CLINIC_TZ = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


class Role:
    ADMIN = "ADMIN"
    RECEPTIONIST = "RECEPTIONIST"
    DOCTOR = "DOCTOR"
    PATIENT = "PATIENT"
    ALL = (ADMIN, RECEPTIONIST, DOCTOR, PATIENT)
    STAFF = (ADMIN, RECEPTIONIST, DOCTOR)


class SlotStatus:
    OPEN = "OPEN"
    BOOKED = "BOOKED"
    BLOCKED = "BLOCKED"


class AppointmentStatus:
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    IN_CONSULT = "IN_CONSULT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    ACTIVE = (BOOKED, CHECKED_IN, IN_CONSULT)
    TERMINAL = (COMPLETED, CANCELLED, NO_SHOW)


TRANSITIONS = {
    AppointmentStatus.BOOKED: {
        AppointmentStatus.CHECKED_IN,
        AppointmentStatus.CANCELLED,
        AppointmentStatus.NO_SHOW,
    },
    AppointmentStatus.CHECKED_IN: {
        AppointmentStatus.IN_CONSULT,
        AppointmentStatus.CANCELLED,
        AppointmentStatus.NO_SHOW,
    },
    AppointmentStatus.IN_CONSULT: {AppointmentStatus.COMPLETED},
    AppointmentStatus.COMPLETED: set(),
    AppointmentStatus.CANCELLED: set(),
    AppointmentStatus.NO_SHOW: set(),
}


class QueueStatus:
    WAITING = "WAITING"
    CALLED = "CALLED"
    DONE = "DONE"
    SKIPPED = "SKIPPED"


class InvoiceStatus:
    DUE = "DUE"
    PAID = "PAID"
    VOID = "VOID"


class PaymentMethod:
    CASH = "CASH"
    UPI = "UPI"
    CARD = "CARD"
    ALL = (CASH, UPI, CARD)


def clinic_now() -> datetime:
    return datetime.now(CLINIC_TZ)


def combine_slot(slot_date: date, slot_time: time) -> datetime:
    return datetime.combine(slot_date, slot_time, tzinfo=CLINIC_TZ)
