# 발주 수량 한도 요청·응답 스키마 (R7, Ch0ngchongchong/frontend README 계약)
# 상품명·단위로 저장한다. product_id가 아니다.

from pydantic import BaseModel, ConfigDict


class PurchaseOrderLimitIn(BaseModel):
    product: str
    limit: int
    unit: str


class PurchaseOrderLimitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product: str
    limit: int
    unit: str
