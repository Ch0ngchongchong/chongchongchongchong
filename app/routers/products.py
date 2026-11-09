# 상품 등록·목록·수정 엔드포인트 (API.md 항목 1, 1-2 / US-08 / F-01)
# 수정(PATCH /products/{id})은 US-08 인수 조건 #2를 위한 것으로,
# API.md에 아직 항목이 없다.
# 경로·응답은 항목 1과 같은 규칙으로 맞춘 [제안]이며 PM이 API.md에 옮겨야 한다.

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.product import Product
from app.models.user import StoreUser
from app.schemas.product import ProductCreate, ProductOut, ProductUpdate

router = APIRouter(prefix="/products", tags=["products"])


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """API.md 공통 규칙 오류 응답 형식: {"error": {"code", "message"}}"""
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def get_current_user(
    x_user_id: int = Header(...),
    db: Session = Depends(get_db),
) -> StoreUser:
    """X-User-Id 헤더로 매장 사용자를 찾는다 (API.md 공통 규칙 [제안]).
    없는 사용자일 때의 응답은 API.md에 없어 미정이다. 임시로 401을 돌려준다."""
    user = db.get(StoreUser, x_user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="등록되지 않은 사용자입니다")
    return user


@router.post("", response_model=ProductOut)
def create_product(
    body: ProductCreate,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # ③ 환산값이 0 이하이면 저장하지 않는다 (US-08)
    if body.conversion_qty is not None and body.conversion_qty <= 0:
        return error_response(
            400, "INVALID_CONVERSION_QTY", "환산값은 0보다 커야 합니다"
        )

    # ① 같은 매장에 상품 코드가 이미 있으면 저장하지 않는다 (US-08)
    exists = db.scalar(
        select(Product.id).where(
            Product.store_id == user.store_id,
            Product.product_code == body.product_code,
        )
    )
    if exists is not None:
        return error_response(
            400, "DUPLICATE_PRODUCT_CODE", "이미 등록된 상품 코드입니다"
        )

    # ② 필수값(product_code) 누락은 요청 검증 단계에서
    #    REQUIRED_FIELD_MISSING으로 막는다 (app/main.py)

    product = Product(store_id=user.store_id, **body.model_dump())
    db.add(product)
    try:
        db.commit()
    except IntegrityError:
        # 동시에 같은 코드가 들어온 경우 DB 고유 제약에서 막힌다
        db.rollback()
        return error_response(
            400, "DUPLICATE_PRODUCT_CODE", "이미 등록된 상품 코드입니다"
        )
    db.refresh(product)
    return product


@router.get("", response_model=list[ProductOut])
def list_products(
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 로그인한 사용자의 매장 상품만 돌려준다.
    # 다른 매장 상품은 목록에 나오지 않는다 (US-08 권한)
    return db.scalars(
        select(Product).where(Product.store_id == user.store_id).order_by(Product.id)
    ).all()


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int,
    body: ProductUpdate,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """상품 수정 (US-08 인수 조건 #2).
    상품 행에는 지금 쓰는 환산값·기준 단가 하나만 둔다. 그래서 수정하면 그 뒤에
    확정하는 건부터 새 값이 쓰인다. 이미 재고 반영 완료된 건의 수량·단가가 바뀌지
    않으려면, 입고 확정(US-04·US-06)을 만들 때 그때의 수량·단가를 검수 건 쪽에
    따로 저장해야 한다 (DATA-MODEL.md '직원 확정값을 어디에 저장할지' 미정).
    직원도 수정할 수 있는지는 미정이라(backlog US-08) 역할로 막지 않는다."""
    # 다른 매장 상품은 없는 상품과 똑같이 다룬다 (US-08 권한).
    # 응답 코드는 API.md에 없어 [제안]으로 404 PRODUCT_NOT_FOUND를 쓴다.
    product = db.scalar(
        select(Product).where(
            Product.id == product_id, Product.store_id == user.store_id
        )
    )
    if product is None:
        return error_response(404, "PRODUCT_NOT_FOUND", "상품을 찾을 수 없습니다")

    changes = body.model_dump(exclude_unset=True)

    # ③ 환산값이 0 이하이면 저장하지 않는다 (US-08, 등록과 같은 규칙)
    conversion_qty = changes.get("conversion_qty")
    if conversion_qty is not None and conversion_qty <= 0:
        return error_response(
            400, "INVALID_CONVERSION_QTY", "환산값은 0보다 커야 합니다"
        )

    # ① 바꾸려는 상품 코드가 같은 매장의 다른 상품에 있으면 저장하지 않는다 (US-08)
    new_code = changes.get("product_code")
    if new_code is not None and new_code != product.product_code:
        exists = db.scalar(
            select(Product.id).where(
                Product.store_id == user.store_id,
                Product.product_code == new_code,
                Product.id != product.id,
            )
        )
        if exists is not None:
            return error_response(
                400, "DUPLICATE_PRODUCT_CODE", "이미 등록된 상품 코드입니다"
            )

    for field, value in changes.items():
        setattr(product, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return error_response(
            400, "DUPLICATE_PRODUCT_CODE", "이미 등록된 상품 코드입니다"
        )
    db.refresh(product)
    return product
