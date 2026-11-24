"""실험 전용 규칙 방식: 표 양식도 읽는 OCR+규칙 (이슈 #36)

서버의 `RuleBasedStructurer`는 `품목 N박스 × 단가 = 금액` 한 줄 형식만 읽는다.
비교를 공정하게 하려고, 공급처마다 템플릿을 만들지 않는 **일반 규칙 하나**를 더한다.
  1. 머리글 줄: 열 이름 사전(아래 COLUMNS)으로 열 순서를 알아낸다
  2. 그 아래 줄: 칸(공백 두 칸 이상)으로 나눠, 칸 수가 머리글과 같으면 품목 줄로 읽는다
  3. 머리글이 없으면 서버와 같은 한 줄 형식(`_LINE`)으로 읽는다
품목 후보는 서버와 같은 `_candidates()`를 쓴다. 서버 코드는 고치지 않는다.
"""

import re

from app.services.structurer import (
    _LINE,
    DraftLine,
    _candidates,
    _to_int,
)

# 열 이름 사전 (앞에 있는 것부터 확인). 공급처별이 아니라 거래명세서에 흔한 열 이름
COLUMNS = [
    ("code", ("코드", "품번")),
    ("unit_price", ("단가",)),
    ("quantity", ("수량",)),
    ("unit", ("단위",)),
    ("name", ("품명", "품목", "상품")),  # '품목 / 규격'처럼 합쳐진 열은 품명으로 본다
    ("spec", ("규격", "포장", "용량")),
    ("amount", ("금액", "공급가")),
]
TOTAL_WORDS = ("합계", "총액", "총 금액", "총금액", "청구 금액", "청구금액")
DATE = re.compile(
    r"(?P<y>20\d{2})\s*(?:[-./]|년)\s*(?P<m>\d{1,2})\s*(?:[-./]|월)\s*(?P<d>\d{1,2})"
)
NUMBER = re.compile(r"\d[\d,]*")
CELL_SPLIT = re.compile(r"\s{2,}|\t|\|")
QTY_WITH_UNIT = re.compile(r"^(?P<qty>\d[\d,]*)\s*(?P<unit>[^\d\s][^\s]*)?$")
HEADER_UNIT = re.compile(r"\((?P<unit>[^)]+)\)")


def _cells(line):
    return [c.strip() for c in CELL_SPLIT.split(line.strip()) if c.strip()]


def _column(cell):
    lowered = cell.lower()
    for key, words in COLUMNS:
        if any(word in lowered for word in words):
            return key
    return None


def _header(line):
    """열 이름이 3개 이상이고 그중에 품명과 금액(또는 단가)이 있으면 머리글로 본다."""
    cells = _cells(line)
    keys = [_column(c) for c in cells]
    found = {k for k in keys if k}
    if len(found) >= 3 and "name" in found and found & {"amount", "unit_price"}:
        unit = next((m["unit"] for c in cells if (m := HEADER_UNIT.search(c))), None)
        return keys, unit
    return None


def _number(cell):
    found = NUMBER.search(cell or "")
    return _to_int(found.group()) if found else None


def _total(line):
    text = line.strip()
    if any(text.startswith(word) for word in TOTAL_WORDS):
        numbers = NUMBER.findall(text)
        return _to_int(numbers[-1]) if numbers else None
    return None


class TableRuleStructurer:
    """서버 structurer와 같은 모양: structure()는 줄 목록을 돌려주고 합계는
    `total_amount` 속성에 둔다. 작성일도 `document_date` 속성에 둔다 (실험용)."""

    def __init__(self):
        self.total_amount = None
        self.document_date = None

    def structure(self, masked_text, products):
        lines, total, date, header = [], None, None, None
        for raw in masked_text.splitlines():
            text = raw.strip()
            if not text:
                continue
            if date is None and (found := DATE.search(text)):
                date = f"{found['y']}-{int(found['m']):02d}-{int(found['d']):02d}"
            if (value := _total(text)) is not None:
                if total is None or text.startswith("합계"):
                    total = value
                continue
            if header is None and (found_header := _header(text)):
                header = found_header
                continue
            if header is not None:
                line = self._table_line(text, *header, products)
            else:
                line = self._one_line(text, products)
            if line is not None:
                lines.append(line)
        # 규칙 방식이라 '확신하지 못한 값'은 만들지 않는다 (서버 규칙 방식과 같음)
        self.total_amount, self.document_date = total, date
        return lines

    @staticmethod
    def _one_line(text, products):
        match = _LINE.match(text)
        if match is None:
            return None
        name = match["name"].strip()
        return DraftLine(
            name=name,
            quantity=_to_int(match["qty"]),
            unit=match["unit"],
            unit_price=_to_int(match["price"]),
            amount=_to_int(match["amount"]),
            candidates=_candidates(name, products),
        )

    @staticmethod
    def _table_line(text, keys, header_unit, products):
        cells = _cells(text)
        if len(cells) != len(keys):
            return None  # 칸 수가 다르면 품목 줄이 아니라고 본다
        row = {k: c for k, c in zip(keys, cells) if k}
        if not row.get("name") or _number(row.get("amount")) is None:
            return None
        quantity, unit = row.get("quantity"), row.get("unit")
        if quantity and (found := QTY_WITH_UNIT.match(quantity)):
            quantity, unit = found["qty"], unit or found["unit"]
        name = row["name"]
        lookup = f"{row['code']} {name}" if row.get("code") else name
        return DraftLine(
            name=name,
            spec=row.get("spec"),
            quantity=_number(quantity),
            unit=unit or header_unit,
            unit_price=_number(row.get("unit_price")),
            amount=_number(row.get("amount")),
            candidates=_candidates(lookup, products),
        )
