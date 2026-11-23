# US-03 거래명세서 업로드·판독 — 인수 조건 중 test_demo_scenario.py가 확인하지 않는 것
# 근거: document 저장소 docs/requirements/backlog.md US-03 인수 조건,
#       필드 이름은 docs/DATA-MODEL.md '판독 결과 줄'(spec, uncertain_fields)과
#       03 3-4 공통 JSON(document_date, lines, total_amount, uncertain_fields)
# 사용자: conftest.py 시드 — 1 = 매장 1 사장님, 2 = 매장 1 직원
# 이 파일은 테스트를 먼저 쓴 것이다. 구현이 없어 실패하는 테스트가 있다.
#
# 이 파일에서 다루지 않은 US-03 인수 조건 (팀 질문으로 남김)
#  - 판독 완료 알림, 판독 실패 시 다시 올려 달라는 알림: 알림 API 약속이 없음
#  - 사진·PDF가 아닌 파일 거절: 지금 서버는 데모용으로 text/plain을 받는다.
#    text/plain도 거절해야 하는지 팀이 정해야 함

from types import SimpleNamespace

import pytest

# 아직 구현이 없는 인수 조건 표시. 기대값은 그대로 두고 표시만 한다.
# strict=True라서 구현이 끝나 통과하면 이 표시 때문에 실패한다 → 그때 표시를 지운다
NOT_IMPLEMENTED = pytest.mark.xfail(
    strict=True, reason="US-03 구현 전 (테스트 먼저 작성, document 이슈 #143)"
)

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

# 시드 값으로 만든 가상 명세서 (발주와 모두 일치). 실제 개인정보·사업자 정보 아님
MATCHING_STATEMENT = """\
거래명세서
서울우유 1000ml 1L 10개 × 2,650원 = 26,500원
합계 26,500원
"""

# 03 3-4 공통 JSON 모양의 정상 LLM 출력 (발주와 모두 일치)
MATCHING_LINE = {
    "raw_name": "서울우유 1000ml",
    "name": "서울우유 1000ml",
    "spec": "1L",
    "quantity": 10,
    "unit": "개",
    "unit_price": 2650,
    "amount": 26500,
    "uncertain_fields": [],
}


def _document(**line_changes):
    return {
        "document_date": None,
        "lines": [{**MATCHING_LINE, **line_changes}],
        "total_amount": 26500,
        "uncertain_fields": [],
    }


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
def inspection_id(client, product_id):
    """발주(P-0123 × 10)를 `입고 대기`까지 보내 `업로드 대기` 검수 건을 만든다."""
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
    [inspection] = client.get(
        "/inspections", params={"status": "업로드 대기"}, headers=STAFF
    ).json()
    return inspection["id"]


def _upload(client, inspection_id, content, filename="statement.txt",
            content_type="text/plain"):
    response = client.post(
        f"/inspections/{inspection_id}/document",
        files={"file": (filename, content, content_type)},
        headers=STAFF,
    )
    assert response.status_code == 200, response.text
    return response


def _get(client, inspection_id):
    response = client.get(f"/inspections/{inspection_id}", headers=STAFF)
    assert response.status_code == 200, response.text
    return response.json()


def _llm_returns(monkeypatch, document):
    """LLM(OpenAI) 자리에 정해진 공통 JSON을 돌려주는 가짜를 끼운다.
    OCR은 데모 엔진(text/plain 내용을 그대로 읽음)을 쓴다. 보낸 요청을 돌려준다."""
    import openai

    seen = []

    class FakeResponses:
        def parse(self, **kwargs):
            seen.append(kwargs)
            return SimpleNamespace(
                output_parsed=kwargs["text_format"](**document),
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            )

    monkeypatch.setattr(
        openai, "OpenAI", lambda **kwargs: SimpleNamespace(responses=FakeResponses())
    )
    monkeypatch.setenv("STRUCTURER", "openai")
    monkeypatch.setenv("OCR_ENGINE", "demo")
    return seen


def _llm_returns_text(monkeypatch, output_text):
    """실제 OpenAI SDK가 받는 응답 본문의 글자(output_text)를 정해 둔다.
    JSON 모양이 맞지 않는 LLM 출력을 흉내 낼 때 쓴다."""
    import httpx
    import openai

    def respond(request):
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
                                "text": output_text,
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
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
    monkeypatch.setenv("STRUCTURER", "openai")
    monkeypatch.setenv("OCR_ENGINE", "demo")


# ---------- (정상) 줄마다 품목명·규격·수량·단위·단가·금액 ----------


@NOT_IMPLEMENTED
def test_us03_each_line_shows_spec(monkeypatch, client, product_id, inspection_id):
    # US-03 (정상) 각 줄이 품목명·규격·수량·단위·단가·금액과 품목 후보로 표시된다
    _llm_returns(monkeypatch, _document())
    _upload(client, inspection_id, MATCHING_STATEMENT.encode())
    draft = _get(client, inspection_id)
    assert draft["status"] == "직원 확인 대기"
    [line] = draft["lines"]
    assert line["read"]["spec"] == "1L"


# ---------- (정상) 불확실한 값·규칙 검증 실패 칸은 추측값 없이 빈칸으로 강조 ----------


@NOT_IMPLEMENTED
def test_us03_uncertain_value_is_blank_and_highlighted(
    monkeypatch, client, product_id, inspection_id
):
    # US-03 (정상) LLM이 확신하지 못한 값(uncertain_fields)은 추측값 없이 빈칸으로
    # 강조 표시된다. LLM이 값을 채워 보냈더라도 화면에는 빈칸이어야 한다
    _llm_returns(monkeypatch, _document(uncertain_fields=["quantity"]))
    _upload(client, inspection_id, MATCHING_STATEMENT.encode())
    draft = _get(client, inspection_id)
    [line] = draft["lines"]
    assert line["read"]["quantity"] is None
    assert line["quantity"] is None
    assert line["uncertain_fields"] == ["quantity"]
    assert draft["check_count"] == 1


@NOT_IMPLEMENTED
def test_us03_quantity_times_price_not_amount_is_highlighted(
    client, product_id, inspection_id
):
    # US-03 (정상) 규칙 검증 실패 칸(수량×단가≠금액)은 강조 표시된다
    # 10 × 2,650 = 26,500인데 금액이 30,000.
    # 합계는 금액과 같게 둬서 이 규칙만 어긋나게 함
    statement = "서울우유 1000ml 10개 × 2,650원 = 30,000원\n합계 30,000원\n"
    _upload(client, inspection_id, statement.encode())
    draft = _get(client, inspection_id)
    assert draft["status"] == "직원 확인 대기"
    assert draft["check_count"] == 1
    assert draft["all_match"] is False


@NOT_IMPLEMENTED
def test_us03_line_amounts_not_total_is_highlighted(client, product_id, inspection_id):
    # US-03 (정상) 규칙 검증 실패 칸(줄 금액 합≠합계)은 강조 표시된다
    # 줄 금액 26,500인데 합계가 30,000
    statement = "서울우유 1000ml 10개 × 2,650원 = 26,500원\n합계 30,000원\n"
    _upload(client, inspection_id, statement.encode())
    draft = _get(client, inspection_id)
    assert draft["status"] == "직원 확인 대기"
    assert draft["check_count"] == 1
    assert draft["all_match"] is False


@NOT_IMPLEMENTED
def test_us03_number_not_in_ocr_text_is_blank_and_highlighted(
    monkeypatch, client, product_id, inspection_id
):
    # US-03 (정상) OCR 글자에 없는 숫자가 판독 결과에 있으면 추측값 없이 빈칸으로
    # 강조 표시된다 (미팅1 피드백 6). OCR 글자는 10개인데 LLM이 12를 돌려줌
    _llm_returns(monkeypatch, _document(quantity=12, amount=31800))
    _upload(client, inspection_id, MATCHING_STATEMENT.encode())
    draft = _get(client, inspection_id)
    [line] = draft["lines"]
    assert line["read"]["quantity"] is None
    assert line["quantity"] is None
    assert draft["check_count"] >= 1


# ---------- (정상) 판독 로그 ----------


def test_us03_reading_log_records_tokens_cost_and_elapsed_time(
    monkeypatch, client, product_id, inspection_id
):
    # US-03 (정상) 판독 건마다 LLM 입력·출력 토큰 수, 호출 비용, 업로드부터
    # `직원 확인 대기`까지 걸린 시간이 판독 로그에 남는다
    _llm_returns(monkeypatch, _document())
    monkeypatch.setenv("OPENAI_INPUT_USD_PER_MILLION", "1")
    monkeypatch.setenv("OPENAI_OUTPUT_USD_PER_MILLION", "2")
    _upload(client, inspection_id, MATCHING_STATEMENT.encode())
    assert _get(client, inspection_id)["status"] == "직원 확인 대기"
    [log] = client.get(
        f"/inspections/{inspection_id}/reading-logs", headers=OWNER
    ).json()
    assert (log["input_tokens"], log["output_tokens"]) == (10, 5)
    assert log["cost"] is not None
    assert log["elapsed_seconds"] is not None
    assert log["elapsed_seconds"] >= 0


# ---------- (실패·거절) LLM 출력이 공통 JSON 모양이 아니면 판독 실패 ----------


@NOT_IMPLEMENTED
@pytest.mark.parametrize(
    "missing_field", ["document_date", "total_amount", "uncertain_fields"]
)
def test_us03_llm_output_missing_common_json_field_is_read_failure(
    monkeypatch, client, product_id, inspection_id, missing_field
):
    # US-03 (실패·거절) LLM 출력이 공통 JSON 필드 모양(document_date, lines,
    # total_amount, uncertain_fields)에 맞지 않으면 판독 실패로 `업로드 대기`로 돌아간다
    import json

    document = _document()
    del document[missing_field]
    _llm_returns_text(monkeypatch, json.dumps(document, ensure_ascii=False))
    _upload(client, inspection_id, MATCHING_STATEMENT.encode())
    inspection = _get(client, inspection_id)
    assert inspection["status"] == "업로드 대기"
    assert inspection["lines"] == []


def test_us03_llm_output_not_json_is_read_failure(
    monkeypatch, client, product_id, inspection_id
):
    # US-03 (실패·거절) LLM 출력이 JSON이 아니면 판독 실패로 `업로드 대기`로 돌아간다
    _llm_returns_text(monkeypatch, "서울우유 10개 2650원")
    _upload(client, inspection_id, MATCHING_STATEMENT.encode())
    assert _get(client, inspection_id)["status"] == "업로드 대기"


# ---------- (LLM) 후보가 없으면 빈 배열, 새 상품을 만들지 않는다 ----------


def test_us03_no_candidate_is_empty_and_no_product_is_created(
    client, product_id, inspection_id
):
    # US-03 (LLM) 후보가 없으면 빈 배열로 두며 새 상품을 만들지 않는다
    before = client.get("/products", headers=OWNER).json()
    _upload(client, inspection_id, "처음 보는 원두 2개 × 3,000원 = 6,000원\n".encode())
    [line] = _get(client, inspection_id)["lines"]
    assert line["candidates"] == []
    assert client.get("/products", headers=OWNER).json() == before


# ---------- (LLM) 보내지 않을 정보 ----------


def test_us03_business_info_is_not_sent_to_llm(
    monkeypatch, client, product_id, inspection_id
):
    # US-03 (LLM) 사업자 정보는 가린 뒤 보내며 LLM 요청에 포함되지 않는다
    # 가상 사업자등록번호. 낱말 없이 번호만 있는 줄도 넣었다
    statement = (
        "거래명세서\n"
        "사업자등록번호 123-45-67890\n"
        "(가상) 유제품 공급처 A 123-45-67890\n"
        "서울우유 1000ml 1L 10개 × 2,650원 = 26,500원\n"
        "합계 26,500원\n"
    )
    seen = _llm_returns(monkeypatch, _document())
    _upload(client, inspection_id, statement.encode())
    [request] = seen
    assert "123-45-67890" not in str(request)
    assert "서울우유 1000ml" in str(request)


def test_us03_original_photo_is_not_sent_to_llm(
    monkeypatch, client, product_id, inspection_id
):
    # US-03 (LLM) 원본 사진은 외부 LLM으로 보내지 않는다 (OCR 글자만 보낸다)
    seen = _llm_returns(monkeypatch, _document())
    photo = b"\xff\xd8\xff ORIGINAL-PHOTO-BYTES"
    _upload(client, inspection_id, photo, "photo.jpg", "image/jpeg")
    [request] = seen
    assert "ORIGINAL-PHOTO-BYTES" not in str(request)
    assert "input_image" not in str(request)
