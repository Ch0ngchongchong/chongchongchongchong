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
    spec: str | None = None
    quantity: int | None
    unit: str | None
    unit_price: int | None
    amount: int | None


class InspectionLineOut(BaseModel):
    id: int
    line_no: int
    read: ReadValuesOut
    candidates: list[CandidateOut]
    # LLM이 확신하지 못해 비워 둔 필드 이름 (US-03). 추측값은 넣지 않는다
    uncertain_fields: list[str] = []
    # 지금 고른 값 (처음엔 1순위 후보·읽은 수량)
    product_id: int | None
    quantity: int | None
    unit: str | None
    unit_price: int | None = None
    amount: int | None = None
    # 단위를 환산할 수 없을 때 직원이 직접 넣은 기준 단위 수량 (US-05)
    manual_base_quantity: int | None = None
    # 직원이 파손을 표시함 → 예외 건 (US-04)
    damaged: bool = False
    # 기준 단위로 바꾼 수량과 발주 수량
    base_quantity: int | None
    # 확정해서 재고에 반영될 때 저장한 기준 단위 단가 (US-08 인수 조건 #2).
    # 확정 전이면 아직 저장된 값이 없어 비어 있다
    applied_unit_price: int | None = None
    order_quantity: int | None
    # 일치 / 확인 필요 / 발주에 없음 / 수량 다름 / 단가 다름 / 파손
    match_status: str
    # 규칙 검증 실패 칸: AMOUNT_MISMATCH(수량×단가≠금액) · NUMBER_NOT_IN_OCR
    # (OCR 글자에 없는 숫자). 비어 있으면 통과
    rule_violations: list[str]
    # 직원이 위 칸을 확인했다는 표시 (US-03 안전장치)
    checked: bool


class MissingOrderLineOut(BaseModel):
    product_id: int
    order_quantity: int


class ShortOrderLineOut(BaseModel):
    """발주보다 적게 들어온 줄 (0개보다는 많지만 발주 수량에 못 미침, US-06)"""

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
    exception_reason: str | None = None
    reject_reason: str | None = None
    document: DocumentOut | None
    lines: list[InspectionLineOut]
    missing_order_lines: list[MissingOrderLineOut]
    # 발주보다 적게 들어온 줄 (승인 뒤 미입고로 남는 수량, US-06)
    short_order_lines: list[ShortOrderLineOut] = []
    # 직원이 채워야 하는 칸 수. 0이어야 확정할 수 있다
    check_count: int
    # 발주와 모두 같으면 true (확정하면 바로 재고 반영)
    all_match: bool
    # 판독이 읽은 명세서 합계. 못 찾았으면 null (검증하지 않음)
    total_amount: int | None
    # 줄 금액 합≠합계면 true (규칙 검증 실패 칸)
    summary_mismatch: bool
    # 위 칸을 사장님/직원이 확인했다는 표시
    summary_checked: bool
    # 확정하면 실제로 반영될 금액
    final_amount: int
    # final_amount이 발주의 금액 경고 기준을 넘으면 true (예외 건으로 분류)
    amount_over_limit: bool
    # 판독이 읽은 명세서 작성일. LLM이 돌려준 글자 그대로(형식 검증 안 함).
    # 확신 못 했거나 못 찾았으면 null
    document_date: str | None = None


class InspectionLineUpdate(BaseModel):
    """직원이 품목 후보를 고르거나 수량을 고칠 때. 보낸 필드만 바뀐다.
    고치면(새 값이 기존과 달라도) 그 줄의 강조 칸(후보 여러 개·규칙 검증 실패)을
    확인한 것으로 본다. checked를 직접 보내면 그 값을 따른다."""

    product_id: int | None = None
    quantity: int | None = None
    unit: str | None = None
    # OCR·LLM이 잘못 읽은 단가·금액을 직원이 고친다 (US-07 정확도 지표의
    # 비교 기준이 되는 '지금 고른 값'. read_unit_price·read_amount는
    # 원본 그대로 둔다)
    unit_price: int | None = None
    amount: int | None = None
    # 단위를 환산할 수 없을 때 직원이 직접 넣는 기준 단위 수량 (US-05)
    manual_base_quantity: int | None = None
    # 직원이 파손을 표시함 → 예외 건 (US-04)
    damaged: bool | None = None
    # 규칙 검증 실패 칸을 확인했다는 표시 (US-03 안전장치)
    checked: bool | None = None


class InspectionLineCreate(BaseModel):
    """판독 결과에 없는 줄을 직원이 추가할 때 (US-04 인수 조건, 미팅1 질의 3).
    OCR이 읽은 값이 없으니 품목은 직원이 직접 고른다."""

    product_id: int
    quantity: int
    unit: str | None = None


class InventoryOut(BaseModel):
    product_id: int
    product_code: str
    name: str | None
    base_unit: str | None
    quantity: int


class ReasonInput(BaseModel):
    reason: str
