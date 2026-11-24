# 포팅된 기능(알림·단위 환산 수동 입력·부족 입고 줄) 테스트 — 다른 파일이 확인하지
# 않는 것만 다룬다. 원래 신은총님 PR #22~27의 같은 기능을 이 브랜치에서 다시 쓴
# 것으로, 응답 모양은 이 브랜치의 실제 구현
# (app/schemas/inspection.py, app/routers/inspections.py,
# app/routers/notifications.py)을 따른다 — open_checks·summary 중첩 객체·
# exception_types 같은 신은총님 쪽 모양은 쓰지 않는다 (해당 개념은
# match_status·rule_violations·total_amount/summary_mismatch로 대신한다).
# 사용자: conftest.py 시드 — 1 = 매장 1 사장님, 2 = 매장 1 직원, 3 = 매장 2 사장님

import pytest

OWNER = {"X-User-Id": "1"}
STAFF = {"X-User-Id": "2"}
OTHER_STORE_OWNER = {"X-User-Id": "3"}

SEOUL_MILK = {
    "product_code": "P-0123",
    "name": "서울우유 1000ml",
    "spec": "1L",
    "base_unit": "개",
    "pack_unit": "박스",
    "conversion_qty": 10,
    "base_unit_price": 2650,
}
MATCHING = "서울우유 1000ml 10개 × 2,650원 = 26,500원\n합계 26,500원\n"
SHORT_8 = "서울우유 1000ml 8개 × 2,650원 = 21,200원\n합계 21,200원\n"


@pytest.fixture(autouse=True)
def allow_text_upload(monkeypatch):
    monkeypatch.setenv("ALLOW_TEXT_UPLOAD", "1")


@pytest.fixture
def product_id(client):
    response = client.post("/products", json=SEOUL_MILK, headers=OWNER)
    assert response.status_code == 200, response.text
    return response.json()["id"]


@pytest.fixture
def order_id(client, product_id):
    response = client.post(
        "/purchase-orders",
        json={"lines": [{"product_id": product_id, "quantity": 10}]},
        headers=OWNER,
    )
    order_id = response.json()["id"]
    client.post(f"/purchase-orders/{order_id}/approve", headers=OWNER)
    client.post(f"/purchase-orders/{order_id}/mark-delivered", headers=OWNER)
    return order_id


@pytest.fixture
def inspection_id(client, order_id):
    [inspection] = client.get(
        "/inspections", params={"status": "업로드 대기"}, headers=STAFF
    ).json()
    return inspection["id"]


def upload(client, inspection_id, text, headers=STAFF):
    return client.post(
        f"/inspections/{inspection_id}/document",
        files={"file": ("statement.txt", text.encode(), "text/plain")},
        headers=headers,
    )


def get(client, inspection_id, headers=STAFF):
    response = client.get(f"/inspections/{inspection_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def post(client, inspection_id, action, headers=STAFF, reason=None):
    body = None if reason is None else {"reason": reason}
    return client.post(
        f"/inspections/{inspection_id}/{action}", headers=headers, json=body
    )


def patch_line(client, inspection_id, line_id, body, headers=STAFF):
    return client.patch(
        f"/inspections/{inspection_id}/lines/{line_id}", json=body, headers=headers
    )


def stock(client, product_id):
    rows = client.get("/inventory", headers=OWNER).json()
    return next((r["quantity"] for r in rows if r["product_id"] == product_id), 0)


# ---------- 판독 실패 알림 (US-03) ----------


def test_read_failure_notifies_uploader(client, inspection_id):
    upload(client, inspection_id, "흐릿함")
    assert get(client, inspection_id)["status"] == "업로드 대기"

    [note] = client.get("/notifications", headers=STAFF).json()
    assert note["inspection_id"] == inspection_id
    assert "다시 올려" in note["message"]
    assert note["read_at"] is None
    # 다른 사용자에게는 가지 않는다
    assert client.get("/notifications", headers=OWNER).json() == []

    response = client.post(f"/notifications/{note['id']}/read", headers=OWNER)
    assert response.status_code == 404

    response = client.post(f"/notifications/{note['id']}/read", headers=STAFF)
    assert response.json()["read_at"] is not None
    assert client.get("/notifications?unread=true", headers=STAFF).json() == []


def test_successful_reading_does_not_notify(client, inspection_id):
    upload(client, inspection_id, MATCHING)
    assert get(client, inspection_id)["status"] == "직원 확인 대기"
    assert client.get("/notifications", headers=STAFF).json() == []


# ---------- 단위 환산 수동 입력 (US-05) ----------


def test_unknown_unit_requires_manual_base_quantity(client, product_id, inspection_id):
    upload(client, inspection_id, "서울우유 1000ml 10통 × 2,650원\n")
    [line] = get(client, inspection_id)["lines"]
    assert line["match_status"] == "확인 필요"
    assert line["base_quantity"] is None
    assert get(client, inspection_id)["check_count"] == 1

    after = patch_line(
        client, inspection_id, line["id"], {"manual_base_quantity": 10}
    ).json()
    assert after["lines"][0]["base_quantity"] == 10
    assert after["lines"][0]["manual_base_quantity"] == 10
    assert after["check_count"] == 0
    assert post(client, inspection_id, "confirm").json()["status"] == "재고 반영 완료"
    assert stock(client, product_id) == 10


def test_manual_base_quantity_must_be_positive(client, product_id, inspection_id):
    upload(client, inspection_id, "서울우유 1000ml 10통 × 2,650원\n")
    [line] = get(client, inspection_id)["lines"]
    response = patch_line(
        client, inspection_id, line["id"], {"manual_base_quantity": 0}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_QUANTITY"


# ---------- 부족 입고 (US-06) ----------


def test_owner_approve_leaves_short_quantity(
    client, product_id, order_id, inspection_id
):
    upload(client, inspection_id, SHORT_8)
    confirm = post(client, inspection_id, "confirm", reason="8개만 옴")
    assert confirm.json()["status"] == "사장 승인 대기"

    response = post(client, inspection_id, "approve", headers=OWNER)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "재고 반영 완료"
    assert body["short_order_lines"] == [
        {
            "product_id": product_id,
            "order_quantity": 10,
            "received_quantity": 8,
            "short_quantity": 2,
        }
    ]
    assert stock(client, product_id) == 8
    # 발주는 전량 입고될 때까지 열려 있다
    assert (
        client.get(f"/purchase-orders/{order_id}", headers=OWNER).json()["status"]
        == "입고 대기"
    )


def test_matching_delivery_has_no_short_order_lines(client, inspection_id):
    upload(client, inspection_id, MATCHING)
    assert post(client, inspection_id, "confirm").json()["short_order_lines"] == []


def test_other_store_cannot_view_notifications(client, inspection_id):
    upload(client, inspection_id, "흐릿함")
    # 알림은 매장이 아니라 사용자별이라, 다른 매장 사장님은 자기 알림(없음)만 본다
    assert client.get("/notifications", headers=OTHER_STORE_OWNER).json() == []
