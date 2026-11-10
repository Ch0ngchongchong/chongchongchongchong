# 첫 데모 시나리오 (3주차) 0~5단계 + '질문이 오면' 3가지
# 사용자: conftest.py 시드 — 1 = 매장 1 사장님, 2 = 매장 1 직원, 3 = 매장 2 사장님
# 데이터: DATA-MODEL.md 시드 #2(상품) · #4(발주) · #5(입고 검수 건)
# OCR은 데모 엔진(OCR_ENGINE=demo), LLM 자리는 규칙 기반 정리기(STRUCTURER=rule)다.

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

    response = client.post(f"/inspections/{inspection_id}/confirm", headers=STAFF)
    assert response.json()["status"] == "사장 승인 대기"
    assert _stock(client, product_id) == 0
    assert _order_status(client, order_id) == "입고 대기"


def test_price_difference_goes_to_owner_approval(client, product_id, inspection_id):
    _upload(client, inspection_id, "서울우유 1000ml 10개 × 2,900원\n".encode())
    assert _get(client, inspection_id)["lines"][0]["match_status"] == "단가 다름"
    response = client.post(f"/inspections/{inspection_id}/confirm", headers=STAFF)
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
