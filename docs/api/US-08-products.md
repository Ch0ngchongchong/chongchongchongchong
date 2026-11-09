# US-08 상품·단위 정보 API 명세

- 기능 ID: F-01 / 스토리: US-08 상품·단위 정보 등록
- 근거: document 레포 `docs/API.md` 항목 1·1-2, `docs/DATA-MODEL.md` 상품 모델, `docs/requirements/backlog.md` US-08
- 응답 예시는 2026-11-09에 `feat/us08-product-update-and-tests` 브랜치 코드를 테스트 DB에 띄워 실제로 호출한 결과다
- `[제안]` 표시는 document `docs/API.md`에 아직 없는 내용이다. PM이 `API.md`에 옮기면 표시를 지운다

## 한눈에 보기

| 메서드 | URL | 언제 쓰나 | 화면 |
| --- | --- | --- | --- |
| `POST` | `/products` | 사장님이 새 상품을 등록할 때 | 상품 목록·등록 — 저장 버튼 |
| `GET` | `/products` | 내 매장 상품 목록을 볼 때 | 상품 목록·등록 — 목록 표시 |
| `PATCH` | `/products/{product_id}` | 등록한 상품의 환산값·기준 단가 등을 고칠 때 `[제안]` | 상품 목록·등록 — 수정 |

## 공통 규칙

| 항목 | 내용 |
| --- | --- |
| 요청·응답 형식 | JSON (`Content-Type: application/json`) |
| 사용자 확인 | 요청 헤더 `X-User-Id`에 매장 사용자 ID를 넣는다. 서버는 그 사용자의 `store_id`로 매장을 정한다. 로그인 방식이 정해질 때까지의 임시 방식이다 (API.md 공통 규칙 [제안]) |
| 매장 구분 | `store_id`는 요청으로 받지 않는다. 다른 매장 상품은 보이지 않고 고칠 수도 없다 |
| 오류 응답 형식 | `{"error": {"code": "<원인 코드>", "message": "<사람이 읽는 설명>"}}` |

### 상품 필드

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `id` | 정수 | 응답에만 | 상품 ID |
| `store_id` | 정수 | 응답에만 | 상품이 속한 매장 |
| `product_code` | 문자열 | **예** | 상품 코드. 같은 매장 안에서 중복 불가. 빈칸·공백만 있으면 안 됨 |
| `name` | 문자열 \| null | 아니오 | 상품명 |
| `spec` | 문자열 \| null | 아니오 | 규격 (예: `1L`) |
| `base_unit` | 문자열 \| null | 아니오 | 기준 재고 단위 (예: `개`) |
| `pack_unit` | 문자열 \| null | 아니오 | 포장 단위 (예: `박스`) |
| `conversion_qty` | 정수 \| null | 아니오 | 포장 단위 1개당 기준 단위 수. 넣으면 1 이상 |
| `base_unit_price` | 정수 \| null | 아니오 | 기준 단가 (원) |

### 모든 API에 공통인 실패

| 상황 | 상태 코드 | 응답 본문 |
| --- | --- | --- |
| `X-User-Id` 헤더가 없음 | `422` | FastAPI 기본 형식 `{"detail": [...]}` (API.md에 정해진 것 없음) |
| 등록되지 않은 사용자 ID | `401` | `{"detail": "등록되지 않은 사용자입니다"}` (API.md에 정해진 것 없음, 임시) |
| 필드 타입이 틀림 (예: `conversion_qty`에 `"abc"`) | `422` | FastAPI 기본 형식 `{"detail": [...]}` (API.md에 정해진 것 없음) |

---

## 1. 상품 등록 — `POST /products`

사장님이 상품 코드·상품명·규격·단위·환산값·기준 단가를 입력해 저장한다. 저장한 상품은 상품 목록에 추가되고, 이후 판독의 품목 후보 대상이 된다 (US-08 정상).

**요청**

```http
POST /products
X-User-Id: 1
Content-Type: application/json

{
  "product_code": "P-0123",
  "name": "서울우유 1000ml",
  "spec": "1L",
  "base_unit": "개",
  "pack_unit": "박스",
  "conversion_qty": 10,
  "base_unit_price": 2650
}
```

`product_code`만 보내도 저장된다. 나머지 필드는 `null`로 저장된다.

**성공 — `200`**: 저장된 상품 1건

```json
{
  "id": 1,
  "store_id": 1,
  "product_code": "P-0123",
  "name": "서울우유 1000ml",
  "spec": "1L",
  "base_unit": "개",
  "pack_unit": "박스",
  "conversion_qty": 10,
  "base_unit_price": 2650
}
```

**실패** — 저장되지 않는다 (US-08 실패·거절)

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 같은 매장에 같은 `product_code`가 있음 | `400` | `DUPLICATE_PRODUCT_CODE` | 이미 등록된 상품 코드입니다 |
| `product_code`가 없음·`null`·빈칸·공백만 있음 | `400` | `REQUIRED_FIELD_MISSING` | 필수값이 비어 있습니다: product_code |
| `conversion_qty`가 0 이하 | `400` | `INVALID_CONVERSION_QTY` | 환산값은 0보다 커야 합니다 |

`REQUIRED_FIELD_MISSING`의 상태 코드는 API.md에 없어 다른 실패와 같은 `400`으로 맞췄다 `[제안]`.

---

## 2. 상품 목록 조회 — `GET /products`

로그인한 사용자 매장의 상품을 `id` 순서로 돌려준다. 다른 매장 상품은 오류 없이 목록에 나오지 않는다 (US-08 권한).

**요청**

```http
GET /products
X-User-Id: 1
```

**성공 — `200`**: 상품 목록 (상품이 없으면 `[]`)

```json
[
  {
    "id": 1,
    "store_id": 1,
    "product_code": "P-0123",
    "name": "서울우유 1000ml",
    "spec": "1L",
    "base_unit": "개",
    "pack_unit": "박스",
    "conversion_qty": 10,
    "base_unit_price": 2650
  },
  {
    "id": 2,
    "store_id": 1,
    "product_code": "P-0201",
    "name": null,
    "spec": null,
    "base_unit": null,
    "pack_unit": null,
    "conversion_qty": null,
    "base_unit_price": null
  }
]
```

**실패**: 이 API만의 실패는 없다 (공통 실패만).

---

## 3. 상품 수정 — `PATCH /products/{product_id}` `[제안]`

등록한 상품의 값을 고친다. 주로 환산값·기준 단가를 바꿀 때 쓴다 (US-08 인수 조건 #2).

- **보낸 필드만 바뀐다.** 보내지 않은 필드는 그대로다. 빈 본문 `{}`이면 아무것도 바뀌지 않고 지금 값을 돌려준다
- `product_code`를 제외한 필드는 `null`을 보내면 값이 지워진다
- 수정한 값은 **그 뒤에 확정하는 입고 건부터** 쓰인다. 이미 `재고 반영 완료`된 건의 수량·단가가 바뀌지 않게 하려면, 입고 확정(US-04·US-06)을 만들 때 그때 값을 검수 건 쪽에 따로 저장해야 한다 (DATA-MODEL.md 미정 항목)
- 직원도 수정할 수 있는지는 미정이라(backlog US-08) 지금은 역할로 막지 않는다

**요청**

```http
PATCH /products/1
X-User-Id: 1
Content-Type: application/json

{
  "conversion_qty": 12,
  "base_unit_price": 2800
}
```

**성공 — `200`**: 수정된 상품 1건

```json
{
  "id": 1,
  "store_id": 1,
  "product_code": "P-0123",
  "name": "서울우유 1000ml",
  "spec": "1L",
  "base_unit": "개",
  "pack_unit": "박스",
  "conversion_qty": 12,
  "base_unit_price": 2800
}
```

**실패** — 저장되지 않는다

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 상품이 없거나 다른 매장 상품 | `404` | `PRODUCT_NOT_FOUND` `[제안]` | 상품을 찾을 수 없습니다 |
| 바꾸려는 `product_code`가 같은 매장의 다른 상품에 있음 | `400` | `DUPLICATE_PRODUCT_CODE` | 이미 등록된 상품 코드입니다 |
| `product_code`를 `null`·빈칸·공백으로 보냄 | `400` | `REQUIRED_FIELD_MISSING` | 필수값이 비어 있습니다: product_code |
| `conversion_qty`가 0 이하 | `400` | `INVALID_CONVERSION_QTY` | 환산값은 0보다 커야 합니다 |

다른 매장 상품을 고치려 하면 "있지만 권한 없음"이 아니라 "없음"으로 응답한다. 다른 매장에 그 상품이 있다는 것 자체를 알려 주지 않기 위해서다.

---

## 아직 정하지 않은 것

| 항목 | 누가 정하나 |
| --- | --- |
| 이 문서의 `PATCH /products/{product_id}`와 `PRODUCT_NOT_FOUND`를 document `docs/API.md`에 옮길지 | PM |
| document `docs/API.md` 항목 1 ②의 "422로 다르게 구현돼 있음" 메모를 지금 구현(400 `REQUIRED_FIELD_MISSING`)에 맞게 고칠지 | PM |
| `X-User-Id` 없음(422)·없는 사용자(401)·타입 오류(422)의 응답을 공통 오류 형식으로 맞출지 | 팀 |
| 직원도 상품을 등록·수정할 수 있는지 (backlog US-08 미확정) | 팀 |
