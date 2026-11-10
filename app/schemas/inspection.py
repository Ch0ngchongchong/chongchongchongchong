# 입고 검수 건·재고 요청·응답 스키마 (첫 데모 2~5단계 / US-03·US-04)
# API.md에 아직 항목이 없어 모두 [제안]이다.

from datetime import datetime

from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: int
    filename: str
    content_type: str
    uploaded_at: datetime
    # 판독 실패 안내. 있으면 화면에서 '다시 올려 주세요'를 보여 준다 (US-03)
    read_error: str | None


class CandidateOut(BaseModel):
    product_id: int
    score: float
    reason: str


class ReadValuesOut(BaseModel):
    """OCR이 읽은 값 그대로 (고치지 않음)"""

    name: str
    quantity: int | None
    unit: str | None
    unit_price: int | None
    amount: int | None


class InspectionLineOut(BaseModel):
    id: int
    line_no: int
    read: ReadValuesOut
    candidates: list[CandidateOut]
    # 지금 고른 값 (처음엔 1순위 후보·읽은 수량)
    product_id: int | None
    quantity: int | None
    unit: str | None
    # 기준 단위로 바꾼 수량과 발주 수량
    base_quantity: int | None
    order_quantity: int | None
    # 일치 / 확인 필요 / 발주에 없음 / 수량 다름 / 단가 다름
    match_status: str


class MissingOrderLineOut(BaseModel):
    product_id: int
    order_quantity: int


class InspectionOut(BaseModel):
    id: int
    purchase_order_id: int
    status: str
    # true면 화면 위쪽에 "AI가 읽은 초안이에요. 확인한 뒤 확정해 주세요" 배너를 띄운다
    ai_draft: bool
    document: DocumentOut | None
    lines: list[InspectionLineOut]
    missing_order_lines: list[MissingOrderLineOut]
    # 직원이 채워야 하는 칸 수. 0이어야 확정할 수 있다
    check_count: int
    # 발주와 모두 같으면 true (확정하면 바로 재고 반영)
    all_match: bool


class InspectionLineUpdate(BaseModel):
    """직원이 품목 후보를 고르거나 수량을 고칠 때. 보낸 필드만 바뀐다."""

    product_id: int | None = None
    quantity: int | None = None


class InventoryOut(BaseModel):
    product_id: int
    product_code: str
    name: str | None
    base_unit: str | None
    quantity: int
