# 상품 요청·응답 스키마 (API.md 항목 1, 1-2 / US-08)
# store_id는 요청으로 받지 않는다.
# 로그인한 사용자의 매장으로 정한다 (API.md 공통 규칙 [제안]).

from pydantic import BaseModel, ConfigDict, field_validator

# 필수 입력값: product_code만 (DATA-MODEL.md, 2026-11-03 확정).
# 비어 있으면 API.md 항목 1 실패 응답 ② REQUIRED_FIELD_MISSING으로
# 돌려준다 (app/main.py).
REQUIRED_PRODUCT_FIELDS = ("product_code",)


def _reject_blank(value: str | None) -> str:
    # 빈 문자열·공백만 있는 값·null은 '비어 있음'으로 본다
    if value is None or not value.strip():
        raise ValueError("필수값이 비어 있습니다")
    return value


class ProductCreate(BaseModel):
    product_code: str
    name: str | None = None
    spec: str | None = None
    base_unit: str | None = None
    pack_unit: str | None = None
    conversion_qty: int | None = None
    base_unit_price: int | None = None

    _check_product_code = field_validator("product_code")(_reject_blank)


class ProductUpdate(BaseModel):
    """상품 수정 요청 (US-08 인수 조건 #2). 보낸 필드만 바꾼다.
    product_code를 보낼 때는 비울 수 없다. 나머지는 null로 보내면 값을 지운다."""

    product_code: str | None = None
    name: str | None = None
    spec: str | None = None
    base_unit: str | None = None
    pack_unit: str | None = None
    conversion_qty: int | None = None
    base_unit_price: int | None = None

    # 보내지 않은 필드에는 검사가 돌지 않는다 (기본값은 검증하지 않음)
    _check_product_code = field_validator("product_code")(_reject_blank)


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
