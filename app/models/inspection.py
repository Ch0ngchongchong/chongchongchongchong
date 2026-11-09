# 입고 검수 건 모델 (DATA-MODEL.md 입고 검수 건 / 03 3-2 핵심 대상)
# 지금은 US-01의 "발주가 입고 대기가 되면 업로드 대기 검수 건 1건 생성"까지만 쓴다.
# exception_reason·reject_reason은 US-04·US-06을 만들 때 추가한다.
# store_id를 직접 둘지는 미정이라(DATA-MODEL.md) 발주 건을 거쳐 매장을 확인한다.

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# 입고 검수 건 상태 (03 3-2). 지금은 처음 상태만 쓴다.
INSPECTION_UPLOAD_WAITING = "업로드 대기"


class Inspection(Base):
    __tablename__ = "inspections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
