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


@pytest.mark.skip(reason="입고 확정 및 판독 기능과 API 계약이 아직 없음")
def test_us08_changes_apply_to_future_confirmations_and_product_is_candidate():
    pass


# US-08 인수 조건 #2 — 환산값·기준 단가 수정 (상품 쪽 저장까지만).
# '이후 확정 건부터 적용·재고 반영 완료 건은 그대로'는
# 입고 확정 기능이 생긴 뒤 위 skip 테스트에서 확인한다.
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
