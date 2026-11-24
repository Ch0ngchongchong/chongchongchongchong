# US-01 발주 작성·승인·전달 / US-02 공급처 전달 전 발주 취소 —
# 인수 조건 중 test_purchase_orders.py가 확인하지 않는 것
# 근거: document 저장소 docs/requirements/backlog.md US-01·US-02 인수 조건
# 사용자: conftest.py 시드 — 1 = 매장 1 사장님, 2 = 매장 1 직원, 3 = 매장 2 사장님
# test_purchase_orders.py 머리 주석의 "재고 모델이 아직 없어 R3는 나중에 테스트 추가"를
# 이 파일에서 채운다 (지금은 GET /inventory가 있음).
#
# 이 파일에서 다루지 않은 인수 조건 (팀 질문으로 남김)
#  - US-01 (실패·거절) 한 상품 수량이 한도를 넘으면 승인 전 경고 (R7): 한도 값 미정
#  - US-02 `발주 확인 완료`에서 취소할 수 있는지: backlog US-02 미확정
#  - US-01 (화면) 사장님 화면 크기 기준: 화면(frontend) 테스트 범위

import pytest

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


def _stock(client, product_id):
    response = client.get("/inventory", headers=OWNER)
    assert response.status_code == 200, response.text
    return next(
        (row["quantity"] for row in response.json() if row["product_id"] == product_id),
        0,
    )


def _upload_waiting_inspections(client):
    response = client.get(
        "/inspections", params={"status": "업로드 대기"}, headers=STAFF
    )
    assert response.status_code == 200, response.text
    return response.json()


def _post(client, order_id, action, headers=OWNER):
    return client.post(f"/purchase-orders/{order_id}/{action}", headers=headers)


# ---------- US-01 (정상) 어느 단계에서도 재고는 바뀌지 않는다 (R3) ----------


def test_us01_stock_does_not_change_at_any_order_step(client, product_id):
    # US-01 (정상) 발주 작성·승인·전달 어느 단계에서도 재고 수량은 바뀌지 않는다 (R3)
    assert _stock(client, product_id) == 0
    order = client.post(
        "/purchase-orders",
        json={"lines": [{"product_id": product_id, "quantity": 10}]},
        headers=OWNER,
    ).json()
    assert _stock(client, product_id) == 0  # 작성
    assert _post(client, order["id"], "approve").status_code == 200
    assert _stock(client, product_id) == 0  # 승인
    assert _post(client, order["id"], "mark-delivered").status_code == 200
    assert _status(client, order["id"]) == "입고 대기"
    assert _stock(client, product_id) == 0  # 전달 → 입고 대기


# ---------- US-01 (정상) 입고 대기가 되면 검수 건이 1건만 ----------


def test_us01_marking_delivered_twice_still_makes_one_inspection(client, draft_order):
    # US-01 (정상) 발주 건이 `입고 대기`가 되면 연결된 입고 검수 건이 `업로드 대기`
    # 상태로 1건 만들어진다 — 전달 완료를 한 번 더 눌러도 1건이다
    order_id = draft_order["id"]
    _post(client, order_id, "approve")
    assert _post(client, order_id, "mark-delivered").status_code == 200
    _post(client, order_id, "mark-delivered")
    inspections = [
        row
        for row in _upload_waiting_inspections(client)
        if row["purchase_order_id"] == order_id
    ]
    assert len(inspections) == 1
    assert _status(client, order_id) == "입고 대기"


# ---------- US-01 (권한) 다른 매장 사용자 ----------


@pytest.mark.parametrize("action", ["approve", "mark-delivered"])
def test_us01_other_store_cannot_change_order(client, draft_order, action):
    # US-01 (권한) 다른 매장 사용자는 이 발주를 조회할 수 없다
    # (볼 수 없는 발주는 승인하거나 전달 완료로 바꿀 수도 없다)
    order_id = draft_order["id"]
    if action == "mark-delivered":
        _post(client, order_id, "approve")
    before = _status(client, order_id)
    response = _post(client, order_id, action, headers=OTHER_STORE_OWNER)
    assert response.status_code >= 400
    assert _status(client, order_id) == before
    assert _upload_waiting_inspections(client) == []


# ---------- US-02 (정상) 취소된 발주는 재고를 바꾸지 않는다 ----------


def test_us02_cancel_does_not_change_stock(client, product_id, draft_order):
    # US-02 (정상) 취소된 발주에는 입고 검수 건이 만들어지지 않고 재고도 바뀌지 않는다
    # (검수 건은 test_purchase_orders.py에서 확인)
    assert _post(client, draft_order["id"], "cancel").status_code == 200
    assert _status(client, draft_order["id"]) == "발주 취소"
    assert _stock(client, product_id) == 0


# ---------- US-02 (권한) 다른 매장 사용자 ----------


def test_us02_other_store_cannot_cancel(client, draft_order):
    # US-01 (권한) 다른 매장 사용자는 이 발주를 조회할 수 없다 → 취소할 수도 없다
    response = _post(client, draft_order["id"], "cancel", headers=OTHER_STORE_OWNER)
    assert response.status_code >= 400
    assert _status(client, draft_order["id"]) == "발주 초안"
