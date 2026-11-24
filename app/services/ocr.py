# OCR 단계: 명세서 원본(사진·PDF)에서 글자를 읽는다.
# LLM은 글자를 읽지 않는다. 글자는 여기서만 읽고, LLM 쪽에는 가린 텍스트만 넘긴다.
#
# 어떤 OCR 엔진을 쓸지는 아직 정하지 않았다 (STACK.md 미정).
# 지금은 환경변수 OCR_ENGINE으로 고르며, 데모용 `demo` 엔진만 있다.
#  - text/plain 파일을 올리면 그 내용을 OCR 결과로 쓴다 (테스트·리허설용)
#  - 사진·PDF를 올리면 시드 값으로 만든 가상 명세서 텍스트를 돌려준다
#    (실제 OCR이 붙기 전까지 첫 데모를 돌리기 위한 임시 동작이다)
# 실제 엔진을 붙일 때는 OcrEngine을 구현하고 get_ocr_engine()에 추가한다.

import os
from pathlib import Path
from typing import Protocol


class OcrError(Exception):
    """글자를 읽지 못했을 때. 검수 건은 `업로드 대기`로 돌아간다 (US-03)."""


class OcrEngine(Protocol):
    def read_text(self, path: Path, content_type: str) -> str: ...


# 시드 #2·#4로 만든 가상 거래명세서 (실제 개인정보·사업자 정보 없음).
# 가리기 단계가 동작하는 것을 보이기 위해 가상 연락처 줄을 일부러 넣어 두었다.
DEMO_STATEMENT_TEXT = """\
거래명세서
공급자 (가상) 유제품 공급처 A
사업자등록번호 000-00-00000
담당자 홍길동 연락처 010-0000-0000
품목 수량 단가 금액
서울우유 1000ml 10개 × 2,650원 = 26,500원
합계 26,500원
"""


class DemoOcr:
    def read_text(self, path: Path, content_type: str) -> str:
        if content_type.startswith("text/"):
            try:
                return path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise OcrError("글자를 읽을 수 없는 파일입니다") from exc
        return DEMO_STATEMENT_TEXT


def get_ocr_engine() -> OcrEngine:
    name = os.environ.get(
        "OCR_ENGINE", "local" if os.environ.get("STRUCTURER") == "openai" else "demo"
    )
    if name == "demo":
        return DemoOcr()
    if name == "local":
        return LocalOcr()
    raise RuntimeError(f"알 수 없는 OCR_ENGINE입니다: {name}")


class LocalOcr:
    """서버의 Tesseract와 Poppler로 원본을 외부에 전송하지 않고 읽는다."""

    def read_text(self, path: Path, content_type: str) -> str:
        import subprocess
        import tempfile

        if content_type == "text/plain":
            return DemoOcr().read_text(path, content_type)
        try:
            with tempfile.TemporaryDirectory() as directory:
                if content_type == "application/pdf":
                    extracted = subprocess.run(
                        ["pdftotext", "-layout", str(path), "-"],
                        capture_output=True,
                        text=True,
                        check=True,
                        timeout=45,
                    ).stdout
                    if extracted.strip():
                        return extracted
                    prefix = str(Path(directory) / "page")
                    subprocess.run(
                        ["pdftoppm", "-png", "-r", "200", str(path), prefix],
                        capture_output=True,
                        check=True,
                        timeout=90,
                    )
                    images = sorted(Path(directory).glob("page-*.png"))
                else:
                    images = [path]
                if not images:
                    raise OcrError("명세서 페이지를 읽을 수 없습니다")
                # 비교 실험(이슈 #31·#33) 결과: psm 기본값(3, 자동 레이아웃 분석)은
                # 표 양식에서 수량 칸을 통째로 놓치는 일이 있었다. psm 4(여러 줄의
                # 한 단만 있다고 가정)로 바꾸면 그 수량 칸은 살아나지만, 다른 표본
                # 하나에서 줄이 합쳐지는 손해가 있었다 — 어느 쪽도 완벽하지 않다.
                # 칸이 통째로 비는 쪽이 뒤 단계(LLM)에서 되살릴 수 없어 더 나쁘다고
                # 보고 4를 기본값으로 뒀다. 값을 바꾼 뒤에는 run_compare.py로 다시
                # 돌려 수치로 확인한다.
                psm = os.environ.get("OCR_TESSERACT_PSM", "4")
                return "\n".join(
                    subprocess.run(
                        [
                            "tesseract",
                            str(image),
                            "stdout",
                            "-l",
                            "kor+eng",
                            "--psm",
                            psm,
                        ],
                        capture_output=True,
                        text=True,
                        check=True,
                        timeout=90,
                    ).stdout
                    for image in images
                )
        except (OSError, subprocess.SubprocessError) as exc:
            raise OcrError("서버 OCR 처리에 실패했습니다") from exc
