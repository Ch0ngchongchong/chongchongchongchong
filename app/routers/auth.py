# 로그인(JWT, 2026-11-24 추가). 기존 X-User-Id 헤더 방식은 그대로 둔다 —
# 바꾸지 않고 추가만 하기로 함 (서버 영역, 팀 확인 필요: 로그인 방식 자체는
# API.md 공통 규칙에 "미정"으로 남아 있던 것이다).
# StoreUser에는 아이디·이메일이 없어 store_user_id + 비밀번호로 로그인한다.
# 회원가입 화면이 없는 지금 단계라, 비밀번호는 register-password로 처음
# 한 번만 정할 수 있다(이미 있으면 거절) — 임시 동작이다.

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import StoreUser
from app.routers.products import error_response
from app.schemas.auth import LoginIn, PasswordIn, TokenOut
from app.services.auth import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register-password")
def register_password(body: PasswordIn, db: Session = Depends(get_db)):
    user = db.get(StoreUser, body.store_user_id)
    if user is None:
        return error_response(404, "USER_NOT_FOUND", "사용자를 찾을 수 없습니다")
    if user.password_hash is not None:
        return error_response(
            400, "PASSWORD_ALREADY_SET", "이미 비밀번호가 설정돼 있습니다"
        )
    if not body.password:
        return error_response(400, "REQUIRED_FIELD_MISSING", "비밀번호를 입력해 주세요")
    user.password_hash = hash_password(body.password)
    db.commit()
    return {"ok": True}


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.get(StoreUser, body.store_user_id)
    if (
        user is None
        or user.password_hash is None
        or not verify_password(body.password, user.password_hash)
    ):
        return error_response(
            401, "INVALID_CREDENTIALS", "아이디 또는 비밀번호가 올바르지 않습니다"
        )
    return {"access_token": create_access_token(user.id), "token_type": "bearer"}
