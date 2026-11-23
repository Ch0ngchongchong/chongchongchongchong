# US-07 입고 변경 이력 조회 — 인수 조건 중 test_demo_scenario.py가 확인하지 않는 것
# 근거: document 저장소 docs/requirements/backlog.md US-07 인수 조건
#       응답 모양은 docs/api/US-06-07-exceptions-history.md 9절 (PR #24)
#       — {"changes": [{changed_by, changed_at, action, field, old_value, new_value}],
#          "reading_logs": [...]}, 값은 모두 문자열(숫자·목록은 JSON 문자열)
# 사용자: conftest.py 시드 — 1 = 매장 1 사장님, 2 = 매장 1 직원, 3 = 매장 2 사장님
#
# 이 파일에서 다루지 않은 US-07 인수 조건 (팀 질문으로 남김)
#  - 필드별 정확도·직원이 고친 줄 비율·직원이 추가한 줄 비율(행 누락률)·
#    업로드부터 확정까지 걸린 시간 조회: 조회 API 약속(경로·필드)이 없음
#  - 직원도 이력을 볼 수 있는지: backlog US-07 미확정(사장님 열람 범위)

import json

import pytest

OWNER_ID, STAFF_ID = 1, 2
OWNER = {"X-User-Id": str(OWNER_ID)}
STAFF = {"X-User-Id": str(STAFF_ID)}
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

# 발주는 10개인데 8개로 읽힘 (예외 건)
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
def inspection_id(client, product_id):
    """발주 P-0123 × 10의 `업로드 대기` 검수 건"""
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


def _upload(client, inspection_id, text):
    response = client.post(
        f"/inspections/{inspection_id}/document",
        files={"file": ("statement.txt", text.encode(), "text/plain")},
        headers=STAFF,
    )
    assert response.status_code == 200, response.text


def _post(client, inspection_id, action, headers, body=None):
    response = client.post(
        f"/inspections/{inspection_id}/{action}", headers=headers, json=body
    )
    assert response.status_code == 200, response.text
    return response.json()


def _changes(client, inspection_id):
    response = client.get(f"/inspections/{inspection_id}/history", headers=OWNER)
    assert response.status_code == 200, response.text
    return response.json()["changes"]


def _staff_edits_then_owner_approves(client, inspection_id):
    """판독(8개) → 직원이 9개로 고침 → 예외 사유와 함께 확정 → 사장님 승인"""
    _upload(client, inspection_id, SHORT_DELIVERY)
    [line] = client.get(f"/inspections/{inspection_id}", headers=STAFF).json()["lines"]
    response = client.patch(
        f"/inspections/{inspection_id}/lines/{line['id']}",
        json={"quantity": 9},
        headers=STAFF,
    )
    assert response.status_code == 200, response.text
    _post(client, inspection_id, "confirm", STAFF, {"exception_reason": "1개 부족"})
    _post(client, inspection_id, "approve", OWNER)


def _first(rows, action, field):
    return next(
        row for row in rows if row["action"] == action and row["field"] == field
    )


# ---------- (정상) 생길 때마다 변경자·시각·이전 값·새 값이 한 줄씩 ----------


def test_us07_every_row_has_who_when_old_and_new(client, product_id, inspection_id):
    # US-07 (정상) 이력이 생길 때마다 변경자·시각·이전 값·새 값이 한 줄씩 기록된다
    _staff_edits_then_owner_approves(client, inspection_id)
    rows = _changes(client, inspection_id)
    assert rows
    for row in rows:
        assert {"changed_by", "changed_at", "old_value", "new_value"} <= row.keys()
        assert row["changed_by"] is not None
        assert row["changed_at"] is not None


def test_us07_read_original_value_is_recorded(client, product_id, inspection_id):
    # US-07 (정상) 판독 원본값이 기록된다 (OCR이 읽은 8개)
    _staff_edits_then_owner_approves(client, inspection_id)
    original = _first(_changes(client, inspection_id), "판독", "line 1")
    assert original["old_value"] is None
    assert json.loads(original["new_value"])["quantity"] == 8


def test_us07_staff_edit_is_recorded_with_old_and_new(
    client, product_id, inspection_id
):
    # US-07 (정상) 직원 수정값이 변경자(직원)·이전 값(8)·새 값(9)으로 기록된다
    _staff_edits_then_owner_approves(client, inspection_id)
    edit = _first(_changes(client, inspection_id), "줄 수정", "line 1 quantity")
    assert edit["changed_by"] == STAFF_ID
    assert edit["old_value"] == "8"
    assert edit["new_value"] == "9"


def test_us07_confirm_approval_and_stock_are_recorded(
    client, product_id, inspection_id
):
    # US-07 (정상) 검수 결과(직원 확정), 사장 승인, 최종 재고 반영 수량이 기록된다
    _staff_edits_then_owner_approves(client, inspection_id)
    rows = _changes(client, inspection_id)
    confirm = _first(rows, "확정", "status")
    assert confirm["changed_by"] == STAFF_ID
    assert confirm["new_value"] == "사장 승인 대기"
    approve = _first(rows, "승인", "status")
    assert approve["changed_by"] == OWNER_ID
    stock = _first(rows, "재고 반영", "inventory P-0123")
    assert (stock["old_value"], stock["new_value"]) == ("0", "9")


def test_us07_reject_reason_is_recorded(client, product_id, inspection_id):
    # US-07 (정상) 사장 반려(사유 포함)가 기록된다
    _upload(client, inspection_id, SHORT_DELIVERY)
    _post(client, inspection_id, "confirm", STAFF, {"exception_reason": "2개 부족"})
    _post(client, inspection_id, "reject", OWNER, {"reject_reason": "공급처에 확인"})
    reject = _first(_changes(client, inspection_id), "반려", "reject_reason")
    assert reject["changed_by"] == OWNER_ID
    assert reject["new_value"] == "공급처에 확인"


# ---------- (정상) 입고 검수 건별 시간순 ----------


def test_us07_history_is_in_time_order(client, product_id, inspection_id):
    # US-07 (정상) 사장님은 입고 검수 건별로 변경 이력을 시간순으로 볼 수 있다
    _staff_edits_then_owner_approves(client, inspection_id)
    rows = _changes(client, inspection_id)
    times = [row["changed_at"] for row in rows]
    assert times == sorted(times)
    actions = [row["action"] for row in rows]
    order = [actions.index(a) for a in ("판독", "줄 수정", "확정", "승인")]
    assert order == sorted(order)


# ---------- (실패·거절) 기록된 이력은 누구도 수정·삭제할 수 없다 ----------


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_us07_history_cannot_be_changed_through_api(
    client, product_id, inspection_id, method
):
    # US-07 (실패·거절) 기록된 이력은 누구도 수정하거나 삭제할 수 없다 (API로)
    _staff_edits_then_owner_approves(client, inspection_id)
    before = _changes(client, inspection_id)
    row_id = before[0]["id"]
    for url in (
        f"/inspections/{inspection_id}/history",
        f"/inspections/{inspection_id}/history/{row_id}",
    ):
        for headers in (OWNER, STAFF):
            kwargs = {} if method == "delete" else {"json": {"new_value": "x"}}
            response = getattr(client, method)(url, headers=headers, **kwargs)
            assert response.status_code >= 400
    assert _changes(client, inspection_id) == before


def test_us07_history_cannot_be_changed_in_database(client, product_id, inspection_id):
    # US-07 (실패·거절) 기록된 이력은 누구도 수정하거나 삭제할 수 없다.
    # API를 거치지 않고 서버 코드(DB 세션)로 고치거나 지우려 해도 이력이 그대로여야 한다
    # (팀 API 문서 9절: "서버 코드에서 고치거나 지우려 해도 오류가 난다")
    from app.db import SessionLocal
    from app.models.history import ChangeLog

    _staff_edits_then_owner_approves(client, inspection_id)
    before = _changes(client, inspection_id)
    row_id = next(row["id"] for row in before if row["id"] > 0)

    with SessionLocal() as db:
        row = db.get(ChangeLog, row_id)
        try:
            row.new_value = "999"
            db.commit()
        except Exception:
            db.rollback()
    with SessionLocal() as db:
        row = db.get(ChangeLog, row_id)
        try:
            db.delete(row)
            db.commit()
        except Exception:
            db.rollback()

    assert _changes(client, inspection_id) == before


# ---------- (권한) 다른 매장 사용자 ----------


def test_us07_other_store_cannot_view_reading_logs(client, product_id, inspection_id):
    # US-07 (권한) 다른 매장 사용자는 이 매장의 변경 이력(판독 비용·처리 시간 포함)을
    # 볼 수 없다 (변경 이력 자체는 test_demo_scenario에서 확인)
    _upload(client, inspection_id, SHORT_DELIVERY)
    response = client.get(
        f"/inspections/{inspection_id}/reading-logs", headers=OTHER_STORE_OWNER
    )
    assert response.status_code == 404
