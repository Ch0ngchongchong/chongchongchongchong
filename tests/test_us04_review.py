# US-04 발주·납품 대조 및 일반 건 확정 — 인수 조건 중 test_demo_scenario.py가
# 확인하지 않는 것
# 근거: document 저장소 docs/requirements/backlog.md US-04 인수 조건
# 사용자: conftest.py 시드 — 1 = 매장 1 사장님, 2 = 매장 1 직원, 3 = 매장 2 사장님
# 이 파일은 테스트를 먼저 쓴 것이다. 구현이 없는 조건은 @NOT_IMPLEMENTED로 표시했다.
#
# 이 파일에서 다루지 않은 US-04 인수 조건 (팀 질문으로 남김)
#  - 직원이 판독 결과에 없는 줄을 추가하고 '직원이 추가한 줄'로 이력에 남기기:
#    줄 추가 API 약속이 없음 (main docs/api, PR #8 API 문서 모두 없음)
#  - 규칙 검증 실패 칸을 직원이 '확인'하는 방법: API 약속이 없어 '확정할 수 없다'만 확인

from types import SimpleNamespace

import pytest

# 아직 구현이 없는 인수 조건 표시. 기대값은 그대로 두고 표시만 한다.
# strict=True라서 구현이 끝나 통과하면 이 표시 때문에 실패한다 → 그때 표시를 지운다
NOT_IMPLEMENTED = pytest.mark.xfail(
    strict=True, reason="US-04 구현 전 (테스트 먼저 작성, document 이슈 #144)"
)

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
PAPER_CUP = {
    "product_code": "P-0201",
    "name": "종이컵 12oz",
    "spec": "12oz",
    "base_unit": "개",
    "pack_unit": "박스",
    "conversion_qty": 24,
}

# 시드 값으로 만든 가상 명세서 (발주 P-0123 × 10과 모두 일치)
MATCHING_STATEMENT = """\
거래명세서
서울우유 1000ml 10개 × 2,650원 = 26,500원
합계 26,500원
"""


@pytest.fixture(autouse=True)
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    return tmp_path


def _create_product(client, product):
    response = client.post("/products", json=product, headers=OWNER)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _inspection_for_order(client, lines):
    """발주를 `입고 대기`까지 보내고 만들어진 `업로드 대기` 검수 건 ID를 돌려준다."""
    order = client.post(
        "/purchase-orders",
        json={"supplier": "(가상) 공급처 A", "lines": lines},
        headers=OWNER,
    ).json()
    assert client.post(
        f"/purchase-orders/{order['id']}/approve", headers=OWNER
    ).is_success
    assert client.post(
        f"/purchase-orders/{order['id']}/mark-delivered", headers=OWNER
    ).is_success
    [inspection] = client.get(
        "/inspections", params={"status": "업로드 대기"}, headers=STAFF
    ).json()
    return inspection["id"]


@pytest.fixture
def product_id(client):
    return _create_product(client, SEOUL_MILK)


@pytest.fixture
def inspection_id(client, product_id):
    """발주 P-0123 × 10의 `업로드 대기` 검수 건"""
    return _inspection_for_order(client, [{"product_id": product_id, "quantity": 10}])


def _upload(client, inspection_id, text):
    response = client.post(
        f"/inspections/{inspection_id}/document",
        files={"file": ("statement.txt", text.encode(), "text/plain")},
        headers=STAFF,
    )
    assert response.status_code == 200, response.text
    return response


def _get(client, inspection_id):
    response = client.get(f"/inspections/{inspection_id}", headers=STAFF)
    assert response.status_code == 200, response.text
    return response.json()


def _confirm(client, inspection_id, reason=None, headers=STAFF):
    body = None if reason is None else {"reason": reason}
    return client.post(
        f"/inspections/{inspection_id}/confirm", headers=headers, json=body
    )


def _patch_line(client, inspection_id, line_id, changes, headers=STAFF):
    return client.patch(
        f"/inspections/{inspection_id}/lines/{line_id}", json=changes, headers=headers
    )


def _stock(client, product_id):
    rows = client.get("/inventory", headers=OWNER).json()
    return next(
        (row["quantity"] for row in rows if row["product_id"] == product_id), 0
    )


def _llm_returns(monkeypatch, document):
    """LLM(OpenAI) 자리에 정해진 공통 JSON을 돌려주는 가짜를 끼운다.
    OCR은 데모 엔진(text/plain 내용을 그대로 읽음)을 쓴다."""
    import openai

    class FakeResponses:
        def parse(self, **kwargs):
            return SimpleNamespace(
                output_parsed=kwargs["text_format"](**document),
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            )

    monkeypatch.setattr(
        openai, "OpenAI", lambda **kwargs: SimpleNamespace(responses=FakeResponses())
    )
    monkeypatch.setenv("STRUCTURER", "openai")
    monkeypatch.setenv("OCR_ENGINE", "demo")


# ---------- (정상) 예외 건이면 `사장 승인 대기`, 재고는 그대로 ----------


def test_us04_damaged_line_goes_to_owner_approval(client, product_id, inspection_id):
    # US-04 (정상) 확정한 내용에 파손이 하나라도 있으면(예외 건) `사장 승인 대기`가
    # 되고 재고는 바뀌지 않는다. 파손 표시 방법은 PR #8 API 문서의
    # `PATCH .../lines/{id}` `{"damaged": true}`를 [제안]으로 따랐다
    _upload(client, inspection_id, MATCHING_STATEMENT)
    [line] = _get(client, inspection_id)["lines"]
    response = _patch_line(client, inspection_id, line["id"], {"damaged": True})
    assert response.status_code == 200, response.text
    assert response.json()["all_match"] is False

    response = _confirm(client, inspection_id, reason="상자 파손")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "사장 승인 대기"
    assert _stock(client, product_id) == 0


def test_us04_order_line_missing_in_statement_goes_to_owner_approval(client):
    # US-04 (정상) 수량 차이가 있으면(예외 건) `사장 승인 대기`, 재고는 그대로다.
    # 발주에 있는 종이컵 줄이 명세서에 아예 없음 (= 0개 들어옴)
    milk = _create_product(client, SEOUL_MILK)
    cup = _create_product(client, PAPER_CUP)
    inspection_id = _inspection_for_order(
        client,
        [
            {"product_id": milk, "quantity": 10},
            {"product_id": cup, "quantity": 48},
        ],
    )
    _upload(client, inspection_id, MATCHING_STATEMENT)
    draft = _get(client, inspection_id)
    assert draft["all_match"] is False

    response = _confirm(client, inspection_id, reason="종이컵 안 옴")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "사장 승인 대기"
    assert _stock(client, milk) == 0
    assert _stock(client, cup) == 0


# ---------- (실패·거절) 강조된 칸이 확인되지 않았으면 확정할 수 없다 ----------


def test_us04_multiple_candidates_must_be_checked_before_confirm(
    client, product_id, inspection_id
):
    # US-04 (실패·거절) 품목 후보가 2개 이상인 칸이 확인되지 않았으면 확정할 수 없다.
    # 직원이 상품을 고르면 확정할 수 있다
    _create_product(client, {"product_code": "P-0124", "name": "서울우유 900ml"})
    _upload(client, inspection_id, MATCHING_STATEMENT)
    [line] = _get(client, inspection_id)["lines"]
    assert len(line["candidates"]) >= 2  # 전제: 비슷한 상품 2개가 후보로 나옴

    response = _confirm(client, inspection_id)
    assert response.status_code == 400
    assert _get(client, inspection_id)["status"] == "직원 확인 대기"
    assert _stock(client, product_id) == 0

    _patch_line(client, inspection_id, line["id"], {"product_id": product_id})
    response = _confirm(client, inspection_id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "재고 반영 완료"


def test_us04_rule_check_failure_blocks_confirm(client, product_id, inspection_id):
    # US-04 (실패·거절) 규칙 검증 실패 칸(수량×단가≠금액)이 확인되지 않았으면
    # 확정할 수 없다. 10 × 2,650 = 26,500인데 금액이 30,000
    _upload(
        client,
        inspection_id,
        "서울우유 1000ml 10개 × 2,650원 = 30,000원\n합계 30,000원\n",
    )
    response = _confirm(client, inspection_id)
    assert response.status_code == 400
    assert _get(client, inspection_id)["status"] == "직원 확인 대기"
    assert _stock(client, product_id) == 0


def test_us04_uncertain_value_must_be_filled_before_confirm(
    monkeypatch, client, product_id, inspection_id
):
    # US-04 (실패·거절) 불확실한 값(uncertain_fields) 칸이 확인되지 않았으면
    # 확정할 수 없다. 직원이 수량을 직접 넣으면 확정할 수 있다
    _llm_returns(
        monkeypatch,
        {
            "document_date": None,
            "lines": [
                {
                    "name": "서울우유 1000ml",
                    "quantity": 10,
                    "unit": "개",
                    "unit_price": 2650,
                    "amount": 26500,
                    "uncertain_fields": ["quantity"],
                }
            ],
            "total_amount": 26500,
            "uncertain_fields": [],
        },
    )
    _upload(client, inspection_id, MATCHING_STATEMENT)
    response = _confirm(client, inspection_id)
    assert response.status_code == 400
    assert _get(client, inspection_id)["status"] == "직원 확인 대기"
    assert _stock(client, product_id) == 0

    [line] = _get(client, inspection_id)["lines"]
    _patch_line(client, inspection_id, line["id"], {"quantity": 10})
    response = _confirm(client, inspection_id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "재고 반영 완료"


# ---------- (실패·거절) `재고 반영 완료`된 건은 다시 수정할 수 없다 ----------


def test_us04_applied_inspection_cannot_be_edited(client, product_id, inspection_id):
    # US-04 (실패·거절) `재고 반영 완료`가 된 건은 직원이 다시 수정할 수 없다
    _upload(client, inspection_id, MATCHING_STATEMENT)
    [line] = _get(client, inspection_id)["lines"]
    assert _confirm(client, inspection_id).json()["status"] == "재고 반영 완료"

    response = _patch_line(client, inspection_id, line["id"], {"quantity": 1})
    assert response.status_code >= 400
    after = _get(client, inspection_id)
    assert after["status"] == "재고 반영 완료"
    assert after["lines"][0]["quantity"] == 10
    assert _stock(client, product_id) == 10


# ---------- (권한) 다른 매장 사용자 ----------


def test_us04_other_store_cannot_edit_or_confirm(client, product_id, inspection_id):
    # US-04 (권한) 다른 매장 사용자는 이 입고 검수 건을 볼 수 없다
    # (볼 수 없는 건은 고치거나 확정할 수도 없다)
    _upload(client, inspection_id, MATCHING_STATEMENT)
    [line] = _get(client, inspection_id)["lines"]

    response = _patch_line(
        client, inspection_id, line["id"], {"quantity": 1}, headers=OTHER_STORE_OWNER
    )
    assert response.status_code >= 400
    response = _confirm(client, inspection_id, headers=OTHER_STORE_OWNER)
    assert response.status_code >= 400

    after = _get(client, inspection_id)
    assert after["status"] == "직원 확인 대기"
    assert after["lines"][0]["quantity"] == 10
    assert _stock(client, product_id) == 0


# ---------- (LLM) 이 단계에서는 LLM을 호출하지 않는다 ----------


def test_us04_confirm_does_not_call_llm(monkeypatch, client, product_id, inspection_id):
    # US-04 (LLM) 해당 없음 — 대조·확정 단계에서는 LLM을 호출하지 않는다
    from app.services import reading, structurer

    _upload(client, inspection_id, MATCHING_STATEMENT)

    def must_not_be_called(*args, **kwargs):
        raise AssertionError("확정 단계에서 LLM(정리기)을 불렀다")

    monkeypatch.setattr(reading, "get_structurer", must_not_be_called)
    monkeypatch.setattr(structurer, "get_structurer", must_not_be_called)
    [line] = _get(client, inspection_id)["lines"]
    _patch_line(client, inspection_id, line["id"], {"quantity": 10})
    response = _confirm(client, inspection_id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "재고 반영 완료"
