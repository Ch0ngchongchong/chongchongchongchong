# 발주 요청·응답 스키마 (US-01·US-02). API.md에 아직 항목이 없어 [제안]이다.
# store_id는 요청으로 받지 않고 로그인한 사용자의 매장으로 정한다 (API.md 공통 규칙).

from pydantic import BaseModel, ConfigDict


class PurchaseOrderLineIn(BaseModel):
    product_id: int
    quantity: int


class PurchaseOrderCreate(BaseModel):
    supplier: str | None = None
    lines: list[PurchaseOrderLineIn]


class PurchaseOrderLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    quantity: int


class PurchaseOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    store_id: int
    supplier: str | None
    status: str
    lines: list[PurchaseOrderLineOut]
