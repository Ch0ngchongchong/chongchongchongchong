# US-06·US-07 입고 검수 API

모든 요청은 `X-User-Id` 헤더를 사용하며, 다른 매장의 검수 건은 404로 응답합니다. 기존 `POST /inspections/{id}/confirm`은 예외 건일 때 JSON `{"reason":"사유"}`를 필수로 받습니다. 일반 건은 기존처럼 본문 없이 확정할 수 있습니다. 검수 상세 응답의 `exception_reason`, `reject_reason`에서 최근 사유를 확인할 수 있습니다.

| 메서드·경로 | 권한 | 동작 |
| --- | --- | --- |
| POST `/inspections/{id}/approve` | 사장님 | 승인 대기 건의 재고와 판독 단가 반영 |
| POST `/inspections/{id}/reject` | 사장님 | `{"reason":"반려 사유"}` 필수, 반려 |
| POST `/inspections/{id}/cancel-confirmation` | 직원 | 승인 전 확정 취소 |
| POST `/inspections/{id}/reinspect` | 직원 | 반려 건을 직원 확인 대기로 변경 |
| POST `/inspections/{id}/close` | 사장님 | 반려 건 검수 종료 |
| GET `/inspections/{id}/history` | 사장님 | 변경 이력 시간순 조회 |
| GET `/inspections/{id}/reading-logs` | 사장님 | 문서별 판독 결과·시간·토큰·비용 조회 |

규칙 기반 데모 판독기는 실제 LLM을 호출하지 않으므로 토큰과 비용은 `null`입니다. 새 업로드 원본은 DB에 저장하고 OCR 처리 시 임시 파일로만 사용합니다. 앱 시작 시 `create_all`로 새 테이블을 만들 권한이 필요합니다. 기존 디스크에 저장된 문서는 종전 경로로 읽습니다.

배포 환경의 오류 로그와 실제 PostgreSQL에서의 검증이 필요합니다.

## 추가 API

- `POST /inspections/{id}/exception-photos`: 직원 확인 대기 중 `file` 사진을 업로드합니다. `GET /inspections/{id}/exception-photos`는 목록, `GET /inspections/{id}/exception-photos/{photo_id}`는 원본을 반환합니다. 같은 매장 사용자만 접근할 수 있습니다.
- 미등록 품목은 `POST /products`로 상품을 등록하고 `PATCH /inspections/{id}/lines/{line_id}`에 `product_id`를 지정합니다. 발주에 없는 상품으로 표시되며 예외 사유를 입력해 직원 확정 후 사장 승인해야 재고에 반영됩니다. 판독 단위가 잘못됐을 때도 PATCH의 `unit`으로 수정할 수 있습니다.
- `GET /purchase-orders/{id}/remaining`은 상품별 미입고 수량을 반환합니다. `POST /purchase-orders/{id}/redeliveries`는 진행 중인 검수가 없고 미입고가 남은 발주에 새 검수 건을 만듭니다. 새 건은 남은 수량을 기준으로 대조합니다.

## OpenAI 및 OCR 설정

패키지 설치 후 환경변수 `STRUCTURER=openai`, `OPENAI_API_KEY`를 설정합니다. 기본 모델은 `gpt-4o-mini`이며 `OPENAI_MODEL`로 변경할 수 있습니다. OpenAI 모드에서 `OCR_ENGINE` 기본값은 `local`이며, 서버에 Tesseract와 한국어·영어 언어 데이터(`kor`, `eng`), PDF용 Poppler(`pdftotext`, `pdftoppm`)가 필요합니다. 사진 원본은 외부에 전송하지 않고 서버에서 OCR을 수행합니다. `OCR_ENGINE=demo`는 가상 명세서를 반환하므로 테스트에만 사용합니다.

OCR 결과는 서버의 규칙 기반 마스킹을 거친 후 OpenAI Responses API로 전송됩니다. 이 마스킹은 모든 개인정보를 보장해 제거하지는 못하므로 실제 데이터 사용 전 검증과 개선이 필요합니다. 호출은 `store=false`로 설정합니다. 토큰 수는 OpenAI 사용량에서 기록합니다. 선택적으로 `OPENAI_INPUT_USD_PER_MILLION`과 `OPENAI_OUTPUT_USD_PER_MILLION`을 둘 다 설정하면 비용 추정치를 USD로 기록합니다. 캐시·요금제 차이 등을 반영하지 않은 추정치이며 미설정 시 `null`입니다. API 키는 코드나 Git에 저장하지 말고 실행 환경의 비밀값으로 설정합니다.
