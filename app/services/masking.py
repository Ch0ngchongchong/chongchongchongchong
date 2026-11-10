# LLM에 보내기 전에 민감 정보를 가린다 (데모 '꼭 짚을 말' 3번, STACK.md).
# 원본 사진은 애초에 LLM 단계로 넘기지 않고(reading.py), OCR 텍스트에서
# 거래처 담당자 이름·연락처·사업자 정보를 지운다.
# 지금은 서버 쪽에서 임시로 가린다. 기기 안에서 가리는 방식은 이후에 정한다.

import re

# 이 낱말이 들어간 줄은 통째로 뺀다 (담당자 이름처럼 패턴으로 잡기 어려운 값 때문)
_DROP_LINE_KEYWORDS = (
    "담당",
    "대표",
    "사업자",
    "등록번호",
    "주소",
    "연락처",
    "전화",
    "팩스",
    "이메일",
    "계좌",
)

_PATTERNS = (
    # 사업자등록번호 000-00-00000
    re.compile(r"\b\d{3}-\d{2}-\d{5}\b"),
    # 전화번호 010-0000-0000, 02-000-0000, 01000000000
    re.compile(r"\b0\d{1,2}[-. ]?\d{3,4}[-. ]?\d{4}\b"),
    # 이메일
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
)

MASK = "[가림]"


def mask_sensitive(text: str) -> str:
    kept = []
    for line in text.splitlines():
        if any(keyword in line for keyword in _DROP_LINE_KEYWORDS):
            continue
        for pattern in _PATTERNS:
            line = pattern.sub(MASK, line)
        kept.append(line)
    return "\n".join(kept)
