# US-02 공급처 전달 전 발주 취소 API 명세

- 기능 ID: F-02 / 스토리: US-02 공급처 전달 전 발주 취소 (취소·반려 경로)
- 근거: document 레포 `docs/requirements/backlog.md` US-02, `docs/DATA-MODEL.md` 발주 건 상태, `docs/domain/03-rules-states-llm.md` 3-2
- 응답 예시는 2026-11-10에 `feat/us02-cancel-purchase-order` 코드(PR #5로 `main`에 병합됨)를 테스트 DB에 띄워 실제로 호출한 결과다
- **이 문서의 URL·오류 코드·상태 코드는 모두 `[제안]`이다.** document `docs/API.md`에 아직 US-02 항목이 없다. PM이 `API.md`에 옮기면 표시를 지운다
- 발주 저장·조회·승인·전달 완료는 `US-01-purchase-orders.md`를 본다. 공통 규칙·응답 필드도 그 문서와 같다

## 한눈에 보기

| 메서드 | URL | 언제 쓰나 | 바뀌는 상태 | 누가 |
| --- | --- | --- | --- | --- |
| `POST` | `/purchase-orders/{order_id}/cancel` | 공급처에 보내기 전, 잘못 만들었거나 필요 없어진 발주를 취소할 때 | `발주 초안` → `발주 취소` (끝 상태) | 사장님만 |

**상태 흐름**

```
발주 초안 ──cancel──▶ 발주 취소 (끝. 다른 상태로 바뀌지 않음)
    │
    └─approve──▶ 발주 확인 완료 ──mark-delivered──▶ 입고 대기   ← 이 둘에서는 취소 불가
```

- 취소된 발주에는 **입고 검수 건이 만들어지지 않고 재고도 바뀌지 않는다** (US-02 정상, R3)
- `발주 확인 완료`(승인 후, 전달 전)에서 취소할 수 있는지는 미정(backlog US-02 미확정)이라 **지금은 막아 둔다**

## 공통 규칙

US-01 명세와 같다.

| 항목 | 내용 |
| --- | --- |
| 요청·응답 형식 | JSON |
| 사용자 확인 | 요청 헤더 `X-User-Id`에 매장 사용자 ID. 서버가 그 사용자의 `store_id`·`role`을 쓴다 (API.md 공통 규칙 [제안], 임시) |
| 매장 구분 | 다른 매장 발주는 "없음"(`404`)으로 응답한다 |
| 오류 응답 형식 | `{"error": {"code": "<원인 코드>", "message": "<사람이 읽는 설명>"}}` |
| 공통 실패 | `X-User-Id` 없음 `422`, 없는 사용자 `401` (US-01 명세 '모든 API에 공통인 실패'와 같음) |

---

## 발주 취소 — `POST /purchase-orders/{order_id}/cancel`

사장님이 `발주 초안` 상태의 발주를 취소한다. `발주 취소`가 되면 끝 상태라 승인·전달 완료·다시 취소 모두 할 수 없다 (US-02). 요청 본문은 없다.

**경로 값**

| 이름 | 타입 | 설명 |
| --- | --- | --- |
| `order_id` | 정수 | 취소할 발주 건 ID (`GET /purchase-orders`의 `id`) |

**요청**

```http
POST /purchase-orders/1/cancel
X-User-Id: 1
```

**성공 — `200`**: 바뀐 발주 건

```json
{
  "id": 1,
  "store_id": 1,
  "supplier": "(가상) 유제품 공급처 A",
  "status": "발주 취소",
  "lines": [
    { "product_id": 1, "quantity": 10 }
  ]
}
```

**실패** — 상태는 그대로다 (US-02 실패·거절, 권한)

| 상황 | 상태 코드 | `error.code` | `error.message` |
| --- | --- | --- | --- |
| 직원이 요청함 | `403` | `FORBIDDEN_ROLE` | 사장님만 할 수 있습니다 |
| 발주가 없거나 다른 매장 발주 | `404` | `PURCHASE_ORDER_NOT_FOUND` | 발주를 찾을 수 없습니다 |
| `입고 대기` (공급처 전달 완료 뒤) | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(입고 대기)에서는 할 수 없습니다 |
| `발주 확인 완료` (미정이라 지금은 막음) | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(발주 확인 완료)에서는 할 수 없습니다 |
| 이미 `발주 취소` | `400` | `INVALID_STATUS_TRANSITION` | 지금 상태(발주 취소)에서는 할 수 없습니다 |

역할 검사를 먼저 하므로, 직원이 보내면 발주가 있든 없든 `403`이다.

**`공급처 전달 완료` 상태에 대해**: backlog US-02는 "`공급처 전달 완료` 또는 `입고 대기` 상태의 발주는 취소할 수 없다"고 한다. 지금 구현에서는 전달 완료 표시(`mark-delivered`) 한 요청으로 `입고 대기`까지 넘어가서 `공급처 전달 완료`에 머무는 발주가 없다. 그래서 실제로 만나는 경우는 `입고 대기`뿐이다 (US-01 명세 5번).

### 끝 상태 확인

`발주 취소`된 발주에 다른 동작을 보내도 모두 거부되고 상태는 `발주 취소` 그대로다.

| 요청 | 상태 코드 | `error.code` |
| --- | --- | --- |
| `POST /purchase-orders/{order_id}/approve` | `400` | `INVALID_STATUS_TRANSITION` |
| `POST /purchase-orders/{order_id}/mark-delivered` | `400` | `INVALID_STATUS_TRANSITION` |
| `POST /purchase-orders/{order_id}/cancel` | `400` | `INVALID_STATUS_TRANSITION` |

취소된 발주에는 입고 검수 건이 만들어지지 않는다 (실제 호출 뒤 DB에서 확인: 전달 완료한 발주에만 `업로드 대기` 검수 건 1건, 취소한 발주에는 0건).

---

## 아직 정하지 않은 것

| 항목 | 누가 정하나 |
| --- | --- |
| 이 문서의 URL·오류 코드·상태 코드를 document `docs/API.md`에 옮길지 | PM |
| `발주 확인 완료`(승인 후, 전달 전)에서도 취소할 수 있는지 (backlog US-02 미확정, 5-2는 '보내기 전'이라고만 적혀 있음) | 팀 |
| 상태가 맞지 않을 때 `400` 대신 `409`(충돌)를 쓸지 | 팀 |
| 취소 사유를 남길지 (지금 DATA-MODEL.md 발주 건에 필드 없음) | 팀 |
