# 상품 요청·응답 스키마 (API.md 항목 1, 1-2)
# store_id는 요청으로 받지 않는다.
# 로그인한 사용자의 매장으로 정한다 (API.md 공통 규칙 [제안]).

from pydantic import BaseModel, ConfigDict


class ProductCreate(BaseModel):
    product_code: str
    name: str | None = None
    spec: str | None = None
    base_unit: str | None = None
    pack_unit: str | None = None
    conversion_qty: int | None = None
    base_unit_price: int | None = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    store_id: int
    product_code: str
    name: str | None
    spec: str | None
    base_unit: str | None
    pack_unit: str | None
    conversion_qty: int | None
    base_unit_price: int | None
