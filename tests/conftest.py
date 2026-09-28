import json
from datetime import datetime, time, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.domain import clinic_now
from app.factory import create_app
from app.models import Appointment, AppointmentSlot, UserAccount
from app.security import hash_password
from app.services.appointments import AppointmentService


@pytest.fixture()
def settings(tmp_path):
    return Settings(
        database_url="sqlite:///" + tmp_path.joinpath("clinic.db").as_posix(),
        jwt_secret="test-secret-key-with-32-characters-min",
        seed=False,
        password_iterations=1000,
        cache_ttl_seconds=120,
        cancel_cutoff_hours=2,
    )


@pytest.fixture()
def app(settings):
    return create_app(settings)


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def login(client, email, password):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['token']}"}, body


def insert_user(app, email, full_name, role, password="Password@1"):
    db = app.state.session_factory()
    try:
        user = UserAccount(
            email=email,
            password_hash=hash_password(password, app.state.settings.password_iterations),
            full_name=full_name,
            phone=None,
            role=role,
            enabled=True,
            created_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        return user.id
    finally:
        db.close()
