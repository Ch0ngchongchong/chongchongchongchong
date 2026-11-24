"""OCR+규칙 vs OCR+LLM 비교 실행 (이슈 #33)

표본을 서버와 같은 단계로 처리하고 answers/의 정답 표와 비교해 결과 표를 찍는다.
  이미지 ─LocalOcr(Tesseract)─▶ 글자 ─mask_sensitive─▶ 가린 글자 ─structurer─▶ 초안
서버 코드는 고치지 않는다.

--text ocr  : 실제 OCR(Tesseract)로 읽은 글자를 쓴다 (서버와 같음)
--structurer rule-table : 표 양식도 읽는 실험 전용 규칙 방식 (table_rule.py)
--text html : OCR을 거치지 않고 HTML 원본에서 꺼낸 글자를 쓴다.
              OCR 오류를 빼고 '정리 단계(규칙 vs LLM)'만 비교하려는 조건이다

실행 (backend 폴더에서, --text ocr은 Tesseract·kor 언어팩 필요):
  python tests/fixtures/ocr_llm_compare/run_compare.py --structurer rule --text ocr
  OPENAI_API_KEY=... python tests/fixtures/ocr_llm_compare/run_compare.py \
      --structurer openai --text html
  --out <폴더>: 명세서마다 읽은 글자·가린 글자·초안 JSON을 저장한다 (원인 찾기용)
"""

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))  # backend 폴더 (app 패키지)

from app.services.masking import mask_sensitive  # noqa: E402
from app.services.ocr import LocalOcr  # noqa: E402
from app.services.structurer import ProductRef  # noqa: E402

# README: 같은 뜻의 단위는 같게 본다
UNIT_ALIASES = {"box": "박스", "bx": "박스", "ea": "개"}
FIELDS = ["product", "in_top3", "quantity", "unit", "unit_price", "amount"]
LABELS = ["품목 1순위", "후보 3개 안", "수량", "단위", "단가", "금액"]


class _HtmlText(HTMLParser):
    """화면에 보이는 글자를 줄 단위로 꺼낸다. 표 칸은 공백 두 칸으로 띄운다."""

    BREAKS = {"br", "tr", "div", "h1", "p"}

    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], False

    def handle_starttag(self, tag, attrs):
        self.skip = tag == "style"
        if tag in self.BREAKS:
            self.parts.append("\n")
        elif tag in ("td", "th", "span"):
            self.parts.append("  ")

    def handle_endtag(self, tag):
        self.skip = False

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(" ".join(data.split()))


def html_text(image: Path) -> str:
    parser = _HtmlText()
    parser.feed(image.with_suffix(".html").read_text())
    lines = (line.strip() for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


def norm_unit(unit):
    if unit is None:
        return None
    unit = unit.strip()
    return UNIT_ALIASES.get(unit.lower(), unit)


def load_products():
    rows = json.loads((HERE / "products.json").read_text())
    refs = [
        ProductRef(i, row["product_code"], row["name"], row["spec"])
        for i, row in enumerate(rows, start=1)
    ]
    return refs, {ref.id: ref.product_code for ref in refs}


def top_code(line, code_of):
    return code_of.get(line.candidates[0].product_id) if line.candidates else None


def match_lines(answer_lines, draft_lines, code_of):
    """정답 줄마다 초안 줄 하나를 짝짓는다.
    먼저 금액이 같은 줄, 없으면 1순위 상품이 같은 줄. 짝이 없으면 행 누락."""
    left = list(range(len(draft_lines)))
    pairs = []
    for ans in answer_lines:
        found = next((i for i in left if draft_lines[i].amount == ans["amount"]), None)
        if found is None:
            found = next(
                (
                    i
                    for i in left
                    if top_code(draft_lines[i], code_of) == ans["product_code"]
                ),
                None,
            )
        if found is not None:
            left.remove(found)
        pairs.append((ans, draft_lines[found] if found is not None else None))
    return pairs, len(left)


def score_line(ans, line, code_of):
    if line is None:
        return {f: False for f in FIELDS}
    codes = [code_of.get(c.product_id) for c in line.candidates[:3]]
    return {
        "product": bool(codes) and codes[0] == ans["product_code"],
        "in_top3": ans["product_code"] in codes,
        "quantity": line.quantity == ans["quantity"],
        "unit": norm_unit(line.unit) == norm_unit(ans["unit"]),
        "unit_price": line.unit_price == ans["unit_price"],
        "amount": line.amount == ans["amount"],
    }


def pct(hit, total):
    return f"{hit}/{total} ({hit / total:.0%})" if total else "-"


def ox(ok):
    return "O" if ok else "X"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--structurer", choices=["rule", "rule-table", "openai"], required=True
    )
    parser.add_argument("--text", choices=["ocr", "html"], default="ocr")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.structurer == "rule-table":
        # 실험 전용 규칙 방식 (표 양식도 읽음, 이슈 #36)
        sys.path.insert(0, str(HERE))
        from table_rule import TableRuleStructurer

        structurer = TableRuleStructurer()
    else:
        os.environ["STRUCTURER"] = args.structurer
        from app.services.structurer import get_structurer

        structurer = get_structurer()
    refs, code_of = load_products()
    ocr = LocalOcr()

    rows = []
    totals = dict.fromkeys(FIELDS + ["lines", "missing", "extra", "date", "total"], 0)
    usage = dict.fromkeys(["input_tokens", "output_tokens", "cost"], 0)
    for answer_path in sorted((HERE / "answers").glob("*.json")):
        answer = json.loads(answer_path.read_text())
        image = HERE / answer["statement"]

        started = time.perf_counter()
        if args.text == "ocr":
            text = ocr.read_text(image, "image/png")
        else:
            text = html_text(image)
        read_sec = time.perf_counter() - started
        masked = mask_sensitive(text)
        started = time.perf_counter()
        lines = structurer.structure(masked, refs)
        struct_sec = time.perf_counter() - started
        # main(PR #28 이후): structure()는 줄 목록만 돌려주고, 합계·사용량은
        # structurer 속성에 둔다. 작성일은 서버가 밖으로 넘기지 않아 채점하지 않는다
        # (속성이 있으면 채점한다 — 실험 전용 table_rule)
        draft = {
            "lines": lines,
            "document_date": getattr(structurer, "document_date", None),
            "total_amount": getattr(structurer, "total_amount", None),
        }

        pairs, extra = match_lines(answer["lines"], lines, code_of)
        scores = [score_line(a, line, code_of) for a, line in pairs]
        n = len(scores)
        missing = sum(1 for _, line in pairs if line is None)
        hits = {f: sum(s[f] for s in scores) for f in FIELDS}
        has_date = hasattr(structurer, "document_date")
        date_ok = has_date and draft["document_date"] == answer["document_date"]
        total_ok = draft["total_amount"] == answer["total_amount"]
        for f in FIELDS:
            totals[f] += hits[f]
        totals["lines"] += n
        totals["missing"] += missing
        totals["extra"] += extra
        totals["date"] += date_ok
        totals["total"] += total_ok
        for key in usage:
            usage[key] += getattr(structurer, key, None) or 0
        cells = [answer_path.stem, f"{len(lines)}/{n}", missing, extra]
        cells += [f"{hits[f]}/{n}" for f in FIELDS]
        cells += [ox(date_ok) if has_date else "-", ox(total_ok)]
        cells += [f"{read_sec:.1f}", f"{struct_sec:.2f}"]
        rows.append("| " + " | ".join(str(c) for c in cells) + " |")

        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            stem = f"{answer_path.stem}.{args.text}.{args.structurer}"
            (args.out / f"{stem}.text.txt").write_text(text)
            (args.out / f"{stem}.masked.txt").write_text(masked)
            (args.out / f"{stem}.draft.json").write_text(
                json.dumps(
                    {**draft, "lines": [asdict(line) for line in lines]},
                    ensure_ascii=False,
                    indent=2,
                )
            )

    n, docs = totals["lines"], len(rows)
    head = ["명세서", "읽은 줄/정답 줄", "행 누락", "남는 줄", *LABELS]
    head += ["작성일", "합계", "글자 읽기 초", "정리 초"]
    print(f"## 글자={args.text}, STRUCTURER={args.structurer}\n")
    print("| " + " | ".join(head) + " |")
    print("|" + " --- |" * len(head))
    print("\n".join(rows))
    print("\n**전체**")
    for label, key in zip(LABELS, FIELDS):
        print(f"- {label}: {pct(totals[key], n)}")
    print(f"- 행 누락률: {pct(totals['missing'], n)}")
    print(f"- 남는 줄(정답에 없는 줄): {totals['extra']}")
    date = pct(totals["date"], docs) if hasattr(structurer, "document_date") else "-"
    print(f"- 작성일: {date}, 합계: {pct(totals['total'], docs)}")
    print(
        f"- LLM 사용량 합: 입력 {usage['input_tokens']} / "
        f"출력 {usage['output_tokens']} 토큰, 비용 {usage['cost']}"
    )


if __name__ == "__main__":
    main()
