# 발주 수량 한도 조회·등록·수정·삭제 (R7)
# 계약은 Ch0ngchongchong/frontend README(상품별 발주 한도)를 그대로 따른다:
# GET/POST /purchase-order-limits, PATCH/DELETE /purchase-order-limits/{id},
# 항목은 {id, product, limit, unit}, 생성·수정 본문은 {product, limit, unit}.
# 등록·수정·삭제는 사장님만 할 수 있다 (US-01 권한: "직원은 발주 수량 한도와
# 최종 금액 한도를 설정하거나 바꿀 수 없다").

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.purchase_order import PurchaseOrderLimit
from app.models.user import StoreUser
from app.routers.products import error_response, forbidden_unless_role, get_current_user
from app.schemas.purchase_order_limit import PurchaseOrderLimitIn, PurchaseOrderLimitOut

router = APIRouter(prefix="/purchase-order-limits", tags=["purchase-order-limits"])

OWNER = "사장님"


def _forbidden_unless_owner(user: StoreUser):
    return forbidden_unless_role(
        user, OWNER, message="사장님만 발주 수량 한도를 설정·변경할 수 있습니다"
    )


def _validate(body: PurchaseOrderLimitIn):
    if not body.product.strip() or not body.unit.strip():
        return error_response(
            400, "REQUIRED_FIELD_MISSING", "상품명과 단위를 입력해 주세요"
        )
    if body.limit < 1:
        return error_response(
            400, "INVALID_PURCHASE_ORDER_LIMIT", "발주 한도는 1 이상이어야 합니다"
        )
    return None


def _find(db: Session, limit_id: int, user: StoreUser) -> PurchaseOrderLimit | None:
    return db.scalar(
        select(PurchaseOrderLimit).where(
            PurchaseOrderLimit.id == limit_id,
            PurchaseOrderLimit.store_id == user.store_id,
        )
    )


def _not_found():
    return error_response(
        404, "PURCHASE_ORDER_LIMIT_NOT_FOUND", "발주 한도를 찾을 수 없습니다"
    )


@router.get("", response_model=list[PurchaseOrderLimitOut])
def list_purchase_order_limits(
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.scalars(
        select(PurchaseOrderLimit)
        .where(PurchaseOrderLimit.store_id == user.store_id)
        .order_by(PurchaseOrderLimit.id)
    ).all()


@router.post("", response_model=PurchaseOrderLimitOut)
def create_purchase_order_limit(
    body: PurchaseOrderLimitIn,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if (denied := _forbidden_unless_owner(user)) is not None:
        return denied
    if (invalid := _validate(body)) is not None:
        return invalid
    limit = PurchaseOrderLimit(store_id=user.store_id, **body.model_dump())
    db.add(limit)
    db.commit()
    db.refresh(limit)
    return limit


@router.patch("/{limit_id}", response_model=PurchaseOrderLimitOut)
def update_purchase_order_limit(
    limit_id: int,
    body: PurchaseOrderLimitIn,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if (denied := _forbidden_unless_owner(user)) is not None:
        return denied
    limit = _find(db, limit_id, user)
    if limit is None:
        return _not_found()
    if (invalid := _validate(body)) is not None:
        return invalid
    for field, value in body.model_dump().items():
        setattr(limit, field, value)
    db.commit()
    db.refresh(limit)
    return limit


@router.delete("/{limit_id}", status_code=204)
def delete_purchase_order_limit(
    limit_id: int,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if (denied := _forbidden_unless_owner(user)) is not None:
        return denied
    limit = _find(db, limit_id, user)
    if limit is None:
        return _not_found()
    db.delete(limit)
    db.commit()
