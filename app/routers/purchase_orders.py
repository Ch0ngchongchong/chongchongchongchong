# 발주 작성·승인·전달·취소·조회 엔드포인트 (US-01·US-02 / F-02)
# API.md에 아직 항목이 없다. 경로·오류 코드·HTTP 상태 코드는 항목 1과 같은 규칙으로
# 맞춘 [제안]이며 PM이 API.md에 옮겨야 한다.
# 만들지 않은 것: R7 수량 한도 경고(한도 값 미정), 발주 줄 단위·발주 번호·작성일
# (DATA-MODEL.md에 없음), `발주 확인 완료`에서의 취소(미정, US-02).
# 재고는 이 파일의 어느 API에서도 바꾸지 않는다 (R3).

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.inspection import INSPECTION_UPLOAD_WAITING, Inspection
from app.models.product import Product
from app.models.purchase_order import (
    ORDER_AWAITING_DELIVERY,
    ORDER_CANCELED,
    ORDER_CONFIRMED,
    ORDER_DRAFT,
    PurchaseOrder,
    PurchaseOrderLine,
)
from app.models.user import StoreUser
from app.routers.products import error_response, get_current_user
from app.schemas.purchase_order import PurchaseOrderCreate, PurchaseOrderOut

router = APIRouter(prefix="/purchase-orders", tags=["purchase-orders"])

OWNER = "사장님"  # DATA-MODEL.md 매장 사용자 role


def _forbidden_unless_owner(user: StoreUser):
    # 직원은 발주를 승인·전달 완료·취소할 수 없다 (US-01·US-02 권한)
    if user.role != OWNER:
        return error_response(403, "FORBIDDEN_ROLE", "사장님만 할 수 있습니다")
    return None


def _find_order(db: Session, order_id: int, user: StoreUser) -> PurchaseOrder | None:
    # 다른 매장 발주는 없는 발주와 똑같이 다룬다 (US-01 권한)
    return db.scalar(
        select(PurchaseOrder).where(
            PurchaseOrder.id == order_id, PurchaseOrder.store_id == user.store_id
        )
    )


def _not_found():
    return error_response(404, "PURCHASE_ORDER_NOT_FOUND", "발주를 찾을 수 없습니다")


def _invalid_status(order: PurchaseOrder):
    # 상태가 맞지 않으면 바꾸지 않고 그대로 둔다 (US-02 실패·거절)
    return error_response(
        400,
        "INVALID_STATUS_TRANSITION",
        f"지금 상태({order.status})에서는 할 수 없습니다",
    )


@router.post("", response_model=PurchaseOrderOut)
def create_purchase_order(
    body: PurchaseOrderCreate,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """상품·수량을 골라 저장하면 `발주 초안`이 된다 (US-01 정상).
    발주 작성을 직원도 할 수 있는지는 인수 조건에 없어 역할로 막지 않는다."""
    # 상품을 하나도 고르지 않으면 저장하지 않는다 [제안]
    if not body.lines:
        return error_response(
            400, "REQUIRED_FIELD_MISSING", "필수값이 비어 있습니다: lines"
        )

    # 수량이 0 이하이면 저장하지 않는다 (US-01 실패·거절)
    if any(line.quantity <= 0 for line in body.lines):
        return error_response(400, "INVALID_QUANTITY", "수량은 1 이상이어야 합니다")

    # 이 매장에 등록되지 않은 상품이 있으면 저장하지 않는다 (US-01 실패·거절)
    product_ids = {line.product_id for line in body.lines}
    found = set(
        db.scalars(
            select(Product.id).where(
                Product.id.in_(product_ids), Product.store_id == user.store_id
            )
        )
    )
    if found != product_ids:
        return error_response(
            400, "UNREGISTERED_PRODUCT", "등록되지 않은 상품이 있습니다"
        )

    order = PurchaseOrder(
        store_id=user.store_id,
        supplier=body.supplier,
        status=ORDER_DRAFT,
        lines=[
            PurchaseOrderLine(product_id=line.product_id, quantity=line.quantity)
            for line in body.lines
        ],
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


@router.get("", response_model=list[PurchaseOrderOut])
def list_purchase_orders(
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 내 매장 발주만 돌려준다 (US-01 권한)
    return db.scalars(
        select(PurchaseOrder)
        .where(PurchaseOrder.store_id == user.store_id)
        .order_by(PurchaseOrder.id)
    ).all()


@router.get("/{order_id}", response_model=PurchaseOrderOut)
def get_purchase_order(
    order_id: int,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = _find_order(db, order_id, user)
    if order is None:
        return _not_found()
    return order


@router.post("/{order_id}/approve", response_model=PurchaseOrderOut)
def approve_purchase_order(
    order_id: int,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """`발주 초안` → `발주 확인 완료` (US-01 정상).
    R7 한도 초과 경고는 한도 값이 미정이라 아직 검사하지 않는다."""
    if (denied := _forbidden_unless_owner(user)) is not None:
        return denied
    order = _find_order(db, order_id, user)
    if order is None:
        return _not_found()
    if order.status != ORDER_DRAFT:
        return _invalid_status(order)
    order.status = ORDER_CONFIRMED
    db.commit()
    db.refresh(order)
    return order


@router.post("/{order_id}/mark-delivered", response_model=PurchaseOrderOut)
def mark_purchase_order_delivered(
    order_id: int,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """공급처 전달 완료로 표시하면 `공급처 전달 완료` → `입고 대기`가 되고,
    연결된 입고 검수 건이 `업로드 대기`로 1건 만들어진다 (US-01 정상, 03 3-2).
    `공급처 전달 완료` 다음은 시스템이 바로 `입고 대기`로 넘기므로
    (DATA-MODEL.md 발주 건 상태) 한 요청에서 두 단계를 함께 처리한다."""
    if (denied := _forbidden_unless_owner(user)) is not None:
        return denied
    order = _find_order(db, order_id, user)
    if order is None:
        return _not_found()
    if order.status != ORDER_CONFIRMED:
        return _invalid_status(order)
    order.status = ORDER_AWAITING_DELIVERY
    db.add(Inspection(purchase_order_id=order.id, status=INSPECTION_UPLOAD_WAITING))
    db.commit()
    db.refresh(order)
    return order


@router.post("/{order_id}/cancel", response_model=PurchaseOrderOut)
def cancel_purchase_order(
    order_id: int,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """`발주 초안`이면 `발주 취소`(끝 상태)가 된다 (US-02).
    그 밖의 상태는 취소할 수 없고 그대로 둔다.
    `발주 확인 완료`에서 취소할 수 있는지는 미정이라(US-02 미확정) 지금은 막는다.
    취소된 발주에는 입고 검수 건을 만들지 않는다."""
    if (denied := _forbidden_unless_owner(user)) is not None:
        return denied
    order = _find_order(db, order_id, user)
    if order is None:
        return _not_found()
    if order.status != ORDER_DRAFT:
        return _invalid_status(order)
    order.status = ORDER_CANCELED
    db.commit()
    db.refresh(order)
    return order
