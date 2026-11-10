# 판독 흐름 (US-03): `판독 중` → `직원 확인 대기` (실패하면 `업로드 대기`)
# 와 발주 대조·확인할 칸 계산(US-04·US-05), 재고 반영(US-04·US-06·R3).
#
#   원본 파일 ─OCR─▶ 텍스트 ─가리기─▶ 가린 텍스트 ─LLM(정리·후보)─▶ 초안 줄
#
# 원본 파일은 OCR에만 넘긴다. LLM 단계에는 가린 텍스트와 상품 기준 정보만 넘긴다.
# 이 파일의 판독 단계는 재고를 바꾸지 않는다. 재고는 apply_stock()에서만 바꾸고,
# apply_stock()은 직원 확정(일반 건)과 사장 승인(예외 건) API에서만 부른다 (R3).

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.history import Notification, ReadingLog
from app.models.inspection import Inspection
from app.models.product import Product
from app.models.purchase_order import ORDER_RECEIVED, PurchaseOrder
from app.models.receiving import (
    FILE_STATEMENT,
    INSPECTION_READING,
    INSPECTION_STAFF_REVIEW,
    INSPECTION_STATUS_UPLOAD_WAITING,
    InspectionDetail,
    InspectionFile,
    InspectionLine,
    Inventory,
)
from app.services import history
from app.services.masking import mask_sensitive
from app.services.ocr import OcrError, get_ocr_engine
from app.services.structurer import ProductRef, get_structurer

# 줄 대조 결과 (match_status)
MATCH_OK = "일치"
MATCH_NEEDS_CHECK = "확인 필요"  # 확인할 칸이 남아 있어 대조할 수 없음
MATCH_NOT_IN_ORDER = "발주에 없음"
MATCH_QTY_DIFF = "수량 다름"
MATCH_PRICE_DIFF = "단가 다름"
MATCH_DAMAGED = "파손"
MATCH_MISSING_IN_STATEMENT = "명세서에 없음"  # 발주 줄인데 명세서에 없음

# 확인할 칸 (US-04 실패·거절, US-05)
# - 값을 채워야만 풀리는 칸
CHECK_NO_PRODUCT = "품목 미선택"
CHECK_NO_QUANTITY = "수량 없음"
# 환산값이 없거나 단위를 모름 → 기준 단위 수량을 직접 넣어야 함 (US-05)
CHECK_UNIT_UNKNOWN = "단위 환산 불가"
# - 직원이 확인(checked)하면 풀리는 칸
CHECK_MULTI_CANDIDATES = "후보 여러 개"
CHECK_UNCERTAIN = "불확실한 값"
CHECK_AMOUNT_RULE = "수량×단가≠금액"
CHECK_TOTAL_RULE = "줄 금액 합≠합계"


def latest_statement(db: Session, inspection_id: int) -> InspectionFile | None:
    return db.scalar(
        select(InspectionFile)
        .where(
            InspectionFile.inspection_id == inspection_id,
            InspectionFile.kind == FILE_STATEMENT,
        )
        .order_by(InspectionFile.id.desc())
        .limit(1)
    )


def get_detail(db: Session, inspection_id: int) -> InspectionDetail:
    detail = db.get(InspectionDetail, inspection_id)
    if detail is None:
        detail = InspectionDetail(
            inspection_id=inspection_id, uncertain_fields=[], summary_checked=False
        )
        db.add(detail)
        db.flush()
    return detail


def _elapsed(uploaded_at: datetime) -> float:
    if uploaded_at.tzinfo is None:
        uploaded_at = uploaded_at.replace(tzinfo=UTC)
    return round((datetime.now(UTC) - uploaded_at).total_seconds(), 3)


def _reading_failed(db, inspection, document, actor, message):
    """판독 실패: `업로드 대기`로 돌아가고, 올린 직원에게
    다시 올려 달라는 알림을 남긴다 (US-03)"""
    document.read_error = message
    history.record_status(
        db, inspection, actor, "판독 실패", INSPECTION_STATUS_UPLOAD_WAITING
    )
    db.add(Notification(user_id=actor, inspection_id=inspection.id, message=message))
    db.add(
        ReadingLog(
            inspection_id=inspection.id,
            file_id=document.id,
            succeeded=False,
            input_tokens=0,
            output_tokens=0,
            cost=0.0,
            elapsed_seconds=_elapsed(document.uploaded_at),
        )
    )
    db.commit()


def run_reading(inspection_id: int) -> None:
    """업로드 직후 백그라운드에서 돈다. 요청과 다른 DB 세션을 쓴다."""
    with SessionLocal() as db:
        inspection = db.get(Inspection, inspection_id)
        if inspection is None or inspection.status != INSPECTION_READING:
            return
        document = latest_statement(db, inspection_id)
        if document is None:
            return
        actor = document.uploaded_by
        order = db.get(PurchaseOrder, inspection.purchase_order_id)
        try:
            text = get_ocr_engine().read_text(
                Path(document.stored_path), document.content_type
            )
            products = db.scalars(
                select(Product).where(Product.store_id == order.store_id)
            ).all()
            refs = [ProductRef(p.id, p.product_code, p.name, p.spec) for p in products]
            draft = get_structurer().structure(mask_sensitive(text), refs)
            if not draft.lines:
                raise OcrError("명세서에서 품목 줄을 찾지 못했습니다")
        except OcrError as exc:
            _reading_failed(
                db, inspection, document, actor, f"{exc}. 명세서를 다시 올려 주세요"
            )
            return

        # 다시 판독하는 경우를 대비해 이전 초안 줄은 지운다
        for old in db.scalars(
            select(InspectionLine).where(InspectionLine.inspection_id == inspection_id)
        ):
            db.delete(old)

        detail = get_detail(db, inspection_id)
        detail.document_date = draft.document_date
        detail.total_amount = draft.total_amount
        detail.uncertain_fields = list(draft.uncertain_fields)
        detail.summary_checked = False

        for no, line in enumerate(draft.lines, start=1):
            top = line.candidates[0].product_id if line.candidates else None
            db.add(
                InspectionLine(
                    inspection_id=inspection_id,
                    line_no=no,
                    read_name=line.name,
                    read_spec=line.spec,
                    read_quantity=line.quantity,
                    read_unit=line.unit,
                    read_unit_price=line.unit_price,
                    read_amount=line.amount,
                    candidates=[
                        {
                            "product_id": c.product_id,
                            "score": c.score,
                            "reason": c.reason,
                        }
                        for c in line.candidates
                    ],
                    uncertain_fields=list(line.uncertain_fields),
                    product_id=top,
                    quantity=line.quantity,
                    unit=line.unit,
                    damaged=False,
                    checked=False,
                )
            )
            # 판독 원본값 (US-07)
            history.record(
                db,
                inspection_id,
                actor,
                "판독",
                f"line {no}",
                None,
                {
                    "name": line.name,
                    "spec": line.spec,
                    "quantity": line.quantity,
                    "unit": line.unit,
                    "unit_price": line.unit_price,
                    "amount": line.amount,
                    "candidates": [c.product_id for c in line.candidates],
                    "uncertain_fields": line.uncertain_fields,
                },
            )
        history.record(
            db,
            inspection_id,
            actor,
            "판독",
            "summary",
            None,
            {
                "document_date": draft.document_date,
                "total_amount": draft.total_amount,
                "uncertain_fields": draft.uncertain_fields,
            },
        )
        document.read_error = None
        history.record_status(db, inspection, actor, "판독", INSPECTION_STAFF_REVIEW)
        db.add(
            ReadingLog(
                inspection_id=inspection_id,
                file_id=document.id,
                succeeded=True,
                input_tokens=draft.usage.input_tokens,
                output_tokens=draft.usage.output_tokens,
                cost=draft.usage.cost,
                elapsed_seconds=_elapsed(document.uploaded_at),
            )
        )
        db.commit()


# ---------- 단위 환산 (US-05) ----------


def unit_factor(unit: str | None, product: Product) -> int | None:
    """읽은 단위 1개가 기준 단위 몇 개인지. 알 수 없으면 None (자동 환산하지 않음).
    [가정] 발주 수량은 기준 단위다 (R6 미정)."""
    if unit is None:
        return None
    if product.base_unit and unit == product.base_unit:
        return 1
    if product.pack_unit and unit == product.pack_unit:
        return product.conversion_qty  # 환산값이 없으면 None
    return None


# ---------- 발주 대조 ----------


@dataclass
class LineCheck:
    line: InspectionLine
    product: Product | None
    base_quantity: int | None
    order_quantity: int | None
    # 아직 풀리지 않은 확인할 칸
    open_checks: list[str] = field(default_factory=list)
    status: str = ""

    @property
    def per_base_unit_price(self) -> int | None:
        """명세서 단가를 기준 단위 1개당 단가로 바꾼 값"""
        if self.line.read_unit_price is None or self.product is None:
            return None
        factor = unit_factor(self.line.unit, self.product)
        if not factor:
            return None
        return round(self.line.read_unit_price / factor)


@dataclass
class OrderGap:
    product_id: int
    order_quantity: int
    received_quantity: int

    @property
    def short_quantity(self) -> int:
        return self.order_quantity - self.received_quantity


@dataclass
class Evaluation:
    lines: list[LineCheck]
    missing: list[OrderGap]  # 발주에 있는데 명세서에 없음
    short: list[OrderGap]  # 발주보다 적게 들어옴 (명세서에 없는 것 포함)
    summary_open_checks: list[str]
    line_amount_sum: int | None

    @property
    def check_count(self) -> int:
        """직원이 풀어야 확정할 수 있는 칸 수 (US-04 실패·거절)"""
        return sum(len(c.open_checks) for c in self.lines) + len(
            self.summary_open_checks
        )

    @property
    def exception_types(self) -> list[str]:
        """예외 종류 (US-06 사장님 화면). 비어 있으면 일반 건"""
        found = []
        for c in self.lines:
            if c.status in (MATCH_OK, MATCH_NEEDS_CHECK) or c.status in found:
                continue
            found.append(c.status)
        if self.missing:
            found.append(MATCH_MISSING_IN_STATEMENT)
        return found

    @property
    def all_match(self) -> bool:
        return bool(self.lines) and self.check_count == 0 and not self.exception_types


def _line_checks(line: InspectionLine, product: Product | None) -> list[str]:
    checks = []
    if product is None:
        checks.append(CHECK_NO_PRODUCT)
    if line.manual_base_quantity is None:
        if line.quantity is None:
            checks.append(CHECK_NO_QUANTITY)
        elif product is not None and unit_factor(line.unit, product) is None:
            checks.append(CHECK_UNIT_UNKNOWN)
    if not line.checked:
        if len(line.candidates) >= 2:
            checks.append(CHECK_MULTI_CANDIDATES)
        if line.uncertain_fields:
            checks.append(CHECK_UNCERTAIN)
        if (
            line.read_quantity is not None
            and line.read_unit_price is not None
            and line.read_amount is not None
            and line.read_quantity * line.read_unit_price != line.read_amount
        ):
            checks.append(CHECK_AMOUNT_RULE)
    return checks


def evaluate(db: Session, inspection: Inspection) -> Evaluation:
    order = db.get(PurchaseOrder, inspection.purchase_order_id)
    ordered: dict[int, int] = {}
    for po_line in order.lines:
        ordered[po_line.product_id] = (
            ordered.get(po_line.product_id, 0) + po_line.quantity
        )

    lines = db.scalars(
        select(InspectionLine)
        .where(InspectionLine.inspection_id == inspection.id)
        .order_by(InspectionLine.line_no)
    ).all()

    # 같은 상품이 여러 줄에 나오면 합쳐서 발주 수량과 비교한다
    received: dict[int, int] = {}
    checks = []
    for line in lines:
        product = db.get(Product, line.product_id) if line.product_id else None
        base = None
        if product is not None:
            if line.manual_base_quantity is not None:
                base = line.manual_base_quantity
            elif line.quantity is not None:
                factor = unit_factor(line.unit, product)
                base = line.quantity * factor if factor else None
        if base is not None:
            received[product.id] = received.get(product.id, 0) + base
        checks.append(
            LineCheck(
                line,
                product,
                base,
                ordered.get(product.id) if product else None,
                _line_checks(line, product),
            )
        )

    for check in checks:
        product = check.product
        if product is None or check.base_quantity is None:
            check.status = MATCH_NEEDS_CHECK
        elif check.line.damaged:
            check.status = MATCH_DAMAGED
        elif product.id not in ordered:
            check.status = MATCH_NOT_IN_ORDER
        elif received[product.id] != ordered[product.id]:
            check.status = MATCH_QTY_DIFF
        elif (
            check.per_base_unit_price is not None
            and product.base_unit_price is not None
            and check.per_base_unit_price != product.base_unit_price
        ):
            check.status = MATCH_PRICE_DIFF
        else:
            check.status = MATCH_OK

    # 명세서 전체 규칙 검증 (US-03): 줄 금액 합 ≠ 합계
    detail = db.get(InspectionDetail, inspection.id)
    amounts = [line.read_amount for line in lines]
    line_sum = sum(amounts) if amounts and None not in amounts else None
    summary_checks = []
    if detail is not None and lines and not detail.summary_checked:
        if detail.uncertain_fields:
            summary_checks.append(CHECK_UNCERTAIN)
        if (
            detail.total_amount is not None
            and line_sum is not None
            and detail.total_amount != line_sum
        ):
            summary_checks.append(CHECK_TOTAL_RULE)

    # 판독 전(줄이 없음)에는 발주와 비교하지 않는다
    missing, short = [], []
    if lines:
        missing = [
            OrderGap(pid, qty, 0) for pid, qty in ordered.items() if pid not in received
        ]
        short = [
            OrderGap(pid, qty, received.get(pid, 0))
            for pid, qty in ordered.items()
            if received.get(pid, 0) < qty
        ]
    return Evaluation(checks, missing, short, summary_checks, line_sum)


# ---------- 재고 반영 ----------


def apply_stock(
    db: Session, inspection: Inspection, evaluation: Evaluation, actor: int
) -> None:
    """직원 확정(일반 건) 또는 사장 승인(예외 건) 뒤에만 부른다 (R3).
    커밋은 부른 쪽에서 한다. 줄마다 반영한 수량·환산값·단가를 남겨 두어,
    나중에 상품을 고쳐도 이 건의 값은 바뀌지 않는다 (US-08).
    단가는 명세서 단가(기준 단위 1개당)를 쓰고, 읽지 못했으면 상품 기준 단가를 쓴다.
    상품의 기준 단가(base_unit_price)는 바꾸지 않는다 (매입 단가와 같은 값인지 미정)."""
    order = db.get(PurchaseOrder, inspection.purchase_order_id)
    for check in evaluation.lines:
        product = check.product
        line = check.line
        line.applied_base_quantity = check.base_quantity
        line.applied_conversion_qty = product.conversion_qty
        line.applied_unit_price = (
            check.per_base_unit_price
            if check.per_base_unit_price is not None
            else product.base_unit_price
        )

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
        before = stock.quantity
        stock.quantity = before + check.base_quantity
        history.record(
            db,
            inspection.id,
            actor,
            "재고 반영",
            f"inventory {product.product_code}",
            before,
            stock.quantity,
        )
    order.status = ORDER_RECEIVED
