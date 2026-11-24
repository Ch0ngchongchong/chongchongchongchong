# 발주 수량 한도 조회·등록·수정·삭제 (R7)
# 계약 근거: Ch0ngchongchong/frontend README "상품별 발주 한도"
#   GET/POST /purchase-order-limits, PATCH/DELETE /purchase-order-limits/{id},
#   항목 {id, product, limit, unit}, 생성·수정 본문 {product, limit, unit}
# 등록·수정·삭제는 사장님만 (US-01 권한). 승인 때 한도를 실제로 쓰는지는
# test_purchase_orders.py의 R7 테스트에서 확인한다.
# 사용자: conftest.py 시드 — 1 = 매장 1 사장님, 2 = 매장 1 직원, 3 = 매장 2 사장님

import pytest

OWNER = {"X-User-Id": "1"}
STAFF = {"X-User-Id": "2"}
OTHER_STORE_OWNER = {"X-User-Id": "3"}

BODY = {"product": "서울우유 1000ml", "limit": 10, "unit": "개"}


@pytest.fixture
def limit(client):
    response = client.post("/purchase-order-limits", json=BODY, headers=OWNER)
    assert response.status_code == 200, response.text
    return response.json()


def test_us01_owner_creates_and_lists_limit(client):
    response = client.post("/purchase-order-limits", json=BODY, headers=OWNER)
    assert response.status_code == 200, response.text
    created = response.json()
    assert created["product"] == "서울우유 1000ml"
    assert created["limit"] == 10
    assert created["unit"] == "개"
    assert created in client.get("/purchase-order-limits", headers=OWNER).json()


def test_us01_owner_updates_limit(client, limit):
    response = client.patch(
        f"/purchase-order-limits/{limit['id']}",
        json={"product": "서울우유 1000ml", "limit": 20, "unit": "개"},
        headers=OWNER,
    )
    assert response.status_code == 200, response.text
    assert response.json()["limit"] == 20
    [stored] = client.get("/purchase-order-limits", headers=OWNER).json()
    assert stored["limit"] == 20


def test_us01_owner_deletes_limit(client, limit):
    response = client.delete(f"/purchase-order-limits/{limit['id']}", headers=OWNER)
    assert response.status_code == 204
    assert client.get("/purchase-order-limits", headers=OWNER).json() == []


@pytest.mark.parametrize("bad_limit", [0, -1])
def test_us01_nonpositive_limit_is_rejected(client, bad_limit):
    response = client.post(
        "/purchase-order-limits",
        json={**BODY, "limit": bad_limit},
        headers=OWNER,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PURCHASE_ORDER_LIMIT"
    assert client.get("/purchase-order-limits", headers=OWNER).json() == []


# ---------- (권한) 직원은 발주 수량 한도를 설정·변경할 수 없다 ----------


def test_us01_staff_cannot_create_limit(client):
    response = client.post("/purchase-order-limits", json=BODY, headers=STAFF)
    assert response.status_code >= 400
    assert client.get("/purchase-order-limits", headers=OWNER).json() == []


def test_us01_staff_cannot_update_limit(client, limit):
    response = client.patch(
        f"/purchase-order-limits/{limit['id']}",
        json={"product": "서울우유 1000ml", "limit": 99, "unit": "개"},
        headers=STAFF,
    )
    assert response.status_code >= 400
    [stored] = client.get("/purchase-order-limits", headers=OWNER).json()
    assert stored["limit"] == 10


def test_us01_staff_cannot_delete_limit(client, limit):
    response = client.delete(f"/purchase-order-limits/{limit['id']}", headers=STAFF)
    assert response.status_code >= 400
    assert len(client.get("/purchase-order-limits", headers=OWNER).json()) == 1


def test_us01_staff_can_view_limits(client, limit):
    # 등록·수정만 사장님으로 막는다 (US-01 권한 문구는 "설정하거나 바꿀 수
    # 없다"로 조회를 가리키지 않는다. US-08 PR #13과 같은 판단)
    assert client.get("/purchase-order-limits", headers=STAFF).json() == [limit]


# ---------- (권한) 다른 매장 한도는 볼 수도 바꿀 수도 없다 ----------


def test_us01_other_store_cannot_view_limit(client, limit):
    assert client.get("/purchase-order-limits", headers=OTHER_STORE_OWNER).json() == []


def test_us01_other_store_cannot_update_or_delete_limit(client, limit):
    response = client.patch(
        f"/purchase-order-limits/{limit['id']}",
        json=BODY,
        headers=OTHER_STORE_OWNER,
    )
    assert response.status_code == 404
    response = client.delete(
        f"/purchase-order-limits/{limit['id']}", headers=OTHER_STORE_OWNER
    )
    assert response.status_code == 404
    assert len(client.get("/purchase-order-limits", headers=OWNER).json()) == 1
