# US-06·US-07 예외 건 사장 승인·반려, 변경 이력·알림 API 명세

- 기능: F-06·F-07 / 스토리: US-06 예외 건 사장 승인·반려 (취소·반려 경로), US-07 입고 변경 이력 조회, US-03 판독 실패 알림
- 근거: document 레포 `docs/requirements/backlog.md` US-03·US-06·US-07, `docs/DATA-MODEL.md` 입고 검수 건(exception_reason·reject_reason)·판독 로그·변경 이력·재고, `docs/domain/03-rules-states-llm.md` 3-2·R3
- 응답 예시는 2026-11-10에 `feat/remaining-inspection-apis` 브랜치 코드를 테스트 DB에 띄우고 `scripts/seed_demo.py` 시드로 실제로 호출한 결과다
- **이 문서의 URL·오류 코드·상태 코드는 모두 `[제안]`이다.** document `docs/API.md`에 아직 US-06·US-07 항목이 없다. PM이 `API.md`에 옮기면 표시를 지운다
- 공통 규칙, 검수 건 응답 필드, 판독·직원 확인·일반 건 확정은 `US-03-04-inspections.md`를 본다

## 한눈에 보기

| 메서드 | URL | 언제 쓰나 | 바뀌는 상태 | 누가 |
| --- | --- | --- | --- | --- |
| `POST` | `/inspections/{inspection_id}/exception-photos` | 확정 전에 예외 사진(파손 등)을 올릴 때 | 없음 | 누구나 (역할 제한 미정) |
| `POST` | `/inspections/{inspection_id}/confirm` | 예외 건을 예외 사유와 함께 확정할 때 (US-03-04 문서 7번) | `직원 확인 대기` → `사장 승인 대기` | 누구나 (역할 제한 미정) |
| `POST` | `/inspections/{inspection_id}/cancel-confirm` | 사장님이 처리하기 전에 직원이 확정을 취소할 때 | `사장 승인 대기` → `직원 확인 대기` | 누구나 (역할 제한 미정) |
| `POST` | `/inspections/{inspection_id}/approve` | 사장님이 예외 내용을 받아들일 때 | `사장 승인 대기` → `승인` → `재고 반영 완료` | **사장님만** |
| `POST` | `/inspections/{inspection_id}/reject` | 사장님이 사유를 적고 받아들이지 않을 때 | `사장 승인 대기` → `반려` | **사장님만** |
| `POST` | `/inspections/{inspection_id}/recheck` | 반려된 건을 직원이 다시 검수할 때 | `반려` → `직원 확인 대기` | 누구나 (역할 제한 미정) |
| `POST` | `/inspections/{inspection_id}/close` | 공급처에 반품·정정을 요청하고 검수 건을 닫을 때 | `반려` → `검수 종료` (끝 상태) | **사장님만** |
| `POST` | `/inspections` | `검수 종료` 뒤 다시 납품돼 같은 발주에 새 검수 건이 필요할 때 | (새로 만듦) → `업로드 대기` | 누구나 (역할 제한 미정) |
| `GET` | `/inspections/{inspection_id}/history` | 검수 건의 변경 이력과 판독 로그를 볼 때 | 없음 | 누구나 (열람 범위 미정) |
| `GET` | `/notifications` | 내 알림(판독 실패 등)을 볼 때 | 없음 | 본인 |
| `POST` | `/notifications/{notification_id}/read` | 알림을 읽음으로 표시할 때 | 없음 | 본인 |

**상태 흐름 (입고 검수 건, 이 문서 범위)**

```
직원 확인 대기 ──confirm(예외 사유)──▶ 사장 승인 대기 ──approve──▶ 승인 ──(시스템)──▶ 재고 반영 완료
      ▲   ▲                              │    │
      │   └──────── cancel-confirm ──────┘    └──reject(반려 사유)──▶ 반려 ──close──▶ 검수 종료 (끝)
      └───────────────── recheck ────────────────────────────────────┘
                                                         POST /inspections ─▶ (같은 발주에 새 검수 건) 업로드 대기
```

- **예외 건의 재고는 사장님 승인 뒤에만 바뀐다** (R3). 반려·확정 취소·검수 종료는 재고를 바꾸지 않는다
- `승인` 다음은 시스템이 바로 재고를 반영하므로 **한 요청에서 `재고 반영 완료`까지 간다.** 응답의 `status`는 `재고 반영 완료`이고, `승인`을 거친 것은 변경 이력에 남는다 (US-01 명세의 `mark-delivered`와 같은 방식)
- `재고 반영 완료`·`검수 종료`는 끝 상태다. 다른 동작은 모두 `INVALID_STATUS_TRANSITION`으로 거부된다

## 공통 규칙

`US-03-04-inspections.md` 공통 규칙과 같다. 여기서 더하는 것:

| 항목 | 내용 |
| --- | --- |
| 역할 검사 | 승인·반려·검수 종료는 역할 검사를 먼저 한다. 직원이 보내면 검수 건이 있든 없든 `403` `FORBIDDEN_ROLE` "사장님만 할 수 있습니다" (US-01·US-02와 같은 순서) |
| 사유 검사 | 예외 사유·반려 사유는 빈칸·공백만 있으면 없는 것으로 본다. 저장할 때 앞뒤 공백을 지운다 |
| 변경 이력 | 이 문서의 모든 상태 변경과 사유 입력은 변경 이력(US-07)에 한 줄씩 남는다 |

---

## 1. 예외 건 확정 — `POST /inspections/{inspection_id}/confirm`

요청·실패는 `US-03-04-inspections.md` 7번과 같다. 대조 결과에 예외(`exception_types`)가 있으면 **예외 사유가 있어야 확정되고** (US-06 실패·거절), `사장 승인 대기`가 된다. 재고는 그대로다.

```http
POST /inspections/1/confirm
X-User-Id: 2
Content-Type: application/json

{ "exception_reason": "8개만 도착, 2개는 다음 납품 예정" }
```

**성공 — `200`**: 명세서에 `서울우유 1000ml 8개 × 2,650원 = 21,200원`만 있고(발주 10개), 예외 사진 1장을 올린 뒤 확정한 결과. 사장님 화면(`GET /inspections?status=사장 승인 대기`)에도 같은 모양으로 보인다 (US-06 정상: 예외 종류·예외 사유·사진):

```json
{
  "id": 1,
  "purchase_order_id": 1,
  "status": "사장 승인 대기",
  "ai_draft": false,
  "document": {
    "id": 1,
    "filename": "s.txt",
    "content_type": "text/plain",
    "uploaded_at": "2026-11-10T06:38:15.112929Z",
    "read_error": null
  },
  "exception_photos": [
    {
      "id": 2,
      "filename": "box.jpg",
      "content_type": "image/jpeg",
      "uploaded_at": "2026-11-10T06:38:15.237015Z"
    }
  ],
  "summary": {
    "document_date": null,
    "total_amount": null,
    "line_amount_sum": 21200,
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
      "checked": false,
      "base_quantity": 8,
      "order_quantity": 10,
      "open_checks": [],
      "match_status": "수량 다름",
      "applied_unit_price": null
    }
  ],
  "missing_order_lines": [],
  "short_order_lines": [
    { "product_id": 1, "order_quantity": 10, "received_quantity": 8, "short_quantity": 2 }
  ],
  "check_count": 0,
  "exception_types": ["수량 다름"],
  "all_match": false,
  "exception_reason": "8개만 도착, 2개는 다음 납품 예정",
  "reject_reason": null
}
```

**실패 (이 문서와 관련된 것)**

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 예외 건인데 예외 사유가 없음·빈칸·공백만 있음 | `400` | `EXCEPTION_REASON_REQUIRED` | 예외 사유를 적어 주세요 |

---

## 2. 예외 사진 올리기 — `POST /inspections/{inspection_id}/exception-photos`

파손 등 예외 상황 사진을 올린다 (US-06). 여러 장 올릴 수 있고, 사장님은 `GET /inspections/{id}/files/{file_id}`로 본다. **예외 사진은 LLM에 보내지 않는다.**

- `직원 확인 대기`에서만 된다 (확정 전에 올린다)
- 예외 사진이 없어도 예외 건을 확정할 수 있다 (인수 조건에서 필수인 것은 예외 사유뿐)

**요청 본문** (`multipart/form-data`)

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `file` | 파일 | **예** | `image/jpeg`, `image/png`, `image/heic` 중 하나. 10MB 이하 `[제안]` |

```http
POST /inspections/1/exception-photos
X-User-Id: 2
Content-Type: multipart/form-data; boundary=...

file=@box.jpg (image/jpeg)
```

**성공 — `200`**: 바뀐 검수 건. `exception_photos`에 올린 사진이 더해진다 (1번 예시의 `exception_photos`와 같은 모양)

**실패** — 저장하지 않는다

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 검수 건이 없거나 다른 매장 검수 건 | `404` | `INSPECTION_NOT_FOUND` | 입고 검수 건을 찾을 수 없습니다 |
| `직원 확인 대기`가 아님 | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(사장 승인 대기)에서는 할 수 없습니다 |
| 사진이 아님 (PDF 포함) | `400` | `UNSUPPORTED_FILE_TYPE` | 사진(JPG·PNG·HEIC)만 올릴 수 있습니다 |
| 빈 파일 / 10MB 초과 | `400` | `EMPTY_FILE` / `FILE_TOO_LARGE` | 빈 파일입니다 / 10MB 이하 파일만 올릴 수 있습니다 |

---

## 3. 확정 취소 — `POST /inspections/{inspection_id}/cancel-confirm`

사장님이 처리하기 전이면 직원이 잘못 확정한 것을 취소한다. `사장 승인 대기` → `직원 확인 대기` (US-06 취소·반려). 요청 본문은 없다.

- 줄 값·예외 사유·예외 사진은 그대로 남는다. 고친 뒤 다시 확정하면 된다
- 사장님이 승인·반려한 뒤에는 할 수 없다

```http
POST /inspections/1/cancel-confirm
X-User-Id: 2
```

**성공 — `200`**: 바뀐 검수 건 (`"status": "직원 확인 대기"`, `"ai_draft": true`)

**실패** — 상태는 그대로다

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 검수 건이 없거나 다른 매장 검수 건 | `404` | `INSPECTION_NOT_FOUND` | 입고 검수 건을 찾을 수 없습니다 |
| `사장 승인 대기`가 아님 (예: 이미 승인함) | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(재고 반영 완료)에서는 할 수 없습니다 |

---

## 4. 사장님 승인 — `POST /inspections/{inspection_id}/approve`

사장님이 예외 내용을 받아들인다 (US-06 정상). 요청 본문은 없다.

- **직원이 확정한 수량·단가로 재고를 반영한다.** 단가는 명세서 단가(기준 단위 1개당)이고, 읽지 못했으면 상품 기준 단가다. 반영한 수량·환산값·단가는 줄에 따로 저장된다
- 상품의 기준 단가(`base_unit_price`)는 바꾸지 않는다 ('매입 단가'와 같은 값인지 미정)
- 발주 건은 `입고 완료`가 된다. **모자란 수량은 `short_order_lines`로 보인다** (발주 건에 미입고로 남길 필드는 미정이라 저장하지 않고 계산해서 보여 준다)
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
    { "base_quantity": 8, "order_quantity": 10, "match_status": "수량 다름", "applied_unit_price": 2650 }
  ],
  "short_order_lines": [
    { "product_id": 1, "order_quantity": 10, "received_quantity": 8, "short_quantity": 2 }
  ]
}
```

이 뒤 `GET /inventory`의 P-0123 `quantity`는 `8`, `GET /purchase-orders/1`의 `status`는 `입고 완료`였다.

**실패** — 상태·재고 모두 그대로다

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 직원이 요청함 | `403` | `FORBIDDEN_ROLE` | 사장님만 할 수 있습니다 |
| 검수 건이 없거나 다른 매장 검수 건 | `404` | `INSPECTION_NOT_FOUND` | 입고 검수 건을 찾을 수 없습니다 |
| `사장 승인 대기`가 아님 | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(○○)에서는 할 수 없습니다 |
| 확정 뒤 상품 정보(환산값 등)가 바뀌어 수량을 다시 계산할 수 없음 | `400` | `CHECK_REQUIRED` | 확인할 칸이 N개 남아 있습니다. 직원이 확정을 취소하고 다시 확인해야 합니다 |

---

## 5. 사장님 반려 — `POST /inspections/{inspection_id}/reject`

사장님이 예외 내용을 받아들이지 않는다 (US-06 취소·반려). `사장 승인 대기` → `반려`. 재고는 바뀌지 않는다.

**요청 본문**

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `reject_reason` | 문자열 | **예** | 반려 사유. 앞뒤 공백은 지운다 |

```http
POST /inspections/1/reject
X-User-Id: 1
Content-Type: application/json

{ "reject_reason": "다시 세어 주세요" }
```

**성공 — `200`**: 바뀐 검수 건 (`"status": "반려"`, `"reject_reason": "다시 세어 주세요"`, 나머지는 1번 응답과 같은 모양)

**실패** — 상태는 그대로다

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 직원이 요청함 | `403` | `FORBIDDEN_ROLE` | 사장님만 할 수 있습니다 |
| 검수 건이 없거나 다른 매장 검수 건 | `404` | `INSPECTION_NOT_FOUND` | 입고 검수 건을 찾을 수 없습니다 |
| `사장 승인 대기`가 아님 | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(○○)에서는 할 수 없습니다 |
| 반려 사유가 없음·빈칸·공백만 있음 | `400` | `REJECT_REASON_REQUIRED` | 반려 사유를 적어 주세요 |

---

## 6. 재검수 — `POST /inspections/{inspection_id}/recheck`

반려된 건을 직원이 다시 검수한다. `반려` → `직원 확인 대기` (US-06). 요청 본문은 없다. 줄 값은 그대로 남아 있어 고친 뒤 다시 확정한다. 반려 사유도 응답에 남아 있다.

```http
POST /inspections/1/recheck
X-User-Id: 2
```

**성공 — `200`**: 바뀐 검수 건 (`"status": "직원 확인 대기"`)

**실패**

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 검수 건이 없거나 다른 매장 검수 건 | `404` | `INSPECTION_NOT_FOUND` | 입고 검수 건을 찾을 수 없습니다 |
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

## 8. 새 검수 건 만들기 — `POST /inspections`

`검수 종료` 뒤 다시 납품되면 같은 발주에 새 입고 검수 건을 `업로드 대기`로 만든다 (US-06, DATA-MODEL.md 관계).

- 발주가 `입고 대기`이고, 그 발주의 검수 건이 **모두 `검수 종료`**일 때만 된다

**요청 본문**

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `purchase_order_id` | 정수 | **예** | 내 매장 발주 건 ID |

```http
POST /inspections
X-User-Id: 2
Content-Type: application/json

{ "purchase_order_id": 1 }
```

**성공 — `200`**: 새 검수 건

```json
{
  "id": 2,
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
```

**실패** — 만들지 않는다

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 발주가 없거나 다른 매장 발주 | `404` | `PURCHASE_ORDER_NOT_FOUND` | 발주를 찾을 수 없습니다 |
| 발주가 `입고 대기`가 아님 (예: `입고 완료`) | `400` | `INVALID_STATUS_TRANSITION` | 지금 발주 상태(입고 완료)에서는 할 수 없습니다 |
| `검수 종료`가 아닌 검수 건이 이미 있음 | `400` | `OPEN_INSPECTION_EXISTS` | 아직 끝나지 않은 검수 건이 있습니다 |

---

## 9. 변경 이력·판독 로그 — `GET /inspections/{inspection_id}/history`

입고 검수 건의 변경 이력을 시간순으로, 판독 로그를 판독 순서로 돌려준다 (US-07).

- **기록된 이력은 누구도 고치거나 지울 수 없다.** 고치거나 지우는 API가 없고(`PATCH`·`DELETE`는 `405`), 서버 코드에서 고치거나 지우려 해도 오류가 난다
- 열람 범위가 미정이라(backlog US-07) 지금은 같은 매장이면 누구나 볼 수 있다

**이력이 남는 때**

| `action` | `field` | `old_value` → `new_value` | 남기는 사람 (`changed_by`) |
| --- | --- | --- | --- |
| `업로드` | `document` / `status` | 파일 이름 / `업로드 대기` → `판독 중` | 올린 사용자 |
| `판독` | `line N` | (없음) → 판독 원본값 JSON (이름·규격·수량·단위·단가·금액·후보 상품 ID·불확실한 필드) | 올린 사용자 (시스템이 대신 기록) |
| `판독` | `summary` | (없음) → 작성일·합계·불확실한 필드 JSON | 올린 사용자 |
| `판독` / `판독 실패` | `status` | `판독 중` → `직원 확인 대기` / `업로드 대기` | 올린 사용자 |
| `줄 수정` | `line N <필드>`, `summary checked` | 이전 값 → 새 값 | 고친 사용자 |
| `예외 사진` | `exception_photo` | (없음) → 파일 이름 | 올린 사용자 |
| `확정` | `result` | (없음) → `일반 건` 또는 `{"예외 건": [예외 종류]}` | 확정한 사용자 |
| `확정` | `exception_reason` / `status` | 이전 사유 → 새 사유 / 상태 변경 | 확정한 사용자 |
| `확정 취소`·`재검수` | `status` | 상태 변경 | 한 사용자 |
| `승인` | `status` | `사장 승인 대기` → `승인`, `승인` → `재고 반영 완료` | 사장님 |
| `반려` | `reject_reason` / `status` | 이전 사유 → 새 사유 / `사장 승인 대기` → `반려` | 사장님 |
| `검수 종료` | `status` | `반려` → `검수 종료` | 사장님 |
| `재고 반영` | `inventory <상품 코드>` | 반영 전 재고 → 반영 후 재고 | 확정한 직원(일반 건) 또는 승인한 사장님(예외 건) |
| `검수 건 생성` | `status` | (없음) → `업로드 대기` | 만든 사용자 (8번 API로 만든 건만) |

값은 모두 문자열로 저장한다 (숫자·목록은 JSON 문자열).

```http
GET /inspections/1/history
X-User-Id: 1
```

**성공 — `200`**: 1번(예외 건 확정) → 4번(승인)까지 간 건의 실제 응답. `changes`는 12줄 중 앞 3줄만 싣고, 전체는 아래 표로 줄였다.

```json
{
  "inspection_id": 1,
  "changes": [
    {
      "id": 1,
      "changed_by": 2,
      "changed_at": "2026-11-10T06:38:15.110425Z",
      "action": "업로드",
      "field": "document",
      "old_value": null,
      "new_value": "s.txt"
    },
    {
      "id": 2,
      "changed_by": 2,
      "changed_at": "2026-11-10T06:38:15.110425Z",
      "action": "업로드",
      "field": "status",
      "old_value": "업로드 대기",
      "new_value": "판독 중"
    },
    {
      "id": 3,
      "changed_by": 2,
      "changed_at": "2026-11-10T06:38:15.116805Z",
      "action": "판독",
      "field": "line 1",
      "old_value": null,
      "new_value": "{\"name\": \"서울우유 1000ml\", \"spec\": null, \"quantity\": 8, \"unit\": \"개\", \"unit_price\": 2650, \"amount\": 21200, \"candidates\": [1], \"uncertain_fields\": []}"
    }
  ],
  "reading_logs": [
    {
      "id": 1,
      "file_id": 1,
      "succeeded": true,
      "input_tokens": 0,
      "output_tokens": 0,
      "cost": 0.0,
      "elapsed_seconds": 0.008,
      "created_at": "2026-11-10T06:38:15.116805Z"
    }
  ]
}
```

같은 응답의 `changes` 전체 (`changed_by`, `action`, `field`, `old_value` → `new_value`):

| # | 누가 | action | field | 값 |
| --- | --- | --- | --- | --- |
| 1 | 2 (직원) | 업로드 | document | → `s.txt` |
| 2 | 2 | 업로드 | status | `업로드 대기` → `판독 중` |
| 3 | 2 | 판독 | line 1 | → 판독 원본값 JSON (수량 8) |
| 4 | 2 | 판독 | summary | → `{"document_date": null, "total_amount": null, "uncertain_fields": []}` |
| 5 | 2 | 판독 | status | `판독 중` → `직원 확인 대기` |
| 6 | 2 | 예외 사진 | exception_photo | → `box.jpg` |
| 7 | 2 | 확정 | result | → `{"예외 건": ["수량 다름"]}` |
| 8 | 2 | 확정 | exception_reason | → `8개만 도착, 2개는 다음 납품 예정` |
| 9 | 2 | 확정 | status | `직원 확인 대기` → `사장 승인 대기` |
| 10 | 1 (사장님) | 승인 | status | `사장 승인 대기` → `승인` |
| 11 | 1 | 재고 반영 | inventory P-0123 | `0` → `8` |
| 12 | 1 | 승인 | status | `승인` → `재고 반영 완료` |

표의 `#`은 응답의 `id`와 같다. 같은 요청에서 생긴 줄은 `changed_at`이 같아서(예: 1·2번, 3~5번), 같은 시각이면 `id` 순서로 정렬한다.

**판독 로그 (`reading_logs[]`)** — 판독할 때마다 1줄 (재업로드하면 여러 줄)

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `file_id` | 정수 | 판독한 명세서 파일 |
| `succeeded` | 불리언 | 판독 성공 여부 |
| `input_tokens`, `output_tokens` | 정수 | LLM 입력·출력 토큰 수. 지금 정리기는 LLM을 부르지 않아 0 |
| `cost` | 숫자 | LLM 호출 비용. 통화 단위 미정, 지금은 0 |
| `elapsed_seconds` | 숫자 | 업로드부터 판독이 끝날 때(`직원 확인 대기` 또는 실패)까지 걸린 초 |
| `created_at` | 문자열 | 기록 시각 |

**실패**

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 검수 건이 없거나 다른 매장 검수 건 | `404` | `INSPECTION_NOT_FOUND` | 입고 검수 건을 찾을 수 없습니다 |

---

## 10. 알림 — `GET /notifications`, `POST /notifications/{notification_id}/read`

판독에 실패하면 명세서를 올린 사용자에게 "다시 올려 달라"는 알림이 1건 만들어진다 (US-03 실패·거절). 푸시·문자 같은 발송 방식은 미정이라, 화면이 이 API로 내 알림을 가져간다. 지금 알림이 만들어지는 경우는 판독 실패뿐이다.

### 내 알림 목록 — `GET /notifications`

| 쿼리 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `unread` | 불리언 | 아니오 | `true`면 읽지 않은 것만 |

```http
GET /notifications
X-User-Id: 2
```

**성공 — `200`**: 내 알림, 최근 것부터 (없으면 `[]`)

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `id` | 정수 | 알림 ID |
| `inspection_id` | 정수 \| null | 관련 검수 건 |
| `message` | 문자열 | 알림 내용 (판독 실패면 `read_error`와 같음) |
| `created_at` | 문자열 | 만든 시각 |
| `read_at` | 문자열 \| null | 읽음 표시한 시각. 안 읽었으면 `null` |

### 읽음 표시 — `POST /notifications/{notification_id}/read`

요청 본문은 없다. 이미 읽은 알림이면 그대로 돌려준다.

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
| 업로드·확정·확정 취소·재검수·새 검수 건 만들기를 직원만 할 수 있는지 (지금은 역할로 막지 않음) | 팀 |
| 사장님이 승인할 때 수량·단가를 고쳐서 승인할 수 있게 할지 (지금은 직원 확정값 그대로) | 팀 |
| 승인 단가를 상품 기준 단가(`base_unit_price`)에 반영할지 ('매입 단가'와 같은 값인지) | 팀 (DATA-MODEL.md 미정) |
| 모자란 수량을 발주 건에 '미입고'로 저장할 필드 (지금은 `short_order_lines`로 계산만) | 팀 (DATA-MODEL.md 미정) |
| 파손 수량을 따로 받을지 (지금은 줄에 파손 표시만 하고, 수량은 직원이 확정한 값) | 팀 |
| '평소보다 높은 단가' 판정 기준 (R8). 지금은 1원이라도 다르면 `단가 다름` | 다음 고객 미팅 |
| 변경 이력 열람 범위(사장님만인지)와 보존 기간 | 팀 (client-meeting-1 피드백 9) |
| 변경 이력 `field`를 정식 필드로 둘지 (DATA-MODEL.md 미정. 지금은 `[제안]`으로 넣음) | 팀 |
| 판독 로그 `cost`의 통화 단위 | 미정 |
| 알림 발송 방식(푸시·문자 등)과, 판독 실패 말고도 알림을 보낼지 (예: 사장 승인 대기가 생겼을 때) | 팀 |
| 사장님 검토 기기 (태블릿 또는 PC) | 다음 미팅 |
