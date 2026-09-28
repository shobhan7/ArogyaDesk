from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.errors import forbidden, unauthorized
from app.models import UserAccount
from app.security import read_token

bearer = HTTPBearer(auto_error=False)


def get_db(request: Request):
    db = request.app.state.session_factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> UserAccount:
    if credentials is None or not credentials.credentials:
        raise unauthorized("Missing bearer token")
    payload = read_token(request.app.state.settings, credentials.credentials)
    user = db.get(UserAccount, int(payload["sub"]))
    if not user or not user.enabled:
        raise unauthorized("Invalid or expired token")
    return user


def require(*roles: str):
    def checker(user: UserAccount = Depends(get_current_user)) -> UserAccount:
        if user.role not in roles:
            raise forbidden("You do not have access to this action")
        return user

    return checker
