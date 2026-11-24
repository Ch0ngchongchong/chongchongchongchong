# US-03·US-04·US-05 명세서 판독·직원 확인·입고 확정 API 명세

- 기능: F-03·F-04·F-05 / 스토리: US-03 명세서 업로드·판독, US-04 발주·납품 대조 및 일반 건 확정, US-05 단위 환산 및 수량 검증. 첫 데모 시나리오(3주차 초안) 1~5단계
- 근거: document 레포 `docs/requirements/backlog.md` US-03·US-04·US-05, `docs/DATA-MODEL.md` 입고 검수 건·판독 결과 줄·시드 #1·#2·#4·#5, `docs/domain/03-rules-states-llm.md` 3-2·3-4·R3·R6
- **이 문서의 URL·오류 코드·상태 코드는 모두 `[제안]`이다.** document `docs/API.md`에 아직 US-03~US-05 항목이 없다. PM이 `API.md`에 옮기면 표시를 지운다
- 예외 건 사장 승인·반려, 확정 취소, 변경 이력, 알림(US-06·US-07)은 `US-06-07-inspections.md`를 본다
- 2026-11-24 병합 조율 메모: 이 문서는 한때 `feat/r7-quantity-limit-and-amount-alert`(규칙 검증·R7·R8)와 `feat/remaining-inspection-apis`(신은총님, 예외 건·변경 이력·open_checks 설계) 두 브랜치로 갈라졌다. 팀 결정으로 이 문서의 모양(`rule_violations`·평평한 `total_amount`/`summary_mismatch`/`summary_checked`·`ChangeHistory` 기반 이력)을 기준으로 합쳤고, 신은총님 쪽에만 있던 알림·단위 환산 수동 입력(`manual_base_quantity`)·부족 입고(`short_order_lines`)는 이 모양 위로 다시 옮겨 왔다. `open_checks`·중첩 `summary` 객체·`exception_types`·`InspectionDetail` 테이블은 쓰지 않는다

## 한눈에 보기

| 데모 | 메서드 | URL | 언제 쓰나 | 바뀌는 상태 | 누가 |
| --- | --- | --- | --- | --- | --- |
| 1 | `GET` | `/inspections` | 내 매장 검수 건 목록 | 없음 | 누구나 |
| 2·3 | `GET` | `/inspections/{inspection_id}` | 검수 건 1건, 판독 초안·대조 결과. `판독 중`인 동안 화면이 폴링 | 없음 | 누구나 |
| 2 | `POST` | `/inspections/{inspection_id}/document` | 명세서 사진·PDF를 올릴 때 | `업로드 대기` → `판독 중` → (서버가 따로) `직원 확인 대기` 또는 `업로드 대기` | 담당 직원 또는 사장님 (`FORBIDDEN_ROLE`) |
| 4 | `POST` | `/inspections/{inspection_id}/lines` | 판독 결과에 없는 줄을 직원이 추가할 때 (US-04 인수 조건) | 없음 | 담당 직원 또는 사장님 |
| 4 | `PATCH` | `/inspections/{inspection_id}/lines/{line_id}` | 품목·수량을 고치거나, 강조된 칸을 확인할 때 | 없음 | 담당 직원 또는 사장님 |
| 4 | `POST` | `/inspections/{inspection_id}/summary-check` | 줄 금액 합≠합계(규칙 검증 실패)를 확인할 때 | 없음 | 담당 직원 또는 사장님 |
| 4·5 | `POST` | `/inspections/{inspection_id}/confirm` | 직원이 [확정]을 누를 때 | `직원 확인 대기` → `재고 반영 완료`(일반 건) 또는 `사장 승인 대기`(예외 건) | 담당 직원 또는 사장님 |
| — | `GET` | `/inspections/{inspection_id}/metrics` | 판독 정확도·고친 줄 비율·행 누락률·걸린 시간 (US-07) | 없음 | 사장님만 |
| — | `GET` | `/inspections/{inspection_id}/history` | 변경 이력 (US-07) | 없음 | 사장님만 |
| — | `GET` | `/inspections/{inspection_id}/reading-logs` | 판독 로그 (토큰·비용·걸린 시간) | 없음 | 사장님만 |
| — | `POST`/`GET` | `/inspections/{inspection_id}/exception-photos` | 예외 사진 올리기·목록 (US-06) | 없음 | 담당 직원 또는 사장님 (올리기) / 누구나 (목록) |
| 3·5 | `GET` | `/inventory` | 상품별 현재 재고 보기 | 없음 | 누구나 |
| — | `GET`/`POST` | `/notifications`, `/notifications/{id}/read` | 내 알림 목록·읽음 표시 (지금은 판독 실패만) | 없음 | 본인 알림만 |

예외 건 사장 승인·반려(`approve`/`reject`/`cancel-confirmation`/`reinspect`/`close`)는 `US-06-07-inspections.md`를 본다.

**상태 흐름 (입고 검수 건, 이 문서 범위)**

```
업로드 대기 ──document──▶ 판독 중 ──(판독 성공)──▶ 직원 확인 대기 ──confirm──┬─▶ 재고 반영 완료  (일반 건: 재고 반영, 발주 → 입고 완료)
     ▲                         │                                        └─▶ 사장 승인 대기  (예외 건: 예외 사유 필수, 재고 그대로 → US-06-07 문서)
     └──────(판독 실패, 알림 발송)─┘
```

- **재고는 일반 건 `confirm`과 예외 건 사장 승인(US-06-07 문서)에서만 바뀐다.** 다른 API는 재고를 바꾸지 않는다 (R3)
- 상태값은 문서의 한국어 이름을 그대로 쓴다
- 검수 건은 발주를 `mark-delivered`할 때 `업로드 대기`로 1건 만들어진다 (US-01 명세 5번). `검수 종료` 뒤 새 검수 건은 US-06-07 문서의 `POST /purchase-orders/{id}/redeliveries`로 만든다

## 공통 규칙

US-01 명세와 같다.

| 항목 | 내용 |
| --- | --- |
| 요청·응답 형식 | JSON. 단, 파일 업로드는 `multipart/form-data` |
| 사용자 확인 | 요청 헤더 `X-User-Id`에 매장 사용자 ID. 서버가 그 사용자의 `store_id`·`role`을 쓴다 (API.md 공통 규칙 [제안], 임시) |
| 매장 구분 | 검수 건은 연결된 발주의 매장으로 구분한다. 다른 매장 검수 건은 목록에 나오지 않고, 1건 단위 API에서는 "없음"(`404`)으로 응답한다 |
| 담당 직원 | 사장님은 모든 검수 건을 다룰 수 있다. 직원은 담당(처음 명세서를 올린) 검수 건만 다룰 수 있다. 담당자가 아직 없으면(사장님이 올렸거나 업로드 전) 막지 않는다 (2026-11-16 멘토 데모 피드백 팀 결정) |
| 오류 응답 형식 | `{"error": {"code": "<원인 코드>", "message": "<사람이 읽는 설명>"}}` |
| 공통 실패 | `X-User-Id` 없음 `422`, 없는 사용자 `401`, 필드 타입 오류 `422` (US-01 명세 '모든 API에 공통인 실패'와 같음) |
| 검수 건 1건 단위 공통 실패 | 검수 건이 없거나 다른 매장 검수 건 → `404` `INSPECTION_NOT_FOUND` "입고 검수 건을 찾을 수 없습니다". 상태가 맞지 않음 → `400` `INVALID_STATUS_TRANSITION` "지금 상태(○○)에서는 할 수 없습니다" (상태는 그대로). 담당 아닌 직원 → `403` `FORBIDDEN_ROLE` "다른 직원이 담당하는 입고 건입니다" |

### 판독은 이렇게 돈다

```
원본 파일 ─OCR─▶ 텍스트 ─가리기─▶ 가린 텍스트 ─LLM(서식 정리·품목 후보)─▶ 판독 초안
```

- **LLM은 글자를 읽지 않는다.** 글자는 OCR이 읽고, LLM은 줄을 표로 나누고(품목명·규격·수량·단위·단가·금액, 명세서 합계) 품목 후보(최대 3개, 이유 포함)를 붙이는 일만 한다
- **LLM이 확신하지 못한 값은 추측하지 않고 비워 두고, 줄의 `uncertain_fields`에 필드 이름을 적는다** (US-03). 문서 전체 합계(`total_amount`)가 불확실하면 `null`로 둔다
- **LLM에는 가린 텍스트와 상품 기준 정보(ID·코드·이름·규격)만 넘긴다.** 원본 사진·PDF·예외 사진은 넘기지 않는다. 담당자·연락처·사업자·주소·계좌 같은 낱말이 있는 줄은 통째로 빼고, 전화번호·사업자등록번호·이메일 모양은 `[가림]`으로 바꾼다. 지금은 서버에서 임시로 가린다 (기기 안에서 가리기는 이후에 정함, STACK.md)
- 판독이 끝나면 판독 로그(토큰 수·비용·걸린 시간)가 남는다 (`GET .../reading-logs`). 판독에 실패하면 올린 직원에게 알림이 간다 (`GET /notifications`)
- **OCR과 정리기는 환경변수로 선택한다.**

  | 환경변수 | 지금 값 | 하는 일 |
  | --- | --- | --- |
  | `OCR_ENGINE` | `demo` (기본) | `text/plain` 파일은 그 내용을 그대로 쓴다. **사진·PDF는 실제로 읽지 않고, 시드 값으로 만든 가상 명세서 텍스트를 돌려준다** |
  | `STRUCTURER` | `rule` (기본) | LLM 대신 정규식으로 `품목명 수량단위 × 단가원 = 금액원` 줄과 `합계 N원` 줄을 나눈다. 불확실한 값은 만들지 않고, 토큰·비용은 `null`이다 |
  | `ALLOW_TEXT_UPLOAD` | 없음 (기본) | `1`이면 명세서로 `text/plain`도 받는다 (데모 리허설·테스트용). 기본은 사진·PDF만 |

  `STRUCTURER=openai`일 때 OpenAI 및 로컬 OCR 설정(`OPENAI_API_KEY`·`OPENAI_MODEL`·비용 추정 환경변수)은 `US-06-07-inspections.md`를 본다.

### 검수 건 필드 (응답)

모든 검수 건 API는 아래 모양으로 응답한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `id` | 정수 | 검수 건 ID |
| `purchase_order_id` | 정수 | 연결된 발주 건 ID |
| `status` | 문자열 | 검수 건 상태 |
| `ai_draft` | 불리언 | `직원 확인 대기`이면 `true`. 화면 위쪽에 "AI가 읽은 초안이에요. 확인한 뒤 확정해 주세요" 배너를 띄울 때 쓴다 |
| `exception_reason` | 문자열 \| null | 직원이 적은 예외 사유 (US-06-07 문서) |
| `reject_reason` | 문자열 \| null | 사장님 반려 사유 (US-06-07 문서) |
| `document` | 객체 \| null | 가장 최근에 올린 명세서 (`id`, `filename`, `content_type`, `uploaded_at`, `read_error`). 올린 적 없으면 `null`. `read_error`에 값이 있으면 판독 실패 안내다 |
| `lines` | 목록 | 판독 초안 줄. 판독 전에는 `[]` (아래 표) |
| `missing_order_lines` | 목록 | 발주에는 있는데 명세서에 아예 안 들어온 상품(`product_id`, `order_quantity`). 판독 전에는 `[]` |
| `short_order_lines` | 목록 | 발주보다 적게(0개보다는 많이) 들어온 상품 (`product_id`, `order_quantity`, `received_quantity`, `short_quantity`). 승인 뒤에도 남는 미입고 수량을 보여 준다 (US-06-07). 판독 전에는 `[]` |
| `check_count` | 정수 | 아직 풀리지 않은 확인할 칸 수. **0이어야 확정할 수 있다** (아래 '확인할 칸' 표) |
| `all_match` | 불리언 | 발주와 모두 같고 확인할 칸이 0이면 `true`. 이때 확정하면 바로 재고에 반영된다 |
| `total_amount` | 정수 \| null | 판독이 읽은 명세서 합계. 못 찾았거나 불확실하면 `null` (검증하지 않음) |
| `summary_mismatch` | 불리언 | 줄 금액 합이 `total_amount`와 다르면 `true` (규칙 검증 실패 칸). 합계를 못 읽었으면 항상 `false` |
| `summary_checked` | 불리언 | 위 칸을 사장님/직원이 확인했다는 표시 (`POST .../summary-check`) |
| `final_amount` | 정수 | 지금 값으로 확정하면 실제로 반영될 금액 (기준 단위 수량 × 단가의 합) |
| `amount_over_limit` | 불리언 | `final_amount`가 발주의 금액 경고 기준(`amount_alert_threshold`)을 넘으면 `true` → 예외 건으로 분류 (R7, 2026-11-16 멘토 데모 피드백) |

**판독 초안 줄 (`lines[]`)**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `id` | 정수 | 줄 ID (`PATCH .../lines/{line_id}`에 쓴다). 다시 판독하면 새 ID가 된다 |
| `line_no` | 정수 | 명세서 안 순서 (1부터). 직원이 추가한 줄은 그 뒤 번호 |
| `read` | 객체 | 판독 값 그대로 (`name`, `spec`, `quantity`, `unit`, `unit_price`, `amount`). 직원이 고쳐도 바뀌지 않는다. `name` 말고는 `null`일 수 있다. 직원이 추가한 줄은 전부 `null`(`name` 제외) |
| `candidates` | 목록 | 품목 후보 최대 3개, 점수 높은 순 (`product_id`, `score` 0~1, `reason`). 맞는 상품이 없으면 `[]`. LLM이 새 상품을 만들지 않는다 |
| `uncertain_fields` | 문자열 목록 | LLM이 확신하지 못한 필드 이름. 그 필드 값(`read` 쪽)은 비어 있다 |
| `product_id` | 정수 \| null | 지금 고른 상품. 처음엔 1순위 후보, 후보가 없으면 `null` |
| `quantity` | 정수 \| null | 지금 수량 (`unit` 단위). 처음엔 읽은 수량 |
| `unit` | 문자열 \| null | 수량 단위 (읽은 값) |
| `manual_base_quantity` | 정수 \| null | 단위를 환산할 수 없을 때 직원이 직접 넣은 기준 단위 수량 (US-05) |
| `damaged` | 불리언 | 직원이 파손으로 표시했는지. `true`면 예외 건 |
| `base_quantity` | 정수 \| null | 기준 단위(개) 수량. `manual_base_quantity`가 있으면 그 값, 없으면 단위로 환산한 값, 환산할 수 없으면 `null`. 재고 반영이 끝난 건은 그때 반영한 값 |
| `order_quantity` | 정수 \| null | 같은 상품의 발주 수량. 발주에 없는 상품이면 `null` |
| `match_status` | 문자열 | 발주 대조 결과 (아래 표) |
| `rule_violations` | 문자열 목록 | 규칙 검증 실패 칸: `AMOUNT_MISMATCH`(수량×단가≠금액) · `NUMBER_NOT_IN_OCR`(OCR 글자에 없는 숫자). 비어 있으면 통과 |
| `checked` | 불리언 | 직원이 이 줄의 강조 칸(후보 여러 개·규칙 검증 실패)을 확인했는지 |

**확인할 칸 (`check_count`)** — 하나라도 남아 있으면 확정할 수 없다 (`CHECK_REQUIRED`, US-04 실패·거절)

| 상황 | 언제 생기나 | 어떻게 푸나 |
| --- | --- | --- |
| `match_status`가 `확인 필요` | 상품을 못 골랐거나, 수량이 비었거나, 단위를 환산할 수 없음 | `product_id`·`quantity`·`manual_base_quantity`를 채운다 |
| 줄의 `rule_violations`가 있고 `checked`가 `false` | 수량×단가≠금액, 또는 OCR 글자에 없는 숫자 | 줄을 고치거나(자동으로 `checked: true`) `{"checked": true}`를 보낸다 |
| 후보가 2개 이상이고 `checked`가 `false` | 품목 후보가 여러 개 | 줄을 고치거나 `{"checked": true}`를 보낸다 |
| `summary_mismatch`가 `true`이고 `summary_checked`가 `false` | 줄 금액 합이 합계와 다름 | `POST .../summary-check` |

**발주 대조 결과 (`match_status`)** — 위에서부터 먼저 걸리는 하나

| 값 | 뜻 | 확정하면 |
| --- | --- | --- |
| `확인 필요` | 상품이나 기준 단위 수량을 알 수 없어 대조하지 못함 | 확정할 수 없음 (`CHECK_REQUIRED`) |
| `파손` | 직원이 `damaged: true`로 표시함 | 예외 건 |
| `발주에 없음` | 고른 상품이 발주에 없음 | 예외 건 |
| `수량 다름` | 기준 단위 수량이 발주 수량과 다름 (같은 상품 여러 줄은 합쳐서 비교) | 예외 건 |
| `단가 다름` | 명세서 단가(기준 단위 1개당)가 상품 기준 단가와 다름. 상품마다 `price_alert_threshold_percent`를 설정했으면 그 비율 이상 '높을 때만' 다르다고 본다 (R8, 더 싸게 들어온 건 경고하지 않음). 단가를 읽지 못했거나 기준 단가가 없거나 단위를 환산할 수 없으면 비교하지 않는다 | 예외 건 |
| `일치` | 위에 모두 해당하지 않음 | — (단, `rule_violations` 미확인·`amount_over_limit`이면 여전히 예외 건) |

`rule_violations`·`summary_mismatch`는 `match_status`와는 다른 축이다. 예를 들어 금액 규칙 검증에 실패한 줄도 상품·수량이 발주와 같으면 `match_status`는 `일치`이고, 그 줄의 `rule_violations`에 `AMOUNT_MISMATCH`가 남는다 — `checked: true`가 될 때까지 `check_count`를 올리고 `all_match`를 `false`로 만든다.

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

**성공 — `200`**: 검수 건 목록 (없으면 `[]`). 판독 전 검수 건은 이런 모양이다:

```json
[
  {
    "id": 1,
    "purchase_order_id": 1,
    "status": "업로드 대기",
    "ai_draft": false,
    "exception_reason": null,
    "reject_reason": null,
    "document": null,
    "lines": [],
    "missing_order_lines": [],
    "short_order_lines": [],
    "check_count": 0,
    "all_match": false,
    "total_amount": null,
    "summary_mismatch": false,
    "summary_checked": false,
    "final_amount": 0,
    "amount_over_limit": false
  }
]
```

**실패**: 공통 실패만. 다른 매장 사용자가 부르면 `[]`다.

---

## 2. 검수 건 1건 — `GET /inspections/{inspection_id}`

검수 건 1건의 상태·판독 초안·대조 결과를 본다. 명세서를 올린 뒤 `판독 중`인 동안 화면이 이 API를 다시 불러 상태를 확인한다(폴링, STACK.md).

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
  "exception_reason": null,
  "reject_reason": null,
  "document": {
    "id": 1,
    "filename": "statement.jpg",
    "content_type": "image/jpeg",
    "uploaded_at": "2026-11-10T06:38:13.824435Z",
    "read_error": null
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
      "base_quantity": 10,
      "order_quantity": 10,
      "match_status": "일치",
      "rule_violations": [],
      "checked": false
    }
  ],
  "missing_order_lines": [],
  "short_order_lines": [],
  "check_count": 0,
  "all_match": true,
  "total_amount": 26500,
  "summary_mismatch": false,
  "summary_checked": false,
  "final_amount": 26500,
  "amount_over_limit": false
}
```

**규칙 검증에 걸린 경우** — 명세서가 `서울우유 1000ml 10개 × 2,650원 = 25,000원` / `합계 30,000원`일 때 (바뀐 부분만):

```json
{
  "total_amount": 30000,
  "summary_mismatch": true,
  "summary_checked": false,
  "lines": [
    {
      "read": { "name": "서울우유 1000ml", "spec": null, "quantity": 10, "unit": "개", "unit_price": 2650, "amount": 25000 },
      "rule_violations": ["AMOUNT_MISMATCH"],
      "checked": false,
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
      "match_status": "확인 필요"
    }
  ],
  "check_count": 1
}
```

**판독에 실패한 경우** — `업로드 대기`로 돌아가고 `document.read_error`에 안내가 남는다. 올린 사용자에게 `GET /notifications`로 보이는 알림이 간다:

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
  "lines": []
}
```

**실패**: 검수 건 1건 단위 공통 실패 (`404 INSPECTION_NOT_FOUND`).

---

## 3. 명세서 업로드 — `POST /inspections/{inspection_id}/document`

직원이 거래명세서 사진이나 PDF를 올린다 (데모 2단계, US-03). 응답은 바로 `판독 중`으로 오고, 판독은 응답을 보낸 뒤 서버가 따로 돌린다. 결과는 2번 API로 확인한다.

- `업로드 대기`에서만 올릴 수 있다. 판독에 실패해 `업로드 대기`로 돌아온 건은 다시 올릴 수 있다
- 처음 올린 직원이 그 건의 담당 직원이 된다 (사장님이 올리면 담당자는 그대로 비어 있다)

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
| 다른 직원이 담당하는 건 | `403` | `FORBIDDEN_ROLE` | 다른 직원이 담당하는 입고 건입니다 |
| 사진·PDF가 아님 (기본 설정에서 `text/plain` 포함) | `400` | `UNSUPPORTED_FILE_TYPE` | 사진(JPG·PNG·HEIC) 또는 PDF만 올릴 수 있습니다 |
| 빈 파일 | `400` | `EMPTY_FILE` | 빈 파일입니다 |
| 10MB 초과 | `400` | `FILE_TOO_LARGE` | 10MB 이하 파일만 올릴 수 있습니다 |
| `file` 필드가 없음 | `422` | — | FastAPI 기본 형식 `{"detail": [...]}` |

**판독 단계의 결과** (응답 뒤에 서버에서 일어남)

| 상황 | 검수 건 상태 | 그 밖에 |
| --- | --- | --- |
| 품목 줄을 1개 이상 찾음 | `직원 확인 대기` | 이전 초안 줄을 지우고 새로 만든다. `summary_checked`도 처음(`false`)으로 돌아간다. 판독 로그(성공)가 남는다 |
| 품목 줄을 하나도 찾지 못함, 또는 그 밖의 판독 실패 | `업로드 대기` | `read_error`에 안내. 올린 사용자에게 알림(`GET /notifications`). 판독 로그(실패)가 남는다 |

---

## 4. 판독 결과에 없는 줄 추가 — `POST /inspections/{inspection_id}/lines`

직원이 판독 결과에 없는 품목을 직접 추가한다 (US-04 인수 조건, 미팅1 질의 3 줄 누락·피드백 8 행 누락률). OCR이 읽은 값이 없으니 품목은 직원이 직접 고른다. `read`는 전부 `null`(`name` 제외)이라 정확도 지표(`GET .../metrics`)의 행 누락률에 그대로 잡힌다.

- `직원 확인 대기`에서만 된다

**요청 본문**

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `product_id` | 정수 | **예** | 이 매장에 등록된 상품 ID |
| `quantity` | 정수 | **예** | 1 이상 |
| `unit` | 문자열 \| null | 아니오 | 비우면 상품 기준 단위를 쓴다 |

```http
POST /inspections/1/lines
X-User-Id: 2
Content-Type: application/json

{ "product_id": 2, "quantity": 48 }
```

**성공 — `200`**: 바뀐 검수 건. 새 줄이 `lines`의 마지막(`line_no`는 기존 최댓값 + 1)에 추가된다.

**실패**

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| `직원 확인 대기`가 아님 | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(○○)에서는 할 수 없습니다 |
| 다른 직원이 담당하는 건 | `403` | `FORBIDDEN_ROLE` | 다른 직원이 담당하는 입고 건입니다 |
| `quantity`가 0 이하 | `400` | `INVALID_QUANTITY` | 수량은 1 이상이어야 합니다 |
| 등록되지 않은 상품 | `400` | `UNREGISTERED_PRODUCT` | 등록되지 않은 상품이 있습니다 |

---

## 5. 판독 줄 수정·확인 — `PATCH /inspections/{inspection_id}/lines/{line_id}`

직원이 품목 후보를 고르거나(후보에 없는 상품도 고를 수 있음), 수량을 고치거나, 기준 단위 수량을 직접 넣거나, 파손을 표시하거나, 강조된 칸을 확인한다 (데모 4단계, US-04·US-05). 고친 뒤의 대조 결과가 응답에 바로 반영된다. 재고는 바뀌지 않는다 (R3).

- `직원 확인 대기`에서만 된다
- **보낸 필드만 바뀐다.** `product_id`·`quantity`·`manual_base_quantity`에 `null`을 보내면 값이 지워진다
- **고치면(값이 실제로 달라지면) 그 줄의 강조 칸(후보 여러 개·규칙 검증 실패)을 확인한 것으로 본다** (`checked`가 `true`가 됨). `checked`를 직접 보내면(`false` 포함) 그 값을 따른다. 값을 채워야 풀리는 칸(품목 미선택·수량 없음·단위 환산 불가)은 `checked`로 풀리지 않는다

**요청 본문**

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `product_id` | 정수 \| null | 아니오 | 이 매장에 등록된 상품 ID |
| `quantity` | 정수 \| null | 아니오 | 1 이상. 줄의 `unit` 단위 |
| `unit` | 문자열 \| null | 아니오 | 단위를 고칠 때 |
| `manual_base_quantity` | 정수 \| null | 아니오 | 1 이상. 기준 단위 수량을 직접 넣는다. 있으면 환산보다 먼저 쓴다 (US-05) |
| `damaged` | 불리언 \| null | 아니오 | 파손 표시. `true`면 예외 건 |
| `checked` | 불리언 \| null | 아니오 | 강조된 칸을 확인했는지. 보내지 않으면(다른 필드를 함께 보냈을 때) `true`로 본다 |

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
| 다른 직원이 담당하는 건 | `403` | `FORBIDDEN_ROLE` | 다른 직원이 담당하는 입고 건입니다 |
| 이 검수 건에 없는 줄 ID | `404` | `LINE_NOT_FOUND` | 판독 줄을 찾을 수 없습니다 |
| `quantity`·`manual_base_quantity`가 0 이하 | `400` | `INVALID_QUANTITY` | 수량은 1 이상이어야 합니다 |
| 등록되지 않은 상품 (없는 ID, 다른 매장 상품 포함) | `400` | `UNREGISTERED_PRODUCT` | 등록되지 않은 상품이 있습니다 |

---

## 6. 명세서 전체 칸 확인 — `POST /inspections/{inspection_id}/summary-check`

`summary_mismatch`(줄 금액 합≠합계)를 직원이 확인했다고 표시한다 (US-04). `직원 확인 대기`에서만 된다. 요청 본문은 없다.

```http
POST /inspections/1/summary-check
X-User-Id: 2
```

**성공 — `200`**: 바뀐 검수 건 (`summary_checked`가 `true`)

**실패**: 검수 건 1건 단위 공통 실패.

---

## 7. 직원 확정 — `POST /inspections/{inspection_id}/confirm`

직원이 초안을 확인하고 [확정]을 누른다 (데모 4~5단계, US-04). 확정할 때 대조 결과를 다시 계산해서 다음 중 하나가 된다.

| 대조 결과 | 검수 건 | 재고 | 발주 건 |
| --- | --- | --- | --- |
| 일반 건 (`all_match: true`) | `재고 반영 완료` | 줄마다 `base_quantity`만큼 늘어남 | 전량 입고되면 `입고 완료` |
| 예외 건 (`all_match: false`) | `사장 승인 대기` (예외 사유 필수) | **그대로** | 그대로 (`입고 대기`) |

- 재고에 반영할 때 그 시점의 상품 환산값과 단가(명세서 단가를 기준 단위 1개당으로 바꾼 값, 읽지 못했으면 상품 기준 단가)를 줄에 따로 저장한다. 나중에 상품을 수정해도(`PATCH /products/{id}`) 이미 반영된 건의 값은 바뀌지 않는다 (US-08 인수 조건 #2)
- 예외 건 다음 단계(사장 승인·반려, 확정 취소)는 US-06-07 문서를 본다

**요청 본문** (선택)

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `reason` | 문자열 | 예외 건이면 **예** | 예외 사유. 앞뒤 공백은 지운다. 일반 건이면 무시한다 |

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
    { "base_quantity": 10, "match_status": "일치" }
  ],
  "all_match": true
}
```

이 뒤 `GET /purchase-orders/1`의 `status`는 `입고 완료`, `GET /inventory`의 P-0123 `quantity`는 `10`이다.

예외 건 확정 예시는 `US-06-07-inspections.md`를 본다.

**실패** — 상태·재고 모두 그대로다

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| `직원 확인 대기`가 아님 (예: 판독 전, 이미 확정함) | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(업로드 대기)에서는 할 수 없습니다 |
| 다른 직원이 담당하는 건 | `403` | `FORBIDDEN_ROLE` | 다른 직원이 담당하는 입고 건입니다 |
| 확인할 칸이 남아 있음 (`check_count` > 0) | `400` | `CHECK_REQUIRED` | 확인할 칸이 2개 남아 있습니다 |
| 예외 건인데 사유가 없음·빈칸·공백만 있음 | `400` | `REASON_REQUIRED` | 예외 사유를 입력해 주세요 |

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
| 한 명세서에 박스·낱개가 섞여 있을 때 구분 방법 (지금은 줄마다 적힌 단위로만 판단, 직원이 `manual_base_quantity`로 직접 넣을 수 있음) | 다음 고객 미팅 (R6) |
| 업로드·줄 수정·확정을 직원만 할 수 있는지 (지금은 담당 직원 또는 사장님만) | 팀 |
| 재고 반영 단가를 상품 기준 단가(`base_unit_price`)에도 반영할지 (지금은 바꾸지 않음) | 팀 (DATA-MODEL.md 미정) |
| 허용 파일 형식·최대 크기(10MB), 원본을 얼마나 보관할지 | 팀 |
| 상태가 맞지 않을 때 `400` 대신 `409`(충돌)를 쓸지 (US-02 명세와 같은 질문) | 팀 |
| 기기 안에서 가리기로 바꿀 때 서버 가리기를 남길지 | 팀 (STACK.md) |
| `ChangeHistory`(이 브랜치가 쓰는 이력 테이블)를 더 풍부한 변경 이력(필드별 action/old/new)으로 바꿀지 — US-07 문서 참고 | 팀 |
