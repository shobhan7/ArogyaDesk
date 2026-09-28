from datetime import timedelta

from tests.conftest import insert_user, login


def test_slot_list_is_cached_until_a_booking(client, app):
    admin_id = insert_user(app, "admin@example.com", "Admin", "ADMIN")
    headers, _ = login(client, "admin@example.com", "Password@1")
    clinic = client.post(
        "/api/v1/clinics",
        headers=headers,
        json={"name": "CityCare OPD", "city": "Hyderabad", "address": "12 Lake View Road"},
    )
    assert clinic.status_code == 201, clinic.text
    department = client.post(
        f"/api/v1/clinics/{clinic.json()['id']}/departments",
        headers=headers,
        json={"name": "General Medicine", "code": "GM"},
    )
    doctor = client.post(
        "/api/v1/admin/staff",
        headers=headers,
        json={
            "fullName": "Dr. Meera Iyer",
            "email": "meera@example.com",
            "password": "Doctor@123",
            "role": "DOCTOR",
            "departmentId": department.json()["id"],
            "registrationNumber": "MCI-TS-20481",
            "consultationFeePaise": 50000,
        },
    )
    assert doctor.status_code == 201, doctor.text
    doctor_id = doctor.json()["doctor"]["id"]
    schedule = client.put(
        f"/api/v1/doctors/{doctor_id}/schedule",
        headers=headers,
        json={
            "blocks": [
                {
                    "dayOfWeek": day,
                    "startTime": "09:00:00",
                    "endTime": "10:00:00",
                    "slotMinutes": 30,
                }
                for day in range(1, 8)
            ]
        },
    )
    assert schedule.status_code == 200, schedule.text
    target = ( __import__("app.domain", fromlist=["clinic_now"]).clinic_now() + timedelta(days=2) ).date()
    generated = client.post(
        f"/api/v1/doctors/{doctor_id}/slots",
        headers=headers,
        json={"fromDate": target.isoformat(), "toDate": target.isoformat()},
    )
    assert generated.status_code == 200, generated.text
    assert generated.json()["created"] == 2

    first = client.get(
        f"/api/v1/doctors/{doctor_id}/slots", headers=headers, params={"day": target.isoformat()}
    )
    second = client.get(
        f"/api/v1/doctors/{doctor_id}/slots", headers=headers, params={"day": target.isoformat()}
    )
    assert first.status_code == 200
    assert len(first.json()) == 2
    assert second.json() == first.json()
    stats = client.get("/api/v1/admin/cache-stats", headers=headers)
    assert stats.json()["misses"] >= 1
    assert stats.json()["hits"] >= 1

    patient = client.post(
        "/api/v1/auth/register",
        json={"fullName": "Asha Rao", "email": "asha@example.com", "password": "Patient@123"},
    )
    patient_headers = {"Authorization": f"Bearer {patient.json()['token']}"}
    patient_id = client.get("/api/v1/patients/me", headers=patient_headers).json()["patientId"]
    booked = client.post(
        "/api/v1/appointments",
        headers=patient_headers,
        json={"slotId": first.json()[0]["id"], "patientId": patient_id},
    )
    assert booked.status_code == 201, booked.text
    assert booked.json()["tokenNumber"] == 1
    assert booked.json()["status"] == "BOOKED"

    remaining = client.get(
        f"/api/v1/doctors/{doctor_id}/slots", headers=headers, params={"day": target.isoformat()}
    )
    assert len(remaining.json()) == 1
    assert admin_id > 0
