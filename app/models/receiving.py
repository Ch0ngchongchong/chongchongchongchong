# 입고 검수 흐름 모델 (첫 데모 시나리오 2~5단계 / US-03·US-04 / R3)
# 기존 Inspection(app/models/inspection.py)은 고치지 않고, 검수 건에 딸린 정보를
# 별도 테이블로 둔다.
# 검수 건 상태는 Inspection.status에 03 3-2의 한국어 이름으로 저장한다.
#
# - InspectionDocument: 올린 명세서 원본(사진·PDF)의 저장 위치.
#   원본은 LLM에 보내지 않는다.
# - InspectionLine: 판독 초안 줄(OCR이 읽은 값 + 품목 후보)과 직원 확정값.
#   확정 때의 환산값·기준 단가를 줄에 따로 저장해, 나중에 상품을 수정해도
#   이미 재고 반영 완료된 건의 값은 바뀌지 않는다 (US-08 인수 조건 #2).
# - Inventory: 매장·상품별 현재 재고 (기준 단위). 행이 없으면 0으로 본다.

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.inspection import INSPECTION_UPLOAD_WAITING

# 입고 검수 건 상태 (03 3-2). 처음 상태는 inspection.py에 있는 값을 그대로 쓴다.
INSPECTION_STATUS_UPLOAD_WAITING = INSPECTION_UPLOAD_WAITING  # 업로드 대기
INSPECTION_READING = "판독 중"
INSPECTION_STAFF_REVIEW = "직원 확인 대기"
INSPECTION_OWNER_APPROVAL = "사장 승인 대기"  # US-06 (이번 데모에서는 들어가기만 한다)
INSPECTION_STOCK_APPLIED = "재고 반영 완료"


class InspectionDocument(Base):
    """검수 건에 올린 거래명세서 원본.
    다시 올리면 행이 하나 더 생기고 가장 최근 것을 쓴다."""

    __tablename__ = "inspection_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inspection_id: Mapped[int] = mapped_column(
        ForeignKey("inspections.id"), nullable=False, index=True
    )
    uploaded_by: Mapped[int] = mapped_column(
        ForeignKey("store_users.id"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    # 서버 디스크 경로. 응답으로 내보내지 않는다.
    stored_path: Mapped[str] = mapped_column(String, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 판독 실패 이유 (실패하면 검수 건은 `업로드 대기`로 돌아간다, US-03)
    read_error: Mapped[str | None] = mapped_column(String, nullable=True)


class InspectionLine(Base):
    """판독 초안의 한 줄.
    read_* 는 OCR이 읽은 값(LLM은 글자를 읽지 않고 서식만 정리한다),
    candidates 는 품목 후보 최대 3개 [{product_id, score, reason}],
    product_id·quantity 는 지금 고른 값
    (처음엔 1순위 후보·읽은 수량, 직원이 고칠 수 있음),
    applied_* 는 확정해서 재고에 반영할 때의 값 스냅샷이다."""

    __tablename__ = "inspection_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inspection_id: Mapped[int] = mapped_column(
        ForeignKey("inspections.id"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)

    read_name: Mapped[str] = mapped_column(String, nullable=False)
    read_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    read_unit: Mapped[str | None] = mapped_column(String, nullable=True)
    read_unit_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    read_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    candidates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id"), nullable=True
    )
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)

    applied_base_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    applied_conversion_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    applied_unit_price: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Inventory(Base):
    """매장·상품별 현재 재고 (기준 단위). 재고는 직원 확정 뒤 시스템만 바꾼다 (R3)."""

    __tablename__ = "inventories"
    __table_args__ = (
        UniqueConstraint("store_id", "product_id", name="uq_inventories_store_product"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
