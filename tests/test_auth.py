# 로그인(JWT) — 2026-11-24 추가. 기존 X-User-Id 헤더 방식은 그대로 둔다
# (API.md 공통 규칙은 여전히 "로그인 방식 미정"이고, 이건 그 위에 추가한
# 선택적 경로다. 사용자 확인: X-User-Id는 유지, JWT는 추가만).
# 사용자: conftest.py 시드 — 1 = 매장 1 사장님, 2 = 매장 1 직원, 3 = 매장 2 사장님

import pytest

OWNER = {"X-User-Id": "1"}


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-do-not-use-in-prod-32bytes+")


def _register(client, store_user_id, password="pw1234"):
    return client.post(
        "/auth/register-password",
        json={"store_user_id": store_user_id, "password": password},
    )


def _login(client, store_user_id, password="pw1234"):
    return client.post(
        "/auth/login",
        json={"store_user_id": store_user_id, "password": password},
    )


def test_register_then_login_returns_token(client):
    assert _register(client, 1).status_code == 200
    response = _login(client, 1)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_cannot_register_password_twice(client):
    _register(client, 1)
    response = _register(client, 1, password="other")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PASSWORD_ALREADY_SET"


def test_login_without_password_set_is_rejected(client):
    response = _login(client, 1)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_with_wrong_password_is_rejected(client):
    _register(client, 1)
    response = _login(client, 1, password="wrong")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_bearer_token_authenticates_like_x_user_id(client):
    _register(client, 2)
    token = _login(client, 2).json()["access_token"]
    response = client.get(
        "/products", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    # 직원(2)이 상품을 수정하려 하면 X-User-Id로 할 때와 똑같이 거절된다
    response = client.post(
        "/products",
        json={"product_code": "P-9999"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200  # 등록은 역할 제한이 없다 (기존 동작)


def test_invalid_bearer_token_is_rejected(client):
    response = client.get(
        "/products", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401


def test_x_user_id_still_works_without_authorization_header(client):
    # 기존 방식은 그대로 둔다 — JWT를 전혀 안 써도 동작해야 한다
    assert client.get("/products", headers=OWNER).status_code == 200


def test_bearer_token_takes_priority_over_x_user_id(client):
    # 둘 다 보내면 Authorization을 따른다 (사용자 2로 로그인했으면 2로 처리)
    _register(client, 2)
    token = _login(client, 2).json()["access_token"]
    response = client.patch(
        "/products/1",
        json={"name": "다른 이름"},
        headers={"Authorization": f"Bearer {token}", "X-User-Id": "1"},
    )
    # 상품이 없어 404거나 매장이 달라 생기는 오류가 아니라, 직원(2)이라
    # 수정 자체가 막혀야 한다 — X-User-Id(1, 사장님)를 따랐다면 통과했을 것
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN_ROLE"
