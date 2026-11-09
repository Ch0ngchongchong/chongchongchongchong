# US-01 발주 작성·승인·전달 API 명세

- 기능 ID: F-02 / 스토리: US-01 발주 작성·승인·전달
- 근거: document 레포 `docs/requirements/backlog.md` US-01, `docs/DATA-MODEL.md` 발주 건·입고 검수 건, `docs/domain/03-rules-states-llm.md` 3-2·R3·R7
- 응답 예시는 2026-11-09에 `feat/us01-purchase-orders` 브랜치 코드를 테스트 DB에 띄워 실제로 호출한 결과다
- **이 문서의 URL·오류 코드·상태 코드는 모두 `[제안]`이다.** document `docs/API.md`에 아직 US-01 항목이 없다. PM이 `API.md`에 옮기면 표시를 지운다
- 발주 취소(US-02)는 이 문서에 없다. 따로 정리한다

## 한눈에 보기

| 메서드 | URL | 언제 쓰나 | 바뀌는 상태 | 누가 |
| --- | --- | --- | --- | --- |
| `POST` | `/purchase-orders` | 상품·수량을 골라 발주를 저장할 때 | (새로 만듦) → `발주 초안` | 누구나 (역할 제한 미정) |
| `GET` | `/purchase-orders` | 내 매장 발주 목록을 볼 때 | 없음 | 누구나 |
| `GET` | `/purchase-orders/{order_id}` | 발주 1건을 자세히 볼 때 | 없음 | 누구나 |
| `POST` | `/purchase-orders/{order_id}/approve` | 사장님이 발주 초안을 승인할 때 | `발주 초안` → `발주 확인 완료` | 사장님만 |
| `POST` | `/purchase-orders/{order_id}/mark-delivered` | 사장님이 공급처에 전달했다고 표시할 때 | `발주 확인 완료` → `공급처 전달 완료` → `입고 대기` (+ 입고 검수 건 생성) | 사장님만 |

**상태 흐름**

```
(저장) → 발주 초안 ──approve──▶ 발주 확인 완료 ──mark-delivered──▶ 입고 대기
                                                                   └ 입고 검수 건 1건 `업로드 대기`로 생성
```

- 어느 API도 재고 수량을 바꾸지 않는다 (US-01, R3)
- 상태값은 문서의 한국어 이름을 그대로 쓴다 (`발주 초안`, `발주 확인 완료`, `공급처 전달 완료`, `입고 대기`, `입고 완료`, `발주 취소`)

## 공통 규칙

| 항목 | 내용 |
| --- | --- |
| 요청·응답 형식 | JSON (`Content-Type: application/json`) |
| 사용자 확인 | 요청 헤더 `X-User-Id`에 매장 사용자 ID를 넣는다. 서버는 그 사용자의 `store_id`·`role`(사장님 / 직원)을 쓴다. 로그인 방식이 정해질 때까지의 임시 방식이다 (API.md 공통 규칙 [제안]) |
| 매장 구분 | `store_id`는 요청으로 받지 않는다. 다른 매장 발주는 목록에 나오지 않고, 1건 조회·승인·전달 완료에서는 "없음"(`404`)으로 응답한다 |
| 오류 응답 형식 | `{"error": {"code": "<원인 코드>", "message": "<사람이 읽는 설명>"}}` |

### 발주 건 필드 (응답)

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `id` | 정수 | 발주 건 ID |
| `store_id` | 정수 | 발주한 매장 |
| `supplier` | 문자열 \| null | 공급처. 필수 여부 미정이라 비워도 저장된다 |
| `status` | 문자열 | 발주 건 상태 (위 상태값 중 하나) |
| `lines` | 목록 | 발주 줄. 줄마다 `product_id`(정수), `quantity`(정수, 1 이상) |

### 모든 API에 공통인 실패

| 상황 | 상태 코드 | 응답 본문 |
| --- | --- | --- |
| `X-User-Id` 헤더가 없음 | `422` | FastAPI 기본 형식 `{"detail": [...]}` (API.md에 정해진 것 없음) |
| 등록되지 않은 사용자 ID | `401` | `{"detail": "등록되지 않은 사용자입니다"}` (API.md에 정해진 것 없음, 임시) |
| 필드 타입이 틀림 (예: `quantity`에 `"abc"`) | `422` | FastAPI 기본 형식 `{"detail": [...]}` |

---

## 1. 발주 저장 — `POST /purchase-orders`

사장님이 필요한 상품과 수량을 골라 발주를 저장한다. 저장하면 `발주 초안` 상태가 된다 (US-01 정상).

**요청 본문**

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `supplier` | 문자열 \| null | 아니오 | 공급처 이름 |
| `lines` | 목록 | **예** | 발주 줄 1개 이상 |
| `lines[].product_id` | 정수 | 예 | 이 매장에 등록된 상품 ID (`GET /products`의 `id`) |
| `lines[].quantity` | 정수 | 예 | 1 이상 |

```http
POST /purchase-orders
X-User-Id: 1
Content-Type: application/json

{
  "supplier": "(가상) 유제품 공급처 A",
  "lines": [
    { "product_id": 1, "quantity": 10 },
    { "product_id": 2, "quantity": 2 }
  ]
}
```

**성공 — `200`**: 저장된 발주 건

```json
{
  "id": 1,
  "store_id": 1,
  "supplier": "(가상) 유제품 공급처 A",
  "status": "발주 초안",
  "lines": [
    { "product_id": 1, "quantity": 10 },
    { "product_id": 2, "quantity": 2 }
  ]
}
```

**실패** — 저장되지 않는다 (US-01 실패·거절)

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 수량이 0 이하인 줄이 있음 | `400` | `INVALID_QUANTITY` | 수량은 1 이상이어야 합니다 |
| 등록되지 않은 상품이 있음 (없는 ID, 다른 매장 상품 포함) | `400` | `UNREGISTERED_PRODUCT` | 등록되지 않은 상품이 있습니다 |
| `lines`가 빈 목록 `[]` | `400` | `REQUIRED_FIELD_MISSING` | 필수값이 비어 있습니다: lines |
| `lines` 필드 자체가 없음 | `422` | — | FastAPI 기본 형식 `{"detail": [...]}` (빈 목록과 형식이 다름, 아래 '아직 정하지 않은 것') |

---

## 2. 발주 목록 조회 — `GET /purchase-orders`

로그인한 사용자 매장의 발주를 `id` 순서로 모두 돌려준다. 다른 매장 발주는 오류 없이 목록에 나오지 않는다 (US-01 권한).

```http
GET /purchase-orders
X-User-Id: 1
```

**성공 — `200`**: 발주 건 목록 (없으면 `[]`)

```json
[
  {
    "id": 1,
    "store_id": 1,
    "supplier": "(가상) 유제품 공급처 A",
    "status": "발주 초안",
    "lines": [
      { "product_id": 1, "quantity": 10 },
      { "product_id": 2, "quantity": 2 }
    ]
  },
  {
    "id": 2,
    "store_id": 1,
    "supplier": null,
    "status": "발주 초안",
    "lines": [{ "product_id": 1, "quantity": 1 }]
  }
]
```

**실패**: 이 API만의 실패는 없다 (공통 실패만).

---

## 3. 발주 1건 조회 — `GET /purchase-orders/{order_id}`

발주 1건의 상태와 줄을 볼 때 쓴다.

```http
GET /purchase-orders/1
X-User-Id: 1
```

**성공 — `200`**: 발주 건 1건 (1번 응답과 같은 모양)

**실패**

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 발주가 없거나 다른 매장 발주 | `404` | `PURCHASE_ORDER_NOT_FOUND` | 발주를 찾을 수 없습니다 |

---

## 4. 발주 승인 — `POST /purchase-orders/{order_id}/approve`

사장님이 `발주 초안`을 확인하고 승인한다. `발주 확인 완료`가 된다 (US-01 정상). 요청 본문은 없다.

- **R7 수량 한도 경고는 아직 없다.** 한도 값이 정해지지 않아(다음 고객 미팅에서 확인) 한도를 넘어도 그대로 승인된다

```http
POST /purchase-orders/1/approve
X-User-Id: 1
```

**성공 — `200`**: 바뀐 발주 건

```json
{
  "id": 1,
  "store_id": 1,
  "supplier": "(가상) 유제품 공급처 A",
  "status": "발주 확인 완료",
  "lines": [
    { "product_id": 1, "quantity": 10 },
    { "product_id": 2, "quantity": 2 }
  ]
}
```

**실패** — 상태는 그대로다

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 직원이 요청함 | `403` | `FORBIDDEN_ROLE` | 사장님만 할 수 있습니다 |
| 발주가 없거나 다른 매장 발주 | `404` | `PURCHASE_ORDER_NOT_FOUND` | 발주를 찾을 수 없습니다 |
| `발주 초안`이 아님 (예: 이미 승인함) | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(발주 확인 완료)에서는 할 수 없습니다 |

역할 검사를 먼저 하므로, 직원이 보내면 발주가 있든 없든 `403`이다.

---

## 5. 공급처 전달 완료 표시 — `POST /purchase-orders/{order_id}/mark-delivered`

사장님이 공급처에 발주를 전달했다고 표시한다. MVP에서는 공급처에 자동으로 보내지 않고 사장님이 직접 표시한다 (mvp-scope.md). 요청 본문은 없다.

- `공급처 전달 완료` 다음은 시스템이 바로 `입고 대기`로 넘기므로(DATA-MODEL.md), **한 요청에서 `입고 대기`까지 간다.** 응답의 `status`는 `입고 대기`다
- 이때 이 발주에 연결된 **입고 검수 건이 `업로드 대기` 상태로 1건 만들어진다** (US-01 정상, 03 3-2). 첫 데모 흐름의 시작점이다. 입고 검수 건 조회 API는 아직 없다

```http
POST /purchase-orders/1/mark-delivered
X-User-Id: 1
```

**성공 — `200`**: 바뀐 발주 건

```json
{
  "id": 1,
  "store_id": 1,
  "supplier": "(가상) 유제품 공급처 A",
  "status": "입고 대기",
  "lines": [
    { "product_id": 1, "quantity": 10 },
    { "product_id": 2, "quantity": 2 }
  ]
}
```

**실패** — 상태는 그대로이고 입고 검수 건도 만들어지지 않는다

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 직원이 요청함 | `403` | `FORBIDDEN_ROLE` | 사장님만 할 수 있습니다 |
| 발주가 없거나 다른 매장 발주 | `404` | `PURCHASE_ORDER_NOT_FOUND` | 발주를 찾을 수 없습니다 |
| `발주 확인 완료`가 아님 (예: 승인 전, 이미 전달 완료) | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(발주 초안)에서는 할 수 없습니다 |

---

## 아직 정하지 않은 것

| 항목 | 누가 정하나 |
| --- | --- |
| 이 문서의 URL·오류 코드·상태 코드를 document `docs/API.md`에 옮길지 | PM |
| R7 수량 한도 값과 경고 방식 (승인 전 경고 → 다시 확인) | 다음 고객 미팅에서 확인 |
| 직원도 발주를 저장할 수 있는지 (인수 조건에는 승인·전달 완료 제한만 있음) | 팀 |
| `supplier`가 필수인지 | 팀 |
| 발주 줄에 단위(개·박스)를 둘지 — 화면 시안에는 있으나 DATA-MODEL.md에는 없음 | 팀 |
| 발주 번호(예: `PO-0012`)·작성일을 둘지 — DESIGN.md에는 있으나 DATA-MODEL.md에는 없음 | 팀 |
| `lines`가 아예 없을 때(`422` 기본 형식)와 빈 목록일 때(`400` 공통 형식)의 응답을 하나로 맞출지 | 팀 |
| `X-User-Id` 없음(422)·없는 사용자(401)·타입 오류(422)의 응답을 공통 오류 형식으로 맞출지 | 팀 |
