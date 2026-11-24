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
    # 이 발주의 최종 입고 금액이 이 값을 넘으면 입고 확정 때 사장 승인이
    # 필요하다 (2026-11-16 멘토 데모 피드백 팀 결정: "최종 금액이 한도를
    # 넘으면 알람을 준다"). 사장님이 발주 작성 때 직접 정한다. 비워 두면
    # 보지 않는다. backlog.md에는 아직 반영되지 않았다.
    amount_alert_threshold: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

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


class PurchaseOrderLimit(Base):
    """R7 발주 수량 한도 (2026-11-16 멘토 데모 피드백 팀 결정: 상품별로 사장님이
    직접 설정). product_id가 아니라 상품명·단위로 저장한다
    (Ch0ngchongchong/frontend README 계약). 발주 승인 때 발주 줄의 상품 이름·
    기준 단위가 같은 한도를 찾아 비교한다 — 상품을 나중에 고쳐도 한도 자체는
    그대로 남고, 이름이 바뀌면 더는 맞지 않게 된다."""

    __tablename__ = "purchase_order_limits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    product: Mapped[str] = mapped_column(String, nullable=False)
    limit: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str] = mapped_column(String, nullable=False)
