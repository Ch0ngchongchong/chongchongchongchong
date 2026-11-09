# 발주 건·발주 줄 모델 (DATA-MODEL.md 발주 건 / US-01·US-02 / F-02)
# 상태값은 03-rules-states-llm.md·DATA-MODEL.md의 한국어 이름을 그대로 저장한다
# (영문 코드로 바꿀지는 미정).

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# 발주 건 상태 (DATA-MODEL.md 발주 건 status)
ORDER_DRAFT = "발주 초안"
ORDER_CONFIRMED = "발주 확인 완료"
ORDER_SENT = "공급처 전달 완료"
ORDER_AWAITING_DELIVERY = "입고 대기"
ORDER_RECEIVED = "입고 완료"
ORDER_CANCELED = "발주 취소"


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # 필수 여부 미정 (DATA-MODEL.md) — 정해질 때까지 빈 값을 허용한다
    supplier: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)

    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        order_by="PurchaseOrderLine.id",
    )


class PurchaseOrderLine(Base):
    """발주 건의 lines (product_id, quantity). 단위 필드는 DATA-MODEL.md에 없어
    두지 않았다 (화면 시안에는 단위가 있음 — 팀 확인 필요)."""

    __tablename__ = "purchase_order_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    # 1 이상 (US-01)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="lines")
