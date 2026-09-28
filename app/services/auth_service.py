from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.domain import Role
from app.errors import bad_request, conflict, unauthorized
from app.models import Patient, UserAccount
from app.schemas import LoginIn, MeOut, RegisterIn, TokenOut
from app.security import hash_password, issue_token, password_is_acceptable, verify_password
from app.throttle import LoginThrottle


class AuthService:
    def __init__(self, db: Session, settings: Settings, throttle: LoginThrottle):
        self.db = db
        self.settings = settings
        self.throttle = throttle

    def register(self, body: RegisterIn) -> TokenOut:
        email = body.email.strip().lower()
        if not password_is_acceptable(body.password):
            raise bad_request(
                "Password must be 8 to 72 characters and include a letter and a digit"
            )
        existing = self.db.scalar(select(UserAccount).where(UserAccount.email == email))
        if existing:
            raise conflict("An account with this email already exists")
        user = UserAccount(
            email=email,
            password_hash=hash_password(body.password, self.settings.password_iterations),
            full_name=body.full_name.strip(),
            phone=body.phone,
            role=Role.PATIENT,
            enabled=True,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(user)
        self.db.flush()
        self.db.add(Patient(user_id=user.id))
        self.db.flush()
        return self._token(user)

    def login(self, body: LoginIn, client_key: str) -> TokenOut:
        self.throttle.check(client_key)
        email = body.email.strip().lower()
        user = self.db.scalar(select(UserAccount).where(UserAccount.email == email))
        if (
            not user
            or not user.enabled
            or not verify_password(body.password, user.password_hash)
        ):
            raise unauthorized()
        return self._token(user)

    def me(self, user: UserAccount) -> MeOut:
        return MeOut(
            user_id=user.id, full_name=user.full_name, email=user.email, role=user.role
        )

    def _token(self, user: UserAccount) -> TokenOut:
        token = issue_token(self.settings, user.id, user.role, user.email)
        return TokenOut(
            token=token,
            expires_in_seconds=self.settings.jwt_ttl_minutes * 60,
            user_id=user.id,
            full_name=user.full_name,
            email=user.email,
            role=user.role,
        )
