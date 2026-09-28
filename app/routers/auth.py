from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models import UserAccount
from app.schemas import LoginIn, MeOut, RegisterIn, TokenOut
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


def _service(request: Request, db: Session) -> AuthService:
    return AuthService(db, request.app.state.settings, request.app.state.throttle)


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    return _service(request, db).register(body)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    client = request.client.host if request.client else "unknown"
    return _service(request, db).login(body, client)


@router.get("/me", response_model=MeOut)
def me(request: Request, user: UserAccount = Depends(get_current_user), db: Session = Depends(get_db)):
    return _service(request, db).me(user)
