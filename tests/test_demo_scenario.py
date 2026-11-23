# 첫 데모 시나리오 (3주차) 0~5단계 + '질문이 오면' 3가지
# 사용자: conftest.py 시드 — 1 = 매장 1 사장님, 2 = 매장 1 직원, 3 = 매장 2 사장님
# 데이터: DATA-MODEL.md 시드 #2(상품) · #4(발주) · #5(입고 검수 건)
# OCR은 데모 엔진(OCR_ENGINE=demo), LLM 자리는 규칙 기반 정리기(STRUCTURER=rule)다.

import pytest

OWNER = {"X-User-Id": "1"}
STAFF = {"X-User-Id": "2"}
OTHER_STORE_OWNER = {"X-User-Id": "3"}
OTHER_STAFF = {"X-User-Id": "4"}  # store 1의 또 다른 직원 (담당 아님)

SEOUL_MILK = {
    "product_code": "P-0123",
    "name": "서울우유 1000ml",
    "spec": "1L",
    "base_unit": "개",
    "pack_unit": "박스",
    "conversion_qty": 10,
    "base_unit_price": 2650,
}

# 시드 값으로 만든 가상 명세서 (발주와 모두 일치). 가상 연락처 줄은 가리기 확인용
MATCHING_STATEMENT = """\
거래명세서
담당자 홍길동 연락처 010-0000-0000
서울우유 1000ml 10개 × 2,650원 = 26,500원
합계 26,500원
"""


@pytest.fixture(autouse=True)
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def product_id(client):
    response = client.post("/products", json=SEOUL_MILK, headers=OWNER)
    assert response.status_code == 200, response.text
    return response.json()["id"]


@pytest.fixture
def order_id(client, product_id):
    """발주 #4: (가상) 유제품 공급처 A, P-0123 × 10, `입고 대기`"""
    response = client.post(
        "/purchase-orders",
        json={
            "supplier": "(가상) 유제품 공급처 A",
            "lines": [{"product_id": product_id, "quantity": 10}],
        },
        headers=OWNER,
    )
    order_id = response.json()["id"]
    assert client.post(f"/purchase-orders/{order_id}/approve", headers=OWNER).is_success
    assert client.post(
        f"/purchase-orders/{order_id}/mark-delivered", headers=OWNER
    ).is_success
    return order_id


@pytest.fixture
def inspection_id(client, order_id):
    """검수 건 #5: 발주에 연결, `업로드 대기`"""
    listed = client.get(
        "/inspections", params={"status": "업로드 대기"}, headers=STAFF
    ).json()
    assert len(listed) == 1
    return listed[0]["id"]


def _upload(
    client,
    inspection_id,
    content,
    filename="statement.txt",
    content_type="text/plain",
    headers=STAFF,
):
    return client.post(
        f"/inspections/{inspection_id}/document",
        files={"file": (filename, content, content_type)},
        headers=headers,
    )


def _get(client, inspection_id, headers=STAFF):
    response = client.get(f"/inspections/{inspection_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _stock(client, product_id):
    rows = client.get("/inventory", headers=OWNER).json()
    return next(row["quantity"] for row in rows if row["product_id"] == product_id)


def _order_status(client, order_id):
    return client.get(f"/purchase-orders/{order_id}", headers=OWNER).json()["status"]


# ---------- 데모 0~5단계 (한 흐름) ----------


def test_demo_happy_path(client, product_id, order_id, inspection_id):
    # 0. 상품이 등록돼 있다
    products = client.get("/products", headers=OWNER).json()
    assert [p["product_code"] for p in products] == ["P-0123"]

    # 1. 발주는 `입고 대기`, 검수 건은 `업로드 대기`
    assert _order_status(client, order_id) == "입고 대기"
    first = _get(client, inspection_id)
    assert first["status"] == "업로드 대기"
    assert first["purchase_order_id"] == order_id
    assert _stock(client, product_id) == 0

    # 2. 직원이 명세서를 올린다: 업로드 대기 → 판독 중
    response = _upload(client, inspection_id, MATCHING_STATEMENT.encode())
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "판독 중"

    # 3. 판독이 끝나면 직원 확인 대기. 품목 후보(이유 포함), 재고는 아직 0 (R3)
    draft = _get(client, inspection_id)
    assert draft["status"] == "직원 확인 대기"
    assert draft["ai_draft"] is True
    [line] = draft["lines"]
    assert line["read"] == {
        "name": "서울우유 1000ml",
        "quantity": 10,
        "unit": "개",
        "unit_price": 2650,
        "amount": 26500,
    }
    assert 1 <= len(line["candidates"]) <= 3
    assert line["candidates"][0]["product_id"] == product_id
    assert line["candidates"][0]["reason"]
    assert line["match_status"] == "일치"
    assert draft["check_count"] == 0
    assert draft["all_match"] is True
    assert _stock(client, product_id) == 0

    # 4~5. 직원이 확정 → 재고 반영 완료, 재고 0 → 10, 발주 입고 완료
    response = client.post(f"/inspections/{inspection_id}/confirm", headers=STAFF)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "재고 반영 완료"
    assert response.json()["ai_draft"] is False
    assert _stock(client, product_id) == 10
    assert _order_status(client, order_id) == "입고 완료"


def test_photo_upload_uses_demo_statement(client, product_id, inspection_id):
    # 사진을 올리면 데모 OCR이 시드 값 가상 명세서를 돌려준다
    response = _upload(
        client, inspection_id, b"\xff\xd8\xff fake jpeg", "photo.jpg", "image/jpeg"
    )
    assert response.status_code == 200, response.text
    draft = _get(client, inspection_id)
    assert draft["status"] == "직원 확인 대기"
    assert draft["all_match"] is True


# ---------- 꼭 짚을 말 ----------


def test_llm_step_receives_only_masked_text(monkeypatch, client, inspection_id):
    # 원본 파일이 아니라 가린 텍스트만 LLM(정리기)에 넘어간다
    from app.services import reading
    from app.services.structurer import RuleBasedStructurer

    seen = []

    class Spy(RuleBasedStructurer):
        def structure(self, masked_text, products):
            seen.append(masked_text)
            return super().structure(masked_text, products)

    monkeypatch.setattr(reading, "get_structurer", lambda: Spy())
    _upload(client, inspection_id, MATCHING_STATEMENT.encode())
    [text] = seen
    assert "홍길동" not in text
    assert "010-0000-0000" not in text
    assert "서울우유 1000ml" in text


def test_confirm_is_only_allowed_in_staff_review(client, product_id, inspection_id):
    # 판독 전에 확정할 수 없다. 재고도 그대로다 (R3)
    response = client.post(f"/inspections/{inspection_id}/confirm", headers=STAFF)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert _stock(client, product_id) == 0


# ---------- 질문이 오면 ----------


def test_different_line_goes_to_owner_approval(
    client, product_id, order_id, inspection_id
):
    statement = "서울우유 1000ml 8개 × 2,650원 = 21,200원\n"
    _upload(client, inspection_id, statement.encode())
    draft = _get(client, inspection_id)
    assert draft["lines"][0]["match_status"] == "수량 다름"
    assert draft["all_match"] is False

    response = client.post(
        f"/inspections/{inspection_id}/confirm",
        headers=STAFF,
        json={"reason": "차이 확인"},
    )
    assert response.json()["status"] == "사장 승인 대기"
    assert _stock(client, product_id) == 0
    assert _order_status(client, order_id) == "입고 대기"


def test_price_difference_goes_to_owner_approval(client, product_id, inspection_id):
    _upload(client, inspection_id, "서울우유 1000ml 10개 × 2,900원\n".encode())
    assert _get(client, inspection_id)["lines"][0]["match_status"] == "단가 다름"
    response = client.post(
        f"/inspections/{inspection_id}/confirm",
        headers=STAFF,
        json={"reason": "차이 확인"},
    )
    assert response.json()["status"] == "사장 승인 대기"
    assert _stock(client, product_id) == 0


def test_pack_unit_is_converted_to_base_unit(client, product_id, inspection_id):
    # 1박스 = 10개 (환산값). 박스 단가 26,500원 = 개당 2,650원
    _upload(client, inspection_id, "서울우유 1000ml 1박스 × 26,500원\n".encode())
    line = _get(client, inspection_id)["lines"][0]
    assert line["base_quantity"] == 10
    assert line["match_status"] == "일치"
    client.post(f"/inspections/{inspection_id}/confirm", headers=STAFF)
    assert _stock(client, product_id) == 10


def test_mixed_units_for_same_product_need_check(client, product_id, inspection_id):
    # 같은 상품이 개·박스로 섞여 있으면 구분할 수 없어 자동 환산하지 않는다
    # (US-05, 미팅1 피드백 5, R6)
    statement = (
        "서울우유 1000ml 5개 × 2,650원\n서울우유 1000ml 1박스 × 26,500원\n"
    )
    _upload(client, inspection_id, statement.encode())
    draft = _get(client, inspection_id)
    assert [line["match_status"] for line in draft["lines"]] == [
        "확인 필요",
        "확인 필요",
    ]
    assert draft["check_count"] == 2

    response = client.post(f"/inspections/{inspection_id}/confirm", headers=STAFF)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CHECK_REQUIRED"


def test_add_line_for_missed_item_fixes_quantity_mismatch(
    client, product_id, inspection_id
):
    # OCR이 품목 한 줄을 덜 읽어 수량이 모자라면, 직원이 빠진 줄을 추가해
    # 발주와 맞출 수 있다 (US-04 인수 조건, 미팅1 질의 3)
    _upload(client, inspection_id, "서울우유 1000ml 7개 × 2,650원\n".encode())
    draft = _get(client, inspection_id)
    assert len(draft["lines"]) == 1
    assert draft["lines"][0]["match_status"] == "수량 다름"

    response = client.post(
        f"/inspections/{inspection_id}/lines",
        json={"product_id": product_id, "quantity": 3, "unit": "개"},
        headers=STAFF,
    )
    assert response.status_code == 200, response.text
    lines = response.json()["lines"]
    assert len(lines) == 2
    assert [line["match_status"] for line in lines] == ["일치", "일치"]

    history = client.get(f"/inspections/{inspection_id}/history", headers=OWNER).json()
    assert any(h["kind"] == "직원이 추가한 줄" for h in history)

    metrics = client.get(f"/inspections/{inspection_id}/metrics", headers=OWNER).json()
    assert metrics["line_count"] == 2
    assert metrics["added_line_ratio"] == 0.5

    response = client.post(f"/inspections/{inspection_id}/confirm", headers=STAFF)
    assert response.status_code == 200, response.text
    assert _stock(client, product_id) == 10


def test_add_line_requires_assigned_employee_or_owner(
    client, product_id, inspection_id
):
    _upload(client, inspection_id, MATCHING_STATEMENT.encode(), headers=STAFF)
    response = client.post(
        f"/inspections/{inspection_id}/lines",
        json={"product_id": product_id, "quantity": 1, "unit": "개"},
        headers=OTHER_STAFF,
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN_ROLE"


def test_read_failure_returns_to_upload_waiting(client, product_id, inspection_id):
    _upload(client, inspection_id, "흐릿해서 읽을 수 없음".encode())
    inspection = _get(client, inspection_id)
    assert inspection["status"] == "업로드 대기"
    assert "다시 올려" in inspection["document"]["read_error"]
    assert _stock(client, product_id) == 0

    # 다시 올리면 정상 진행된다
    _upload(client, inspection_id, MATCHING_STATEMENT.encode())
    inspection = _get(client, inspection_id)
    assert inspection["status"] == "직원 확인 대기"
    assert inspection["document"]["read_error"] is None


def test_other_store_cannot_see_or_touch_inspection(client, inspection_id):
    assert client.get("/inspections", headers=OTHER_STORE_OWNER).json() == []
    response = client.get(f"/inspections/{inspection_id}", headers=OTHER_STORE_OWNER)
    assert response.status_code == 404
    response = _upload(
        client, inspection_id, MATCHING_STATEMENT.encode(), headers=OTHER_STORE_OWNER
    )
    assert response.status_code == 404
    assert _get(client, inspection_id)["status"] == "업로드 대기"


# 2026-11-16 멘토 데모 피드백 팀 결정: "직원은 담당(처음 올린) 입고 건만 다룰 수 있다"
def test_other_staff_cannot_touch_assigned_inspection(client, inspection_id):
    _upload(client, inspection_id, MATCHING_STATEMENT.encode(), headers=STAFF)
    response = client.patch(
        f"/inspections/{inspection_id}/lines/1", json={}, headers=OTHER_STAFF
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN_ROLE"
    response = client.post(
        f"/inspections/{inspection_id}/confirm", headers=OTHER_STAFF
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN_ROLE"
    # 담당 직원은 그대로 확정할 수 있다
    assert (
        client.post(f"/inspections/{inspection_id}/confirm", headers=STAFF).status_code
        == 200
    )


def test_owner_can_touch_any_staffs_inspection(client, inspection_id):
    _upload(client, inspection_id, MATCHING_STATEMENT.encode(), headers=STAFF)
    assert (
        client.post(f"/inspections/{inspection_id}/confirm", headers=OWNER).status_code
        == 200
    )


# ---------- 직원 확인 ----------


def test_unknown_item_needs_check_before_confirm(client, product_id, inspection_id):
    _upload(client, inspection_id, "알 수 없는 품목 10개 × 2,650원\n".encode())
    draft = _get(client, inspection_id)
    [line] = draft["lines"]
    assert line["candidates"] == []
    assert draft["check_count"] == 1

    response = client.post(f"/inspections/{inspection_id}/confirm", headers=STAFF)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CHECK_REQUIRED"

    # 직원이 품목을 골라 주면 확정할 수 있다
    response = client.patch(
        f"/inspections/{inspection_id}/lines/{line['id']}",
        json={"product_id": product_id},
        headers=STAFF,
    )
    assert response.json()["check_count"] == 0
    response = client.post(f"/inspections/{inspection_id}/confirm", headers=STAFF)
    assert response.json()["status"] == "재고 반영 완료"
    assert _stock(client, product_id) == 10


def test_unsupported_file_type_is_rejected(client, inspection_id):
    response = _upload(client, inspection_id, b"x", "a.zip", "application/zip")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert _get(client, inspection_id)["status"] == "업로드 대기"


def test_cannot_upload_twice_while_reviewing(client, inspection_id):
    _upload(client, inspection_id, MATCHING_STATEMENT.encode())
    response = _upload(client, inspection_id, MATCHING_STATEMENT.encode())
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


def test_owner_approval_records_history_and_preserves_shortfall(
    client, product_id, order_id, inspection_id
):
    _upload(client, inspection_id, "서울우유 1000ml 8개 × 2,900원\n".encode())
    response = client.post(f"/inspections/{inspection_id}/confirm", headers=STAFF)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REASON_REQUIRED"
    response = client.post(
        f"/inspections/{inspection_id}/confirm",
        headers=STAFF,
        json={"reason": "수량 및 단가 차이"},
    )
    assert response.json()["exception_reason"] == "수량 및 단가 차이"
    assert (
        client.post(f"/inspections/{inspection_id}/approve", headers=STAFF).status_code
        == 403
    )
    response = client.post(f"/inspections/{inspection_id}/approve", headers=OWNER)
    assert response.json()["status"] == "재고 반영 완료"
    assert _stock(client, product_id) == 8
    assert _order_status(client, order_id) == "입고 대기"
    assert (
        client.post(f"/inspections/{inspection_id}/approve", headers=OWNER).status_code
        == 400
    )
    history = client.get(f"/inspections/{inspection_id}/history", headers=OWNER).json()
    assert {"판독 원본", "직원 확정", "재고 반영", "approve"} <= {
        row["kind"] for row in history
    }
    logs = client.get(
        f"/inspections/{inspection_id}/reading-logs", headers=OWNER
    ).json()
    assert len(logs) == 1 and logs[0]["outcome"] == "성공"
    assert logs[0]["cost"] is None
    assert (
        client.get(
            f"/inspections/{inspection_id}/history", headers=OTHER_STORE_OWNER
        ).status_code
        == 404
    )


def test_reject_requires_reason_and_can_reinspect(client, inspection_id):
    _upload(client, inspection_id, "서울우유 1000ml 8개 × 2,650원\n".encode())
    client.post(
        f"/inspections/{inspection_id}/confirm",
        headers=STAFF,
        json={"reason": "수량 차이"},
    )
    assert (
        client.post(f"/inspections/{inspection_id}/reject", headers=OWNER).status_code
        == 400
    )
    response = client.post(
        f"/inspections/{inspection_id}/reject", headers=OWNER, json={"reason": "재확인"}
    )
    assert response.json()["reject_reason"] == "재확인"
    assert (
        client.post(
            f"/inspections/{inspection_id}/cancel-confirmation", headers=STAFF
        ).status_code
        == 400
    )
    assert (
        client.post(f"/inspections/{inspection_id}/reinspect", headers=STAFF).json()[
            "status"
        ]
        == "직원 확인 대기"
    )


def test_reading_unexpected_error_allows_retry(client, inspection_id, monkeypatch):
    from app.services import reading

    def fail():
        raise RuntimeError("engine unavailable")

    monkeypatch.setattr(reading, "get_ocr_engine", fail)
    _upload(client, inspection_id, MATCHING_STATEMENT.encode())
    assert _get(client, inspection_id)["status"] == "업로드 대기"
    logs = client.get(
        f"/inspections/{inspection_id}/reading-logs", headers=OWNER
    ).json()
    assert logs[0]["outcome"] == "실패"


def test_redelivery_uses_remaining_quantity(
    client, product_id, order_id, inspection_id
):
    _upload(client, inspection_id, "서울우유 1000ml 8개 × 2,650원\n".encode())
    client.post(
        f"/inspections/{inspection_id}/confirm", headers=STAFF, json={"reason": "부족"}
    )
    client.post(f"/inspections/{inspection_id}/approve", headers=OWNER)
    assert client.get(
        f"/purchase-orders/{order_id}/remaining", headers=OWNER
    ).json() == [{"product_id": product_id, "remaining_quantity": 2}]
    response = client.post(f"/purchase-orders/{order_id}/redeliveries", headers=STAFF)
    new_id = response.json()["inspection_id"]
    assert (
        client.post(
            f"/purchase-orders/{order_id}/redeliveries", headers=STAFF
        ).status_code
        == 400
    )
    _upload(client, new_id, "서울우유 1000ml 2개 × 2,650원\n".encode())
    assert _get(client, new_id)["all_match"] is True
    assert (
        client.post(f"/inspections/{new_id}/confirm", headers=STAFF).status_code == 200
    )
    assert _stock(client, product_id) == 10
    assert _order_status(client, order_id) == "입고 완료"


def test_exception_photos_are_store_scoped(client, inspection_id):
    _upload(client, inspection_id, MATCHING_STATEMENT.encode())
    response = client.post(
        f"/inspections/{inspection_id}/exception-photos",
        headers=STAFF,
        files={"file": ("photo.png", b"example", "image/png")},
    )
    photo_id = response.json()["id"]
    assert (
        client.get(
            f"/inspections/{inspection_id}/exception-photos/{photo_id}", headers=OWNER
        ).content
        == b"example"
    )
    assert (
        client.get(
            f"/inspections/{inspection_id}/exception-photos/{photo_id}",
            headers=OTHER_STORE_OWNER,
        ).status_code
        == 404
    )


# ---------- 규칙 검증 실패 칸 (US-03 안전장치, 미팅1 피드백 6) ----------


def test_amount_mismatch_blocks_confirm_until_checked(
    client, product_id, inspection_id
):
    _upload(
        client,
        inspection_id,
        "서울우유 1000ml 10개 × 2,650원 = 20,000원\n".encode(),
    )
    line = _get(client, inspection_id)["lines"][0]
    assert line["rule_violations"] == ["AMOUNT_MISMATCH"]
    assert line["checked"] is False

    response = client.post(f"/inspections/{inspection_id}/confirm", headers=STAFF)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CHECK_REQUIRED"

    client.patch(
        f"/inspections/{inspection_id}/lines/{line['id']}",
        json={"checked": True},
        headers=STAFF,
    )
    response = client.post(f"/inspections/{inspection_id}/confirm", headers=STAFF)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "재고 반영 완료"


def test_number_not_in_ocr_is_flagged(
    client, product_id, inspection_id, monkeypatch
):
    from app.services import reading
    from app.services.structurer import Candidate, DraftLine

    class FakeStructurer:
        total_amount = None

        def structure(self, masked_text, products):
            return [
                DraftLine(
                    name="서울우유 1000ml",
                    quantity=10,
                    unit="개",
                    unit_price=2650,
                    amount=99999,  # OCR 글자(아래 명세서)에 없는 숫자
                    candidates=[Candidate(product_id, 1.0, "테스트 후보")],
                )
            ]

    monkeypatch.setattr(reading, "get_structurer", lambda: FakeStructurer())
    _upload(client, inspection_id, "서울우유 1000ml 10개 × 2,650원\n".encode())
    line = _get(client, inspection_id)["lines"][0]
    assert "NUMBER_NOT_IN_OCR" in line["rule_violations"]

    response = client.post(f"/inspections/{inspection_id}/confirm", headers=STAFF)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CHECK_REQUIRED"

    client.patch(
        f"/inspections/{inspection_id}/lines/{line['id']}",
        json={"checked": True},
        headers=STAFF,
    )
    response = client.post(f"/inspections/{inspection_id}/confirm", headers=STAFF)
    assert response.status_code == 200, response.text


def test_summary_mismatch_blocks_confirm_until_summary_checked(
    client, product_id, inspection_id
):
    statement = "서울우유 1000ml 10개 × 2,650원 = 26,500원\n합계 30,000원\n"
    _upload(client, inspection_id, statement.encode())
    draft = _get(client, inspection_id)
    assert draft["total_amount"] == 30000
    assert draft["summary_mismatch"] is True
    assert draft["summary_checked"] is False

    response = client.post(f"/inspections/{inspection_id}/confirm", headers=STAFF)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CHECK_REQUIRED"

    client.post(f"/inspections/{inspection_id}/summary-check", headers=STAFF)
    response = client.post(f"/inspections/{inspection_id}/confirm", headers=STAFF)
    assert response.status_code == 200, response.text


def test_summary_check_requires_assigned_employee_or_owner(client, inspection_id):
    _upload(client, inspection_id, MATCHING_STATEMENT.encode(), headers=STAFF)
    response = client.post(
        f"/inspections/{inspection_id}/summary-check", headers=OTHER_STAFF
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN_ROLE"
    assert (
        client.post(
            f"/inspections/{inspection_id}/summary-check", headers=OWNER
        ).status_code
        == 200
    )


# ---------- 정확도 지표 (US-07, 미팅1 피드백 8) ----------


def test_metrics_for_perfect_match(client, product_id, inspection_id):
    _upload(client, inspection_id, MATCHING_STATEMENT.encode())
    client.post(f"/inspections/{inspection_id}/confirm", headers=STAFF)
    metrics = client.get(f"/inspections/{inspection_id}/metrics", headers=OWNER).json()
    assert metrics["line_count"] == 1
    assert metrics["field_accuracy"] == {
        "품목": 1.0,
        "수량": 1.0,
        "단위": 1.0,
        "단가": 1.0,
        "금액": 1.0,
    }
    assert metrics["corrected_line_ratio"] == 0.0
    assert metrics["added_line_ratio"] == 0.0
    assert metrics["upload_to_confirm_seconds"] >= 0


def test_metrics_reflect_corrected_unknown_item(client, product_id, inspection_id):
    _upload(client, inspection_id, "알 수 없는 품목 10개 × 2,650원\n".encode())
    [line] = _get(client, inspection_id)["lines"]
    client.patch(
        f"/inspections/{inspection_id}/lines/{line['id']}",
        json={"product_id": product_id},
        headers=STAFF,
    )
    client.post(f"/inspections/{inspection_id}/confirm", headers=STAFF)
    metrics = client.get(f"/inspections/{inspection_id}/metrics", headers=OWNER).json()
    # 후보가 없어 직원이 고른 품목만 정확도에서 틀렸다고 센다
    assert metrics["field_accuracy"]["품목"] == 0.0
    assert metrics["field_accuracy"]["수량"] == 1.0
    assert metrics["field_accuracy"]["단위"] == 1.0
    assert metrics["corrected_line_ratio"] == 1.0


def test_metrics_only_owner_can_view(client, inspection_id):
    _upload(client, inspection_id, MATCHING_STATEMENT.encode())
    response = client.get(f"/inspections/{inspection_id}/metrics", headers=STAFF)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN_ROLE"
    response = client.get(
        f"/inspections/{inspection_id}/metrics", headers=OTHER_STORE_OWNER
    )
    assert response.status_code == 404


def test_openai_structurer_sends_masked_text_and_records_usage(
    monkeypatch, client, inspection_id
):
    from types import SimpleNamespace

    import openai

    seen = []

    class FakeResponses:
        def parse(self, **kwargs):
            seen.append(kwargs)
            parsed = kwargs["text_format"](
                lines=[
                    {
                        "name": "서울우유 1000ml",
                        "quantity": 10,
                        "unit": "개",
                        "unit_price": 2650,
                        "amount": 26500,
                    }
                ]
            )
            return SimpleNamespace(
                output_parsed=parsed,
                usage=SimpleNamespace(input_tokens=100, output_tokens=20),
            )

    monkeypatch.setattr(
        openai, "OpenAI", lambda **kwargs: SimpleNamespace(responses=FakeResponses())
    )
    monkeypatch.setenv("STRUCTURER", "openai")
    monkeypatch.setenv("OPENAI_INPUT_USD_PER_MILLION", "1")
    monkeypatch.setenv("OPENAI_OUTPUT_USD_PER_MILLION", "2")
    _upload(client, inspection_id, MATCHING_STATEMENT.encode())
    assert _get(client, inspection_id)["status"] == "직원 확인 대기"
    assert "홍길동" not in str(seen) and "010-0000-0000" not in str(seen)
    assert seen[0]["store"] is False
    log = client.get(
        f"/inspections/{inspection_id}/reading-logs", headers=OWNER
    ).json()[0]
    assert (log["input_tokens"], log["output_tokens"]) == (100, 20)
    assert log["cost"] == pytest.approx(0.00014)


def test_unregistered_item_requires_product_registration_and_owner_approval(
    client, product_id, inspection_id
):
    _upload(client, inspection_id, "새 원두 2개 × 3,000원\n".encode())
    line = _get(client, inspection_id)["lines"][0]
    assert (
        client.post(
            f"/inspections/{inspection_id}/confirm",
            headers=STAFF,
            json={"reason": "신규 상품"},
        ).status_code
        == 400
    )
    new_product = client.post(
        "/products",
        headers=OWNER,
        json={
            "product_code": "NEW",
            "name": "새 원두",
            "base_unit": "개",
            "base_unit_price": 3000,
        },
    ).json()["id"]
    response = client.patch(
        f"/inspections/{inspection_id}/lines/{line['id']}",
        headers=STAFF,
        json={"product_id": new_product},
    )
    assert response.json()["lines"][0]["match_status"] == "발주에 없음"
    client.post(
        f"/inspections/{inspection_id}/confirm",
        headers=STAFF,
        json={"reason": "신규 상품"},
    )
    assert _stock(client, new_product) == 0
    assert (
        client.post(f"/inspections/{inspection_id}/approve", headers=OWNER).status_code
        == 200
    )
    assert _stock(client, new_product) == 2


def test_openai_sdk_structured_response(monkeypatch):
    import httpx
    import openai

    from app.services.structurer import OpenAIStructurer

    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 0,
                "model": "gpt-4o-mini",
                "status": "completed",
                "error": None,
                "incomplete_details": None,
                "instructions": None,
                "metadata": {},
                "output": [
                    {
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    '{"lines":[{"name":"우유","quantity":2,'
                                    '"unit":"개","unit_price":10,"amount":20}]}'
                                ),
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
            },
        )

    real_client = openai.OpenAI
    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda **kwargs: real_client(
            api_key="test",
            http_client=httpx.Client(transport=httpx.MockTransport(respond)),
            **kwargs,
        ),
    )
    result = OpenAIStructurer().structure("우유 2개", [])
    assert result[0].quantity == 2
    assert b'"store":false' in requests[0].content
