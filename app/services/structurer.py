# LLM 단계: OCR이 읽은(그리고 가린) 텍스트를 표로 정리하고 품목 후보를 붙인다.
# LLM이 맡는 일은 두 가지뿐이다 (데모 '꼭 짚을 말' 2번).
#  1) 서식 정리: 줄마다 품목명·수량·단위·단가·금액으로 나눈다
#  2) 품목 후보: 매장 상품 중 최대 3개, 고른 이유와 함께
# LLM은 재고·검수 건 상태를 바꾸지 않는다. 결과는 '초안'으로만 저장된다 (R3).
#
# 어떤 LLM을 쓸지는 아직 정하지 않았다. 지금은 환경변수 STRUCTURER로 고르며,
# 규칙 기반 `rule` 구현만 있다 (LLM 자리에 들어가는 임시 구현).
# 실제 LLM을 붙일 때는 Structurer를 구현하고 get_structurer()에 추가한다.
# 이 인터페이스는 가린 텍스트와 상품 기준 정보만 받는다. 원본 파일은 받지 않는다.

import os
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Protocol

MAX_CANDIDATES = 3
MIN_SCORE = 0.5


@dataclass(frozen=True)
class ProductRef:
    """후보를 고를 때 쓰는 상품 기준 정보 (US-08). 민감 정보는 없다."""

    id: int
    product_code: str
    name: str | None
    spec: str | None


@dataclass
class Candidate:
    product_id: int
    score: float
    reason: str


@dataclass
class DraftLine:
    name: str
    quantity: int | None
    unit: str | None
    unit_price: int | None
    amount: int | None
    candidates: list[Candidate] = field(default_factory=list)


class Structurer(Protocol):
    def structure(
        self, masked_text: str, products: list[ProductRef]
    ) -> list[DraftLine]: ...


# 예: "서울우유 1000ml 10개 × 2,650원 = 26,500원"
_LINE = re.compile(
    r"^(?P<name>.+?)\s+"
    r"(?P<qty>\d[\d,]*)\s*(?P<unit>[^\s\d×xX*=]+)?\s*"
    r"[×xX*]\s*(?P<price>\d[\d,]*)\s*원?"
    r"(?:\s*=\s*(?P<amount>\d[\d,]*)\s*원?)?\s*$"
)


def _to_int(value: str | None) -> int | None:
    return int(value.replace(",", "")) if value else None


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _candidates(name: str, products: list[ProductRef]) -> list[Candidate]:
    target = _normalize(name)
    found = []
    for product in products:
        if _normalize(product.product_code) in target:
            found.append(
                Candidate(
                    product.id, 1.0, f"상품 코드 {product.product_code}가 적혀 있어요"
                )
            )
            continue
        if not product.name:
            continue
        product_name = _normalize(product.name)
        if product_name == target:
            found.append(
                Candidate(product.id, 1.0, f"상품명이 '{product.name}'과 같아요")
            )
            continue
        score = SequenceMatcher(None, target, product_name).ratio()
        if product.spec and _normalize(product.spec) in target:
            score = min(score + 0.1, 0.99)
        if score >= MIN_SCORE:
            found.append(
                Candidate(
                    product.id,
                    round(score, 2),
                    f"상품명이 '{product.name}'과 비슷해요 (유사도 {score:.2f})",
                )
            )
    found.sort(key=lambda c: (-c.score, c.product_id))
    return found[:MAX_CANDIDATES]


class RuleBasedStructurer:
    def structure(
        self, masked_text: str, products: list[ProductRef]
    ) -> list[DraftLine]:
        lines = []
        for raw in masked_text.splitlines():
            match = _LINE.match(raw.strip())
            if match is None:
                continue  # 머리글·합계 같은 줄
            name = match["name"].strip()
            lines.append(
                DraftLine(
                    name=name,
                    quantity=_to_int(match["qty"]),
                    unit=match["unit"],
                    unit_price=_to_int(match["price"]),
                    amount=_to_int(match["amount"]),
                    candidates=_candidates(name, products),
                )
            )
        return lines


def get_structurer() -> Structurer:
    name = os.environ.get("STRUCTURER", "rule")
    if name == "rule":
        return RuleBasedStructurer()
    raise RuntimeError(f"알 수 없는 STRUCTURER입니다: {name}")
