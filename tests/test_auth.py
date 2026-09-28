def test_patient_can_register_and_read_profile(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "fullName": "Asha Rao",
            "email": "asha@example.com",
            "password": "Patient@123",
            "phone": "9000000001",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["role"] == "PATIENT"
    assert body["fullName"] == "Asha Rao"
    assert "token" in body

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "asha@example.com"

    profile = client.get(
        "/api/v1/patients/me", headers={"Authorization": f"Bearer {body['token']}"}
    )
    assert profile.status_code == 200
    assert profile.json()["patientId"] > 0


def test_duplicate_email_is_rejected(client):
    payload = {
        "fullName": "Asha Rao",
        "email": "asha@example.com",
        "password": "Patient@123",
    }
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    again = client.post("/api/v1/auth/register", json=payload)
    assert again.status_code == 409


def test_login_failure_uses_a_generic_message(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": "Patient@123"},
    )
    assert response.status_code == 401
    assert response.json()["message"] == "Invalid email or password"


def test_missing_token_is_unauthorized(client):
    response = client.get("/api/v1/clinics")
    assert response.status_code == 401


def test_patient_cannot_create_a_clinic(client):
    registered = client.post(
        "/api/v1/auth/register",
        json={"fullName": "Asha Rao", "email": "asha@example.com", "password": "Patient@123"},
    )
    token = registered.json()["token"]
    response = client.post(
        "/api/v1/clinics",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "CityCare OPD",
            "city": "Hyderabad",
            "address": "12 Lake View Road",
        },
    )
    assert response.status_code == 403
