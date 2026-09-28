from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db, require
from app.domain import Role
from app.models import UserAccount
from app.schemas import (
    ClinicIn,
    ClinicOut,
    DepartmentIn,
    DepartmentOut,
    DoctorOut,
    GenerateSlotsIn,
    GenerateSlotsOut,
    ScheduleBlockOut,
    ScheduleIn,
    SlotOut,
    StaffIn,
    StaffOut,
)
from app.services.catalog import ClinicService, DoctorService
from app.services.slots import SlotService

router = APIRouter(prefix="/api/v1", tags=["Clinic"])


@router.post("/clinics", response_model=ClinicOut, status_code=201)
def create_clinic(
    body: ClinicIn,
    user: UserAccount = Depends(require(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    return ClinicService(db).create_clinic(user, body)


@router.get("/clinics", response_model=list[ClinicOut])
def list_clinics(
    _: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ClinicService(db).list_clinics()


@router.post("/clinics/{clinic_id}/departments", response_model=DepartmentOut, status_code=201)
def add_department(
    clinic_id: int,
    body: DepartmentIn,
    user: UserAccount = Depends(require(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    return ClinicService(db).add_department(user, clinic_id, body)


@router.get("/clinics/{clinic_id}/departments", response_model=list[DepartmentOut])
def list_departments(
    clinic_id: int,
    _: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ClinicService(db).list_departments(clinic_id)


@router.post("/admin/staff", response_model=StaffOut, status_code=201)
def create_staff(
    body: StaffIn,
    request: Request,
    user: UserAccount = Depends(require(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    iterations = request.app.state.settings.password_iterations
    return DoctorService(db, iterations).create_staff(user, body)


@router.get("/departments/{department_id}/doctors", response_model=list[DoctorOut])
def list_doctors(
    department_id: int,
    request: Request,
    _: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return DoctorService(db, request.app.state.settings.password_iterations).list_by_department(
        department_id
    )


@router.put("/doctors/{doctor_id}/schedule", response_model=list[ScheduleBlockOut])
def replace_schedule(
    doctor_id: int,
    body: ScheduleIn,
    request: Request,
    user: UserAccount = Depends(require(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    return SlotService(db, request.app.state.cache).replace_schedule(user.id, doctor_id, body.blocks)


@router.post("/doctors/{doctor_id}/slots", response_model=GenerateSlotsOut)
def generate_slots(
    doctor_id: int,
    body: GenerateSlotsIn,
    request: Request,
    user: UserAccount = Depends(require(Role.ADMIN, Role.RECEPTIONIST)),
    db: Session = Depends(get_db),
):
    return SlotService(db, request.app.state.cache).generate(
        user.id, doctor_id, body.from_date, body.to_date
    )


@router.get("/doctors/{doctor_id}/slots", response_model=list[SlotOut])
def open_slots(
    doctor_id: int,
    day: date,
    request: Request,
    _: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return SlotService(db, request.app.state.cache).open_slots(doctor_id, day)
