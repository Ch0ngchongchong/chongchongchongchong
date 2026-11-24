# 로그인(JWT) — 2026-11-24 추가만 함, 기존 X-User-Id 헤더 방식은 그대로 둔다.
# 시크릿 키는 환경변수 JWT_SECRET에서만 읽는다. 값은 코드에 쓰지 않는다.
# 비밀번호 해시는 새 의존성을 더하지 않으려고 표준 라이브러리 pbkdf2_hmac을 쓴다.

import hashlib
import hmac
import os
import time

import jwt

JWT_ALGORITHM = "HS256"
JWT_EXPIRES_SECONDS = 60 * 60 * 24  # 하루
_PBKDF2_ITERATIONS = 200_000


def _jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise RuntimeError("환경변수 JWT_SECRET이 설정되지 않았습니다.")
    return secret


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt_hex, _, digest_hex = stored.partition(":")
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt_hex), _PBKDF2_ITERATIONS
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


def create_access_token(user_id: int) -> str:
    payload = {"sub": str(user_id), "exp": int(time.time()) + JWT_EXPIRES_SECONDS}
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """토큰이 없거나·만료됐거나·서명이 안 맞으면 None (호출하는 쪽에서 401로 처리)."""
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
        return int(payload["sub"])
    except jwt.PyJWTError:
        return None
