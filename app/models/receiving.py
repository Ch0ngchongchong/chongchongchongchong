# 입고 검수 흐름 모델 (US-03·US-04·US-05·US-06 / R3)
# 기존 Inspection(app/models/inspection.py)은 고치지 않고, 검수 건에 딸린 정보를
# 별도 테이블로 둔다. 지금은 create_all()만 쓰므로(Alembic 미정) 이미 있는
# inspections 테이블에 열을 더하면 기존 DB에 반영되지 않기 때문이다.
# 검수 건 상태는 Inspection.status에 03 3-2의 한국어 이름으로 저장한다.
#
# - InspectionDetail: 검수 건 1건당 1행.
#   예외 사유·반려 사유(DATA-MODEL.md 입고 검수 건)와
#   명세서 전체 판독값(작성일·합계·불확실한 필드)
# - InspectionFile: 올린 파일. 명세서 원본(사진·PDF)과 예외 사진.
#   원본은 LLM에 보내지 않는다.
# - InspectionLine: 판독 초안 줄(OCR이 읽은 값 + 품목 후보)과 직원 확정값.
#   확정 때의 환산값·단가를 줄에 따로 저장해, 나중에 상품을 수정해도
#   이미 재고 반영 완료된 건의 값은 바뀌지 않는다 (US-08 인수 조건 #2).
# - Inventory: 매장·상품별 현재 재고 (기준 단위). 행이 없으면 0으로 본다.

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
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
INSPECTION_OWNER_APPROVAL = "사장 승인 대기"
INSPECTION_APPROVED = "승인"
INSPECTION_REJECTED = "반려"
INSPECTION_STOCK_APPLIED = "재고 반영 완료"
INSPECTION_CLOSED = "검수 종료"

# 올린 파일 종류
FILE_STATEMENT = "명세서"
FILE_EXCEPTION_PHOTO = "예외 사진"


class InspectionDetail(Base):
    """검수 건 1건당 1행 (Inspection의 확장)."""

    __tablename__ = "inspection_details"

    inspection_id: Mapped[int] = mapped_column(
        ForeignKey("inspections.id"), primary_key=True
    )
    # 직원이 적는 예외 사유. 예외 건이면 없을 때 확정 불가 (US-06)
    exception_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    # 사장님 반려 사유. 없으면 반려 불가 (US-06)
    reject_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    # 명세서 전체 판독값 (03 3-4 공통 JSON)
    document_date: Mapped[str | None] = mapped_column(String, nullable=True)
    total_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uncertain_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # 합계 불일치·불확실한 값을 직원이 확인했는지
    summary_checked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )


class InspectionFile(Base):
    """검수 건에 올린 파일.
    명세서는 다시 올리면 행이 하나 더 생기고 가장 최근 것을 쓴다."""

    __tablename__ = "inspection_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inspection_id: Mapped[int] = mapped_column(
        ForeignKey("inspections.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)  # 명세서 / 예외 사진
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
    # 판독 실패 이유 (명세서만. 실패하면 검수 건은 `업로드 대기`로 돌아간다, US-03)
    read_error: Mapped[str | None] = mapped_column(String, nullable=True)


class InspectionLine(Base):
    """판독 초안의 한 줄.
    read_* 는 OCR이 읽은 값(LLM은 글자를 읽지 않고 서식만 정리한다),
    candidates 는 품목 후보 최대 3개 [{product_id, score, reason}],
    product_id·quantity 는 지금 고른 값
    (처음엔 1순위 후보·읽은 수량, 직원이 고칠 수 있음),
    applied_* 는 재고에 반영할 때의 값 스냅샷이다."""

    __tablename__ = "inspection_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inspection_id: Mapped[int] = mapped_column(
        ForeignKey("inspections.id"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)

    read_name: Mapped[str] = mapped_column(String, nullable=False)
    read_spec: Mapped[str | None] = mapped_column(String, nullable=True)
    read_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    read_unit: Mapped[str | None] = mapped_column(String, nullable=True)
    read_unit_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    read_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    candidates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # LLM이 확신하지 못한 필드 이름. 이 필드 값은 추측 없이 비워 둔다 (US-03)
    uncertain_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id"), nullable=True
    )
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    # 단위를 환산할 수 없을 때 직원이 직접 넣은 기준 단위 수량 (US-05)
    manual_base_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 직원이 파손을 표시함 → 예외 건 (US-04)
    damaged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 강조된 칸(불확실한 값·규칙 검증 실패·후보 여러 개)을 직원이 확인했는지 (US-04)
    checked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    applied_base_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    applied_conversion_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    applied_unit_price: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Inventory(Base):
    """매장·상품별 현재 재고 (기준 단위).
    직원 확정(일반 건) 또는 사장 승인(예외 건) 뒤에만 시스템이 바꾼다 (R3)."""

    __tablename__ = "inventories"
    __table_args__ = (
        UniqueConstraint("store_id", "product_id", name="uq_inventories_store_product"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
