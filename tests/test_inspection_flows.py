# US-03 판독 규칙·알림·판독 로그 / US-04 확인할 칸 / US-05 단위 환산 /
# US-06 예외 건 사장 승인·반려 / US-07 변경 이력
# 사용자: conftest.py 시드 — 1 = 매장 1 사장님, 2 = 매장 1 직원, 3 = 매장 2 사장님

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models.history import ChangeLog, ImmutableHistoryError

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
SHORT_8 = "서울우유 1000ml 8개 × 2,650원 = 21,200원\n"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
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
    [inspection] = client.get("/inspections", headers=STAFF).json()
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


def post(client, inspection_id, action, headers=STAFF, json=None):
    return client.post(
        f"/inspections/{inspection_id}/{action}", headers=headers, json=json
    )


def patch_line(client, inspection_id, line_id, body, headers=STAFF):
    return client.patch(
        f"/inspections/{inspection_id}/lines/{line_id}", json=body, headers=headers
    )


def stock(client, product_id):
    rows = client.get("/inventory", headers=OWNER).json()
    return next(r["quantity"] for r in rows if r["product_id"] == product_id)


def order_status(client, order_id):
    return client.get(f"/purchase-orders/{order_id}", headers=OWNER).json()["status"]


def to_owner_approval(client, inspection_id, text=SHORT_8):
    upload(client, inspection_id, text)
    response = post(
        client, inspection_id, "confirm", json={"exception_reason": "8개만 왔음"}
    )
    assert response.json()["status"] == "사장 승인 대기", response.text
    return response.json()


# ---------- US-03 ----------


def test_us03_non_photo_or_pdf_is_rejected_by_default(
    monkeypatch, client, inspection_id
):
    monkeypatch.delenv("ALLOW_TEXT_UPLOAD")
    response = upload(client, inspection_id, MATCHING)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert get(client, inspection_id)["status"] == "업로드 대기"


def test_us03_read_failure_notifies_uploader(client, inspection_id):
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


def test_us03_reading_log_is_recorded(client, inspection_id):
    upload(client, inspection_id, "흐릿함")
    upload(client, inspection_id, MATCHING)
    logs = client.get(f"/inspections/{inspection_id}/history", headers=OWNER).json()[
        "reading_logs"
    ]
    assert [log["succeeded"] for log in logs] == [False, True]
    for log in logs:
        assert log["input_tokens"] == 0 and log["output_tokens"] == 0
        assert log["cost"] == 0
        assert log["elapsed_seconds"] >= 0


def test_us03_amount_rule_failure_must_be_checked(client, product_id, inspection_id):
    # 10 × 2,650 = 26,500인데 25,000으로 적혀 있음
    upload(client, inspection_id, "서울우유 1000ml 10개 × 2,650원 = 25,000원\n")
    draft = get(client, inspection_id)
    [line] = draft["lines"]
    assert line["open_checks"] == ["수량×단가≠금액"]
    assert draft["check_count"] == 1
    assert post(client, inspection_id, "confirm").json()["error"]["code"] == (
        "CHECK_REQUIRED"
    )

    after = patch_line(client, inspection_id, line["id"], {"checked": True}).json()
    assert after["check_count"] == 0
    assert post(client, inspection_id, "confirm").json()["status"] == "재고 반영 완료"
    assert stock(client, product_id) == 10


def test_us03_total_rule_failure_must_be_checked(client, inspection_id):
    upload(
        client,
        inspection_id,
        "서울우유 1000ml 10개 × 2,650원 = 26,500원\n합계 30,000원\n",
    )
    draft = get(client, inspection_id)
    assert draft["summary"]["total_amount"] == 30000
    assert draft["summary"]["line_amount_sum"] == 26500
    assert draft["summary"]["open_checks"] == ["줄 금액 합≠합계"]
    assert draft["check_count"] == 1

    response = client.patch(
        f"/inspections/{inspection_id}/summary", json={"checked": True}, headers=STAFF
    )
    assert response.json()["check_count"] == 0


def test_us03_uncertain_value_is_blank_and_must_be_filled(
    monkeypatch, client, product_id, inspection_id
):
    # LLM이 수량을 확신하지 못한 경우: 값은 비우고 uncertain_fields에 적는다
    from app.services import reading
    from app.services.structurer import RuleBasedStructurer

    class Unsure(RuleBasedStructurer):
        def structure(self, masked_text, products):
            draft = super().structure(masked_text, products)
            for line in draft.lines:
                line.quantity = None
                line.uncertain_fields = ["quantity"]
            return draft

    monkeypatch.setattr(reading, "get_structurer", lambda: Unsure())
    upload(client, inspection_id, MATCHING)
    [line] = get(client, inspection_id)["lines"]
    assert line["quantity"] is None
    assert line["uncertain_fields"] == ["quantity"]
    assert set(line["open_checks"]) == {"수량 없음", "불확실한 값"}

    after = patch_line(client, inspection_id, line["id"], {"quantity": 10}).json()
    assert after["check_count"] == 0
    assert after["lines"][0]["match_status"] == "일치"


def test_us04_multiple_candidates_must_be_checked(client, product_id, inspection_id):
    client.post(
        "/products",
        json={"product_code": "P-0124", "name": "서울우유 900ml"},
        headers=OWNER,
    )
    upload(client, inspection_id, MATCHING)
    [line] = get(client, inspection_id)["lines"]
    assert len(line["candidates"]) == 2
    assert line["product_id"] == product_id  # 1순위 후보
    assert line["open_checks"] == ["후보 여러 개"]
    after = patch_line(client, inspection_id, line["id"], {"product_id": product_id})
    assert after.json()["check_count"] == 0


# ---------- US-04 ----------


def test_us04_damaged_line_is_exception(client, product_id, inspection_id):
    upload(client, inspection_id, MATCHING)
    [line] = get(client, inspection_id)["lines"]
    after = patch_line(client, inspection_id, line["id"], {"damaged": True}).json()
    assert after["lines"][0]["match_status"] == "파손"
    assert after["exception_types"] == ["파손"]
    assert after["all_match"] is False


def test_us04_applied_inspection_cannot_be_edited(client, inspection_id):
    upload(client, inspection_id, MATCHING)
    [line] = get(client, inspection_id)["lines"]
    post(client, inspection_id, "confirm")
    response = patch_line(client, inspection_id, line["id"], {"quantity": 1})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


def test_us04_missing_order_line_is_exception(client, order_id, inspection_id):
    # 발주에 없는 상품만 들어옴 → 발주 줄은 명세서에 없음
    other = client.post(
        "/products",
        json={
            "product_code": "P-0201",
            "name": "종이컵 12oz",
            "base_unit": "개",
        },
        headers=OWNER,
    ).json()
    upload(client, inspection_id, "종이컵 12oz 48개 × 50원\n")
    draft = get(client, inspection_id)
    assert draft["lines"][0]["product_id"] == other["id"]
    assert draft["exception_types"] == ["발주에 없음", "명세서에 없음"]
    assert draft["missing_order_lines"][0]["order_quantity"] == 10


# ---------- US-05 ----------


def test_us05_unknown_unit_requires_manual_base_quantity(
    client, product_id, inspection_id
):
    upload(client, inspection_id, "서울우유 1000ml 10통 × 2,650원\n")
    [line] = get(client, inspection_id)["lines"]
    assert line["open_checks"] == ["단위 환산 불가"]
    assert line["base_quantity"] is None
    assert line["match_status"] == "확인 필요"

    after = patch_line(
        client, inspection_id, line["id"], {"manual_base_quantity": 10}
    ).json()
    assert after["lines"][0]["base_quantity"] == 10
    assert after["check_count"] == 0
    assert post(client, inspection_id, "confirm").json()["status"] == "재고 반영 완료"
    assert stock(client, product_id) == 10


def test_us05_pack_unit_without_conversion_is_not_converted(
    client, product_id, inspection_id
):
    client.patch(
        f"/products/{product_id}", json={"conversion_qty": None}, headers=OWNER
    )
    upload(client, inspection_id, "서울우유 1000ml 1박스 × 26,500원\n")
    [line] = get(client, inspection_id)["lines"]
    assert line["open_checks"] == ["단위 환산 불가"]


def test_us05_pack_unit_is_converted(client, product_id, inspection_id):
    upload(client, inspection_id, "서울우유 1000ml 1박스 × 26,500원\n")
    [line] = get(client, inspection_id)["lines"]
    assert line["base_quantity"] == 10
    assert line["match_status"] == "일치"


# ---------- US-06 ----------


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_us06_exception_needs_reason(client, product_id, inspection_id, reason):
    upload(client, inspection_id, SHORT_8)
    body = None if reason is None else {"exception_reason": reason}
    response = post(client, inspection_id, "confirm", json=body)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EXCEPTION_REASON_REQUIRED"
    assert get(client, inspection_id)["status"] == "직원 확인 대기"
    assert stock(client, product_id) == 0


def test_us06_owner_sees_exception_types_and_reason(client, inspection_id):
    to_owner_approval(client, inspection_id)
    [waiting] = client.get(
        "/inspections", params={"status": "사장 승인 대기"}, headers=OWNER
    ).json()
    assert waiting["exception_types"] == ["수량 다름"]
    assert waiting["exception_reason"] == "8개만 왔음"


def test_us06_approve_applies_stock_and_leaves_short_quantity(
    client, product_id, order_id, inspection_id
):
    to_owner_approval(client, inspection_id)
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
    assert order_status(client, order_id) == "입고 완료"


def test_us06_approved_price_is_statement_price(client, product_id, inspection_id):
    to_owner_approval(client, inspection_id, "서울우유 1000ml 10개 × 2,900원\n")
    body = post(client, inspection_id, "approve", headers=OWNER).json()
    assert body["lines"][0]["applied_unit_price"] == 2900
    # 상품 기준 단가는 바꾸지 않는다 (매입 단가와 같은 값인지 미정)
    products = client.get("/products", headers=OWNER).json()
    assert products[0]["base_unit_price"] == 2650


@pytest.mark.parametrize("action", ["approve", "reject", "close"])
def test_us06_staff_cannot_approve_reject_or_close(client, inspection_id, action):
    to_owner_approval(client, inspection_id)
    response = post(
        client, inspection_id, action, json={"reject_reason": "x"}, headers=STAFF
    )
    assert response.status_code == 403
    assert get(client, inspection_id)["status"] == "사장 승인 대기"


@pytest.mark.parametrize("reason", [None, "", "  "])
def test_us06_reject_needs_reason(client, product_id, inspection_id, reason):
    to_owner_approval(client, inspection_id)
    body = None if reason is None else {"reject_reason": reason}
    response = post(client, inspection_id, "reject", headers=OWNER, json=body)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REJECT_REASON_REQUIRED"
    assert get(client, inspection_id)["status"] == "사장 승인 대기"


def test_us06_reject_then_recheck(client, product_id, inspection_id):
    to_owner_approval(client, inspection_id)
    response = post(
        client,
        inspection_id,
        "reject",
        headers=OWNER,
        json={"reject_reason": "다시 세기"},
    )
    assert response.json()["status"] == "반려"
    assert response.json()["reject_reason"] == "다시 세기"
    assert stock(client, product_id) == 0

    assert post(client, inspection_id, "recheck").json()["status"] == "직원 확인 대기"
    [line] = get(client, inspection_id)["lines"]
    patch_line(client, inspection_id, line["id"], {"quantity": 10})
    assert post(client, inspection_id, "confirm").json()["status"] == "재고 반영 완료"
    assert stock(client, product_id) == 10


def test_us06_reject_then_close_is_final_and_new_inspection_can_start(
    client, order_id, inspection_id
):
    to_owner_approval(client, inspection_id)
    post(client, inspection_id, "reject", headers=OWNER, json={"reject_reason": "반품"})
    assert post(client, inspection_id, "close", headers=OWNER).json()["status"] == (
        "검수 종료"
    )
    for action in ("recheck", "approve", "close", "confirm"):
        assert post(client, inspection_id, action, headers=OWNER).status_code == 400
    assert get(client, inspection_id)["status"] == "검수 종료"

    # 다시 납품되면 같은 발주에 새 검수 건
    response = client.post(
        "/inspections", json={"purchase_order_id": order_id}, headers=STAFF
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "업로드 대기"
    assert response.json()["id"] != inspection_id
    # 끝나지 않은 검수 건이 있으면 또 만들 수 없다
    again = client.post(
        "/inspections", json={"purchase_order_id": order_id}, headers=STAFF
    )
    assert again.json()["error"]["code"] == "OPEN_INSPECTION_EXISTS"


def test_us06_new_inspection_needs_closed_previous(client, order_id, inspection_id):
    response = client.post(
        "/inspections", json={"purchase_order_id": order_id}, headers=STAFF
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "OPEN_INSPECTION_EXISTS"
    response = client.post(
        "/inspections", json={"purchase_order_id": order_id}, headers=OTHER_STORE_OWNER
    )
    assert response.status_code == 404


def test_us06_staff_can_cancel_confirm_before_owner_acts(client, inspection_id):
    to_owner_approval(client, inspection_id)
    response = post(client, inspection_id, "cancel-confirm")
    assert response.json()["status"] == "직원 확인 대기"


def test_us06_cannot_cancel_confirm_after_owner_acts(client, inspection_id):
    to_owner_approval(client, inspection_id)
    post(client, inspection_id, "approve", headers=OWNER)
    response = post(client, inspection_id, "cancel-confirm")
    assert response.status_code == 400
    assert get(client, inspection_id)["status"] == "재고 반영 완료"


def test_us06_exception_photo_is_shown_to_owner(client, inspection_id):
    upload(client, inspection_id, SHORT_8)
    response = client.post(
        f"/inspections/{inspection_id}/exception-photos",
        files={"file": ("broken.jpg", b"\xff\xd8\xffphoto", "image/jpeg")},
        headers=STAFF,
    )
    assert response.status_code == 200, response.text
    [photo] = response.json()["exception_photos"]

    file = client.get(
        f"/inspections/{inspection_id}/files/{photo['id']}", headers=OWNER
    )
    assert file.status_code == 200
    assert file.content == b"\xff\xd8\xffphoto"
    other = client.get(
        f"/inspections/{inspection_id}/files/{photo['id']}", headers=OTHER_STORE_OWNER
    )
    assert other.status_code == 404

    pdf = client.post(
        f"/inspections/{inspection_id}/exception-photos",
        files={"file": ("a.pdf", b"%PDF", "application/pdf")},
        headers=STAFF,
    )
    assert pdf.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


# ---------- US-07 ----------


def test_us07_history_records_each_change_in_order(client, product_id, inspection_id):
    to_owner_approval(client, inspection_id)
    post(client, inspection_id, "approve", headers=OWNER)
    changes = client.get(f"/inspections/{inspection_id}/history", headers=OWNER).json()[
        "changes"
    ]

    statuses = [
        (c["old_value"], c["new_value"], c["changed_by"])
        for c in changes
        if c["field"] == "status"
    ]
    assert statuses == [
        ("업로드 대기", "판독 중", 2),
        ("판독 중", "직원 확인 대기", 2),
        ("직원 확인 대기", "사장 승인 대기", 2),
        ("사장 승인 대기", "승인", 1),
        ("승인", "재고 반영 완료", 1),
    ]
    actions = {c["action"] for c in changes}
    assert {"업로드", "판독", "확정", "승인", "재고 반영"} <= actions
    stock_change = next(c for c in changes if c["action"] == "재고 반영")
    assert (stock_change["old_value"], stock_change["new_value"]) == ("0", "8")
    reason = next(c for c in changes if c["field"] == "exception_reason")
    assert reason["new_value"] == "8개만 왔음"
    original = next(c for c in changes if c["field"] == "line 1")
    assert '"quantity": 8' in original["new_value"]


def test_us07_staff_edit_is_recorded_with_old_and_new(client, inspection_id):
    upload(client, inspection_id, SHORT_8)
    [line] = get(client, inspection_id)["lines"]
    patch_line(client, inspection_id, line["id"], {"quantity": 10})
    changes = client.get(f"/inspections/{inspection_id}/history", headers=OWNER).json()[
        "changes"
    ]
    edit = next(c for c in changes if c["field"] == "line 1 quantity")
    assert (edit["old_value"], edit["new_value"], edit["changed_by"]) == ("8", "10", 2)


def test_us07_history_cannot_be_changed(client, inspection_id):
    upload(client, inspection_id, MATCHING)
    with SessionLocal() as db:
        entry = db.scalars(select(ChangeLog)).first()
        entry.new_value = "조작"
        with pytest.raises(ImmutableHistoryError):
            db.commit()
        db.rollback()
        entry = db.scalars(select(ChangeLog)).first()
        db.delete(entry)
        with pytest.raises(ImmutableHistoryError):
            db.commit()
    # 고치거나 지우는 API도 없다
    url = f"/inspections/{inspection_id}/history"
    assert client.delete(url, headers=OWNER).status_code == 405
    assert client.patch(url, json={}, headers=OWNER).status_code == 405


def test_us07_other_store_cannot_view_history(client, inspection_id):
    response = client.get(
        f"/inspections/{inspection_id}/history", headers=OTHER_STORE_OWNER
    )
    assert response.status_code == 404
