# 로그인(JWT) 요청·응답 스키마. 아이디·이메일 필드가 없어 store_user_id로 받는다.

from pydantic import BaseModel


class PasswordIn(BaseModel):
    store_user_id: int
    password: str


class LoginIn(BaseModel):
    store_user_id: int
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
