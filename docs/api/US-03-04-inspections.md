# US-03·US-04·US-05 명세서 판독·직원 확인·입고 확정 API 명세

- 기능: F-03·F-04·F-05 / 스토리: US-03 명세서 업로드·판독, US-04 발주·납품 대조 및 일반 건 확정, US-05 단위 환산 및 수량 검증. 첫 데모 시나리오(3주차 초안) 1~5단계
- 근거: document 레포 `docs/requirements/backlog.md` US-03·US-04·US-05, `docs/DATA-MODEL.md` 입고 검수 건·판독 결과 줄·시드 #1·#2·#4·#5, `docs/domain/03-rules-states-llm.md` 3-2·3-4·R3·R6
- 응답 예시는 2026-11-10에 `feat/remaining-inspection-apis` 브랜치 코드를 테스트 DB에 띄우고 `scripts/seed_demo.py` 시드로 실제로 호출한 결과다
- **이 문서의 URL·오류 코드·상태 코드는 모두 `[제안]`이다.** document `docs/API.md`에 아직 US-03~US-05 항목이 없다. PM이 `API.md`에 옮기면 표시를 지운다
- 예외 건 사장 승인·반려, 확정 취소, 변경 이력, 알림(US-06·US-07)은 `US-06-07-exceptions-history.md`를 본다

## 한눈에 보기

| 데모 | 메서드 | URL | 언제 쓰나 | 바뀌는 상태 | 누가 |
| --- | --- | --- | --- | --- | --- |
| 1 | `GET` | `/inspections` | 내 매장 검수 건 목록 | 없음 | 누구나 |
| 2·3 | `GET` | `/inspections/{inspection_id}` | 검수 건 1건, 판독 초안·대조 결과. `판독 중`인 동안 화면이 폴링 | 없음 | 누구나 |
| 2 | `POST` | `/inspections/{inspection_id}/document` | 명세서 사진·PDF를 올릴 때 | `업로드 대기` → `판독 중` → (서버가 따로) `직원 확인 대기` 또는 `업로드 대기` | 누구나 (역할 제한 미정) |
| — | `GET` | `/inspections/{inspection_id}/files/{file_id}` | 올린 명세서 원본·예외 사진을 볼 때 | 없음 | 누구나 |
| 4 | `PATCH` | `/inspections/{inspection_id}/lines/{line_id}` | 품목·수량을 고치거나, 강조된 칸을 확인할 때 | 없음 | 누구나 (역할 제한 미정) |
| 4 | `PATCH` | `/inspections/{inspection_id}/summary` | 명세서 전체 칸(합계 불일치 등)을 확인할 때 | 없음 | 누구나 (역할 제한 미정) |
| 4·5 | `POST` | `/inspections/{inspection_id}/confirm` | 직원이 [확정]을 누를 때 | `직원 확인 대기` → `재고 반영 완료`(일반 건) 또는 `사장 승인 대기`(예외 건) | 누구나 (역할 제한 미정) |
| 3·5 | `GET` | `/inventory` | 상품별 현재 재고 보기 | 없음 | 누구나 |

**상태 흐름 (입고 검수 건, 이 문서 범위)**

```
업로드 대기 ──document──▶ 판독 중 ──(판독 성공)──▶ 직원 확인 대기 ──confirm──┬─▶ 재고 반영 완료  (일반 건: 재고 반영, 발주 → 입고 완료)
     ▲                         │                                        └─▶ 사장 승인 대기  (예외 건: 예외 사유 필수, 재고 그대로 → US-06 문서)
     └──────(판독 실패)─────────┘
```

- **재고는 일반 건 `confirm`과 예외 건 사장 승인(US-06)에서만 바뀐다.** 다른 API는 재고를 바꾸지 않는다 (R3)
- 상태값은 문서의 한국어 이름을 그대로 쓴다
- 검수 건은 발주를 `mark-delivered`할 때 `업로드 대기`로 1건 만들어진다 (US-01 명세 5번). `검수 종료` 뒤 새 검수 건은 US-06 문서의 `POST /inspections`로 만든다

## 공통 규칙

US-01 명세와 같다.

| 항목 | 내용 |
| --- | --- |
| 요청·응답 형식 | JSON. 단, 파일 업로드는 `multipart/form-data` |
| 사용자 확인 | 요청 헤더 `X-User-Id`에 매장 사용자 ID. 서버가 그 사용자의 `store_id`·`role`을 쓴다 (API.md 공통 규칙 [제안], 임시) |
| 매장 구분 | 검수 건은 연결된 발주의 매장으로 구분한다. 다른 매장 검수 건은 목록에 나오지 않고, 1건 단위 API에서는 "없음"(`404`)으로 응답한다 |
| 오류 응답 형식 | `{"error": {"code": "<원인 코드>", "message": "<사람이 읽는 설명>"}}` |
| 공통 실패 | `X-User-Id` 없음 `422`, 없는 사용자 `401`, 필드 타입 오류 `422` (US-01 명세 '모든 API에 공통인 실패'와 같음) |
| 검수 건 1건 단위 공통 실패 | 검수 건이 없거나 다른 매장 검수 건 → `404` `INSPECTION_NOT_FOUND` "입고 검수 건을 찾을 수 없습니다". 상태가 맞지 않음 → `400` `INVALID_STATUS_TRANSITION` "지금 상태(○○)에서는 할 수 없습니다" (상태는 그대로) |

### 판독은 이렇게 돈다

```
원본 파일 ─OCR─▶ 텍스트 ─가리기─▶ 가린 텍스트 ─LLM(서식 정리·품목 후보)─▶ 판독 초안 (03 3-4 공통 JSON 모양)
```

- **LLM은 글자를 읽지 않는다.** 글자는 OCR이 읽고, LLM은 줄을 표로 나누고(품목명·규격·수량·단위·단가·금액, 명세서 작성일·합계) 품목 후보(최대 3개, 이유 포함)를 붙이는 일만 한다
- **LLM이 확신하지 못한 값은 추측하지 않고 비워 두고, `uncertain_fields`에 필드 이름을 적는다** (US-03)
- **LLM에는 가린 텍스트와 상품 기준 정보(ID·코드·이름·규격)만 넘긴다.** 원본 사진·PDF·예외 사진은 넘기지 않는다. 담당자·연락처·사업자·주소·계좌 같은 낱말이 있는 줄은 통째로 빼고, 전화번호·사업자등록번호·이메일 모양은 `[가림]`으로 바꾼다. 지금은 서버에서 임시로 가린다 (기기 안에서 가리기는 이후에 정함, STACK.md)
- 판독이 끝나면 판독 로그(토큰 수·비용·걸린 시간)와 판독 원본값이 변경 이력에 남는다 (US-06-07 문서)
- **지금 OCR·LLM은 임시 구현이다.** 둘 다 아직 정하지 않아 환경변수로 바꿔 끼울 수 있게만 해 두었다

  | 환경변수 | 지금 값 | 하는 일 |
  | --- | --- | --- |
  | `OCR_ENGINE` | `demo` (기본) | `text/plain` 파일은 그 내용을 그대로 쓴다. **사진·PDF는 실제로 읽지 않고, 시드 값으로 만든 가상 명세서 텍스트를 돌려준다** |
  | `STRUCTURER` | `rule` (기본) | LLM 대신 정규식으로 `품목명 수량단위 × 단가원 = 금액원` 줄과 `합계 N원` 줄을 나누고, 문자열 유사도로 후보를 고른다. 불확실한 값은 만들지 않고, 토큰·비용은 0이다 |
  | `ALLOW_TEXT_UPLOAD` | 없음 (기본) | `1`이면 명세서로 `text/plain`도 받는다 (데모 리허설·테스트용). 기본은 사진·PDF만 |
  | `UPLOAD_DIR` | `uploads` (기본) | 올린 파일을 저장할 서버 폴더 |

### 검수 건 필드 (응답)

모든 검수 건 API(US-06 문서 포함)는 아래 모양으로 응답한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `id` | 정수 | 검수 건 ID |
| `purchase_order_id` | 정수 | 연결된 발주 건 ID |
| `status` | 문자열 | 검수 건 상태 |
| `ai_draft` | 불리언 | `직원 확인 대기`이면 `true`. 화면 위쪽에 "AI가 읽은 초안이에요. 확인한 뒤 확정해 주세요" 배너를 띄울 때 쓴다 |
| `document` | 객체 \| null | 가장 최근에 올린 명세서 (`id`, `filename`, `content_type`, `uploaded_at`, `read_error`). 올린 적 없으면 `null`. `read_error`에 값이 있으면 판독 실패 안내다 |
| `exception_photos` | 목록 | 예외 사진 (`id`, `filename`, `content_type`, `uploaded_at`). US-06 문서 |
| `summary` | 객체 \| null | 명세서 전체 판독값과 규칙 검증. 판독 전에는 `null` (아래 표) |
| `lines` | 목록 | 판독 초안 줄. 판독 전에는 `[]` (아래 표) |
| `missing_order_lines` | 목록 | 발주에는 있는데 명세서에 없는 상품. 판독 전에는 `[]` |
| `short_order_lines` | 목록 | 발주보다 적게 들어온 상품 (명세서에 없는 상품 포함). 승인 뒤 미입고로 남는 수량이다 (US-06). 판독 전에는 `[]` |
| `check_count` | 정수 | 아직 풀리지 않은 확인할 칸 수 (`lines[].open_checks`와 `summary.open_checks`를 모두 더한 값). **0이어야 확정할 수 있다** |
| `exception_types` | 문자열 목록 | 예외 종류. 비어 있으면 일반 건이다. `발주에 없음`, `수량 다름`, `단가 다름`, `파손`, `명세서에 없음` 중 해당하는 것 |
| `all_match` | 불리언 | 줄이 있고, 확인할 칸이 0이고, 예외가 없으면 `true`. 이때 확정하면 바로 재고에 반영된다 |
| `exception_reason` | 문자열 \| null | 직원이 적은 예외 사유 (US-06) |
| `reject_reason` | 문자열 \| null | 사장님 반려 사유 (US-06) |

`missing_order_lines`·`short_order_lines` 항목: `product_id`, `order_quantity`(발주 수량), `received_quantity`(명세서 기준 들어온 수량), `short_quantity`(모자란 수량).

**`summary` (명세서 전체)**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `document_date` | 문자열 \| null | 명세서 작성일 (`YYYY-MM-DD`). 읽지 못하면 `null` |
| `total_amount` | 정수 \| null | 명세서에 적힌 합계. 읽지 못하면 `null` |
| `line_amount_sum` | 정수 \| null | 줄 금액의 합. 금액이 빈 줄이 있으면 `null` |
| `uncertain_fields` | 문자열 목록 | LLM이 확신하지 못한 명세서 단위 필드 |
| `checked` | 불리언 | 직원이 명세서 전체 칸을 확인했는지 |
| `open_checks` | 문자열 목록 | 아직 풀리지 않은 칸: `줄 금액 합≠합계`, `불확실한 값` |

**판독 초안 줄 (`lines[]`)**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `id` | 정수 | 줄 ID (`PATCH .../lines/{line_id}`에 쓴다). 다시 판독하면 새 ID가 된다 |
| `line_no` | 정수 | 명세서 안 순서 (1부터) |
| `read` | 객체 | 판독 값 그대로 (`name`, `spec`, `quantity`, `unit`, `unit_price`, `amount`). 직원이 고쳐도 바뀌지 않는다. `name` 말고는 `null`일 수 있다 |
| `candidates` | 목록 | 품목 후보 최대 3개, 점수 높은 순 (`product_id`, `score` 0~1, `reason`). 맞는 상품이 없으면 `[]`. LLM이 새 상품을 만들지 않는다 |
| `uncertain_fields` | 문자열 목록 | LLM이 확신하지 못한 필드. 그 필드 값은 비어 있다 |
| `product_id` | 정수 \| null | 지금 고른 상품. 처음엔 1순위 후보, 후보가 없으면 `null` (자동으로 연결하지 않음, R9) |
| `quantity` | 정수 \| null | 지금 수량 (`unit` 단위). 처음엔 읽은 수량 |
| `unit` | 문자열 \| null | 수량 단위 (읽은 값) |
| `manual_base_quantity` | 정수 \| null | 단위를 환산할 수 없을 때 직원이 직접 넣은 기준 단위 수량 (US-05) |
| `damaged` | 불리언 | 직원이 파손으로 표시했는지. `true`면 예외 건 |
| `checked` | 불리언 | 직원이 이 줄의 강조된 칸을 확인했는지 |
| `base_quantity` | 정수 \| null | 기준 단위(개) 수량. `manual_base_quantity`가 있으면 그 값, 없으면 단위로 환산한 값, 환산할 수 없으면 `null`. 재고 반영이 끝난 건은 그때 반영한 값 |
| `order_quantity` | 정수 \| null | 같은 상품의 발주 수량. 발주에 없는 상품이면 `null` |
| `open_checks` | 문자열 목록 | 아직 풀리지 않은 확인할 칸 (아래 표). 화면에서 강조한다 |
| `match_status` | 문자열 | 발주 대조 결과 (아래 표) |
| `applied_unit_price` | 정수 \| null | 재고에 반영할 때 쓴 기준 단위 1개당 단가. 반영 전에는 `null` |

**확인할 칸 (`open_checks`)** — 하나라도 남아 있으면 확정할 수 없다 (US-04 실패·거절, US-05)

| 값 | 언제 생기나 | 어떻게 푸나 |
| --- | --- | --- |
| `품목 미선택` | 고른 상품이 없음 (후보 없음) | `product_id`를 넣는다. 맞는 상품이 없으면 `POST /products`로 등록한 뒤 고른다 (R9) |
| `수량 없음` | 수량이 비어 있음 (불확실해서 비운 경우 포함) | `quantity` 또는 `manual_base_quantity`를 넣는다 |
| `단위 환산 불가` | 단위를 모르거나(상품의 기준·포장 단위와 다름), 포장 단위인데 환산값이 등록되지 않음 (US-05) | `manual_base_quantity`(기준 단위 수량)를 직접 넣는다 |
| `후보 여러 개` | 품목 후보가 2개 이상 | 줄을 고치거나 `checked: true`를 보낸다 |
| `불확실한 값` | `uncertain_fields`가 있음 | 줄을 고치거나 `checked: true`를 보낸다 |
| `수량×단가≠금액` | 읽은 수량×단가가 읽은 금액과 다름 (규칙 검증 실패) | 줄을 고치거나 `checked: true`를 보낸다 |
| `줄 금액 합≠합계` (`summary`) | 줄 금액 합이 합계와 다름 (규칙 검증 실패) | `PATCH .../summary`에 `checked: true` |
| `불확실한 값` (`summary`) | 명세서 단위 `uncertain_fields`가 있음 | `PATCH .../summary`에 `checked: true` |

**발주 대조 결과 (`match_status`)** — 위에서부터 먼저 걸리는 하나

| 값 | 뜻 | 확정하면 |
| --- | --- | --- |
| `확인 필요` | 상품이나 기준 단위 수량을 알 수 없어 대조하지 못함 | 확정할 수 없음 (`CHECK_REQUIRED`) |
| `파손` | 직원이 `damaged: true`로 표시함 | 예외 건 |
| `발주에 없음` | 고른 상품이 발주에 없음 | 예외 건 |
| `수량 다름` | 기준 단위 수량이 발주 수량과 다름 (같은 상품 여러 줄은 합쳐서 비교) | 예외 건 |
| `단가 다름` | 명세서 단가(기준 단위 1개당)가 상품 기준 단가와 다름. 단가를 읽지 못했거나 기준 단가가 없거나 단위를 환산할 수 없으면 비교하지 않는다 | 예외 건 |
| `일치` | 위에 모두 해당하지 않음 | — |

`확인할 칸`과 `match_status`는 따로 계산한다. 예를 들어 금액 규칙 검증에 실패한 줄도 상품·수량이 발주와 같으면 `match_status`는 `일치`이고, `open_checks`에 `수량×단가≠금액`이 남는다.

---

## 1. 검수 건 목록 — `GET /inspections`

내 매장 검수 건을 `id` 순서로 돌려준다.

**쿼리 값**

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `status` | 문자열 | 아니오 | 이 상태인 건만 (예: `업로드 대기`, `사장 승인 대기`) |

```http
GET /inspections?status=업로드 대기
X-User-Id: 2
```

**성공 — `200`**: 검수 건 목록 (없으면 `[]`). 판독 전 검수 건은 이런 모양이다 (US-06 `POST /inspections` 실제 응답과 같은 모양):

```json
[
  {
    "id": 1,
    "purchase_order_id": 1,
    "status": "업로드 대기",
    "ai_draft": false,
    "document": null,
    "exception_photos": [],
    "summary": null,
    "lines": [],
    "missing_order_lines": [],
    "short_order_lines": [],
    "check_count": 0,
    "exception_types": [],
    "all_match": false,
    "exception_reason": null,
    "reject_reason": null
  }
]
```

**실패**: 공통 실패만. 다른 매장 사용자가 부르면 `[]`다.

---

## 2. 검수 건 1건 — `GET /inspections/{inspection_id}`

검수 건 1건의 상태·판독 초안·대조 결과를 본다. 명세서를 올린 뒤 `판독 중`인 동안 화면이 이 API를 다시 불러 상태를 확인한다(폴링, STACK.md). 실제 서버에서는 폴링 2회(약 0.1초 간격) 안에 `직원 확인 대기`가 됐다 (데모 엔진 기준).

```http
GET /inspections/1
X-User-Id: 2
```

**성공 — `200`**: 사진을 올려 판독이 끝난 뒤(데모 3단계):

```json
{
  "id": 1,
  "purchase_order_id": 1,
  "status": "직원 확인 대기",
  "ai_draft": true,
  "document": {
    "id": 1,
    "filename": "statement.jpg",
    "content_type": "image/jpeg",
    "uploaded_at": "2026-11-10T06:38:13.824435Z",
    "read_error": null
  },
  "exception_photos": [],
  "summary": {
    "document_date": null,
    "total_amount": 26500,
    "line_amount_sum": 26500,
    "uncertain_fields": [],
    "checked": false,
    "open_checks": []
  },
  "lines": [
    {
      "id": 1,
      "line_no": 1,
      "read": {
        "name": "서울우유 1000ml",
        "spec": null,
        "quantity": 10,
        "unit": "개",
        "unit_price": 2650,
        "amount": 26500
      },
      "candidates": [
        { "product_id": 1, "score": 1.0, "reason": "상품명이 '서울우유 1000ml'과 같아요" }
      ],
      "uncertain_fields": [],
      "product_id": 1,
      "quantity": 10,
      "unit": "개",
      "manual_base_quantity": null,
      "damaged": false,
      "checked": false,
      "base_quantity": 10,
      "order_quantity": 10,
      "open_checks": [],
      "match_status": "일치",
      "applied_unit_price": null
    }
  ],
  "missing_order_lines": [],
  "short_order_lines": [],
  "check_count": 0,
  "exception_types": [],
  "all_match": true,
  "exception_reason": null,
  "reject_reason": null
}
```

**규칙 검증에 걸린 경우** — 명세서가 `서울우유 1000ml 10개 × 2,650원 = 25,000원` / `합계 30,000원`일 때 (바뀐 부분만):

```json
{
  "summary": {
    "document_date": null,
    "total_amount": 30000,
    "line_amount_sum": 25000,
    "uncertain_fields": [],
    "checked": false,
    "open_checks": ["줄 금액 합≠합계"]
  },
  "lines": [
    {
      "read": { "name": "서울우유 1000ml", "spec": null, "quantity": 10, "unit": "개", "unit_price": 2650, "amount": 25000 },
      "open_checks": ["수량×단가≠금액"],
      "match_status": "일치"
    }
  ],
  "check_count": 2,
  "all_match": false
}
```

**단위를 환산할 수 없는 경우** — `서울우유 1000ml 10통 × 2,650원` (`통`은 상품의 기준·포장 단위가 아님, US-05):

```json
{
  "lines": [
    {
      "quantity": 10,
      "unit": "통",
      "manual_base_quantity": null,
      "base_quantity": null,
      "order_quantity": 10,
      "open_checks": ["단위 환산 불가"],
      "match_status": "확인 필요"
    }
  ]
}
```

**판독에 실패한 경우** — `업로드 대기`로 돌아가고 `document.read_error`에 안내가 남는다. 올린 사용자에게 알림이 간다 (US-06-07 문서 '알림'):

```json
{
  "status": "업로드 대기",
  "document": {
    "id": 1,
    "filename": "s.txt",
    "content_type": "text/plain",
    "uploaded_at": "2026-11-10T06:38:16.484680Z",
    "read_error": "명세서에서 품목 줄을 찾지 못했습니다. 명세서를 다시 올려 주세요"
  },
  "summary": null,
  "lines": []
}
```

**실패**: 검수 건 1건 단위 공통 실패 (`404 INSPECTION_NOT_FOUND`).

---

## 3. 명세서 업로드 — `POST /inspections/{inspection_id}/document`

직원이 거래명세서 사진이나 PDF를 올린다 (데모 2단계, US-03). 응답은 바로 `판독 중`으로 오고, 판독은 응답을 보낸 뒤 서버가 따로 돌린다. 결과는 2번 API로 확인한다.

- `업로드 대기`에서만 올릴 수 있다. 판독에 실패해 `업로드 대기`로 돌아온 건은 다시 올릴 수 있다
- 원본 파일은 서버 `UPLOAD_DIR`에 저장하고, 응답에는 저장 경로를 내보내지 않는다. 원본은 `GET .../files/{file_id}`로 본다

**요청 본문** (`multipart/form-data`)

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `file` | 파일 | **예** | `image/jpeg`, `image/png`, `image/heic`, `application/pdf` 중 하나. 10MB 이하 `[제안]`. `ALLOW_TEXT_UPLOAD=1`이면 `text/plain`도 받는다 |

```http
POST /inspections/1/document
X-User-Id: 2
Content-Type: multipart/form-data; boundary=...

file=@statement.jpg (image/jpeg)
```

**성공 — `200`**: 바뀐 검수 건 (`"status": "판독 중"`, `document`에 올린 파일, `lines`는 `[]`)

**실패** — 파일을 저장하지 않고 상태도 그대로다

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| `업로드 대기`가 아님 (예: 이미 올려서 `직원 확인 대기`) | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(직원 확인 대기)에서는 할 수 없습니다 |
| 사진·PDF가 아님 (기본 설정에서 `text/plain` 포함) | `400` | `UNSUPPORTED_FILE_TYPE` | 사진(JPG·PNG·HEIC) 또는 PDF만 올릴 수 있습니다 |
| 빈 파일 | `400` | `EMPTY_FILE` | 빈 파일입니다 |
| 10MB 초과 | `400` | `FILE_TOO_LARGE` | 10MB 이하 파일만 올릴 수 있습니다 |
| `file` 필드가 없음 | `422` | — | FastAPI 기본 형식 `{"detail": [...]}` |

**판독 단계의 결과** (응답 뒤에 서버에서 일어남)

| 상황 | 검수 건 상태 | 그 밖에 |
| --- | --- | --- |
| 품목 줄을 1개 이상 찾음 | `직원 확인 대기` | 이전 초안 줄을 지우고 새로 만든다. `checked`·`summary.checked`도 처음으로 돌아간다. 판독 로그(성공)·판독 원본값 이력이 남는다 |
| 품목 줄을 하나도 찾지 못함 | `업로드 대기` | `read_error`: 명세서에서 품목 줄을 찾지 못했습니다. 명세서를 다시 올려 주세요. 올린 사용자에게 알림. 판독 로그(실패)가 남는다 |
| 글자를 읽을 수 없는 파일 (`text/plain`인데 UTF-8이 아님) | `업로드 대기` | `read_error`: 글자를 읽을 수 없는 파일입니다. 명세서를 다시 올려 주세요. 나머지는 위와 같음 |

---

## 4. 파일 보기 — `GET /inspections/{inspection_id}/files/{file_id}`

올린 명세서 원본이나 예외 사진(US-06)을 내려받는다. 사장님이 예외 건을 검토할 때 쓴다. `file_id`는 `document.id`나 `exception_photos[].id`다.

```http
GET /inspections/1/files/1
X-User-Id: 1
```

**성공 — `200`**: 파일 내용 그대로. `Content-Type`은 올릴 때 형식 (예: `image/jpeg`)

**실패**

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 검수 건이 없거나 다른 매장 검수 건 | `404` | `INSPECTION_NOT_FOUND` | 입고 검수 건을 찾을 수 없습니다 |
| 이 검수 건에 없는 파일, 또는 서버에서 파일이 지워짐 | `404` | `FILE_NOT_FOUND` | 파일을 찾을 수 없습니다 |

---

## 5. 판독 줄 수정·확인 — `PATCH /inspections/{inspection_id}/lines/{line_id}`

직원이 품목 후보를 고르거나(후보에 없는 상품도 고를 수 있음), 수량을 고치거나, 기준 단위 수량을 직접 넣거나, 파손을 표시하거나, 강조된 칸을 확인한다 (데모 4단계, US-04·US-05). 고친 뒤의 대조 결과가 응답에 바로 반영된다. 재고는 바뀌지 않는다 (R3).

- `직원 확인 대기`에서만 된다
- **보낸 필드만 바뀐다.** `product_id`·`quantity`·`manual_base_quantity`에 `null`을 보내면 값이 지워진다
- **고치거나 확인하면 그 줄의 강조 칸(후보 여러 개·불확실한 값·금액 규칙)을 확인한 것으로 본다** (`checked`가 `true`가 됨). `checked: false`를 함께 보내면 확인하지 않은 것으로 둔다. 값을 채워야 풀리는 칸(품목 미선택·수량 없음·단위 환산 불가)은 `checked`로 풀리지 않는다
- `read`(판독 값)는 바뀌지 않는다
- 바뀐 값마다 변경 이력이 남는다 (US-07)

**요청 본문**

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `product_id` | 정수 \| null | 아니오 | 이 매장에 등록된 상품 ID |
| `quantity` | 정수 \| null | 아니오 | 1 이상. 줄의 `unit` 단위 |
| `manual_base_quantity` | 정수 \| null | 아니오 | 1 이상. 기준 단위 수량을 직접 넣는다. 있으면 환산보다 먼저 쓴다 (US-05) |
| `damaged` | 불리언 | 아니오 | 파손 표시. `true`면 예외 건 |
| `checked` | 불리언 | 아니오 | 강조된 칸을 확인했는지. 보내지 않으면 `true`로 본다 |

```http
PATCH /inspections/1/lines/1
X-User-Id: 2
Content-Type: application/json

{ "manual_base_quantity": 10 }
```

**성공 — `200`**: 바뀐 검수 건. 위 '단위를 환산할 수 없는 경우'에 기준 단위 수량 10을 넣은 결과 (바뀐 부분만):

```json
{
  "lines": [
    {
      "unit": "통",
      "manual_base_quantity": 10,
      "checked": true,
      "base_quantity": 10,
      "order_quantity": 10,
      "open_checks": [],
      "match_status": "일치"
    }
  ],
  "check_count": 0,
  "all_match": true
}
```

**실패** — 바뀌지 않는다. 아래 표 순서대로 검사한다

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 검수 건이 없거나 다른 매장 검수 건 | `404` | `INSPECTION_NOT_FOUND` | 입고 검수 건을 찾을 수 없습니다 |
| `직원 확인 대기`가 아님 (예: `재고 반영 완료` 뒤 — 재고 조정으로 따로 처리) | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(재고 반영 완료)에서는 할 수 없습니다 |
| 이 검수 건에 없는 줄 ID | `404` | `LINE_NOT_FOUND` | 판독 줄을 찾을 수 없습니다 |
| `quantity`·`manual_base_quantity`가 0 이하 | `400` | `INVALID_QUANTITY` | 수량은 1 이상이어야 합니다 |
| 등록되지 않은 상품 (없는 ID, 다른 매장 상품 포함) | `400` | `UNREGISTERED_PRODUCT` | 등록되지 않은 상품이 있습니다 |

---

## 6. 명세서 전체 칸 확인 — `PATCH /inspections/{inspection_id}/summary`

`summary.open_checks`(줄 금액 합≠합계, 불확실한 값)를 직원이 확인했다고 표시한다 (US-04). `직원 확인 대기`에서만 된다.

**요청 본문**

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `checked` | 불리언 | **예** | 확인했으면 `true` |

```http
PATCH /inspections/1/summary
X-User-Id: 2
Content-Type: application/json

{ "checked": true }
```

**성공 — `200`**: 바뀐 검수 건 (`summary.checked`가 `true`, `summary.open_checks`가 `[]`)

**실패**: 검수 건 1건 단위 공통 실패.

---

## 7. 직원 확정 — `POST /inspections/{inspection_id}/confirm`

직원이 초안을 확인하고 [확정]을 누른다 (데모 4~5단계, US-04). 확정할 때 대조 결과를 다시 계산해서 다음 중 하나가 된다.

| 대조 결과 | 검수 건 | 재고 | 발주 건 |
| --- | --- | --- | --- |
| 일반 건 (`all_match: true`) | `재고 반영 완료` | 줄마다 `base_quantity`만큼 늘어남 | `입고 완료` |
| 예외 건 (`exception_types`가 있음) | `사장 승인 대기` (예외 사유 필수) | **그대로** | 그대로 (`입고 대기`) |

- 재고에 반영할 때 그 시점의 상품 환산값과 단가(명세서 단가를 기준 단위 1개당으로 바꾼 값, 읽지 못했으면 상품 기준 단가)를 줄에 따로 저장한다. 나중에 상품을 수정해도(`PATCH /products/{id}`) 이미 반영된 건의 값은 바뀌지 않는다 (US-08 인수 조건 #2)
- 예외 건 다음 단계(사장 승인·반려, 확정 취소)는 US-06-07 문서를 본다

**요청 본문** (선택)

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `exception_reason` | 문자열 \| null | 예외 건이면 **예** | 예외 사유. 앞뒤 공백은 지운다. 일반 건이면 무시한다 |

```http
POST /inspections/1/confirm
X-User-Id: 2
```

**성공 — `200`**: 바뀐 검수 건. 일반 건(데모 5단계) 응답은 2번 정상 예시에서 아래만 다르다:

```json
{
  "status": "재고 반영 완료",
  "ai_draft": false,
  "lines": [
    { "base_quantity": 10, "match_status": "일치", "applied_unit_price": 2650 }
  ],
  "all_match": true
}
```

이 뒤 `GET /purchase-orders/1`의 `status`는 `입고 완료`, `GET /inventory`의 P-0123 `quantity`는 `10`이다.

예외 건 확정 예시는 US-06-07 문서 1번을 본다.

**실패** — 상태·재고 모두 그대로다

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| `직원 확인 대기`가 아님 (예: 판독 전, 이미 확정함) | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(업로드 대기)에서는 할 수 없습니다 |
| 확인할 칸이 남아 있음 (`check_count` > 0) | `400` | `CHECK_REQUIRED` | 확인할 칸이 2개 남아 있습니다 |
| 예외 건인데 예외 사유가 없음·빈칸·공백만 있음 | `400` | `EXCEPTION_REASON_REQUIRED` | 예외 사유를 적어 주세요 |

---

## 8. 재고 조회 — `GET /inventory`

내 매장 상품별 현재 재고를 상품 `id` 순서로 돌려준다 (데모 3단계 "아직 0", 5단계 "0 → 10개"). 한 번도 입고되지 않은 상품은 `0`이다. 재고를 직접 바꾸는 API는 없다.

```http
GET /inventory
X-User-Id: 1
```

**성공 — `200`**

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

**실패**: 공통 실패만. 다른 매장 상품은 목록에 나오지 않는다.

---

## 데모 준비

```bash
DATABASE_URL=... python -m scripts.seed_demo   # DB를 비우고 시드 #1·#2·#4·#5 상태로 만든다 (개발용 DB에만)
uvicorn app.main:app                            # 리허설에 text 명세서를 쓰려면 ALLOW_TEXT_UPLOAD=1
```

- 시드 결과: 사용자 1(매장 1 사장님)·2(매장 1 직원)·3(매장 2 사장님), 상품 1(P-0123), 발주 1(`입고 대기`, P-0123 × 10), 검수 건 1(`업로드 대기`), 재고 0
- `scripts/demo-statement.txt`: 리허설용 가상 명세서 (가리기 확인용 가상 연락처 줄 포함). 데모 OCR 엔진에서는 사진·PDF를 올려도 이 내용과 같은 텍스트로 판독된다

---

## 아직 정하지 않은 것

| 항목 | 누가 정하나 |
| --- | --- |
| 이 문서의 URL·오류 코드·상태 코드를 document `docs/API.md`에 옮길지 | PM |
| 실제 OCR 엔진과 LLM (지금은 데모 OCR·규칙 기반 정리기) | 팀 (STACK.md) |
| '불확실한 값'으로 표시할 확신도 기준 수치 | 표본 테스트 후 (backlog US-03) |
| 발주 수량의 단위: 지금은 기준 단위(개)로 가정하고 대조한다 | 다음 고객 미팅 (R6) |
| 한 명세서에 박스·낱개가 섞여 있을 때 구분 방법 (지금은 줄마다 적힌 단위로만 판단) | 다음 고객 미팅 (R6) |
| 업로드·줄 수정·확정을 직원만 할 수 있는지 (지금은 역할로 막지 않음) | 팀 |
| 단가가 얼마나 높아야 '높은 단가'인지 (R8). 지금은 1원이라도 다르면 `단가 다름` | 다음 고객 미팅 |
| 재고 반영 단가를 상품 기준 단가(`base_unit_price`)에도 반영할지 (지금은 바꾸지 않음) | 팀 (DATA-MODEL.md 미정) |
| 허용 파일 형식·최대 크기(10MB), 원본을 얼마나 보관할지 | 팀 |
| 상태가 맞지 않을 때 `400` 대신 `409`(충돌)를 쓸지 (US-02 명세와 같은 질문) | 팀 |
| 기기 안에서 가리기로 바꿀 때 서버 가리기를 남길지 | 팀 (STACK.md) |
| 예외 사유·반려 사유·명세서 전체 판독값을 `inspections` 테이블로 옮길지 (지금은 `inspection_details` 별도 테이블. `create_all()`만 써서 기존 테이블에 열을 더할 수 없기 때문) | 팀 (Alembic 도입 여부와 함께) |
