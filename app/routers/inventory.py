# 재고 조회 (첫 데모 3·5단계: "재고가 아직 0" → "0 → 10개")
# API.md에 아직 항목이 없어 [제안]이다. 재고를 바꾸는 API는 없다.
# 재고는 입고 확정(POST /inspections/{id}/confirm) 안에서만 바뀐다 (R3).

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.product import Product
from app.models.receiving import Inventory
from app.models.user import StoreUser
from app.routers.products import get_current_user
from app.schemas.inspection import InventoryOut

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("", response_model=list[InventoryOut])
def list_inventory(
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """내 매장 상품별 현재 재고 (기준 단위). 한 번도 입고되지 않은 상품은 0이다."""
    rows = db.execute(
        select(Product, Inventory.quantity)
        .outerjoin(
            Inventory,
            (Inventory.product_id == Product.id)
            & (Inventory.store_id == Product.store_id),
        )
        .where(Product.store_id == user.store_id)
        .order_by(Product.id)
    ).all()
    return [
        {
            "product_id": product.id,
            "product_code": product.product_code,
            "name": product.name,
            "base_unit": product.base_unit,
            "quantity": quantity or 0,
        }
        for product, quantity in rows
    ]
