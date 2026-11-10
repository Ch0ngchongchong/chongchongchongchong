# US-03·US-04 명세서 판독·입고 확정 API 명세 (첫 데모 시나리오)

- 기능: 첫 데모 시나리오(3주차 초안) 1~5단계 / 스토리: US-03 명세서 업로드·판독, US-04 직원 확인·확정·재고 반영
- 근거: 첫 데모 시나리오 초안, document 레포 `docs/requirements/backlog.md` US-03·US-04, `docs/DATA-MODEL.md` 입고 검수 건·시드 #1·#2·#4·#5, `docs/domain/03-rules-states-llm.md` 3-2·R3
- 응답 예시는 2026-11-10에 `feat/demo-receiving-flow` 브랜치 코드(아직 커밋 전)를 테스트 DB에 띄우고 `scripts/seed_demo.py` 시드로 실제로 호출한 결과다
- **이 문서의 URL·오류 코드·상태 코드는 모두 `[제안]`이다.** document `docs/API.md`에 아직 US-03·US-04 항목이 없다. PM이 `API.md`에 옮기면 표시를 지운다
- 사장 승인·반려(US-06)는 이 문서에 없다. 확정 결과로 `사장 승인 대기`에 들어가는 것까지만 있다

## 한눈에 보기

| 데모 | 메서드 | URL | 언제 쓰나 | 바뀌는 상태 | 누가 |
| --- | --- | --- | --- | --- | --- |
| 1 | `GET` | `/inspections` | 내 매장 검수 건 목록 (업로드할 건 찾기) | 없음 | 누구나 |
| 2·3 | `GET` | `/inspections/{inspection_id}` | 검수 건 1건, 판독 초안·대조 결과 보기. `판독 중`인 동안 화면이 폴링 | 없음 | 누구나 |
| 2 | `POST` | `/inspections/{inspection_id}/document` | 명세서 사진·PDF를 올릴 때 | `업로드 대기` → `판독 중` → (서버가 따로) `직원 확인 대기` 또는 `업로드 대기` | 누구나 (역할 제한 미정) |
| 4 | `PATCH` | `/inspections/{inspection_id}/lines/{line_id}` | 품목 후보를 고르거나 수량을 고칠 때 | 없음 | 누구나 (역할 제한 미정) |
| 4·5 | `POST` | `/inspections/{inspection_id}/confirm` | 직원이 [확정]을 누를 때 | `직원 확인 대기` → `재고 반영 완료` 또는 `사장 승인 대기` | 누구나 (역할 제한 미정) |
| 3·5 | `GET` | `/inventory` | 상품별 현재 재고 보기 | 없음 | 누구나 |

**상태 흐름 (입고 검수 건)**

```
업로드 대기 ──document──▶ 판독 중 ──(판독 성공)──▶ 직원 확인 대기 ──confirm──┬─▶ 재고 반영 완료  (모두 일치: 재고 반영, 발주 → 입고 완료)
     ▲                         │                                        └─▶ 사장 승인 대기  (다른 줄 있음: 재고 그대로, US-06)
     └──────(판독 실패)─────────┘
```

- **재고는 `confirm`에서 모두 일치할 때만 바뀐다.** 다른 API는 재고를 바꾸지 않는다 (R3)
- 상태값은 문서의 한국어 이름을 그대로 쓴다 (`업로드 대기`, `판독 중`, `직원 확인 대기`, `사장 승인 대기`, `재고 반영 완료`)
- 검수 건은 발주를 `mark-delivered`할 때 `업로드 대기`로 1건 만들어진다 (US-01 명세 5번). 검수 건을 직접 만드는 API는 없다

## 공통 규칙

US-01 명세와 같다.

| 항목 | 내용 |
| --- | --- |
| 요청·응답 형식 | JSON. 단, 명세서 업로드만 `multipart/form-data` |
| 사용자 확인 | 요청 헤더 `X-User-Id`에 매장 사용자 ID. 서버가 그 사용자의 `store_id`·`role`을 쓴다 (API.md 공통 규칙 [제안], 임시) |
| 매장 구분 | 검수 건은 연결된 발주의 매장으로 구분한다. 다른 매장 검수 건은 목록에 나오지 않고, 1건 조회·업로드·수정·확정에서는 "없음"(`404`)으로 응답한다 |
| 오류 응답 형식 | `{"error": {"code": "<원인 코드>", "message": "<사람이 읽는 설명>"}}` |
| 공통 실패 | `X-User-Id` 없음 `422`, 없는 사용자 `401`, 필드 타입 오류 `422` (US-01 명세 '모든 API에 공통인 실패'와 같음) |

### 판독은 이렇게 돈다

```
원본 파일 ─OCR─▶ 텍스트 ─가리기─▶ 가린 텍스트 ─LLM(서식 정리·품목 후보)─▶ 판독 초안 줄
```

- **LLM은 글자를 읽지 않는다.** 글자는 OCR이 읽고, LLM은 줄을 표로 나누고 품목 후보(최대 3개, 이유 포함)를 붙이는 일만 한다
- **LLM에는 가린 텍스트와 상품 기준 정보(ID·코드·이름·규격)만 넘긴다.** 원본 사진·PDF는 넘기지 않는다. 담당자·연락처·사업자·주소·계좌 같은 낱말이 있는 줄은 통째로 빼고, 전화번호·사업자등록번호·이메일 모양은 `[가림]`으로 바꾼다. 지금은 서버에서 임시로 가린다 (기기 안에서 가리는 방식은 이후에 정함, STACK.md)
- **지금 OCR·LLM은 임시 구현이다.** 둘 다 아직 정하지 않아 환경변수로 바꿔 끼울 수 있게만 해 두었다

  | 환경변수 | 지금 값 | 하는 일 |
  | --- | --- | --- |
  | `OCR_ENGINE` | `demo` (기본) | `text/plain` 파일은 그 내용을 그대로 쓴다. **사진·PDF는 실제로 읽지 않고, 시드 값으로 만든 가상 명세서 텍스트를 돌려준다** |
  | `STRUCTURER` | `rule` (기본) | LLM 대신 정규식으로 `품목명 수량단위 × 단가원 = 금액원` 모양의 줄을 나누고, 문자열 유사도로 후보를 고른다 |
  | `UPLOAD_DIR` | `uploads` (기본) | 원본 파일을 저장할 서버 폴더 |

### 검수 건 필드 (응답)

모든 검수 건 API는 아래 모양으로 응답한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `id` | 정수 | 검수 건 ID |
| `purchase_order_id` | 정수 | 연결된 발주 건 ID |
| `status` | 문자열 | 검수 건 상태 (위 상태값 중 하나) |
| `ai_draft` | 불리언 | `직원 확인 대기`이면 `true`. 화면 위쪽에 "AI가 읽은 초안이에요. 확인한 뒤 확정해 주세요" 배너를 띄울 때 쓴다 |
| `document` | 객체 \| null | 가장 최근에 올린 명세서. 올린 적 없으면 `null` |
| `document.id` | 정수 | 파일 ID |
| `document.filename` | 문자열 | 올릴 때 파일 이름 |
| `document.content_type` | 문자열 | 파일 형식 |
| `document.uploaded_at` | 문자열 (ISO 8601, UTC) | 올린 시각 |
| `document.read_error` | 문자열 \| null | 판독 실패 안내. 값이 있으면 화면에 "다시 올려 주세요"를 보여 준다 |
| `lines` | 목록 | 판독 초안 줄. 판독 전에는 `[]` |
| `missing_order_lines` | 목록 | 발주에는 있는데 명세서에 없는 줄. 줄마다 `product_id`, `order_quantity` |
| `check_count` | 정수 | 직원이 채워야 하는 칸 수. **0이어야 확정할 수 있다** |
| `all_match` | 불리언 | 발주와 모두 같으면 `true`. 이때 확정하면 바로 재고에 반영된다 |

**판독 초안 줄 (`lines[]`)**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `id` | 정수 | 줄 ID (`PATCH .../lines/{line_id}`에 쓴다). 다시 판독하면 새 ID가 된다 |
| `line_no` | 정수 | 명세서 안 순서 (1부터) |
| `read` | 객체 | OCR이 읽은 값 그대로 (`name`, `quantity`, `unit`, `unit_price`, `amount`). 직원이 고쳐도 바뀌지 않는다. `name` 말고는 `null`일 수 있다 |
| `candidates` | 목록 | 품목 후보 최대 3개, 점수 높은 순. 줄마다 `product_id`, `score`(0~1), `reason`(고른 이유). 맞는 상품이 없으면 `[]` |
| `product_id` | 정수 \| null | 지금 고른 상품. 처음엔 1순위 후보, 후보가 없으면 `null` |
| `quantity` | 정수 \| null | 지금 수량 (`unit` 단위). 처음엔 읽은 수량 |
| `unit` | 문자열 \| null | 수량 단위 (읽은 값) |
| `base_quantity` | 정수 \| null | 기준 단위(개)로 바꾼 수량. 단위가 상품의 포장 단위(예: 박스)면 환산값을 곱한다. 재고 반영이 끝난 건은 그때 반영한 값 |
| `order_quantity` | 정수 \| null | 같은 상품의 발주 수량. 발주에 없는 상품이면 `null` |
| `match_status` | 문자열 | 아래 표 중 하나 |

**`match_status` 값**

| 값 | 뜻 | 확정하면 |
| --- | --- | --- |
| `일치` | 상품·수량·단가가 발주·상품 기준 단가와 같다 | — |
| `확인 필요` | 품목을 고르지 않았거나 수량이 없다. `check_count`에 들어간다 | 확정할 수 없음 (`CHECK_REQUIRED`) |
| `발주에 없음` | 고른 상품이 발주에 없다 | `사장 승인 대기` |
| `수량 다름` | 기준 단위 수량이 발주 수량과 다르다 (같은 상품 여러 줄은 합쳐서 비교) | `사장 승인 대기` |
| `단가 다름` | 읽은 단가(기준 단위 1개당)가 상품의 기준 단가와 다르다. 단가를 읽지 못했거나 기준 단가가 없으면 비교하지 않는다 | `사장 승인 대기` |

`missing_order_lines`가 하나라도 있어도 `all_match`는 `false`이고, 확정하면 `사장 승인 대기`로 간다.

> **주의:** `missing_order_lines`·`all_match`는 판독 전(`업로드 대기`·`판독 중`)에도 계산된다. 판독 전에는 줄이 없으므로 발주 줄이 모두 `missing_order_lines`에 나오고 `all_match`는 `false`다. 화면은 `직원 확인 대기` 이후에만 이 두 값을 보여 준다.

---

## 1. 검수 건 목록 — `GET /inspections`

내 매장 검수 건을 `id` 순서로 돌려준다. 데모 1단계에서 `업로드 대기` 건을 찾을 때 쓴다.

**쿼리 값**

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `status` | 문자열 | 아니오 | 이 상태인 건만 돌려준다 (예: `업로드 대기`) |

```http
GET /inspections?status=업로드 대기
X-User-Id: 2
```

**성공 — `200`**: 검수 건 목록 (없으면 `[]`)

```json
[
  {
    "id": 1,
    "purchase_order_id": 1,
    "status": "업로드 대기",
    "ai_draft": false,
    "document": null,
    "lines": [],
    "missing_order_lines": [
      { "product_id": 1, "order_quantity": 10 }
    ],
    "check_count": 0,
    "all_match": false
  }
]
```

**실패**: 이 API만의 실패는 없다 (공통 실패만). 다른 매장 사장님(`X-User-Id: 3`)이 부르면 `[]`다.

---

## 2. 검수 건 1건 — `GET /inspections/{inspection_id}`

검수 건 1건의 상태·판독 초안·대조 결과를 본다. 명세서를 올린 뒤 `status`가 `판독 중`인 동안 화면이 이 API를 다시 불러 상태를 확인한다(폴링, STACK.md). 실제 서버에서는 업로드 응답 뒤 1초 안쪽에 `직원 확인 대기`가 됐다(데모 엔진 기준, 폴링 2회).

```http
GET /inspections/1
X-User-Id: 2
```

**성공 — `200`**: 검수 건 1건. 판독이 끝난 뒤(데모 3단계) 응답:

```json
{
  "id": 1,
  "purchase_order_id": 1,
  "status": "직원 확인 대기",
  "ai_draft": true,
  "document": {
    "id": 2,
    "filename": "statement.jpg",
    "content_type": "image/jpeg",
    "uploaded_at": "2026-11-10T05:08:08.480267Z",
    "read_error": null
  },
  "lines": [
    {
      "id": 1,
      "line_no": 1,
      "read": {
        "name": "서울우유 1000ml",
        "quantity": 10,
        "unit": "개",
        "unit_price": 2650,
        "amount": 26500
      },
      "candidates": [
        { "product_id": 1, "score": 1.0, "reason": "상품명이 '서울우유 1000ml'과 같아요" }
      ],
      "product_id": 1,
      "quantity": 10,
      "unit": "개",
      "base_quantity": 10,
      "order_quantity": 10,
      "match_status": "일치"
    }
  ],
  "missing_order_lines": [],
  "check_count": 0,
  "all_match": true
}
```

**판독에 실패했을 때** — `업로드 대기`로 돌아가고 `document.read_error`에 안내가 남는다 (US-03). 알림 발송은 아직 없다.

```json
{
  "id": 1,
  "purchase_order_id": 1,
  "status": "업로드 대기",
  "ai_draft": false,
  "document": {
    "id": 1,
    "filename": "blur.txt",
    "content_type": "text/plain",
    "uploaded_at": "2026-11-10T05:08:08.336351Z",
    "read_error": "명세서에서 품목 줄을 찾지 못했습니다. 명세서를 다시 올려 주세요"
  },
  "lines": [],
  "missing_order_lines": [
    { "product_id": 1, "order_quantity": 10 }
  ],
  "check_count": 0,
  "all_match": false
}
```

**실패**

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 검수 건이 없거나 다른 매장 검수 건 | `404` | `INSPECTION_NOT_FOUND` | 입고 검수 건을 찾을 수 없습니다 |

---

## 3. 명세서 업로드 — `POST /inspections/{inspection_id}/document`

직원이 거래명세서 사진이나 PDF를 올린다 (데모 2단계). 응답은 바로 `판독 중`으로 오고, 판독은 응답을 보낸 뒤 서버가 따로 돌린다. 결과는 2번 API로 확인한다.

- `업로드 대기`에서만 올릴 수 있다. 판독에 실패해 `업로드 대기`로 돌아온 건은 다시 올릴 수 있다
- 원본 파일은 서버 `UPLOAD_DIR`에 저장하고, 응답에는 저장 경로를 내보내지 않는다. 원본을 내려받는 API는 아직 없다

**요청 본문** (`multipart/form-data`)

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `file` | 파일 | **예** | `image/jpeg`, `image/png`, `image/heic`, `application/pdf`, `text/plain` 중 하나. 10MB 이하 `[제안]`. `text/plain`은 데모 OCR 리허설·테스트용이다 |

```http
POST /inspections/1/document
X-User-Id: 2
Content-Type: multipart/form-data; boundary=...

file=@statement.jpg (image/jpeg)
```

**성공 — `200`**: 바뀐 검수 건 (판독 전이라 `lines`는 비어 있다)

```json
{
  "id": 1,
  "purchase_order_id": 1,
  "status": "판독 중",
  "ai_draft": false,
  "document": {
    "id": 2,
    "filename": "statement.jpg",
    "content_type": "image/jpeg",
    "uploaded_at": "2026-11-10T05:08:08.480267Z",
    "read_error": null
  },
  "lines": [],
  "missing_order_lines": [
    { "product_id": 1, "order_quantity": 10 }
  ],
  "check_count": 0,
  "all_match": false
}
```

**실패** — 파일을 저장하지 않고 상태도 그대로다

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 검수 건이 없거나 다른 매장 검수 건 | `404` | `INSPECTION_NOT_FOUND` | 입고 검수 건을 찾을 수 없습니다 |
| `업로드 대기`가 아님 (예: 이미 올려서 `직원 확인 대기`) | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(직원 확인 대기)에서는 할 수 없습니다 |
| 허용하지 않는 파일 형식 | `400` | `UNSUPPORTED_FILE_TYPE` | 사진(JPG·PNG·HEIC) 또는 PDF만 올릴 수 있습니다 |
| 빈 파일 | `400` | `EMPTY_FILE` | 빈 파일입니다 |
| 10MB 초과 | `400` | `FILE_TOO_LARGE` | 10MB 이하 파일만 올릴 수 있습니다 |
| `file` 필드가 없음 | `422` | — | FastAPI 기본 형식 `{"detail": [...]}` |

**판독 단계의 결과** (응답 뒤에 서버에서 일어남)

| 상황 | 검수 건 상태 | `document.read_error` |
| --- | --- | --- |
| 품목 줄을 1개 이상 찾음 | `직원 확인 대기` (이전 초안 줄은 지우고 새로 만든다) | `null` |
| 품목 줄을 하나도 찾지 못함 | `업로드 대기` | 명세서에서 품목 줄을 찾지 못했습니다. 명세서를 다시 올려 주세요 |
| 글자를 읽을 수 없는 파일 (`text/plain`인데 UTF-8이 아님) | `업로드 대기` | 글자를 읽을 수 없는 파일입니다. 명세서를 다시 올려 주세요 |

---

## 4. 판독 줄 수정 — `PATCH /inspections/{inspection_id}/lines/{line_id}`

직원이 품목 후보 중 하나를 고르거나(후보에 없는 상품도 고를 수 있음), 수량을 고친다 (데모 4단계, 필요할 때만). 고친 뒤의 대조 결과가 응답에 바로 반영된다. 재고는 바뀌지 않는다 (R3).

- `직원 확인 대기`에서만 된다
- **보낸 필드만 바뀐다.** `null`을 보내면 값이 지워져 그 줄은 `확인 필요`가 된다
- `read`(OCR이 읽은 값)는 바뀌지 않는다

**요청 본문**

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `product_id` | 정수 \| null | 아니오 | 이 매장에 등록된 상품 ID |
| `quantity` | 정수 \| null | 아니오 | 1 이상. 줄의 `unit` 단위 |

```http
PATCH /inspections/1/lines/1
X-User-Id: 2
Content-Type: application/json

{ "product_id": 1, "quantity": 8 }
```

**성공 — `200`**: 바뀐 검수 건. 후보가 없던 줄(`알 수 없는 품목`)에 상품을 고르고 수량을 8로 고친 예:

```json
{
  "id": 1,
  "purchase_order_id": 1,
  "status": "직원 확인 대기",
  "ai_draft": true,
  "document": {
    "id": 1,
    "filename": "s.txt",
    "content_type": "text/plain",
    "uploaded_at": "2026-11-10T05:08:09.082487Z",
    "read_error": null
  },
  "lines": [
    {
      "id": 1,
      "line_no": 1,
      "read": {
        "name": "알 수 없는 품목",
        "quantity": 10,
        "unit": "개",
        "unit_price": 2650,
        "amount": null
      },
      "candidates": [],
      "product_id": 1,
      "quantity": 8,
      "unit": "개",
      "base_quantity": 8,
      "order_quantity": 10,
      "match_status": "수량 다름"
    }
  ],
  "missing_order_lines": [],
  "check_count": 0,
  "all_match": false
}
```

**실패** — 바뀌지 않는다. 아래 표 순서대로 검사한다

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 검수 건이 없거나 다른 매장 검수 건 | `404` | `INSPECTION_NOT_FOUND` | 입고 검수 건을 찾을 수 없습니다 |
| `직원 확인 대기`가 아님 (예: 확정 뒤) | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(사장 승인 대기)에서는 할 수 없습니다 |
| 이 검수 건에 없는 줄 ID | `404` | `LINE_NOT_FOUND` | 판독 줄을 찾을 수 없습니다 |
| 수량이 0 이하 | `400` | `INVALID_QUANTITY` | 수량은 1 이상이어야 합니다 |
| 등록되지 않은 상품 (없는 ID, 다른 매장 상품 포함) | `400` | `UNREGISTERED_PRODUCT` | 등록되지 않은 상품이 있습니다 |

---

## 5. 직원 확정 — `POST /inspections/{inspection_id}/confirm`

직원이 초안을 확인하고 [확정]을 누른다 (데모 4~5단계, US-04). 요청 본문은 없다. 확정할 때 대조 결과를 다시 계산해서 다음 중 하나가 된다.

| 대조 결과 | 검수 건 | 재고 | 발주 건 |
| --- | --- | --- | --- |
| `all_match: true` (모두 일치) | `재고 반영 완료` | 줄마다 `base_quantity`만큼 늘어남 | `입고 완료` |
| 다른 줄이 있음 | `사장 승인 대기` | **그대로** | 그대로 (`입고 대기`) |

- 재고에 반영할 때 그 시점의 상품 환산값·기준 단가를 줄에 따로 저장한다. 나중에 상품을 수정해도(`PATCH /products/{id}`) 이미 반영된 건의 값은 바뀌지 않는다 (US-08 인수 조건 #2)
- `사장 승인 대기` 다음 단계(사장 승인·반려, US-06)는 아직 없다

```http
POST /inspections/1/confirm
X-User-Id: 2
```

**성공 — `200`**: 바뀐 검수 건. 모두 일치한 경우(데모 5단계):

```json
{
  "id": 1,
  "purchase_order_id": 1,
  "status": "재고 반영 완료",
  "ai_draft": false,
  "document": {
    "id": 2,
    "filename": "statement.jpg",
    "content_type": "image/jpeg",
    "uploaded_at": "2026-11-10T05:08:08.480267Z",
    "read_error": null
  },
  "lines": [
    {
      "id": 1,
      "line_no": 1,
      "read": {
        "name": "서울우유 1000ml",
        "quantity": 10,
        "unit": "개",
        "unit_price": 2650,
        "amount": 26500
      },
      "candidates": [
        { "product_id": 1, "score": 1.0, "reason": "상품명이 '서울우유 1000ml'과 같아요" }
      ],
      "product_id": 1,
      "quantity": 10,
      "unit": "개",
      "base_quantity": 10,
      "order_quantity": 10,
      "match_status": "일치"
    }
  ],
  "missing_order_lines": [],
  "check_count": 0,
  "all_match": true
}
```

이 뒤 `GET /purchase-orders/1`의 `status`는 `입고 완료`, `GET /inventory`의 P-0123 `quantity`는 `10`이다.

수량이 다른 줄이 있었던 경우에는 `"status": "사장 승인 대기"`로 오고(나머지 모양은 같음), `GET /inventory`의 재고는 `0` 그대로였다.

**실패** — 상태·재고 모두 그대로다

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 검수 건이 없거나 다른 매장 검수 건 | `404` | `INSPECTION_NOT_FOUND` | 입고 검수 건을 찾을 수 없습니다 |
| `직원 확인 대기`가 아님 (예: 판독 전, 이미 확정함) | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(업로드 대기)에서는 할 수 없습니다 |
| 확인할 칸이 남아 있음 (`check_count` > 0) | `400` | `CHECK_REQUIRED` | 확인할 칸이 1개 남아 있습니다 |

---

## 6. 재고 조회 — `GET /inventory`

내 매장 상품별 현재 재고를 상품 `id` 순서로 돌려준다 (데모 3단계 "아직 0", 5단계 "0 → 10개"). 한 번도 입고되지 않은 상품은 `0`이다. 재고를 직접 바꾸는 API는 없다.

```http
GET /inventory
X-User-Id: 1
```

**성공 — `200`**: 재고 목록 (상품이 없으면 `[]`)

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `product_id` | 정수 | 상품 ID |
| `product_code` | 문자열 | 상품 코드 |
| `name` | 문자열 \| null | 상품명 |
| `base_unit` | 문자열 \| null | 기준 단위 (재고 수량의 단위) |
| `quantity` | 정수 | 현재 재고 (기준 단위) |

```json
[
  {
    "product_id": 1,
    "product_code": "P-0123",
    "name": "서울우유 1000ml",
    "base_unit": "개",
    "quantity": 10
  }
]
```

**실패**: 이 API만의 실패는 없다 (공통 실패만). 다른 매장 상품은 목록에 나오지 않는다.

---

## 데모 준비

```bash
DATABASE_URL=... python -m scripts.seed_demo   # DB를 비우고 시드 #1·#2·#4·#5 상태로 만든다 (개발용 DB에만)
uvicorn app.main:app
```

- 시드 결과: 사용자 1(매장 1 사장님)·2(매장 1 직원)·3(매장 2 사장님), 상품 1(P-0123), 발주 1(`입고 대기`, P-0123 × 10), 검수 건 1(`업로드 대기`), 재고 0
- `scripts/demo-statement.txt`: 리허설용 가상 명세서 (가리기 확인용 가상 연락처 줄 포함). 데모 OCR 엔진에서는 사진·PDF를 올려도 이 내용과 같은 텍스트로 판독된다

---

## 아직 정하지 않은 것

| 항목 | 누가 정하나 |
| --- | --- |
| 이 문서의 URL·오류 코드·상태 코드를 document `docs/API.md`에 옮길지 | PM |
| 실제 OCR 엔진과 LLM (지금은 데모 OCR·규칙 기반 정리기) | 팀 (STACK.md) |
| 발주 수량의 단위: 지금은 기준 단위(개)로 가정하고 대조한다 | 다음 고객 미팅 (R6) |
| 업로드·줄 수정·확정을 직원만 할 수 있는지 (지금은 역할로 막지 않음) | 팀 |
| 판독 실패 알림을 어떻게 보낼지 (지금은 `read_error`만 남김) | 팀 |
| 판독 전에도 `missing_order_lines`·`all_match`를 계산해서 내보낼지, 비워 둘지 | 팀 |
| 허용 파일 형식·최대 크기(10MB), `text/plain` 허용을 데모 뒤에도 둘지 | 팀 |
| 상태가 맞지 않을 때 `400` 대신 `409`(충돌)를 쓸지 (US-02 명세와 같은 질문) | 팀 |
| 원본 파일을 내려받거나 보여 주는 API를 둘지, 원본을 얼마나 보관할지 | 팀 |
| 기기 안에서 가리기로 바꿀 때 서버 가리기를 남길지 | 팀 (STACK.md) |
