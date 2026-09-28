from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import Role
from app.errors import bad_request, conflict, not_found
from app.models import AuditEntry, Clinic, Department, Doctor, UserAccount
from app.schemas import ClinicIn, ClinicOut, DepartmentIn, DepartmentOut, DoctorOut, StaffIn, StaffOut
from app.security import hash_password, password_is_acceptable


def write_audit(db: Session, actor_id: int | None, action: str, entity_type: str, entity_id: int | None, detail: str):
    db.add(
        AuditEntry(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail[:500],
            created_at=datetime.now(timezone.utc),
        )
    )


class ClinicService:
    def __init__(self, db: Session):
        self.db = db

    def create_clinic(self, actor: UserAccount, body: ClinicIn) -> ClinicOut:
        clinic = Clinic(
            name=body.name.strip(),
            city=body.city.strip(),
            address=body.address.strip(),
            phone=body.phone,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(clinic)
        self.db.flush()
        write_audit(self.db, actor.id, "CLINIC_CREATED", "clinic", clinic.id, clinic.name)
        return ClinicOut.model_validate(clinic, from_attributes=True)

    def list_clinics(self) -> list[ClinicOut]:
        rows = self.db.scalars(select(Clinic).order_by(Clinic.name)).all()
        return [ClinicOut.model_validate(row, from_attributes=True) for row in rows]

    def add_department(self, actor: UserAccount, clinic_id: int, body: DepartmentIn) -> DepartmentOut:
        clinic = self.db.get(Clinic, clinic_id)
        if not clinic:
            raise not_found("Clinic not found")
        code = body.code.strip().upper()
        existing = self.db.scalar(
            select(Department).where(Department.clinic_id == clinic_id, Department.code == code)
        )
        if existing:
            raise conflict("This department code already exists in the clinic")
        department = Department(clinic_id=clinic_id, name=body.name.strip(), code=code)
        self.db.add(department)
        self.db.flush()
        write_audit(self.db, actor.id, "DEPARTMENT_CREATED", "department", department.id, code)
        return DepartmentOut.model_validate(department, from_attributes=True)

    def list_departments(self, clinic_id: int) -> list[DepartmentOut]:
        if not self.db.get(Clinic, clinic_id):
            raise not_found("Clinic not found")
        rows = self.db.scalars(
            select(Department).where(Department.clinic_id == clinic_id).order_by(Department.name)
        ).all()
        return [DepartmentOut.model_validate(row, from_attributes=True) for row in rows]


class DoctorService:
    def __init__(self, db: Session, iterations: int):
        self.db = db
        self.iterations = iterations

    def create_staff(self, actor: UserAccount, body: StaffIn) -> StaffOut:
        if body.role not in (Role.DOCTOR, Role.RECEPTIONIST):
            raise bad_request("Staff role must be DOCTOR or RECEPTIONIST")
        if not password_is_acceptable(body.password):
            raise bad_request("Password must be 8 to 72 characters and include a letter and a digit")
        email = body.email.strip().lower()
        if self.db.scalar(select(UserAccount).where(UserAccount.email == email)):
            raise conflict("An account with this email already exists")
        user = UserAccount(
            email=email,
            password_hash=hash_password(body.password, self.iterations),
            full_name=body.full_name.strip(),
            phone=body.phone,
            role=body.role,
            enabled=True,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(user)
        self.db.flush()
        doctor_out = None
        if body.role == Role.DOCTOR:
            doctor_out = self._create_doctor(actor, user, body)
        else:
            write_audit(self.db, actor.id, "STAFF_CREATED", "user", user.id, user.role)
        return StaffOut(
            user_id=user.id,
            full_name=user.full_name,
            email=user.email,
            role=user.role,
            doctor=doctor_out,
        )

    def _create_doctor(self, actor: UserAccount, user: UserAccount, body: StaffIn) -> DoctorOut:
        if not body.department_id or not body.registration_number or body.consultation_fee_paise is None:
            raise bad_request("A doctor needs a department, registration number, and consultation fee")
        if body.consultation_fee_paise < 0:
            raise bad_request("Consultation fee cannot be negative")
        department = self.db.get(Department, body.department_id)
        if not department:
            raise not_found("Department not found")
        registration = body.registration_number.strip().upper()
        if self.db.scalar(select(Doctor).where(Doctor.registration_number == registration)):
            raise conflict("This medical registration number is already on file")
        doctor = Doctor(
            user_id=user.id,
            department_id=department.id,
            registration_number=registration,
            consultation_fee_paise=body.consultation_fee_paise,
            active=True,
        )
        self.db.add(doctor)
        self.db.flush()
        write_audit(self.db, actor.id, "DOCTOR_CREATED", "doctor", doctor.id, registration)
        return self._to_out(doctor, user.full_name)

    def list_by_department(self, department_id: int) -> list[DoctorOut]:
        if not self.db.get(Department, department_id):
            raise not_found("Department not found")
        rows = self.db.scalars(
            select(Doctor).where(Doctor.department_id == department_id, Doctor.active.is_(True)).order_by(Doctor.id)
        ).all()
        return [self._to_out(row, row.user.full_name) for row in rows]

    def require_doctor_user(self, user: UserAccount) -> Doctor:
        doctor = self.db.scalar(select(Doctor).where(Doctor.user_id == user.id, Doctor.active.is_(True)))
        if not doctor:
            raise not_found("No active doctor profile is linked to this account")
        return doctor

    @staticmethod
    def _to_out(doctor: Doctor, full_name: str) -> DoctorOut:
        return DoctorOut(
            id=doctor.id,
            user_id=doctor.user_id,
            full_name=full_name,
            department_id=doctor.department_id,
            registration_number=doctor.registration_number,
            consultation_fee_paise=doctor.consultation_fee_paise,
            active=doctor.active,
        )
