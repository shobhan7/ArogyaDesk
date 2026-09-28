from datetime import timedelta

from app.domain import clinic_now
from tests.conftest import login


def _clinic(client):
    admin_headers, _ = login(client, "admin@example.com", "Password@1")
    clinic = client.post(
        "/api/v1/clinics",
        headers=admin_headers,
        json={"name": "CityCare OPD", "city": "Hyderabad", "address": "12 Lake View Road"},
    ).json()
    department = client.post(
        f"/api/v1/clinics/{clinic['id']}/departments",
        headers=admin_headers,
        json={"name": "General Medicine", "code": "gm"},
    ).json()
    doctor = client.post(
        "/api/v1/admin/staff",
        headers=admin_headers,
        json={
            "fullName": "Dr. Meera Iyer",
            "email": "meera@example.com",
            "password": "Doctor@123",
            "role": "DOCTOR",
            "departmentId": department["id"],
            "registrationNumber": "MCI-TS-20481",
            "consultationFeePaise": 50000,
        },
    ).json()["doctor"]
    reception = client.post(
        "/api/v1/admin/staff",
        headers=admin_headers,
        json={
            "fullName": "Lakshmi Reception",
            "email": "reception@example.com",
            "password": "Reception@123",
            "role": "RECEPTIONIST",
        },
    )
    assert reception.status_code == 201, reception.text
    client.put(
        f"/api/v1/doctors/{doctor['id']}/schedule",
        headers=admin_headers,
        json={
            "blocks": [
                {
                    "dayOfWeek": day,
                    "startTime": "09:00:00",
                    "endTime": "11:00:00",
                    "slotMinutes": 30,
                }
                for day in range(1, 8)
            ]
        },
    )
    target = (clinic_now() + timedelta(days=3)).date()
    generated = client.post(
        f"/api/v1/doctors/{doctor['id']}/slots",
        headers=admin_headers,
        json={"fromDate": target.isoformat(), "toDate": target.isoformat()},
    )
    assert generated.status_code == 200, generated.text
    slots = client.get(
        f"/api/v1/doctors/{doctor['id']}/slots",
        headers=admin_headers,
        params={"day": target.isoformat()},
    ).json()
    return doctor, target, slots


def test_full_opd_visit_ends_with_a_paid_invoice(client, app):
    from tests.conftest import insert_user

    insert_user(app, "admin@example.com", "Admin", "ADMIN")
    doctor, target, slots = _clinic(client)
    patient = client.post(
        "/api/v1/auth/register",
        json={"fullName": "Asha Rao", "email": "asha@example.com", "password": "Patient@123"},
    ).json()
    patient_headers = {"Authorization": f"Bearer {patient['token']}"}
    patient_id = client.get("/api/v1/patients/me", headers=patient_headers).json()["patientId"]
    booked = client.post(
        "/api/v1/appointments",
        headers=patient_headers,
        json={"slotId": slots[0]["id"], "patientId": patient_id},
    )
    assert booked.status_code == 201, booked.text
    appointment_id = booked.json()["id"]

    same_day = client.post(
        "/api/v1/appointments",
        headers=patient_headers,
        json={"slotId": slots[1]["id"], "patientId": patient_id},
    )
    assert same_day.status_code == 409

    reception_headers, _ = login(client, "reception@example.com", "Reception@123")
    checked = client.post(
        f"/api/v1/appointments/{appointment_id}/check-in", headers=reception_headers
    )
    assert checked.status_code == 200, checked.text
    assert checked.json()["status"] == "CHECKED_IN"

    doctor_headers, _ = login(client, "meera@example.com", "Doctor@123")
    called = client.post(
        f"/api/v1/doctors/{doctor['id']}/queue/next",
        headers=doctor_headers,
        params={"day": target.isoformat()},
    )
    assert called.status_code == 200, called.text
    assert called.json()["appointmentStatus"] == "IN_CONSULT"

    encounter = client.post(
        f"/api/v1/appointments/{appointment_id}/encounter",
        headers=doctor_headers,
        json={
            "clinicalNotes": "Viral fever. Rest and fluids.",
            "items": [
                {
                    "medicineName": "Paracetamol 500mg",
                    "dosage": "1 tablet twice a day",
                    "durationDays": 3,
                    "instructions": "After food",
                }
            ],
        },
    )
    assert encounter.status_code == 201, encounter.text
    invoice = client.get(
        f"/api/v1/appointments/{appointment_id}/invoice", headers=reception_headers
    )
    assert invoice.status_code == 200, invoice.text
    assert invoice.json()["amountPaise"] == 50000
    assert invoice.json()["status"] == "DUE"

    partial = client.post(
        f"/api/v1/invoices/{invoice.json()['id']}/payments",
        headers=reception_headers,
        json={"amountPaise": 20000, "method": "CASH"},
    )
    assert partial.status_code == 201, partial.text
    assert partial.json()["status"] == "DUE"
    assert partial.json()["remainingPaise"] == 30000

    paid = client.post(
        f"/api/v1/invoices/{invoice.json()['id']}/payments",
        headers=reception_headers,
        json={"amountPaise": 30000, "method": "UPI", "referenceCode": "UPI123"},
    )
    assert paid.status_code == 201, paid.text
    assert paid.json()["status"] == "PAID"
    assert paid.json()["remainingPaise"] == 0


def test_patient_cancel_reopens_a_future_slot(client, app):
    from tests.conftest import insert_user

    insert_user(app, "admin@example.com", "Admin", "ADMIN")
    doctor, target, slots = _clinic(client)
    patient = client.post(
        "/api/v1/auth/register",
        json={"fullName": "Asha Rao", "email": "asha@example.com", "password": "Patient@123"},
    ).json()
    headers = {"Authorization": f"Bearer {patient['token']}"}
    patient_id = client.get("/api/v1/patients/me", headers=headers).json()["patientId"]
    slot_id = slots[0]["id"]
    booked = client.post(
        "/api/v1/appointments",
        headers=headers,
        json={"slotId": slot_id, "patientId": patient_id},
    )
    cancelled = client.post(
        f"/api/v1/appointments/{booked.json()['id']}/cancel",
        headers=headers,
        json={"reason": "Travel plans changed"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "CANCELLED"
    open_again = client.get(
        f"/api/v1/doctors/{doctor['id']}/slots",
        headers=headers,
        params={"day": target.isoformat()},
    ).json()
    assert slot_id in [slot["id"] for slot in open_again]
