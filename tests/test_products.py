import pytest

from tests.conftest import OWNER_ID_BY_STORE


class ProductApi:
    """테스트 문장(store, product)을 API.md 항목 1·1-2 호출로 바꿔 주는 도우미.
    store 번호는 그 매장 사장님의 X-User-Id로 보낸다 (API.md 공통 규칙)."""

    def __init__(self, client):
        self.client = client

    def _headers(self, store):
        return {"X-User-Id": str(OWNER_ID_BY_STORE[store])}

    def create(self, store, product):
        response = self.client.post(
            "/products", json=product, headers=self._headers(store)
        )
        assert response.status_code == 200, response.text
        return response.json()

    def create_rejected(self, store, product):
        response = self.client.post(
            "/products", json=product, headers=self._headers(store)
        )
        assert response.status_code >= 400, response.text
        return response

    def update(self, store, product_id, changes):
        response = self.client.patch(
            f"/products/{product_id}", json=changes, headers=self._headers(store)
        )
        assert response.status_code == 200, response.text
        return response.json()

    def update_rejected(self, store, product_id, changes):
        response = self.client.patch(
            f"/products/{product_id}", json=changes, headers=self._headers(store)
        )
        assert response.status_code >= 400, response.text
        return response

    def list_products(self, store):
        response = self.client.get("/products", headers=self._headers(store))
        assert response.status_code == 200, response.text
        # 서버가 붙이는 id·store_id를 빼고, 입력한 상품 필드만 비교한다
        return [
            {k: v for k, v in item.items() if k not in ("id", "store_id")}
            for item in response.json()
        ]


@pytest.fixture
def product_api(client):
    return ProductApi(client)


@pytest.fixture
def product():
    return {
        "product_code": "P-0123",
        "name": "서울우유 1000ml",
        "spec": "1L",
        "base_unit": "개",
        "pack_unit": "박스",
        "conversion_qty": 10,
        "base_unit_price": 2650,
        "price_alert_threshold_percent": None,
    }


def test_us08_created_product_appears_in_list(product_api, product):
    product_api.create(store=1, product=product)
    assert product in product_api.list_products(store=1)


def test_us08_duplicate_code_in_same_store_is_rejected(product_api, product):
    product_api.create(store=1, product=product)
    before = product_api.list_products(store=1)
    product_api.create_rejected(store=1, product=product)
    assert product_api.list_products(store=1) == before


@pytest.mark.parametrize("quantity", [0, -1])
def test_us08_nonpositive_conversion_qty_is_rejected(product_api, product, quantity):
    product["conversion_qty"] = quantity
    before = product_api.list_products(store=1)
    product_api.create_rejected(store=1, product=product)
    assert product_api.list_products(store=1) == before


# R8 경고 기준(price_alert_threshold_percent)은 음수면 저장되지 않는다
# (2026-11-16 멘토 데모 피드백 팀 결정: 사장님이 상품마다 직접 설정)
def test_us08_negative_price_alert_threshold_is_rejected(product_api, product):
    product["price_alert_threshold_percent"] = -1
    before = product_api.list_products(store=1)
    response = product_api.create_rejected(store=1, product=product)
    assert response.json()["error"]["code"] == "INVALID_PRICE_ALERT_THRESHOLD"
    assert product_api.list_products(store=1) == before


def test_us08_update_to_negative_price_alert_threshold_is_rejected(
    product_api, product
):
    created = product_api.create(store=1, product=product)
    response = product_api.update_rejected(
        store=1,
        product_id=created["id"],
        changes={"price_alert_threshold_percent": -5},
    )
    assert response.json()["error"]["code"] == "INVALID_PRICE_ALERT_THRESHOLD"
    assert product_api.list_products(store=1) == [product]


def test_us08_other_store_cannot_view_product(product_api, product):
    product_api.create(store=1, product=product)
    assert product not in product_api.list_products(store=2)


# 필수값은 product_code만 (DATA-MODEL.md 2026-11-03 확정)
# 빠졌거나 빈칸이면 저장되지 않는다
@pytest.mark.parametrize("empty_code", [None, "", "   "])
def test_us08_missing_required_value_is_rejected(product_api, product, empty_code):
    if empty_code is None:
        del product["product_code"]
    else:
        product["product_code"] = empty_code
    before = product_api.list_products(store=1)
    response = product_api.create_rejected(store=1, product=product)
    # API.md 항목 1 실패 응답 ②
    assert response.json()["error"]["code"] == "REQUIRED_FIELD_MISSING"
    assert product_api.list_products(store=1) == before


class ReceivingApi:
    """발주 → 명세서 업로드 → 확정을 매장 1 사용자로 진행하는 도우미.
    사용자: conftest.py 시드 — 1 = 매장 1 사장님, 2 = 매장 1 직원."""

    OWNER = {"X-User-Id": "1"}
    STAFF = {"X-User-Id": "2"}

    def __init__(self, client):
        self.client = client

    def inspection_for_order(self, product_id, quantity):
        """발주(상품 × 기준 단위 수량)를 `입고 대기`까지 보내고
        만들어진 `업로드 대기` 검수 건 ID를 돌려준다."""
        order = self.client.post(
            "/purchase-orders",
            json={
                "supplier": "(가상) 유제품 공급처 A",
                "lines": [{"product_id": product_id, "quantity": quantity}],
            },
            headers=self.OWNER,
        ).json()
        for step in ("approve", "mark-delivered"):
            response = self.client.post(
                f"/purchase-orders/{order['id']}/{step}", headers=self.OWNER
            )
            assert response.is_success, response.text
        [inspection] = self.client.get(
            "/inspections", params={"status": "업로드 대기"}, headers=self.STAFF
        ).json()
        return inspection["id"]

    def upload(self, inspection_id, text):
        response = self.client.post(
            f"/inspections/{inspection_id}/document",
            files={"file": ("statement.txt", text.encode(), "text/plain")},
            headers=self.STAFF,
        )
        assert response.status_code == 200, response.text

    def get(self, inspection_id):
        response = self.client.get(f"/inspections/{inspection_id}", headers=self.STAFF)
        assert response.status_code == 200, response.text
        return response.json()

    def confirm(self, inspection_id):
        response = self.client.post(
            f"/inspections/{inspection_id}/confirm", headers=self.STAFF
        )
        assert response.status_code == 200, response.text
        return response.json()["status"]

    def stock(self, product_id):
        rows = self.client.get("/inventory", headers=self.OWNER).json()
        return next(
            (row["quantity"] for row in rows if row["product_id"] == product_id), 0
        )


@pytest.fixture
def receiving(client, monkeypatch):
    # 테스트에서는 명세서를 글자 파일로 올린다 (test_us05_conversion.py와 같은 설정)
    monkeypatch.setenv("ALLOW_TEXT_UPLOAD", "1")
    return ReceivingApi(client)


# US-08 (정상) 저장하면 … 이후 판독의 품목 후보 대상이 된다
def test_us08_saved_product_becomes_reading_candidate(product_api, product, receiving):
    created = product_api.create(store=1, product=product)
    inspection_id = receiving.inspection_for_order(created["id"], 20)
    receiving.upload(inspection_id, "서울우유 1000ml 2박스 × 26,500원 = 53,000원\n")
    [line] = receiving.get(inspection_id)["lines"]
    assert created["id"] in [c["product_id"] for c in line["candidates"]]


# US-08 (정상) 환산값을 수정하면 그 뒤에 확정하는 건부터 새 값이 적용되고,
# 이미 `재고 반영 완료`된 건의 수량은 바뀌지 않는다
def test_us08_conversion_change_applies_only_to_later_confirmations(
    product_api, product, receiving
):
    created = product_api.create(store=1, product=product)  # 박스당 10개
    first = receiving.inspection_for_order(created["id"], 20)
    receiving.upload(first, "서울우유 1000ml 2박스 × 26,500원 = 53,000원\n")
    assert receiving.confirm(first) == "재고 반영 완료"
    assert receiving.stock(created["id"]) == 20

    product_api.update(
        store=1, product_id=created["id"], changes={"conversion_qty": 12}
    )

    # 이미 반영된 건: 수량·재고 그대로
    [done_line] = receiving.get(first)["lines"]
    assert done_line["base_quantity"] == 20
    assert receiving.stock(created["id"]) == 20

    # 수정 뒤 확정하는 건: 2박스 × 12개 = 24개 (기준 단위 1개당 2,650원은 그대로)
    second = receiving.inspection_for_order(created["id"], 24)
    receiving.upload(second, "서울우유 1000ml 2박스 × 31,800원 = 63,600원\n")
    [line] = receiving.get(second)["lines"]
    assert line["base_quantity"] == 24
    assert receiving.confirm(second) == "재고 반영 완료"
    assert receiving.stock(created["id"]) == 20 + 24


# US-08 (정상) 기준 단가를 수정하면 그 뒤에 확정하는 건부터 새 값이 적용되고,
# 이미 `재고 반영 완료`된 건의 단가는 바뀌지 않는다
def test_us08_price_change_applies_only_to_later_confirmations(
    product_api, product, receiving
):
    created = product_api.create(store=1, product=product)  # 기준 단가 2,650원
    first = receiving.inspection_for_order(created["id"], 20)
    receiving.upload(first, "서울우유 1000ml 2박스 × 26,500원 = 53,000원\n")
    assert receiving.confirm(first) == "재고 반영 완료"

    product_api.update(
        store=1, product_id=created["id"], changes={"base_unit_price": 2800}
    )

    # 이미 반영된 건: 단가 그대로
    [done_line] = receiving.get(first)["lines"]
    assert done_line["applied_unit_price"] == 2650

    # 수정 뒤 확정하는 건: 새 기준 단가(1개당 2,800원)와 같으면 일반 건으로 반영된다
    second = receiving.inspection_for_order(created["id"], 20)
    receiving.upload(second, "서울우유 1000ml 2박스 × 28,000원 = 56,000원\n")
    assert receiving.confirm(second) == "재고 반영 완료"
    assert receiving.stock(created["id"]) == 20 + 20


# US-08 인수 조건 #2 — 환산값·기준 단가 수정 (상품 쪽 저장).
# '이후 확정 건부터 적용·재고 반영 완료 건은 그대로'는 위 두 테스트에서 확인한다.
def test_us08_updated_conversion_qty_and_price_are_saved(product_api, product):
    created = product_api.create(store=1, product=product)
    product_api.update(
        store=1,
        product_id=created["id"],
        changes={"conversion_qty": 12, "base_unit_price": 2800},
    )
    expected = {**product, "conversion_qty": 12, "base_unit_price": 2800}
    assert product_api.list_products(store=1) == [expected]


@pytest.mark.parametrize("quantity", [0, -1])
def test_us08_update_with_nonpositive_conversion_qty_is_rejected(
    product_api, product, quantity
):
    created = product_api.create(store=1, product=product)
    product_api.update_rejected(
        store=1, product_id=created["id"], changes={"conversion_qty": quantity}
    )
    assert product_api.list_products(store=1) == [product]


def test_us08_update_to_duplicate_code_is_rejected(product_api, product):
    product_api.create(store=1, product=product)
    other = product_api.create(store=1, product={**product, "product_code": "P-0201"})
    before = product_api.list_products(store=1)
    product_api.update_rejected(
        store=1, product_id=other["id"], changes={"product_code": "P-0123"}
    )
    assert product_api.list_products(store=1) == before


def test_us08_update_cannot_empty_required_value(product_api, product):
    created = product_api.create(store=1, product=product)
    product_api.update_rejected(
        store=1, product_id=created["id"], changes={"product_code": ""}
    )
    assert product_api.list_products(store=1) == [product]


def test_us08_other_store_cannot_update_product(product_api, product):
    created = product_api.create(store=1, product=product)
    product_api.update_rejected(
        store=2, product_id=created["id"], changes={"base_unit_price": 1}
    )
    assert product_api.list_products(store=1) == [product]


# 2026-11-16 멘토 데모 피드백 팀 답변("상품 등은 사장님만") 반영.
# backlog US-08 '미확정'에는 아직 안 옮겨졌다.
def test_us08_staff_cannot_update_product(product_api, product):
    created = product_api.create(store=1, product=product)
    response = product_api.client.patch(
        f"/products/{created['id']}",
        json={"base_unit_price": 1},
        headers={"X-User-Id": "2"},  # store 1 직원 (conftest SEED_USERS)
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN_ROLE"
    assert product_api.list_products(store=1) == [product]
