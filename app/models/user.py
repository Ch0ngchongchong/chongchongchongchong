# 매장 사용자 모델 (DATA-MODEL.md 매장 사용자: store_id, role)
# API.md 공통 규칙 [제안]: 요청 헤더 X-User-Id로 사용자를 찾고,
# 그 사용자의 store_id·role을 쓴다.

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class StoreUser(Base):
    __tablename__ = "store_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # 사장님 / 직원 (DATA-MODEL.md 그대로 한국어로 저장. 영문 코드로 바꿀지는 미정)
    role: Mapped[str] = mapped_column(String, nullable=False)
