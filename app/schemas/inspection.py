# 입고 검수 건·재고·이력·알림 요청·응답 스키마 (US-03~US-07)
# API.md에 아직 항목이 없어 모두 [제안]이다.

from datetime import datetime

from pydantic import BaseModel


class FileOut(BaseModel):
    id: int
    filename: str
    content_type: str
    uploaded_at: datetime


class DocumentOut(FileOut):
    # 판독 실패 안내. 있으면 화면에서 '다시 올려 주세요'를 보여 준다 (US-03)
    read_error: str | None


class CandidateOut(BaseModel):
    product_id: int
    score: float
    reason: str


class ReadValuesOut(BaseModel):
    """OCR이 읽고 LLM이 정리한 값 그대로 (직원이 고쳐도 바뀌지 않음)"""

    name: str
    spec: str | None
    quantity: int | None
    unit: str | None
    unit_price: int | None
    amount: int | None


class InspectionLineOut(BaseModel):
    id: int
    line_no: int
    read: ReadValuesOut
    candidates: list[CandidateOut]
    # LLM이 확신하지 못한 필드 (그 값은 비어 있다)
    uncertain_fields: list[str]
    # 지금 고른 값 (처음엔 1순위 후보·읽은 수량)
    product_id: int | None
    quantity: int | None
    unit: str | None
    # 직원이 직접 넣은 기준 단위 수량 (단위 환산이 안 될 때, US-05)
    manual_base_quantity: int | None
    damaged: bool
    checked: bool
    # 기준 단위로 바꾼 수량과 발주 수량
    base_quantity: int | None
    order_quantity: int | None
    # 아직 풀리지 않은 확인할 칸 (화면에서 강조)
    open_checks: list[str]
    # 일치 / 확인 필요 / 발주에 없음 / 수량 다름 / 단가 다름 / 파손
    match_status: str
    # 재고에 반영할 때 쓴 기준 단위 1개당 단가 (반영 전에는 null)
    applied_unit_price: int | None


class SummaryOut(BaseModel):
    """명세서 전체 판독값과 규칙 검증"""

    document_date: str | None
    total_amount: int | None
    line_amount_sum: int | None
    uncertain_fields: list[str]
    checked: bool
    open_checks: list[str]


class OrderGapOut(BaseModel):
    product_id: int
    order_quantity: int
    received_quantity: int
    short_quantity: int


class InspectionOut(BaseModel):
    id: int
    purchase_order_id: int
    status: str
    # true면 화면 위쪽에 "AI가 읽은 초안이에요. 확인한 뒤 확정해 주세요" 배너를 띄운다
    ai_draft: bool
    document: DocumentOut | None
    exception_photos: list[FileOut]
    summary: SummaryOut | None
    lines: list[InspectionLineOut]
    # 발주에는 있는데 명세서에 없는 줄
    missing_order_lines: list[OrderGapOut]
    # 발주보다 적게 들어온 줄 (승인 뒤 미입고로 남는 수량, US-06)
    short_order_lines: list[OrderGapOut]
    # 직원이 풀어야 하는 칸 수. 0이어야 확정할 수 있다
    check_count: int
    # 예외 종류 (비어 있으면 일반 건)
    exception_types: list[str]
    # 발주와 모두 같으면 true (확정하면 바로 재고 반영)
    all_match: bool
    exception_reason: str | None
    reject_reason: str | None


class InspectionCreate(BaseModel):
    """`검수 종료` 뒤 다시 납품됐을 때 같은 발주에 새 검수 건을 만든다 (US-06)"""

    purchase_order_id: int


class InspectionLineUpdate(BaseModel):
    """직원이 줄을 고치거나 확인할 때. 보낸 필드만 바뀐다.
    고치거나 확인하면 그 줄의 강조 칸(후보 여러 개·불확실한 값·금액 규칙)을
    확인한 것으로 본다. checked=false를 함께 보내면 확인하지 않은 것으로 둔다."""

    product_id: int | None = None
    quantity: int | None = None
    manual_base_quantity: int | None = None
    damaged: bool | None = None
    checked: bool | None = None


class SummaryUpdate(BaseModel):
    """명세서 전체 칸(합계 불일치·불확실한 값)을 직원이 확인했을 때"""

    checked: bool


class ConfirmRequest(BaseModel):
    # 예외 건이면 필수 (US-06). 일반 건이면 무시한다
    exception_reason: str | None = None


class RejectRequest(BaseModel):
    reject_reason: str | None = None


class InventoryOut(BaseModel):
    product_id: int
    product_code: str
    name: str | None
    base_unit: str | None
    quantity: int


class ChangeLogOut(BaseModel):
    id: int
    changed_by: int
    changed_at: datetime
    action: str
    field: str | None
    old_value: str | None
    new_value: str | None


class ReadingLogOut(BaseModel):
    id: int
    file_id: int
    succeeded: bool
    input_tokens: int
    output_tokens: int
    cost: float
    elapsed_seconds: float
    created_at: datetime


class HistoryOut(BaseModel):
    inspection_id: int
    changes: list[ChangeLogOut]
    reading_logs: list[ReadingLogOut]


class NotificationOut(BaseModel):
    id: int
    inspection_id: int | None
    message: str
    created_at: datetime
    read_at: datetime | None
