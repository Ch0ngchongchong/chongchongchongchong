# US-06·US-07 예외 건 사장 승인·반려, 변경 이력·알림 API 명세

- 기능: F-06·F-07 / 스토리: US-06 예외 건 사장 승인·반려 (취소·반려 경로), US-07 변경 이력·정확도 지표, US-03 판독 실패 알림
- 근거: document 레포 `docs/requirements/backlog.md` US-03·US-06·US-07, `docs/DATA-MODEL.md` 입고 검수 건(exception_reason·reject_reason)·판독 로그·변경 이력·재고, `docs/domain/03-rules-states-llm.md` 3-2·R3
- 공통 규칙, 검수 건 응답 필드, 판독·직원 확인·일반 건 확정은 `US-03-04-inspections.md`를 본다
- 2026-11-24 병합 조율 메모: 이 문서는 한때 `feat/r7-quantity-limit-and-amount-alert`와 `feat/remaining-inspection-apis`(신은총님) 두 브랜치로 갈라졌다. 승인·반려 흐름과 변경 이력은 이 브랜치의 설계(`ChangeHistory` 기반, 사유는 단일 `reason` 필드)를 기준으로 하고, 알림(US-03)·단위 환산 수동 입력(`manual_base_quantity`)·부족 입고(`short_order_lines`)는 신은총님 쪽에만 있던 기능이라 이 설계 위로 다시 옮겨 왔다

## 한눈에 보기

| 메서드 | URL | 언제 쓰나 | 바뀌는 상태 | 누가 |
| --- | --- | --- | --- | --- |
| `POST` | `/inspections/{inspection_id}/exception-photos` | 확정 전에 예외 사진(파손 등)을 올릴 때 | 없음 | 담당 직원 또는 사장님 |
| `GET` | `/inspections/{inspection_id}/exception-photos` | 올린 예외 사진 목록 | 없음 | 같은 매장 누구나 |
| `GET` | `/inspections/{inspection_id}/exception-photos/{photo_id}` | 예외 사진 원본 | 없음 | 같은 매장 누구나 |
| `POST` | `/inspections/{inspection_id}/confirm` | 예외 건을 사유와 함께 확정할 때 (`US-03-04-inspections.md` 7번) | `직원 확인 대기` → `사장 승인 대기` | 담당 직원 또는 사장님 |
| `POST` | `/inspections/{inspection_id}/cancel-confirmation` | 사장님이 처리하기 전에 직원이 확정을 취소할 때 | `사장 승인 대기` → `직원 확인 대기` | 담당 직원 또는 사장님 |
| `POST` | `/inspections/{inspection_id}/approve` | 사장님이 예외 내용을 받아들일 때 | `사장 승인 대기` → `재고 반영 완료` | **사장님만** |
| `POST` | `/inspections/{inspection_id}/reject` | 사장님이 사유를 적고 받아들이지 않을 때 | `사장 승인 대기` → `반려` | **사장님만** |
| `POST` | `/inspections/{inspection_id}/reinspect` | 반려된 건을 직원이 다시 검수할 때 | `반려` → `직원 확인 대기` | 담당 직원 또는 사장님 |
| `POST` | `/inspections/{inspection_id}/close` | 공급처에 반품·정정을 요청하고 검수 건을 닫을 때 | `반려` → `검수 종료` (끝 상태) | **사장님만** |
| `POST` | `/purchase-orders/{order_id}/redeliveries` | `검수 종료`·`재고 반영 완료` 건뿐이고 미입고가 남은 발주에 새 검수 건이 필요할 때 | (새로 만듦) → `업로드 대기` | 같은 매장 누구나 |
| `GET` | `/inspections/{inspection_id}/history` | 검수 건의 변경 이력을 볼 때 | 없음 | 사장님만 |
| `GET` | `/inspections/{inspection_id}/reading-logs` | 판독 로그(토큰·비용·걸린 시간)를 볼 때 | 없음 | 사장님만 |
| `GET` | `/inspections/{inspection_id}/metrics` | 판독 정확도·고친 줄 비율·행 누락률·걸린 시간을 볼 때 (US-07) | 없음 | 사장님만 |
| `GET` | `/notifications` | 내 알림(판독 실패 등)을 볼 때 | 없음 | 본인 |
| `POST` | `/notifications/{notification_id}/read` | 알림을 읽음으로 표시할 때 | 없음 | 본인 |

**상태 흐름 (입고 검수 건, 이 문서 범위)**

```
직원 확인 대기 ──confirm(사유)──▶ 사장 승인 대기 ──approve──▶ 재고 반영 완료
      ▲   ▲                           │    │
      │   └─── cancel-confirmation ───┘    └──reject(사유)──▶ 반려 ──close──▶ 검수 종료 (끝)
      └───────────── reinspect ─────────────────────────────────┘
                              POST /purchase-orders/{id}/redeliveries ─▶ (같은 발주에 새 검수 건) 업로드 대기
```

- **예외 건의 재고는 사장님 승인 뒤에만 바뀐다** (R3). 반려·확정 취소·검수 종료는 재고를 바꾸지 않는다
- **승인은 재고 반영까지 한 요청에서 끝난다** — 중간 `승인` 상태 없이 바로 `재고 반영 완료`가 된다
- `재고 반영 완료`·`검수 종료`는 끝 상태다. 다른 동작은 모두 `INVALID_STATUS_TRANSITION`으로 거부된다
- 승인·반려·확정 취소·재검수·검수 종료는 `POST /inspections/{id}/{action}` 하나의 경로로 처리한다 (`action`은 위 표의 `approve`·`reject`·`cancel-confirmation`·`reinspect`·`close`). 정의되지 않은 `action`은 `404` `NOT_FOUND` "요청한 작업을 찾을 수 없습니다"

## 공통 규칙

`US-03-04-inspections.md` 공통 규칙과 같다. 여기서 더하는 것:

| 항목 | 내용 |
| --- | --- |
| 역할 검사 | 승인·반려·검수 종료는 역할 검사를 먼저 한다. 직원이 보내면 검수 건이 있든 없든 `403` `FORBIDDEN_ROLE` "사장님만 할 수 있습니다" (US-01·US-02와 같은 순서) |
| 담당 직원 검사 | 역할 검사 다음으로 담당 직원 검사를 한다 (`US-03-04-inspections.md` 공통 규칙) |
| 사유 검사 | 확정(예외 건)·반려의 사유는 `{"reason": "..."}`로 보낸다. 빈칸·공백만 있으면 없는 것으로 본다. 저장할 때 앞뒤 공백을 지운다 |
| 변경 이력 | 이 문서의 모든 상태 변경과 사유 입력은 변경 이력(US-07, `ChangeHistory`)에 한 줄씩 남는다 |

---

## 1. 예외 건 확정 — `POST /inspections/{inspection_id}/confirm`

요청·실패는 `US-03-04-inspections.md` 7번과 같다. 대조 결과가 `all_match: false`면 **사유(`reason`)가 있어야 확정되고**, `사장 승인 대기`가 된다. 재고는 그대로다.

```http
POST /inspections/1/confirm
X-User-Id: 2
Content-Type: application/json

{ "reason": "8개만 도착, 2개는 다음 납품 예정" }
```

**성공 — `200`**: 명세서에 `서울우유 1000ml 8개 × 2,650원 = 21,200원`만 있고(발주 10개), 예외 사진 1장을 올린 뒤 확정한 결과. 사장님 화면(`GET /inspections?status=사장 승인 대기`)에도 같은 모양으로 보인다:

```json
{
  "id": 1,
  "purchase_order_id": 1,
  "status": "사장 승인 대기",
  "ai_draft": false,
  "exception_reason": "8개만 도착, 2개는 다음 납품 예정",
  "reject_reason": null,
  "document": {
    "id": 1,
    "filename": "s.txt",
    "content_type": "text/plain",
    "uploaded_at": "2026-11-10T06:38:15.112929Z",
    "read_error": null
  },
  "lines": [
    {
      "id": 1,
      "line_no": 1,
      "read": {
        "name": "서울우유 1000ml",
        "spec": null,
        "quantity": 8,
        "unit": "개",
        "unit_price": 2650,
        "amount": 21200
      },
      "candidates": [
        { "product_id": 1, "score": 1.0, "reason": "상품명이 '서울우유 1000ml'과 같아요" }
      ],
      "uncertain_fields": [],
      "product_id": 1,
      "quantity": 8,
      "unit": "개",
      "manual_base_quantity": null,
      "damaged": false,
      "base_quantity": 8,
      "order_quantity": 10,
      "match_status": "수량 다름",
      "rule_violations": [],
      "checked": false
    }
  ],
  "missing_order_lines": [],
  "short_order_lines": [
    { "product_id": 1, "order_quantity": 10, "received_quantity": 8, "short_quantity": 2 }
  ],
  "check_count": 0,
  "all_match": false,
  "total_amount": 21200,
  "summary_mismatch": false,
  "summary_checked": false,
  "final_amount": 21200,
  "amount_over_limit": false
}
```

예외 사진은 이 응답에 포함되지 않는다. 사장님은 2번 API로 따로 목록을 본다.

**실패 (이 문서와 관련된 것)**

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 예외 건인데 사유가 없음·빈칸·공백만 있음 | `400` | `REASON_REQUIRED` | 예외 사유를 입력해 주세요 |

---

## 2. 예외 사진 — `POST`/`GET /inspections/{inspection_id}/exception-photos`

파손 등 예외 상황 사진을 올린다 (US-06). 여러 장 올릴 수 있다. **예외 사진은 LLM에 보내지 않는다.**

- `직원 확인 대기`에서만 올릴 수 있다 (확정 전에 올린다)
- 예외 사진이 없어도 예외 건을 확정할 수 있다 (인수 조건에서 필수인 것은 사유뿐)
- 올리기·보기는 각각 응답 모양이 다르다 (검수 건 전체가 아니라 사진 자체를 돌려준다)

**올리기 요청 본문** (`multipart/form-data`)

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `file` | 파일 | **예** | `image/jpeg`, `image/png`, `image/heic` 중 하나. 10MB 이하 `[제안]` |

```http
POST /inspections/1/exception-photos
X-User-Id: 2
Content-Type: multipart/form-data; boundary=...

file=@box.jpg (image/jpeg)
```

**올리기 성공 — `200`**: 올린 사진 1건 (검수 건 전체가 아니다)

```json
{ "id": 2, "filename": "box.jpg", "content_type": "image/jpeg" }
```

**올리기 실패** — 저장하지 않는다

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 검수 건이 없거나 다른 매장 검수 건 | `404` | `INSPECTION_NOT_FOUND` | 입고 검수 건을 찾을 수 없습니다 |
| 다른 직원이 담당하는 건 | `403` | `FORBIDDEN_ROLE` | 다른 직원이 담당하는 입고 건입니다 |
| `직원 확인 대기`가 아님 | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(사장 승인 대기)에서는 할 수 없습니다 |
| 사진이 아님 (PDF 포함) | `400` | `UNSUPPORTED_FILE_TYPE` | 사진만 올릴 수 있습니다 |
| 빈 파일 / 10MB 초과 | `400` | `INVALID_FILE_SIZE` | 사진은 10MB 이하이어야 합니다 |

**목록 — `GET /inspections/{inspection_id}/exception-photos`**

```json
[
  { "id": 2, "filename": "box.jpg", "content_type": "image/jpeg", "uploaded_at": "2026-11-10T06:38:15.237015Z" }
]
```

**원본 — `GET /inspections/{inspection_id}/exception-photos/{photo_id}`**: 파일 내용 그대로. 없으면 `404` `PHOTO_NOT_FOUND` "사진을 찾을 수 없습니다"

---

## 3. 확정 취소 — `POST /inspections/{inspection_id}/cancel-confirmation`

사장님이 처리하기 전이면 직원이 잘못 확정한 것을 취소한다. `사장 승인 대기` → `직원 확인 대기` (US-06 취소·반려). 요청 본문은 없다.

- 줄 값·예외 사유·예외 사진은 그대로 남는다. 고친 뒤 다시 확정하면 된다
- 사장님이 승인·반려한 뒤에는 할 수 없다

```http
POST /inspections/1/cancel-confirmation
X-User-Id: 2
```

**성공 — `200`**: 바뀐 검수 건 (`"status": "직원 확인 대기"`, `"ai_draft": true`)

**실패** — 상태는 그대로다

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 검수 건이 없거나 다른 매장 검수 건 | `404` | `INSPECTION_NOT_FOUND` | 입고 검수 건을 찾을 수 없습니다 |
| 직원이 담당이 아님 | `403` | `FORBIDDEN_ROLE` | 다른 직원이 담당하는 입고 건입니다 |
| `사장 승인 대기`가 아님 (예: 이미 승인함) | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(재고 반영 완료)에서는 할 수 없습니다 |

---

## 4. 사장님 승인 — `POST /inspections/{inspection_id}/approve`

사장님이 예외 내용을 받아들인다 (US-06 정상). 요청 본문은 없다.

- **직원이 확정한 수량·단가로 바로 재고를 반영한다** (한 요청에서 `재고 반영 완료`까지 간다). 단가는 명세서 단가(기준 단위 1개당)이고, 읽지 못했으면 상품 기준 단가다. 반영한 수량·환산값·단가는 줄에 따로 저장된다
- 상품의 기준 단가(`base_unit_price`)는 바꾸지 않는다 ('매입 단가'와 같은 값인지 미정)
- 전량 입고되면 발주가 `입고 완료`로 바뀐다. **모자란 수량은 `short_order_lines`로 보이며**, `입고 대기`에서 `POST /purchase-orders/{id}/redeliveries`로 새 재납품 검수 건을 만들 수 있다
- 발주에 없는 상품 줄도 승인하면 재고에 더해진다. 파손 줄은 직원이 확정한 수량(`base_quantity`) 그대로 더해진다

```http
POST /inspections/1/approve
X-User-Id: 1
```

**성공 — `200`**: 1번 예시를 승인한 결과. 1번 응답에서 아래만 다르다:

```json
{
  "status": "재고 반영 완료",
  "lines": [
    { "base_quantity": 8, "order_quantity": 10, "match_status": "수량 다름" }
  ],
  "short_order_lines": [
    { "product_id": 1, "order_quantity": 10, "received_quantity": 8, "short_quantity": 2 }
  ]
}
```

이 뒤 `GET /inventory`의 P-0123 `quantity`는 `8`, `GET /purchase-orders/1`의 `status`는 `입고 대기`다.

**실패** — 상태·재고 모두 그대로다

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 직원이 요청함 | `403` | `FORBIDDEN_ROLE` | 사장님만 할 수 있습니다 |
| 검수 건이 없거나 다른 매장 검수 건 | `404` | `INSPECTION_NOT_FOUND` | 입고 검수 건을 찾을 수 없습니다 |
| `사장 승인 대기`가 아님 | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(○○)에서는 할 수 없습니다 |
| 확정 뒤 상품 정보(환산값 등)가 바뀌어 수량을 다시 계산할 수 없음 | `400` | `CHECK_REQUIRED` | 확인이 필요한 항목이 있습니다 |

---

## 5. 사장님 반려 — `POST /inspections/{inspection_id}/reject`

사장님이 예외 내용을 받아들이지 않는다 (US-06 취소·반려). `사장 승인 대기` → `반려`. 재고는 바뀌지 않는다.

**요청 본문**

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `reason` | 문자열 | **예** | 반려 사유. 앞뒤 공백은 지운다 |

```http
POST /inspections/1/reject
X-User-Id: 1
Content-Type: application/json

{ "reason": "다시 세어 주세요" }
```

**성공 — `200`**: 바뀐 검수 건 (`"status": "반려"`, `"reject_reason": "다시 세어 주세요"`, 나머지는 1번 응답과 같은 모양)

**실패** — 상태는 그대로다

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 직원이 요청함 | `403` | `FORBIDDEN_ROLE` | 사장님만 할 수 있습니다 |
| 검수 건이 없거나 다른 매장 검수 건 | `404` | `INSPECTION_NOT_FOUND` | 입고 검수 건을 찾을 수 없습니다 |
| `사장 승인 대기`가 아님 | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(○○)에서는 할 수 없습니다 |
| 반려 사유가 없음·빈칸·공백만 있음 | `400` | `REASON_REQUIRED` | 반려 사유를 입력해 주세요 |

---

## 6. 재검수 — `POST /inspections/{inspection_id}/reinspect`

반려된 건을 직원이 다시 검수한다. `반려` → `직원 확인 대기` (US-06). 요청 본문은 없다. 줄 값은 그대로 남아 있어 고친 뒤 다시 확정한다. 반려 사유도 응답에 남아 있다.

```http
POST /inspections/1/reinspect
X-User-Id: 2
```

**성공 — `200`**: 바뀐 검수 건 (`"status": "직원 확인 대기"`)

**실패**

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 검수 건이 없거나 다른 매장 검수 건 | `404` | `INSPECTION_NOT_FOUND` | 입고 검수 건을 찾을 수 없습니다 |
| 직원이 담당이 아님 | `403` | `FORBIDDEN_ROLE` | 다른 직원이 담당하는 입고 건입니다 |
| `반려`가 아님 (예: `검수 종료`) | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(검수 종료)에서는 할 수 없습니다 |

---

## 7. 검수 종료 — `POST /inspections/{inspection_id}/close`

사장님이 공급처에 반품·수량 누락·단가 정정을 알리고 반려된 검수 건을 닫는다. `반려` → `검수 종료` (끝 상태, US-06). 요청 본문은 없다. 공급처에 알리는 일은 사장님이 직접 한다 (시스템이 보내지 않음).

- `검수 종료`된 건은 다시 열 수 없다. 다시 납품되면 8번 API로 새 검수 건을 만든다
- 발주 건은 `입고 대기` 그대로다

```http
POST /inspections/1/close
X-User-Id: 1
```

**성공 — `200`**: 바뀐 검수 건 (`"status": "검수 종료"`)

**실패**

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 직원이 요청함 | `403` | `FORBIDDEN_ROLE` | 사장님만 할 수 있습니다 |
| 검수 건이 없거나 다른 매장 검수 건 | `404` | `INSPECTION_NOT_FOUND` | 입고 검수 건을 찾을 수 없습니다 |
| `반려`가 아님 | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(○○)에서는 할 수 없습니다 |

---

## 8. 새 검수 건 만들기(재납품) — `POST /purchase-orders/{order_id}/redeliveries`

`검수 종료`(또는 이미 `재고 반영 완료`)된 건뿐이고, 아직 미입고 수량이 남은 발주에 새 입고 검수 건을 `업로드 대기`로 만든다 (US-06).

- 발주가 `입고 대기`여야 한다
- 그 발주의 모든 검수 건이 `검수 종료` 또는 `재고 반영 완료`여야 한다 (하나라도 진행 중이면 안 됨)
- 미입고 수량이 하나도 없으면(이미 전량 입고) 만들 수 없다

요청 본문은 없다.

```http
POST /purchase-orders/1/redeliveries
X-User-Id: 2
```

**성공 — `200`**: 검수 건 전체가 아니라 요약만 돌려준다

```json
{ "inspection_id": 2, "status": "업로드 대기" }
```

**실패** — 만들지 않는다

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 발주가 없거나 다른 매장 발주 | `404` | `PURCHASE_ORDER_NOT_FOUND` | 발주를 찾을 수 없습니다 |
| 발주가 `입고 대기`가 아님 | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(○○)에서는 할 수 없습니다 |
| 진행 중인(끝나지 않은) 검수 건이 있음 | `400` | `INSPECTION_IN_PROGRESS` | 진행 중인 검수가 있습니다 |
| 미입고 수량이 없음 | `400` | `NO_REMAINING_QUANTITY` | 미입고 수량이 없습니다 |

---

## 9. 변경 이력 — `GET /inspections/{inspection_id}/history`

입고 검수 건의 변경 이력을 시간순으로 돌려준다 (US-07). 판독 로그는 10번 API를 따로 본다.

- 같은 매장의 사장님만 조회할 수 있다
- 응답은 **목록**이다 (`{"changes": [...]}`처럼 감싸지 않는다)

**필드**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `id` | 정수 | 이력 ID |
| `changed_by` | 정수 \| null | 변경한 사용자. 판독처럼 시스템이 한 일은 그 일을 일으킨 사용자로 남긴다. `null`은 아직 없음 |
| `changed_at` | 문자열 | 기록 시각 |
| `kind` | 문자열 | 무엇을 했는지 (아래 표) |
| `old_value` | 객체 \| null | 바뀌기 전 값 (JSON, 문자열로 바꾸지 않음) |
| `new_value` | 객체 \| null | 바뀐 뒤 값 (JSON) |

**이력이 남는 때 (`kind`)**

| `kind` | `old_value` → `new_value` | 남기는 사람 |
| --- | --- | --- |
| `판독 원본` | (없음) → 판독 원본값(이름·규격·수량·단위·단가·금액) | (시스템, `changed_by: null`) |
| `직원이 추가한 줄` | (없음) → 추가한 줄 정보 | 추가한 직원 |
| `직원 수정` | 필드별 이전 값 → 새 값 | 고친 사용자 |
| `합계 확인` | `summary_checked` false → true | 확인한 사용자 |
| `직원 확정` | `status`(`직원 확인 대기`) → 새 상태, `reason` | 확정한 사용자 |
| `재고 반영` | `product_id`/`quantity` | 확정한 직원(일반 건) 또는 승인한 사장님(예외 건) |
| `예외 사진 추가` | (없음) → `photo_id` | 올린 사용자 |
| `approve`/`reject`/`cancel-confirmation`/`reinspect`/`close` | `status` 이전 → 새 상태, (반려면) `reason` | 처리한 사용자 |

```http
GET /inspections/1/history
X-User-Id: 1
```

**성공 — `200`** (일부):

```json
[
  {
    "id": 1,
    "changed_by": null,
    "changed_at": "2026-11-10T06:38:15.110425Z",
    "kind": "판독 원본",
    "old_value": null,
    "new_value": { "line_no": 1, "name": "서울우유 1000ml", "quantity": 8, "unit": "개", "unit_price": 2650, "amount": 21200 }
  },
  {
    "id": 2,
    "changed_by": 2,
    "changed_at": "2026-11-10T06:38:20.0Z",
    "kind": "직원 확정",
    "old_value": { "status": "직원 확인 대기" },
    "new_value": { "status": "사장 승인 대기", "reason": "8개만 도착, 2개는 다음 납품 예정" }
  },
  {
    "id": 3,
    "changed_by": 1,
    "changed_at": "2026-11-10T06:38:25.0Z",
    "kind": "approve",
    "old_value": { "status": "사장 승인 대기" },
    "new_value": { "status": "재고 반영 완료", "reason": null }
  }
]
```

**실패**

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 검수 건이 없거나 다른 매장 검수 건 | `404` | `INSPECTION_NOT_FOUND` | 입고 검수 건을 찾을 수 없습니다 |
| 직원이 요청함 | `403` | `FORBIDDEN_ROLE` | 사장님만 조회할 수 있습니다 |

---

## 10. 판독 로그 — `GET /inspections/{inspection_id}/reading-logs`

판독할 때마다 1줄 (재업로드하면 여러 줄). 사장님만 본다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `id` | 정수 | 로그 ID |
| `document_id` | 정수 | 판독한 명세서 파일 |
| `input_tokens`, `output_tokens` | 정수 \| null | LLM 입력·출력 토큰 수. 규칙 기반 정리기는 LLM을 부르지 않아 `null` |
| `cost` | 숫자 \| null | LLM 호출 비용 추정치. 통화 단위 미정, 비용 환경변수 미설정이면 `null` |
| `elapsed_seconds` | 숫자 | 업로드부터 판독이 끝날 때(`직원 확인 대기` 또는 실패)까지 걸린 초 |
| `outcome` | 문자열 | `성공` 또는 `실패` |

```json
[
  {
    "id": 1,
    "document_id": 1,
    "input_tokens": null,
    "output_tokens": null,
    "cost": null,
    "elapsed_seconds": 0.008,
    "outcome": "성공"
  }
]
```

**실패**: 9번과 같음 (`INSPECTION_NOT_FOUND`, 직원이면 `FORBIDDEN_ROLE` "사장님만 조회할 수 있습니다").

---

## 11. 정확도 지표 — `GET /inspections/{inspection_id}/metrics`

판독 원본값과 직원 확정값을 비교한 필드별 정확도·고친 줄 비율·행 누락률·업로드~확정 시간을 본다 (US-07, 미팅1 피드백 8). 사장님만 본다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `line_count` | 정수 | 줄 수 |
| `field_accuracy` | 객체 | `품목`·`수량`·`단위`·`단가`·`금액`별 정확도(0~1). 줄이 없으면 `null`. 단가·금액은 아직 직원이 고칠 수 있는 칸이 아니라 항상 `1.0` |
| `corrected_line_ratio` | 숫자 \| null | 품목·수량·단위 중 하나라도 고친 줄의 비율 |
| `added_line_ratio` | 숫자 \| null | 직원이 추가한 줄(`POST .../lines`)의 비율 — 행 누락률 |
| `upload_to_confirm_seconds` | 숫자 \| null | 업로드부터 직원 확정까지 걸린 초. 아직 확정 전이면 `null` |

```json
{
  "line_count": 1,
  "field_accuracy": { "품목": 1.0, "수량": 1.0, "단위": 1.0, "단가": 1.0, "금액": 1.0 },
  "corrected_line_ratio": 0.0,
  "added_line_ratio": 0.0,
  "upload_to_confirm_seconds": 5.2
}
```

**실패**: 9번과 같음.

---

## 12. 알림 — `GET /notifications`, `POST /notifications/{notification_id}/read`

판독에 실패하면 명세서를 올린 사용자에게 "다시 올려 달라"는 알림이 1건 만들어진다 (US-03 실패·거절). 푸시·문자 같은 발송 방식은 미정이라, 화면이 이 API로 내 알림을 가져간다. 지금 알림이 만들어지는 경우는 판독 실패뿐이다.

### 내 알림 목록 — `GET /notifications`

| 쿼리 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `unread` | 불리언 | 아니오 | `true`면 읽지 않은 것만 |

```http
GET /notifications
X-User-Id: 2
```

**성공 — `200`**: 내 알림, `id` 순서 (없으면 `[]`)

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `id` | 정수 | 알림 ID |
| `inspection_id` | 정수 \| null | 관련 검수 건 |
| `message` | 문자열 | 알림 내용 (판독 실패면 `read_error`와 같음) |
| `created_at` | 문자열 | 만든 시각 |
| `read_at` | 문자열 \| null | 읽음 표시한 시각. 안 읽었으면 `null` |

### 읽음 표시 — `POST /notifications/{notification_id}/read`

요청 본문은 없다. 이미 읽은 알림이면 그대로 돌려준다. 다른 사람의 알림이면 없는 것과 똑같이 다룬다.

```http
POST /notifications/1/read
X-User-Id: 2
```

**성공 — `200`**: 알림 1건

```json
{
  "id": 1,
  "inspection_id": 1,
  "message": "명세서에서 품목 줄을 찾지 못했습니다. 명세서를 다시 올려 주세요",
  "created_at": "2026-11-10T06:38:16.488783Z",
  "read_at": "2026-11-10T06:38:16.629579Z"
}
```

**실패**

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 알림이 없거나 다른 사람의 알림 | `404` | `NOTIFICATION_NOT_FOUND` | 알림을 찾을 수 없습니다 |

---

## 아직 정하지 않은 것

| 항목 | 누가 정하나 |
| --- | --- |
| 이 문서의 URL·오류 코드·상태 코드를 document `docs/API.md`에 옮길지 | PM |
| 사장님이 승인할 때 수량·단가를 고쳐서 승인할 수 있게 할지 (지금은 직원 확정값 그대로) | 팀 |
| 승인 단가를 상품 기준 단가(`base_unit_price`)에 반영할지 ('매입 단가'와 같은 값인지) | 팀 (DATA-MODEL.md 미정) |
| 모자란 수량을 발주 건에 '미입고'로 저장할 필드 (지금은 `short_order_lines`로 계산만) | 팀 (DATA-MODEL.md 미정) |
| 파손 수량을 따로 받을지 (지금은 줄에 파손 표시만 하고, 수량은 직원이 확정한 값) | 팀 |
| 변경 이력 열람 범위(사장님만인지)와 보존 기간 | 팀 (client-meeting-1 피드백 9) |
| `ChangeHistory`를 필드별 action/old/new 이력(문자열 값)으로 바꿀지 — 신은총님 쪽 설계였다. 두 설계의 장단점(JSON 객체 그대로 vs 필드별 조회 용이성)을 팀이 비교해 정한다 | 팀 |
| 판독 로그 `cost`의 통화 단위 | 미정 |
| 알림 발송 방식(푸시·문자 등)과, 판독 실패 말고도 알림을 보낼지 (예: 사장 승인 대기가 생겼을 때) | 팀 |
| 사장님 검토 기기 (태블릿 또는 PC) | 다음 미팅 |
