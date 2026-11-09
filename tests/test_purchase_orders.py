# US-01 발주 작성·승인·전달 / US-02 공급처 전달 전 발주 취소 (F-02)
# 사용자: conftest.py 시드 — 1 = 매장 1 사장님, 2 = 매장 1 직원, 3 = 매장 2 사장님
# 만들지 않은 인수 조건: US-01 R7 수량 한도 경고 (한도 값 미정)
# '재고가 바뀌지 않는다'(R3)는 재고 모델이 아직 없어, 재고를 바꾸는 코드가
# 발주 API에 없다는 것으로만 확인된다 (US-04 재고 반영을 만들 때 테스트 추가).

import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models.inspection import Inspection
from app.models.purchase_order import PurchaseOrder

OWNER = {"X-User-Id": "1"}
STAFF = {"X-User-Id": "2"}
OTHER_STORE_OWNER = {"X-User-Id": "3"}


@pytest.fixture
def product_id(client):
    # DATA-MODEL.md 시드 #2
    response = client.post(
        "/products",
        json={"product_code": "P-0123", "name": "서울우유 1000ml"},
        headers=OWNER,
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


@pytest.fixture
def draft_order(client, product_id):
    # DATA-MODEL.md 시드 #4 (상태만 발주 초안으로 시작)
    response = client.post(
        "/purchase-orders",
        json={
            "supplier": "(가상) 유제품 공급처 A",
            "lines": [{"product_id": product_id, "quantity": 10}],
        },
        headers=OWNER,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _status(client, order_id):
    response = client.get(f"/purchase-orders/{order_id}", headers=OWNER)
    assert response.status_code == 200, response.text
    return response.json()["status"]


def _inspections(order_id):
    with SessionLocal() as db:
        return db.scalars(
            select(Inspection).where(Inspection.purchase_order_id == order_id)
        ).all()


def _approve(client, order_id, headers=OWNER):
    return client.post(f"/purchase-orders/{order_id}/approve", headers=headers)


def _mark_delivered(client, order_id, headers=OWNER):
    return client.post(f"/purchase-orders/{order_id}/mark-delivered", headers=headers)


def _cancel(client, order_id, headers=OWNER):
    return client.post(f"/purchase-orders/{order_id}/cancel", headers=headers)


def _order_count():
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(PurchaseOrder))


# ---------- US-01 (정상) ----------


def test_us01_saving_products_and_quantity_creates_draft(client, product_id):
    response = client.post(
        "/purchase-orders",
        json={"lines": [{"product_id": product_id, "quantity": 1}]},
        headers=OWNER,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "발주 초안"
    assert body["lines"] == [{"product_id": product_id, "quantity": 1}]


def test_us01_approve_then_mark_delivered_goes_to_awaiting_delivery(
    client, draft_order
):
    assert _approve(client, draft_order["id"]).status_code == 200
    assert _status(client, draft_order["id"]) == "발주 확인 완료"

    assert _mark_delivered(client, draft_order["id"]).status_code == 200
    assert _status(client, draft_order["id"]) == "입고 대기"


def test_us01_awaiting_delivery_creates_one_upload_waiting_inspection(
    client, draft_order
):
    assert _inspections(draft_order["id"]) == []
    _approve(client, draft_order["id"])
    assert _inspections(draft_order["id"]) == []  # 승인만으로는 만들어지지 않는다
    _mark_delivered(client, draft_order["id"])

    inspections = _inspections(draft_order["id"])
    assert len(inspections) == 1
    assert inspections[0].status == "업로드 대기"


# ---------- US-01 (실패·거절) ----------


@pytest.mark.parametrize("quantity", [0, -1])
def test_us01_nonpositive_quantity_is_not_saved(client, product_id, quantity):
    response = client.post(
        "/purchase-orders",
        json={"lines": [{"product_id": product_id, "quantity": quantity}]},
        headers=OWNER,
    )
    assert response.status_code >= 400
    assert _order_count() == 0


def test_us01_unregistered_product_is_not_saved(client, product_id):
    response = client.post(
        "/purchase-orders",
        json={
            "lines": [
                {"product_id": product_id, "quantity": 1},
                {"product_id": product_id + 999, "quantity": 1},
            ]
        },
        headers=OWNER,
    )
    assert response.status_code >= 400
    assert _order_count() == 0


def test_us01_other_store_product_counts_as_unregistered(client, product_id):
    # 매장 2 사장님이 매장 1 상품으로 발주할 수 없다
    response = client.post(
        "/purchase-orders",
        json={"lines": [{"product_id": product_id, "quantity": 1}]},
        headers=OTHER_STORE_OWNER,
    )
    assert response.status_code >= 400
    assert _order_count() == 0


# ---------- US-01 (권한) ----------


def test_us01_staff_cannot_approve(client, draft_order):
    assert _approve(client, draft_order["id"], headers=STAFF).status_code >= 400
    assert _status(client, draft_order["id"]) == "발주 초안"


def test_us01_staff_cannot_mark_delivered(client, draft_order):
    _approve(client, draft_order["id"])
    response = _mark_delivered(client, draft_order["id"], headers=STAFF)
    assert response.status_code >= 400
    assert _status(client, draft_order["id"]) == "발주 확인 완료"
    assert _inspections(draft_order["id"]) == []


def test_us01_other_store_cannot_view_order(client, draft_order):
    response = client.get(
        f"/purchase-orders/{draft_order['id']}", headers=OTHER_STORE_OWNER
    )
    assert response.status_code >= 400
    listed = client.get("/purchase-orders", headers=OTHER_STORE_OWNER).json()
    assert draft_order["id"] not in [order["id"] for order in listed]


# ---------- US-02 ----------


def test_us02_cancel_draft_becomes_canceled(client, draft_order):
    assert _cancel(client, draft_order["id"]).status_code == 200
    assert _status(client, draft_order["id"]) == "발주 취소"
    assert _inspections(draft_order["id"]) == []


def test_us02_delivered_order_cannot_be_canceled(client, draft_order):
    # 전달 완료로 표시하면 한 요청에서 `공급처 전달 완료` → `입고 대기`까지 가므로
    # `공급처 전달 완료`에 머무는 발주는 없다.
    # 전달 완료 표시 뒤(`입고 대기`)로 확인한다.
    _approve(client, draft_order["id"])
    _mark_delivered(client, draft_order["id"])
    assert _cancel(client, draft_order["id"]).status_code >= 400
    assert _status(client, draft_order["id"]) == "입고 대기"


def test_us02_staff_cannot_cancel(client, draft_order):
    assert _cancel(client, draft_order["id"], headers=STAFF).status_code >= 400
    assert _status(client, draft_order["id"]) == "발주 초안"


def test_us02_canceled_is_final_state(client, draft_order):
    _cancel(client, draft_order["id"])
    assert _approve(client, draft_order["id"]).status_code >= 400
    assert _mark_delivered(client, draft_order["id"]).status_code >= 400
    assert _cancel(client, draft_order["id"]).status_code >= 400
    assert _status(client, draft_order["id"]) == "발주 취소"
    assert _inspections(draft_order["id"]) == []
