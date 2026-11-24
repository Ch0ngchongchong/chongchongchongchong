# 입고 검수 — OpenAI·OCR 설정

입고 검수 API 전체(승인·반려·변경 이력 등)는 `US-06-07-exceptions-history.md`를, 업로드·판독·확정은 `US-03-04-inspections.md`를 본다. 이 문서는 실제 LLM(OpenAI)·OCR을 쓸 때의 환경변수만 다룬다.

## OpenAI 및 OCR 설정

패키지 설치 후 환경변수 `STRUCTURER=openai`, `OPENAI_API_KEY`를 설정한다. 기본 모델은 `gpt-4o-mini`이며 `OPENAI_MODEL`로 바꿀 수 있다. OpenAI 모드에서 `OCR_ENGINE` 기본값은 `local`이며, 서버에 Tesseract와 한국어·영어 언어 데이터(`kor`, `eng`), PDF용 Poppler(`pdftotext`, `pdftoppm`)가 필요하다. 사진 원본은 외부에 전송하지 않고 서버에서 OCR을 수행한다. `OCR_ENGINE=demo`는 가상 명세서를 반환하므로 테스트에만 쓴다.

OCR 결과는 서버의 규칙 기반 마스킹을 거친 뒤 OpenAI Responses API로 전송된다. 이 마스킹은 모든 개인정보를 보장해 제거하지는 못하므로 실제 데이터 사용 전 검증과 개선이 필요하다. 호출은 `store=false`로 설정한다. 토큰 수는 OpenAI 사용량에서 기록한다. 선택적으로 `OPENAI_INPUT_USD_PER_MILLION`과 `OPENAI_OUTPUT_USD_PER_MILLION`을 둘 다 설정하면 비용 추정치를 USD로 기록한다 (`GET .../reading-logs`의 `cost`). 캐시·요금제 차이 등을 반영하지 않은 추정치이며 미설정 시 `null`이다. API 키는 코드나 Git에 저장하지 말고 실행 환경의 비밀값으로 설정한다.

LLM은 줄마다 품목명·규격·수량·단위·단가·금액을 정리하고, 확신하지 못한 필드는 추측하지 않고 `null`로 두며 그 이름을 그 줄의 `uncertain_fields`에 적는다(US-03). 문서 전체 합계(`total_amount`)가 불확실하면 역시 `null`로 둔다.

새 업로드 원본은 DB에 저장하고 OCR 처리 시 임시 파일로만 사용한다. 앱 시작 시 `create_all`로 테이블을 만든다 (Alembic 도입 여부는 팀 확인 필요).

배포 환경의 오류 로그와 실제 PostgreSQL에서의 검증이 필요하다.
