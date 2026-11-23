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
    # 담당 직원 (2026-11-16 멘토 데모 피드백 팀 결정: "직원은 담당 입고 건만
    # 수정 가능"). 처음 명세서를 올린 직원으로 정하고, 올리기 전에는 비어 있다.
    # 사장님이 직접 올리면 담당자를 정하지 않는다(사장님은 모든 건을 다룰 수 있어서).
    # backlog.md에는 아직 반영되지 않았다.
    assigned_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("store_users.id"), nullable=True
    )
