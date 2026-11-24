# US-06 예외 건 사장 승인·반려 — 인수 조건 중 test_demo_scenario.py가 확인하지 않는 것
# 근거: document 저장소 docs/requirements/backlog.md US-06 인수 조건
# 사용자: conftest.py 시드 — 1 = 매장 1 사장님, 2 = 매장 1 직원
#
# 이 파일에서 다루지 않은 US-06 인수 조건 (팀 질문으로 남김)
#  - 승인 시 '매입 단가' 반영: 매입 단가가 상품 base_unit_price와 같은 값인지
#    DATA-MODEL.md '아직 정하지 못한 것'에 남아 있음
#  - 예외 종류의 값 이름(초과 입고·높은 단가·미등록 상품 등): 정해진 이름이 없어
#    '예외 종류가 보인다'(비어 있지 않음)만 확인
#  - (화면) 사장님 화면 크기 기준: 화면(frontend) 테스트 범위

import pytest

OWNER = {"X-User-Id": "1"}
STAFF = {"X-User-Id": "2"}

SEOUL_MILK = {
    "product_code": "P-0123",
    "name": "서울우유 1000ml",
    "spec": "1L",
    "base_unit": "개",
    "pack_unit": "박스",
    "conversion_qty": 10,
    "base_unit_price": 2650,
}

# 발주는 10개인데 12개가 들어옴 (초과 입고 → 예외 건)
OVER_DELIVERY = "서울우유 1000ml 12개 × 2,650원 = 31,800원\n합계 31,800원\n"
# 발주는 10개인데 8개가 들어옴 (수량 부족 → 예외 건)
SHORT_DELIVERY = "서울우유 1000ml 8개 × 2,650원 = 21,200원\n합계 21,200원\n"


@pytest.fixture(autouse=True)
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    # 리허설·테스트용으로 text/plain 명세서를 받게 한다 (기본은 사진·PDF만, PR #24)
    monkeypatch.setenv("ALLOW_TEXT_UPLOAD", "1")
    return tmp_path


@pytest.fixture
def product_id(client):
    response = client.post("/products", json=SEOUL_MILK, headers=OWNER)
    assert response.status_code == 200, response.text
    return response.json()["id"]


@pytest.fixture
def order_id(client, product_id):
    """발주 P-0123 × 10, `입고 대기`"""
    order = client.post(
        "/purchase-orders",
        json={
            "supplier": "(가상) 유제품 공급처 A",
            "lines": [{"product_id": product_id, "quantity": 10}],
        },
        headers=OWNER,
    ).json()
    assert client.post(
        f"/purchase-orders/{order['id']}/approve", headers=OWNER
    ).is_success
    assert client.post(
        f"/purchase-orders/{order['id']}/mark-delivered", headers=OWNER
    ).is_success
    return order["id"]


@pytest.fixture
def inspection_id(client, order_id):
    [inspection] = client.get(
        "/inspections", params={"status": "업로드 대기"}, headers=STAFF
    ).json()
    return inspection["id"]


def _upload(client, inspection_id, text):
    response = client.post(
        f"/inspections/{inspection_id}/document",
        files={"file": ("statement.txt", text.encode(), "text/plain")},
        headers=STAFF,
    )
    assert response.status_code == 200, response.text
    return response


def _get(client, inspection_id, headers=STAFF):
    response = client.get(f"/inspections/{inspection_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _post(client, inspection_id, action, headers, reason=None):
    body = None if reason is None else {"reason": reason}
    return client.post(
        f"/inspections/{inspection_id}/{action}", headers=headers, json=body
    )


def _stock(client, product_id):
    rows = client.get("/inventory", headers=OWNER).json()
    return next(
        (row["quantity"] for row in rows if row["product_id"] == product_id), 0
    )


def _to_owner_approval(client, inspection_id, statement=OVER_DELIVERY):
    """예외 건을 직원이 사유와 함께 확정해 `사장 승인 대기`로 보낸다."""
    _upload(client, inspection_id, statement)
    response = _post(client, inspection_id, "confirm", STAFF, reason="수량 차이")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "사장 승인 대기"


def _to_rejected(client, inspection_id):
    _to_owner_approval(client, inspection_id)
    response = _post(client, inspection_id, "reject", OWNER, reason="공급처 확인 필요")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "반려"


# ---------- (정상) 사장님 화면에 예외 종류와 직원 예외 사유·사진 ----------


def test_us06_owner_sees_exception_type(client, product_id, inspection_id):
    # US-06 (정상) 예외 건이 `사장 승인 대기`가 되면 사장님 화면에 어느 줄이
    # 왜 예외인지(match_status) 보인다. 이 브랜치에는 별도 exception_types
    # 필드가 없어 all_match=false·줄의 match_status로 확인한다
    _to_owner_approval(client, inspection_id)
    inspection = _get(client, inspection_id, headers=OWNER)
    assert inspection["all_match"] is False
    assert any(line["match_status"] != "일치" for line in inspection["lines"])


def test_us06_owner_sees_staff_reason_and_photo(client, product_id, inspection_id):
    # US-06 (정상) 사장님 화면에 직원이 적은 예외 사유·사진이 보인다
    _upload(client, inspection_id, OVER_DELIVERY)
    photo = client.post(
        f"/inspections/{inspection_id}/exception-photos",
        headers=STAFF,
        files={"file": ("box.png", b"example", "image/png")},
    )
    assert photo.status_code == 200, photo.text
    response = _post(client, inspection_id, "confirm", STAFF, reason="2개 더 옴")
    assert response.json()["status"] == "사장 승인 대기"

    inspection = _get(client, inspection_id, headers=OWNER)
    assert inspection["exception_reason"] == "2개 더 옴"
    photos = client.get(
        f"/inspections/{inspection_id}/exception-photos", headers=OWNER
    ).json()
    assert len(photos) == 1


# ---------- (실패·거절) 사유가 없으면 확정·반려되지 않는다 ----------


def test_us06_blank_exception_reason_cannot_confirm(client, product_id, inspection_id):
    # US-06 (실패·거절) 직원이 예외 사유를 적지 않으면 예외 건을 확정할 수 없다
    # (공백만 적은 것도 적지 않은 것으로 본다)
    _upload(client, inspection_id, OVER_DELIVERY)
    response = _post(client, inspection_id, "confirm", STAFF, reason="   ")
    assert response.status_code == 400
    assert _get(client, inspection_id)["status"] == "직원 확인 대기"
    assert _stock(client, product_id) == 0


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_us06_reject_without_reason_keeps_owner_approval(
    client, product_id, inspection_id, reason
):
    # US-06 (실패·거절) 사장님이 반려 사유를 입력하지 않으면 반려되지 않고
    # 상태는 `사장 승인 대기` 그대로다
    _to_owner_approval(client, inspection_id)
    response = _post(client, inspection_id, "reject", OWNER, reason=reason)
    assert response.status_code == 400
    assert _get(client, inspection_id)["status"] == "사장 승인 대기"


# ---------- (권한) 직원은 승인·반려할 수 없다 ----------


def test_us06_staff_cannot_reject(client, product_id, inspection_id):
    # US-06 (권한) 직원은 예외 건을 반려할 수 없다 (승인 불가는 test_demo_scenario)
    _to_owner_approval(client, inspection_id)
    response = _post(client, inspection_id, "reject", STAFF, reason="직원이 반려")
    assert response.status_code >= 400
    assert _get(client, inspection_id)["status"] == "사장 승인 대기"


def test_us06_staff_cannot_close_rejected_inspection(
    client, product_id, inspection_id
):
    # US-06 (권한·취소·반려) 반려 뒤 공급처에 요청하고 닫는 것은 사장님이 한다
    _to_rejected(client, inspection_id)
    response = _post(client, inspection_id, "close", STAFF)
    assert response.status_code >= 400
    assert _get(client, inspection_id)["status"] == "반려"


# ---------- (취소·반려) 반려 → 재고 그대로, 검수 종료 ----------


def test_us06_reject_does_not_change_stock(client, product_id, inspection_id):
    # US-06 (취소·반려) 사장님이 사유를 입력해 반려하면 `반려`가 되고
    # 재고는 바뀌지 않는다
    _to_rejected(client, inspection_id)
    assert _get(client, inspection_id)["reject_reason"] == "공급처 확인 필요"
    assert _stock(client, product_id) == 0


def test_us06_owner_closes_rejected_inspection(client, product_id, inspection_id):
    # US-06 (취소·반려) 사장님이 공급처에 반품·정정을 요청하고 닫으면 `검수 종료`로 간다
    _to_rejected(client, inspection_id)
    response = _post(client, inspection_id, "close", OWNER)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "검수 종료"
    assert _stock(client, product_id) == 0


@pytest.mark.parametrize("action", ["reinspect", "approve", "reject", "confirm"])
def test_us06_closed_inspection_cannot_be_reopened(
    client, product_id, inspection_id, action
):
    # US-06 (취소·반려) `검수 종료`된 건은 다시 열 수 없다
    _to_rejected(client, inspection_id)
    _post(client, inspection_id, "close", OWNER)
    headers = OWNER if action in {"approve", "reject"} else STAFF
    response = _post(client, inspection_id, action, headers, reason="다시 열기")
    assert response.status_code >= 400
    assert _get(client, inspection_id)["status"] == "검수 종료"


def test_us06_closed_inspection_cannot_receive_new_document(
    client, product_id, inspection_id
):
    # US-06 (취소·반려) `검수 종료`된 건은 다시 열 수 없다
    # (명세서를 다시 올릴 수도 없다)
    _to_rejected(client, inspection_id)
    _post(client, inspection_id, "close", OWNER)
    response = client.post(
        f"/inspections/{inspection_id}/document",
        files={"file": ("statement.txt", OVER_DELIVERY.encode(), "text/plain")},
        headers=STAFF,
    )
    assert response.status_code >= 400
    assert _get(client, inspection_id)["status"] == "검수 종료"


def test_us06_redelivery_after_close_creates_new_inspection(
    client, product_id, order_id, inspection_id
):
    # US-06 (취소·반려) 다시 납품되면 새 입고 검수 건을 만든다
    _to_rejected(client, inspection_id)
    _post(client, inspection_id, "close", OWNER)
    response = client.post(f"/purchase-orders/{order_id}/redeliveries", headers=STAFF)
    assert response.status_code == 200, response.text
    new_id = response.json()["inspection_id"]
    assert new_id != inspection_id
    assert _get(client, new_id)["status"] == "업로드 대기"
    assert _get(client, inspection_id)["status"] == "검수 종료"


# ---------- (취소·반려) 사장님 처리 전에는 직원이 확정을 취소할 수 있다 ----------


def test_us06_staff_can_cancel_confirmation_before_owner_acts(
    client, product_id, inspection_id
):
    # US-06 (취소·반려) 사장님이 처리하기 전이면 직원이 확정을 취소해
    # `직원 확인 대기`로 되돌릴 수 있다
    _to_owner_approval(client, inspection_id)
    response = _post(client, inspection_id, "cancel-confirmation", STAFF)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "직원 확인 대기"
    assert _stock(client, product_id) == 0


def test_us06_staff_cannot_cancel_confirmation_after_approval(
    client, product_id, inspection_id
):
    # US-06 (취소·반려) 사장님이 승인한 뒤에는 직원이 확정을 취소할 수 없다
    # (반려한 뒤는 test_demo_scenario에서 확인)
    _to_owner_approval(client, inspection_id, statement=SHORT_DELIVERY)
    assert _post(client, inspection_id, "approve", OWNER).status_code == 200
    response = _post(client, inspection_id, "cancel-confirmation", STAFF)
    assert response.status_code >= 400
    assert _get(client, inspection_id)["status"] == "재고 반영 완료"
    assert _stock(client, product_id) == 8
