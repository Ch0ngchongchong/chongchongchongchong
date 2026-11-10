# 판독 흐름 (데모 3단계, US-03): `판독 중` → `직원 확인 대기` (실패하면 `업로드 대기`)
# 와 발주 대조·재고 반영(데모 4~5단계, US-04·R3).
#
#   원본 파일 ─OCR─▶ 텍스트 ─가리기─▶ 가린 텍스트 ─LLM(정리·후보)─▶ 초안 줄
#
# 원본 파일은 OCR에만 넘긴다. LLM 단계에는 가린 텍스트와 상품 기준 정보만 넘긴다.
# 이 파일의 판독 단계는 재고를 바꾸지 않는다. 재고는 apply_stock()에서만 바꾸고,
# apply_stock()은 직원 확정 API에서만 부른다 (R3).

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.inspection import Inspection
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
from app.services.structurer import ProductRef, get_structurer

# 줄 대조 결과
MATCH_OK = "일치"
MATCH_NEEDS_CHECK = "확인 필요"  # 품목이나 수량이 비어 있어 직원이 채워야 함
MATCH_NOT_IN_ORDER = "발주에 없음"
MATCH_QTY_DIFF = "수량 다름"
MATCH_PRICE_DIFF = "단가 다름"
MATCH_MISSING_IN_STATEMENT = "명세서에 없음"  # 발주 줄인데 명세서에 없음


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
            text = get_ocr_engine().read_text(
                Path(document.stored_path), document.content_type
            )
            products = db.scalars(
                select(Product).where(Product.store_id == order.store_id)
            ).all()
            refs = [ProductRef(p.id, p.product_code, p.name, p.spec) for p in products]
            drafts = get_structurer().structure(mask_sensitive(text), refs)
            if not drafts:
                raise OcrError("명세서에서 품목 줄을 찾지 못했습니다")
        except OcrError as exc:
            # 판독 실패: `업로드 대기`로 돌아가고,
            # 다시 올려 달라는 안내를 남긴다 (US-03)
            # 알림 발송 자체는 아직 없다. 화면이 폴링으로 read_error를 보여 준다.
            db.rollback()
            inspection.status = INSPECTION_STATUS_UPLOAD_WAITING
            if document is not None:
                document.read_error = f"{exc}. 명세서를 다시 올려 주세요"
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
                    product_id=top,
                    quantity=draft.quantity,
                    unit=draft.unit,
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


@dataclass
class MissingOrderLine:
    product_id: int
    order_quantity: int


@dataclass
class Evaluation:
    lines: list[LineCheck]
    missing: list[MissingOrderLine]

    @property
    def check_count(self) -> int:
        """직원이 채워야 확정할 수 있는 칸 수 (품목 미선택·수량 없음)."""
        return sum(1 for c in self.lines if c.status == MATCH_NEEDS_CHECK)

    @property
    def all_match(self) -> bool:
        return not self.missing and all(c.status == MATCH_OK for c in self.lines)


def evaluate(db: Session, inspection: Inspection) -> Evaluation:
    order = db.get(PurchaseOrder, inspection.purchase_order_id)
    ordered = {}
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
        if product is None or line.quantity is None:
            checks.append(LineCheck(line, product, None, None, MATCH_NEEDS_CHECK))
            continue
        base = to_base_quantity(line.quantity, line.unit, product)
        received[product.id] = received.get(product.id, 0) + base
        checks.append(LineCheck(line, product, base, ordered.get(product.id), ""))

    for check in checks:
        if check.status:
            continue
        product = check.product
        if product.id not in ordered:
            check.status = MATCH_NOT_IN_ORDER
        elif received[product.id] != ordered[product.id]:
            check.status = MATCH_QTY_DIFF
        elif (
            check.line.read_unit_price is not None
            and product.base_unit_price is not None
            and _base_unit_price(check.line, product) != product.base_unit_price
        ):
            check.status = MATCH_PRICE_DIFF
        else:
            check.status = MATCH_OK

    missing = [
        MissingOrderLine(product_id, qty)
        for product_id, qty in ordered.items()
        if product_id not in received
    ]
    return Evaluation(checks, missing)


def _base_unit_price(line: InspectionLine, product: Product) -> int:
    """읽은 단가를 기준 단위 1개당 단가로 바꾼다.
    포장 단위 단가면 환산값으로 나눈다."""
    per_unit = to_base_quantity(1, line.unit, product)
    return line.read_unit_price // per_unit if per_unit else line.read_unit_price


# ---------- 재고 반영 ----------


def apply_stock(db: Session, inspection: Inspection, evaluation: Evaluation) -> None:
    """직원 확정 뒤에만 부른다 (R3). 커밋은 부른 쪽에서 한다.
    확정 때의 환산값·단가를 줄에 남겨 둔다 (나중에 상품을 고쳐도 이 건은 그대로)."""
    order = db.get(PurchaseOrder, inspection.purchase_order_id)
    for check in evaluation.lines:
        product = check.product
        check.line.applied_base_quantity = check.base_quantity
        check.line.applied_conversion_qty = product.conversion_qty
        check.line.applied_unit_price = product.base_unit_price

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
        stock.quantity += check.base_quantity
    order.status = ORDER_RECEIVED
