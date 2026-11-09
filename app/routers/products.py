# 상품 등록·목록 엔드포인트 (API.md 항목 1, 1-2 / US-08 / F-01)
# 수정 엔드포인트는 API.md에 항목이 없고
# first-feature.md 2절 #2가 '오늘 만들지 않음'이라 만들지 않았다.

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.product import Product
from app.models.user import StoreUser
from app.schemas.product import ProductCreate, ProductOut

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

    # ② 필수값 누락(REQUIRED_FIELD_MISSING)은 필수 필드가 미정이라 아직 검사하지 않는다

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
