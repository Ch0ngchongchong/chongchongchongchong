# US-05 단위 환산 및 수량 검증 — 인수 조건 중 test_demo_scenario.py가 확인하지 않는 것
# 근거: document 저장소 docs/requirements/backlog.md US-05 인수 조건,
#       상품 값은 docs/DATA-MODEL.md 시드 #2(서울우유)·#3(종이컵, 박스당 24개)
# 사용자: conftest.py 시드 — 1 = 매장 1 사장님, 2 = 매장 1 직원, 3 = 매장 2 사장님
#
# 이 파일에서 다루지 않은 US-05 인수 조건 (팀 질문으로 남김)
#  - 같은 상품이 한 명세서에 박스와 낱개로 섞여 적혀 있어 구분할 수 없는 경우:
#    무엇을 '구분할 수 없음'으로 볼지가 backlog US-05 미확정(R6)이라
#    기대 결과를 정할 수 없음

import pytest

OWNER = {"X-User-Id": "1"}
STAFF = {"X-User-Id": "2"}
OTHER_STORE_OWNER = {"X-User-Id": "3"}

# DATA-MODEL.md 시드 #3. 기준 단가는 시드에 근거가 없어 넣지 않았다
PAPER_CUP = {
    "product_code": "P-0201",
    "name": "종이컵 12oz",
    "spec": "12oz",
    "base_unit": "개",
    "pack_unit": "박스",
    "conversion_qty": 24,
}
# 같은 상품인데 환산값이 등록되지 않은 경우 (US-05 실패·거절)
PAPER_CUP_WITHOUT_CONVERSION = {**PAPER_CUP, "conversion_qty": None}


@pytest.fixture(autouse=True)
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    return tmp_path


def _create_product(client, product, headers=OWNER):
    response = client.post("/products", json=product, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _inspection_for_order(client, product_id, quantity):
    """매장 1 발주(상품 × 수량, 기준 단위)를 `입고 대기`까지 보내고
    만들어진 `업로드 대기` 검수 건 ID를 돌려준다."""
    order = client.post(
        "/purchase-orders",
        json={
            "supplier": "(가상) 포장재 공급처",
            "lines": [{"product_id": product_id, "quantity": quantity}],
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


def _upload(client, inspection_id, text):
    response = client.post(
        f"/inspections/{inspection_id}/document",
        files={"file": ("statement.txt", text.encode(), "text/plain")},
        headers=STAFF,
    )
    assert response.status_code == 200, response.text


def _get(client, inspection_id):
    response = client.get(f"/inspections/{inspection_id}", headers=STAFF)
    assert response.status_code == 200, response.text
    return response.json()


def _confirm(client, inspection_id):
    return client.post(f"/inspections/{inspection_id}/confirm", headers=STAFF)


def _patch_line(client, inspection_id, line_id, changes):
    return client.patch(
        f"/inspections/{inspection_id}/lines/{line_id}", json=changes, headers=STAFF
    )


def _stock(client, product_id, headers=OWNER):
    rows = client.get("/inventory", headers=headers).json()
    return next(
        (row["quantity"] for row in rows if row["product_id"] == product_id), 0
    )


# ---------- (정상) 박스 → 기준 재고 단위로 환산, 확정하면 재고에 반영 ----------


def test_us05_two_boxes_of_24_are_shown_as_48(client):
    # US-05 (정상) 환산값이 등록된 상품이 박스 단위로 적혀 있으면 기준 재고 단위로
    # 환산해 보여 준다 (인수 조건 예: 박스당 24개, 2박스 → 48개)
    cup = _create_product(client, PAPER_CUP)
    inspection_id = _inspection_for_order(client, cup, 48)
    _upload(client, inspection_id, "종이컵 12oz 2박스 × 1,200원 = 2,400원\n")
    [line] = _get(client, inspection_id)["lines"]
    assert line["product_id"] == cup
    assert line["base_quantity"] == 48


def test_us05_confirm_applies_converted_quantity_to_stock(client):
    # US-05 (정상) 확정되면 재고에는 환산된 기준 단위 수량(48개)이 반영된다
    cup = _create_product(client, PAPER_CUP)
    inspection_id = _inspection_for_order(client, cup, 48)
    _upload(client, inspection_id, "종이컵 12oz 2박스 × 1,200원 = 2,400원\n")
    response = _confirm(client, inspection_id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "재고 반영 완료"
    assert _stock(client, cup) == 48


# ---------- (실패·거절) 환산 못 하면 '확인 필요', 직원이 수량을 넣어야 확정 ----------


def test_us05_box_without_conversion_qty_needs_manual_quantity(client):
    # US-05 (실패·거절) 환산값이 등록되지 않았으면 자동 환산하지 않고 그 줄을
    # '확인 필요'로 강조하며, 직원이 수량을 직접 입력해야 확정할 수 있다
    cup = _create_product(client, PAPER_CUP_WITHOUT_CONVERSION)
    inspection_id = _inspection_for_order(client, cup, 48)
    _upload(client, inspection_id, "종이컵 12oz 2박스 × 1,200원 = 2,400원\n")
    draft = _get(client, inspection_id)
    [line] = draft["lines"]
    assert line["base_quantity"] is None
    assert line["match_status"] == "확인 필요"
    assert draft["check_count"] == 1

    response = _confirm(client, inspection_id)
    assert response.status_code == 400
    assert _get(client, inspection_id)["status"] == "직원 확인 대기"
    assert _stock(client, cup) == 0

    # 직원이 기준 단위 수량을 직접 넣는다
    _patch_line(client, inspection_id, line["id"], {"quantity": 48, "unit": "개"})
    response = _confirm(client, inspection_id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "재고 반영 완료"
    assert _stock(client, cup) == 48


def test_us05_unknown_unit_needs_manual_quantity(client):
    # US-05 (실패·거절) 단위를 알 수 없으면 자동 환산하지 않고 그 줄을 '확인 필요'로
    # 강조하며, 직원이 수량을 직접 입력해야 확정할 수 있다
    # ('통'은 이 상품의 기준 단위(개)도 포장 단위(박스)도 아님)
    cup = _create_product(client, PAPER_CUP)
    inspection_id = _inspection_for_order(client, cup, 48)
    _upload(client, inspection_id, "종이컵 12oz 2통 × 1,200원 = 2,400원\n")
    draft = _get(client, inspection_id)
    [line] = draft["lines"]
    assert line["base_quantity"] is None
    assert line["match_status"] == "확인 필요"
    assert draft["check_count"] == 1

    response = _confirm(client, inspection_id)
    assert response.status_code == 400
    assert _stock(client, cup) == 0

    _patch_line(client, inspection_id, line["id"], {"quantity": 48, "unit": "개"})
    response = _confirm(client, inspection_id)
    assert response.status_code == 200, response.text
    assert _stock(client, cup) == 48


# ---------- (권한) 다른 매장에 등록된 환산값은 적용되지 않는다 ----------


def test_us05_other_store_conversion_qty_is_not_applied(client):
    # US-05 (권한) 다른 매장에 등록된 환산값은 적용되지 않는다
    # 매장 2에는 같은 상품이 박스당 24개로 등록돼 있고, 매장 1에는 환산값이 없다
    other_store_cup = _create_product(client, PAPER_CUP, headers=OTHER_STORE_OWNER)
    cup = _create_product(client, PAPER_CUP_WITHOUT_CONVERSION)
    inspection_id = _inspection_for_order(client, cup, 48)
    _upload(client, inspection_id, "종이컵 12oz 2박스 × 1,200원 = 2,400원\n")
    [line] = _get(client, inspection_id)["lines"]
    assert other_store_cup not in [c["product_id"] for c in line["candidates"]]
    assert line["base_quantity"] is None
    assert line["match_status"] == "확인 필요"
