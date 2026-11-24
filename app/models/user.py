# 매장 사용자 모델 (DATA-MODEL.md 매장 사용자: store_id, role)
# API.md 공통 규칙 [제안]: 요청 헤더 X-User-Id로 사용자를 찾고,
# 그 사용자의 store_id·role을 쓴다.
# 2026-11-24: 로그인(JWT)을 추가만 했다 — X-User-Id는 그대로 둔다. 아이디·
# 이메일 필드가 없어 store_user_id + 비밀번호로 로그인한다 (POST /auth/login).

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class StoreUser(Base):
    __tablename__ = "store_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # 사장님 / 직원 (DATA-MODEL.md 그대로 한국어로 저장. 영문 코드로 바꿀지는 미정)
    role: Mapped[str] = mapped_column(String, nullable=False)
    # 로그인 비밀번호 해시 (pbkdf2_hmac, "salt16진수:해시16진수"). 아직 설정하지
    # 않은 사용자는 null — POST /auth/register-password로 처음 한 번만 정한다
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
