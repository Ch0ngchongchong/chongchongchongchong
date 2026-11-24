# 판독 흐름 (데모 3단계, US-03): `판독 중` → `직원 확인 대기` (실패하면 `업로드 대기`)
# 와 발주 대조·재고 반영(데모 4~5단계, US-04·R3).
#
#   원본 파일 ─OCR─▶ 텍스트 ─가리기─▶ 가린 텍스트 ─LLM(정리·후보)─▶ 초안 줄
#
# 원본 파일은 OCR에만 넘긴다. LLM 단계에는 가린 텍스트와 상품 기준 정보만 넘긴다.
# 이 파일의 판독 단계는 재고를 바꾸지 않는다. 재고는 apply_stock()에서만 바꾸고,
# apply_stock()은 직원 확정 API에서만 부른다 (R3).

import logging
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.audit import ChangeHistory, DocumentContent, ReadingLog
from app.models.inspection import Inspection
from app.models.notification import Notification
from app.models.product import Product
from app.models.purchase_order import ORDER_RECEIVED, PurchaseOrder
from app.models.receiving import (
    INSPECTION_READING,
    INSPECTION_STAFF_REVIEW,
    INSPECTION_STATUS_UPLOAD_WAITING,
    InspectionDocument,
    InspectionLine,
    Inventory,
)
from app.services.masking import mask_sensitive
from app.services.ocr import OcrError, get_ocr_engine
from app.services.structurer import DraftLine, ProductRef, get_structurer

# 줄 대조 결과
MATCH_OK = "일치"
MATCH_NEEDS_CHECK = "확인 필요"  # 품목이나 수량이 비어 있어 직원이 채워야 함
MATCH_NOT_IN_ORDER = "발주에 없음"
MATCH_QTY_DIFF = "수량 다름"
MATCH_PRICE_DIFF = "단가 다름"
MATCH_DAMAGED = "파손"  # 직원이 파손을 표시함 (US-04)
MATCH_MISSING_IN_STATEMENT = "명세서에 없음"  # 발주 줄인데 명세서에 없음

# 규칙 검증 실패 칸 (US-03 안전장치, 미팅1 피드백 6)
RULE_AMOUNT_MISMATCH = "AMOUNT_MISMATCH"  # 수량 × 단가 ≠ 금액
RULE_NUMBER_NOT_IN_OCR = "NUMBER_NOT_IN_OCR"  # OCR 글자에 없는 숫자가 판독 결과에 있음


def _numbers_in_text(text: str) -> set[str]:
    """OCR 글자(원문, 가리기 전)에 실제로 적힌 숫자들(쉼표 뗀 문자열).
    느슨한 검사다 — 다른 자리에 우연히 같은 숫자가 있어도 통과로 본다."""
    return {token.replace(",", "") for token in re.findall(r"\d[\d,]*", text)}


def _has_number_not_in_ocr(draft: DraftLine, numbers_in_ocr: set[str]) -> bool:
    for value in (draft.quantity, draft.unit_price, draft.amount):
        if value is not None and str(value) not in numbers_in_ocr:
            return True
    return False


def latest_document(db: Session, inspection_id: int) -> InspectionDocument | None:
    return db.scalar(
        select(InspectionDocument)
        .where(InspectionDocument.inspection_id == inspection_id)
        .order_by(InspectionDocument.id.desc())
        .limit(1)
    )


def run_reading(inspection_id: int) -> None:
    """업로드 직후 백그라운드에서 돈다. 요청과 다른 DB 세션을 쓴다."""
    with SessionLocal() as db:
        inspection = db.get(Inspection, inspection_id)
        if inspection is None or inspection.status != INSPECTION_READING:
            return
        document = latest_document(db, inspection_id)
        order = db.get(PurchaseOrder, inspection.purchase_order_id)
        try:
            if document is None:
                raise OcrError("올린 명세서가 없습니다")
            content = db.get(DocumentContent, document.id)
            if content is None:
                text = get_ocr_engine().read_text(
                    Path(document.stored_path), document.content_type
                )
            else:
                with tempfile.NamedTemporaryFile() as temporary:
                    temporary.write(content.data)
                    temporary.flush()
                    text = get_ocr_engine().read_text(
                        Path(temporary.name), document.content_type
                    )
            products = db.scalars(
                select(Product).where(Product.store_id == order.store_id)
            ).all()
            refs = [ProductRef(p.id, p.product_code, p.name, p.spec) for p in products]
            structurer = get_structurer()
            drafts = structurer.structure(mask_sensitive(text), refs)
            if not drafts:
                raise OcrError("명세서에서 품목 줄을 찾지 못했습니다")
            total_amount = getattr(structurer, "total_amount", None)
            numbers_in_ocr = _numbers_in_text(text)
        except Exception as exc:
            if not isinstance(exc, OcrError):
                logging.exception("명세서 판독 실패")
                exc = OcrError("명세서를 판독하지 못했습니다")
            # 판독 실패: `업로드 대기`로 돌아가고, 올린 직원에게 다시 올려 달라는
            # 알림을 남긴다 (US-03). 화면은 폴링으로 read_error도 볼 수 있다.
            db.rollback()
            inspection.status = INSPECTION_STATUS_UPLOAD_WAITING
            if document is not None:
                document.read_error = f"{exc}. 명세서를 다시 올려 주세요"
            if document is not None:
                db.add(
                    ReadingLog(
                        inspection_id=inspection_id,
                        document_id=document.id,
                        elapsed_seconds=max(
                            0,
                            (
                                datetime.now(timezone.utc)
                                - document.uploaded_at.replace(tzinfo=timezone.utc)
                            ).total_seconds(),
                        ),
                        outcome="실패",
                    )
                )
                db.add(
                    Notification(
                        user_id=document.uploaded_by,
                        inspection_id=inspection_id,
                        message=document.read_error,
                    )
                )
            db.commit()
            return

        # 다시 판독하는 경우를 대비해 이전 초안 줄은 지운다
        for old in db.scalars(
            select(InspectionLine).where(InspectionLine.inspection_id == inspection_id)
        ):
            db.delete(old)
        for no, draft in enumerate(drafts, start=1):
            top = draft.candidates[0].product_id if draft.candidates else None
            db.add(
                InspectionLine(
                    inspection_id=inspection_id,
                    line_no=no,
                    read_name=draft.name,
                    read_spec=draft.spec,
                    read_quantity=draft.quantity,
                    read_unit=draft.unit,
                    read_unit_price=draft.unit_price,
                    read_amount=draft.amount,
                    candidates=[
                        {
                            "product_id": c.product_id,
                            "score": c.score,
                            "reason": c.reason,
                        }
                        for c in draft.candidates
                    ],
                    uncertain_fields=list(draft.uncertain_fields),
                    product_id=top,
                    quantity=draft.quantity,
                    unit=draft.unit,
                    numbers_not_in_ocr=_has_number_not_in_ocr(draft, numbers_in_ocr),
                )
            )
        inspection.read_total_amount = total_amount
        inspection.summary_checked = False
        db.add(
            ReadingLog(
                inspection_id=inspection_id,
                document_id=document.id,
                elapsed_seconds=max(
                    0,
                    (
                        datetime.now(timezone.utc)
                        - document.uploaded_at.replace(tzinfo=timezone.utc)
                    ).total_seconds(),
                ),
                outcome="성공",
                input_tokens=getattr(structurer, "input_tokens", None),
                output_tokens=getattr(structurer, "output_tokens", None),
                cost=getattr(structurer, "cost", None),
            )
        )
        for no, draft in enumerate(drafts, start=1):
            db.add(
                ChangeHistory(
                    inspection_id=inspection_id,
                    changed_by=None,
                    kind="판독 원본",
                    new_value={
                        "line_no": no,
                        "name": draft.name,
                        "quantity": draft.quantity,
                        "unit": draft.unit,
                        "unit_price": draft.unit_price,
                        "amount": draft.amount,
                    },
                )
            )
        document.read_error = None
        inspection.status = INSPECTION_STAFF_REVIEW
        db.commit()


# ---------- 발주 대조 ----------


def to_base_quantity(quantity: int, unit: str | None, product: Product) -> int:
    """읽은 단위가 포장 단위면 환산값을 곱해 기준 단위로 바꾼다 (US-05).
    단위가 없거나 기준 단위면 그대로 쓴다.
    [가정] 발주 수량은 기준 단위(개)다 (R6 미정)."""
    if (
        unit
        and product.pack_unit
        and unit == product.pack_unit
        and unit != product.base_unit
        and product.conversion_qty
    ):
        return quantity * product.conversion_qty
    return quantity


@dataclass
class LineCheck:
    line: InspectionLine
    product: Product | None
    base_quantity: int | None
    order_quantity: int | None
    status: str
    rule_violations: list[str] = field(default_factory=list)


@dataclass
class MissingOrderLine:
    product_id: int
    order_quantity: int


@dataclass
class OrderGap:
    """발주보다 적게 들어온 줄 (0개보다는 많지만 발주 수량에 못 미침, US-06).
    0개 들어온 줄은 missing_order_lines로 따로 보인다."""

    product_id: int
    order_quantity: int
    received_quantity: int

    @property
    def short_quantity(self) -> int:
        return self.order_quantity - self.received_quantity


@dataclass
class Evaluation:
    lines: list[LineCheck]
    missing: list[MissingOrderLine]
    # 줄 금액 합 ≠ 합계 (03 3-4 규칙 검증 실패). 합계를 못 읽었으면 항상 False
    summary_mismatch: bool = False
    summary_checked: bool = False
    # 확정하면 실제로 반영될 금액(기준 단위 수량 × 단가의 합)
    final_amount: int = 0
    # 최종 금액이 발주의 amount_alert_threshold를 넘으면 true (2026-11-16
    # 멘토 데모 피드백 팀 결정: "최종 금액이 한도를 넘으면 알람을 준다")
    amount_over_limit: bool = False
    short: list[OrderGap] = field(default_factory=list)

    @staticmethod
    def _unresolved(check: "LineCheck") -> bool:
        """규칙 검증 실패·후보 여러 개를 직원이 아직 확인하지 않았는지
        (US-03 안전장치, US-04 후보 여러 개)."""
        return not check.line.checked and bool(
            check.rule_violations or len(check.line.candidates) >= 2
        )

    @property
    def check_count(self) -> int:
        """직원이 채워야 확정할 수 있는 칸 수 (품목 미선택·수량 없음·
        규칙 검증 실패·후보 여러 개 미확인·합계 불일치 미확인)."""
        needs_check = sum(1 for c in self.lines if c.status == MATCH_NEEDS_CHECK)
        unresolved_lines = sum(1 for c in self.lines if self._unresolved(c))
        unresolved_summary = (
            1 if (self.summary_mismatch and not self.summary_checked) else 0
        )
        return needs_check + unresolved_lines + unresolved_summary

    @property
    def all_match(self) -> bool:
        unresolved_lines = any(self._unresolved(c) for c in self.lines)
        unresolved_summary = self.summary_mismatch and not self.summary_checked
        return (
            not self.missing
            and all(c.status == MATCH_OK for c in self.lines)
            and not self.amount_over_limit
            and not unresolved_lines
            and not unresolved_summary
        )


def remaining_quantities(
    db: Session, order: PurchaseOrder, *, before_inspection_id: int | None = None
) -> dict[int, int]:
    """발주 줄마다 아직 안 들어온 수량. before_inspection_id를 주면 그 검수 건
    자신(과 그 뒤에 생긴 검수 건)이 반영한 몫은 빼지 않는다 — 확정·승인
    직후(재고는 이미 반영됐지만) 이 건 기준으로 얼마가 부족했는지 보여 줄 때 쓴다."""
    remaining = {}
    for line in order.lines:
        remaining[line.product_id] = remaining.get(line.product_id, 0) + line.quantity
    query = (
        select(InspectionLine.product_id, InspectionLine.applied_base_quantity)
        .join(Inspection, Inspection.id == InspectionLine.inspection_id)
        .where(
            Inspection.purchase_order_id == order.id,
            InspectionLine.applied_base_quantity.is_not(None),
        )
    )
    if before_inspection_id is not None:
        query = query.where(Inspection.id < before_inspection_id)
    for product_id, quantity in db.execute(query).all():
        if product_id in remaining:
            remaining[product_id] = max(0, remaining[product_id] - quantity)
    return remaining


def evaluate(db: Session, inspection: Inspection) -> Evaluation:
    order = db.get(PurchaseOrder, inspection.purchase_order_id)
    ordered = {
        product_id: qty
        for product_id, qty in remaining_quantities(
            db, order, before_inspection_id=inspection.id
        ).items()
        if qty > 0
    }

    lines = db.scalars(
        select(InspectionLine)
        .where(InspectionLine.inspection_id == inspection.id)
        .order_by(InspectionLine.line_no)
    ).all()

    product_cache: dict[int, Product | None] = {}

    def get_product(product_id: int | None) -> Product | None:
        if product_id is None:
            return None
        if product_id not in product_cache:
            product_cache[product_id] = db.get(Product, product_id)
        return product_cache[product_id]

    # 같은 상품이 한 명세서에 박스·낱개로 섞여 있으면 구분할 수 없으니
    # 자동 환산하지 않고 '확인 필요'로 강조한다 (US-05, 미팅1 피드백 5, R6)
    units_by_product: dict[int, set[str]] = {}
    for line in lines:
        product = get_product(line.product_id)
        if product is None or not line.unit:
            continue
        if line.unit in {product.base_unit, product.pack_unit}:
            units_by_product.setdefault(product.id, set()).add(line.unit)
    mixed_unit_products = {
        product_id for product_id, units in units_by_product.items() if len(units) > 1
    }

    # 같은 상품이 여러 줄에 나오면 합쳐서 발주 수량과 비교한다
    received: dict[int, int] = {}
    checks = []
    for line in lines:
        violations = _rule_violations(line)
        product = get_product(line.product_id)
        unresolved = (
            product is None
            or line.quantity is None
            or line.quantity <= 0
            or not line.unit
            or line.unit not in {product.base_unit, product.pack_unit}
            or (
                line.unit == product.pack_unit
                and line.unit != product.base_unit
                and not product.conversion_qty
            )
            or product.id in mixed_unit_products
        )
        # 단위를 환산할 수 없을 때 직원이 직접 넣은 기준 단위 수량으로 대신한다
        # (US-05 안전장치). 품목은 반드시 골라야 알 수 있다
        if unresolved and product is not None and line.manual_base_quantity is not None:
            unresolved = False
            base = line.manual_base_quantity
        elif not unresolved:
            base = to_base_quantity(line.quantity, line.unit, product)
        if unresolved:
            checks.append(
                LineCheck(line, product, None, None, MATCH_NEEDS_CHECK, violations)
            )
            continue
        received[product.id] = received.get(product.id, 0) + base
        checks.append(
            LineCheck(line, product, base, ordered.get(product.id), "", violations)
        )

    for check in checks:
        if check.status:
            continue
        product = check.product
        if check.line.damaged:
            check.status = MATCH_DAMAGED
        elif product.id not in ordered:
            check.status = MATCH_NOT_IN_ORDER
        elif received[product.id] != ordered[product.id]:
            check.status = MATCH_QTY_DIFF
        elif _price_differs(check.line, product):
            check.status = MATCH_PRICE_DIFF
        else:
            check.status = MATCH_OK

    missing = [
        MissingOrderLine(product_id, qty)
        for product_id, qty in ordered.items()
        if product_id not in received
    ]
    short = [
        OrderGap(product_id, qty, received[product_id])
        for product_id, qty in ordered.items()
        if product_id in received and received[product_id] < qty
    ]

    lines_amount_sum = sum(
        check.line.read_amount for check in checks if check.line.read_amount is not None
    )
    summary_mismatch = (
        inspection.read_total_amount is not None
        and lines_amount_sum != inspection.read_total_amount
    )

    # 확정하면 실제로 반영될 금액 (R8과 같은 기준 단위 단가 사용)
    final_amount = sum(
        check.base_quantity * _base_unit_price(check.line, check.product)
        for check in checks
        if check.base_quantity is not None and check.line.read_unit_price is not None
    )
    amount_over_limit = (
        order.amount_alert_threshold is not None
        and final_amount > order.amount_alert_threshold
    )
    return Evaluation(
        checks,
        missing,
        summary_mismatch,
        inspection.summary_checked,
        final_amount,
        amount_over_limit,
        short,
    )


def _rule_violations(line: InspectionLine) -> list[str]:
    """규칙 검증 실패 칸 (US-03 안전장치, 미팅1 피드백 6).
    품목 매칭(MATCH_*)과는 다른 축이라 따로 둔다 — 틀렸다고 해서
    예외 건(US-06)이 되는 건 아니고, 직원이 확인(checked)해야 확정할 수 있다."""
    violations = []
    if (
        line.read_quantity is not None
        and line.read_unit_price is not None
        and line.read_amount is not None
        and line.read_quantity * line.read_unit_price != line.read_amount
    ):
        violations.append(RULE_AMOUNT_MISMATCH)
    if line.numbers_not_in_ocr:
        violations.append(RULE_NUMBER_NOT_IN_OCR)
    return violations


def _base_unit_price(line: InspectionLine, product: Product) -> int:
    """읽은 단가를 기준 단위 1개당 단가로 바꾼다.
    포장 단위 단가면 환산값으로 나눈다."""
    per_unit = to_base_quantity(1, line.unit, product)
    return line.read_unit_price // per_unit if per_unit else line.read_unit_price


def _price_differs(line: InspectionLine, product: Product) -> bool:
    """단가가 '다르다'(R8)고 볼지 판정한다.
    product.price_alert_threshold_percent가 없으면 지금까지처럼 기준 단가와
    조금이라도 다르면 다르다고 본다. 설정돼 있으면 기준 단가보다 그 비율
    이상 '높을 때만' 다르다고 본다 — 더 싸게 들어온 건 경고하지 않는다
    (2026-11-16 멘토 데모 피드백 팀 결정: 사장님이 상품마다 직접 설정)."""
    if line.read_unit_price is None or product.base_unit_price is None:
        return False
    effective_price = _base_unit_price(line, product)
    threshold = product.price_alert_threshold_percent
    if threshold is None:
        return effective_price != product.base_unit_price
    return effective_price * 100 > product.base_unit_price * (100 + threshold)


# ---------- 재고 반영 ----------


def apply_stock(db: Session, inspection: Inspection, evaluation: Evaluation) -> None:
    """직원 확정 뒤에만 부른다 (R3). 커밋은 부른 쪽에서 한다.
    확정 때의 환산값·단가를 줄에 남겨 둔다 (나중에 상품을 고쳐도 이 건은 그대로)."""
    order = db.get(PurchaseOrder, inspection.purchase_order_id)
    # 같은 상품에 대한 동시 입고와 같은 검수의 중복 행을 직렬화한다.
    db.scalars(
        select(Product)
        .where(Product.id.in_(sorted({check.product.id for check in evaluation.lines})))
        .order_by(Product.id)
        .with_for_update()
    ).all()
    stocks = {}
    for check in evaluation.lines:
        product = check.product
        check.line.applied_base_quantity = check.base_quantity
        check.line.applied_conversion_qty = product.conversion_qty
        if check.line.read_unit_price is not None:
            product.base_unit_price = _base_unit_price(check.line, product)
        check.line.applied_unit_price = product.base_unit_price

        stock = stocks.get(product.id)
        if stock is None:
            stock = db.scalar(
                select(Inventory)
                .where(
                    Inventory.store_id == order.store_id,
                    Inventory.product_id == product.id,
                )
                .with_for_update()
            )
        if stock is None:
            stock = Inventory(
                store_id=order.store_id, product_id=product.id, quantity=0
            )
            db.add(stock)
        stocks[product.id] = stock
        stock.quantity += check.base_quantity
    # 이미 반영된 검수 건까지 합산해 미입고가 남으면 발주를 열어 둔다.
    totals = {}
    applied_lines = db.execute(
        select(InspectionLine.product_id, InspectionLine.applied_base_quantity)
        .join(Inspection, Inspection.id == InspectionLine.inspection_id)
        .where(
            Inspection.purchase_order_id == order.id,
            InspectionLine.applied_base_quantity.is_not(None),
        )
    ).all()
    for product_id, quantity in applied_lines:
        totals[product_id] = totals.get(product_id, 0) + quantity
    for check in evaluation.lines:
        totals[check.product.id] = totals.get(check.product.id, 0) + check.base_quantity
    ordered = {}
    for line in order.lines:
        ordered[line.product_id] = ordered.get(line.product_id, 0) + line.quantity
    if all(totals.get(product_id, 0) >= qty for product_id, qty in ordered.items()):
        order.status = ORDER_RECEIVED
