# 입고 검수 건 엔드포인트 (첫 데모 시나리오 1~5단계 / US-03·US-04 / R3)
# API.md에 아직 항목이 없다. 경로·오류 코드·HTTP 상태 코드는 기존 API와 같은 규칙으로
# 맞춘 [제안]이며 PM이 API.md에 옮겨야 한다.
#
#   1  GET  /inspections                      업로드 대기 건 찾기
#   2  POST /inspections/{id}/document        명세서 올리기: 업로드 대기 → 판독 중
#   3  (백그라운드) 판독                         판독 중 → 직원 확인 대기
#                                               (실패 시 업로드 대기)
#      GET  /inspections/{id}                 화면이 폴링으로 상태·초안을 다시 확인
#   4  PATCH /inspections/{id}/lines/{line_id} (필요할 때) 후보 고르기·수량 고치기
#      POST /inspections/{id}/confirm         직원 확정
#   5  → 모두 일치: 재고 반영 완료 + 발주 입고 완료
#      → 다르면: 사장 승인 대기 (재고 그대로)
#
# 만들지 않은 것: 사장 승인·반려(US-06), 알림 발송, 원본 파일 내려받기.
# 업로드·확정을 직원만 할 수 있는지는 정하지 않아 역할로 막지 않는다.


from datetime import timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.audit import ChangeHistory, DocumentContent, ExceptionPhoto, ReadingLog
from app.models.inspection import Inspection
from app.models.notification import Notification
from app.models.product import Product
from app.models.purchase_order import PurchaseOrder
from app.models.receiving import (
    INSPECTION_OWNER_APPROVAL,
    INSPECTION_READING,
    INSPECTION_STAFF_REVIEW,
    INSPECTION_STATUS_UPLOAD_WAITING,
    INSPECTION_STOCK_APPLIED,
    InspectionDocument,
    InspectionLine,
)
from app.models.user import StoreUser
from app.routers.products import error_response, forbidden_unless_role, get_current_user
from app.schemas.inspection import (
    InspectionLineCreate,
    InspectionLineUpdate,
    InspectionOut,
    ReasonInput,
)
from app.services.reading import (
    apply_stock,
    evaluate,
    latest_document,
    run_reading,
)

router = APIRouter(prefix="/inspections", tags=["inspections"])

# 올릴 수 있는 파일 (사진·PDF). text/plain은 데모 OCR 리허설·테스트용이다.
ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/heic",
    "application/pdf",
    "text/plain",
}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # [제안] 10MB


def _find(db: Session, inspection_id: int, user: StoreUser, lock: bool = False):
    # 다른 매장 검수 건은 없는 건과 똑같이 다룬다 (발주 건을 거쳐 매장을 확인)
    query = (
        select(Inspection)
        .join(PurchaseOrder, PurchaseOrder.id == Inspection.purchase_order_id)
        .where(Inspection.id == inspection_id, PurchaseOrder.store_id == user.store_id)
    )
    if lock:
        query = query.with_for_update(of=Inspection)
    return db.scalar(query)


def _not_found():
    return error_response(
        404, "INSPECTION_NOT_FOUND", "입고 검수 건을 찾을 수 없습니다"
    )


def _invalid_status(inspection: Inspection):
    return error_response(
        400,
        "INVALID_STATUS_TRANSITION",
        f"지금 상태({inspection.status})에서는 할 수 없습니다",
    )


def _forbidden_unless_assigned(user: StoreUser, inspection: Inspection):
    """사장님은 모든 검수 건을 다룰 수 있다. 직원은 담당(처음 명세서를 올린)
    검수 건만 다룰 수 있다 (2026-11-16 멘토 데모 피드백 팀 결정).
    담당자가 아직 없으면(사장님이 올렸거나 업로드 전) 막지 않는다."""
    if user.role == "사장님":
        return None
    if (
        inspection.assigned_employee_id is not None
        and inspection.assigned_employee_id != user.id
    ):
        return error_response(
            403, "FORBIDDEN_ROLE", "다른 직원이 담당하는 입고 건입니다"
        )
    return None


def _to_out(db: Session, inspection: Inspection) -> dict:
    document = latest_document(db, inspection.id)
    evaluation = evaluate(db, inspection)
    histories = db.scalars(
        select(ChangeHistory)
        .where(ChangeHistory.inspection_id == inspection.id)
        .order_by(ChangeHistory.id.desc())
    ).all()
    exception_reason = next(
        (
            h.new_value.get("reason")
            for h in histories
            if h.kind == "직원 확정" and h.new_value and h.new_value.get("reason")
        ),
        None,
    )
    reject_reason = next(
        (
            h.new_value.get("reason")
            for h in histories
            if h.kind == "reject" and h.new_value
        ),
        None,
    )
    return {
        "id": inspection.id,
        "purchase_order_id": inspection.purchase_order_id,
        "status": inspection.status,
        "ai_draft": inspection.status == INSPECTION_STAFF_REVIEW,
        "exception_reason": exception_reason,
        "reject_reason": reject_reason,
        "document": None
        if document is None
        else {
            "id": document.id,
            "filename": document.filename,
            "content_type": document.content_type,
            "uploaded_at": document.uploaded_at,
            "read_error": document.read_error,
        },
        "lines": [
            {
                "id": c.line.id,
                "line_no": c.line.line_no,
                "read": {
                    "name": c.line.read_name,
                    "spec": c.line.read_spec,
                    "quantity": c.line.read_quantity,
                    "unit": c.line.read_unit,
                    "unit_price": c.line.read_unit_price,
                    "amount": c.line.read_amount,
                },
                "candidates": c.line.candidates,
                "uncertain_fields": c.line.uncertain_fields,
                "product_id": c.line.product_id,
                "quantity": c.line.quantity,
                "unit": c.line.unit,
                "unit_price": c.line.unit_price,
                "amount": c.line.amount,
                "manual_base_quantity": c.line.manual_base_quantity,
                "damaged": c.line.damaged,
                # 재고 반영이 끝난 건은 그때 저장한 값을 보여 준다
                "base_quantity": c.line.applied_base_quantity
                if c.line.applied_base_quantity is not None
                else c.base_quantity,
                "applied_unit_price": c.line.applied_unit_price,
                "order_quantity": c.order_quantity,
                "match_status": c.status,
                "rule_violations": c.rule_violations,
                "checked": c.line.checked,
            }
            for c in evaluation.lines
        ],
        "missing_order_lines": [
            {"product_id": m.product_id, "order_quantity": m.order_quantity}
            for m in evaluation.missing
        ],
        "short_order_lines": [
            {
                "product_id": g.product_id,
                "order_quantity": g.order_quantity,
                "received_quantity": g.received_quantity,
                "short_quantity": g.short_quantity,
            }
            for g in evaluation.short
        ],
        "check_count": evaluation.check_count,
        "all_match": evaluation.all_match,
        "total_amount": inspection.read_total_amount,
        "document_date": inspection.read_document_date,
        "summary_mismatch": evaluation.summary_mismatch,
        "summary_checked": evaluation.summary_checked,
        "final_amount": evaluation.final_amount,
        "amount_over_limit": evaluation.amount_over_limit,
    }


@router.get("", response_model=list[InspectionOut])
def list_inspections(
    status: str | None = None,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """내 매장 검수 건 목록 (데모 1단계).
    ?status=업로드 대기 처럼 상태로 거를 수 있다."""
    query = (
        select(Inspection)
        .join(PurchaseOrder, PurchaseOrder.id == Inspection.purchase_order_id)
        .where(PurchaseOrder.store_id == user.store_id)
        .order_by(Inspection.id)
    )
    if status is not None:
        query = query.where(Inspection.status == status)
    return [_to_out(db, inspection) for inspection in db.scalars(query).all()]


@router.get("/{inspection_id}", response_model=InspectionOut)
def get_inspection(
    inspection_id: int,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """검수 건 1건. 화면은 `판독 중`인 동안 이 API를 폴링한다 (STACK.md)."""
    inspection = _find(db, inspection_id, user)
    if inspection is None:
        return _not_found()
    return _to_out(db, inspection)


@router.post("/{inspection_id}/document", response_model=InspectionOut)
def upload_document(
    inspection_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """명세서 사진·PDF를 올린다: `업로드 대기` → `판독 중` (데모 2단계, US-03).
    판독은 응답 뒤 백그라운드에서 돈다."""
    inspection = _find(db, inspection_id, user, lock=True)
    if inspection is None:
        return _not_found()
    if (denied := _forbidden_unless_assigned(user, inspection)) is not None:
        return denied
    if inspection.status != INSPECTION_STATUS_UPLOAD_WAITING:
        return _invalid_status(inspection)

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        return error_response(
            400,
            "UNSUPPORTED_FILE_TYPE",
            "사진(JPG·PNG·HEIC) 또는 PDF만 올릴 수 있습니다",
        )

    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        return error_response(400, "EMPTY_FILE", "빈 파일입니다")
    if len(data) > MAX_UPLOAD_BYTES:
        return error_response(
            400, "FILE_TOO_LARGE", "10MB 이하 파일만 올릴 수 있습니다"
        )

    document = InspectionDocument(
        inspection_id=inspection.id,
        uploaded_by=user.id,
        filename=file.filename or "document",
        content_type=content_type,
        stored_path="database",
    )
    db.add(document)
    db.flush()
    db.add(DocumentContent(document_id=document.id, data=data))
    if inspection.assigned_employee_id is None and user.role == "직원":
        inspection.assigned_employee_id = user.id
    inspection.status = INSPECTION_READING
    db.commit()
    db.refresh(inspection)

    background_tasks.add_task(run_reading, inspection.id)
    return _to_out(db, inspection)


@router.post("/{inspection_id}/lines", response_model=InspectionOut)
def add_line(
    inspection_id: int,
    body: InspectionLineCreate,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """판독 결과에 없는 줄을 직원이 추가한다 (US-04 인수 조건, 미팅1 질의 3
    줄 누락·피드백 8 행 누락률). OCR이 읽은 값이 없으니 read_* 는 비워 두고,
    '판독 원본' 이력이 없는 줄로 남아 정확도 지표의 행 누락률에 그대로
    잡힌다(PR #15 added_line_ratio)."""
    inspection = _find(db, inspection_id, user, lock=True)
    if inspection is None:
        return _not_found()
    if (denied := _forbidden_unless_assigned(user, inspection)) is not None:
        return denied
    if inspection.status != INSPECTION_STAFF_REVIEW:
        return _invalid_status(inspection)
    if body.quantity <= 0:
        return error_response(400, "INVALID_QUANTITY", "수량은 1 이상이어야 합니다")
    product = db.scalar(
        select(Product).where(
            Product.id == body.product_id, Product.store_id == user.store_id
        )
    )
    if product is None:
        return error_response(
            400, "UNREGISTERED_PRODUCT", "등록되지 않은 상품이 있습니다"
        )

    existing_lines = db.scalars(
        select(InspectionLine).where(InspectionLine.inspection_id == inspection.id)
    ).all()
    next_line_no = max((line.line_no for line in existing_lines), default=0) + 1

    line = InspectionLine(
        inspection_id=inspection.id,
        line_no=next_line_no,
        read_name=product.name or product.product_code,
        product_id=product.id,
        quantity=body.quantity,
        unit=body.unit or product.base_unit,
    )
    db.add(line)
    db.flush()
    db.add(
        ChangeHistory(
            inspection_id=inspection.id,
            changed_by=user.id,
            kind="직원이 추가한 줄",
            new_value={
                "line_id": line.id,
                "line_no": next_line_no,
                "product_id": product.id,
                "quantity": body.quantity,
                "unit": line.unit,
            },
        )
    )
    db.commit()
    db.refresh(inspection)
    return _to_out(db, inspection)


@router.patch("/{inspection_id}/lines/{line_id}", response_model=InspectionOut)
def update_line(
    inspection_id: int,
    line_id: int,
    body: InspectionLineUpdate,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """직원이 품목 후보를 고르거나 수량을 고친다. `직원 확인 대기`에서만 된다.
    재고는 바뀌지 않는다 (R3)."""
    inspection = _find(db, inspection_id, user, lock=True)
    if inspection is None:
        return _not_found()
    if (denied := _forbidden_unless_assigned(user, inspection)) is not None:
        return denied
    if inspection.status != INSPECTION_STAFF_REVIEW:
        return _invalid_status(inspection)
    line = db.scalar(
        select(InspectionLine).where(
            InspectionLine.id == line_id, InspectionLine.inspection_id == inspection.id
        )
    )
    if line is None:
        return error_response(404, "LINE_NOT_FOUND", "판독 줄을 찾을 수 없습니다")

    changes = body.model_dump(exclude_unset=True)
    for name in ("quantity", "manual_base_quantity"):
        if name in changes and changes[name] is not None and changes[name] <= 0:
            return error_response(400, "INVALID_QUANTITY", "수량은 1 이상이어야 합니다")
    for name in ("unit_price", "amount"):
        if name in changes and changes[name] is not None and changes[name] <= 0:
            return error_response(
                400, "INVALID_UNIT_PRICE_OR_AMOUNT", "단가·금액은 0보다 커야 합니다"
            )
    if changes.get("product_id") is not None:
        exists = db.scalar(
            select(Product.id).where(
                Product.id == changes["product_id"],
                Product.store_id == user.store_id,
            )
        )
        if exists is None:
            return error_response(
                400, "UNREGISTERED_PRODUCT", "등록되지 않은 상품이 있습니다"
            )
    # 고치면 그 줄의 강조 칸을 확인한 것으로 본다. checked를 직접 보내면
    # (false 포함) 그 값을 따른다
    for name in ("damaged", "checked"):
        if name in changes and changes[name] is None:
            changes.pop(name)
    changes.setdefault("checked", True)
    for field, value in changes.items():
        old = getattr(line, field)
        if old != value:
            db.add(
                ChangeHistory(
                    inspection_id=inspection.id,
                    changed_by=user.id,
                    kind="직원 수정",
                    old_value={"line_id": line.id, field: old},
                    new_value={"line_id": line.id, field: value},
                )
            )
        setattr(line, field, value)
    db.commit()
    return _to_out(db, inspection)


@router.post("/{inspection_id}/summary-check", response_model=InspectionOut)
def check_summary(
    inspection_id: int,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """줄 금액 합≠합계(규칙 검증 실패)를 확인했다고 표시한다. `직원 확인 대기`에서만
    된다. PR #8 설명에서 약속했던 'PATCH /inspections/{id}/summary'에 해당하는
    기능인데 실제로는 없었다 — 이번에 새로 만들었다."""
    inspection = _find(db, inspection_id, user, lock=True)
    if inspection is None:
        return _not_found()
    if (denied := _forbidden_unless_assigned(user, inspection)) is not None:
        return denied
    if inspection.status != INSPECTION_STAFF_REVIEW:
        return _invalid_status(inspection)
    if not inspection.summary_checked:
        inspection.summary_checked = True
        db.add(
            ChangeHistory(
                inspection_id=inspection.id,
                changed_by=user.id,
                kind="합계 확인",
                old_value={"summary_checked": False},
                new_value={"summary_checked": True},
            )
        )
        db.commit()
    return _to_out(db, inspection)


@router.post("/{inspection_id}/confirm", response_model=InspectionOut)
def confirm_inspection(
    inspection_id: int,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    body: ReasonInput | None = None,
):
    """직원 확정 (데모 4~5단계, US-04).
    - 확인할 칸이 남아 있으면 확정하지 않는다
    - 발주와 모두 같으면: 재고에 반영하고 `재고 반영 완료`, 발주는 `입고 완료` (R3)
    - 다른 줄이 있으면: `사장 승인 대기`로 가고 재고는 그대로다 (US-06)"""
    inspection = _find(db, inspection_id, user, lock=True)
    if inspection is None:
        return _not_found()
    if (denied := _forbidden_unless_assigned(user, inspection)) is not None:
        return denied
    if inspection.status != INSPECTION_STAFF_REVIEW:
        return _invalid_status(inspection)

    evaluation = evaluate(db, inspection)
    if evaluation.check_count > 0:
        return error_response(
            400,
            "CHECK_REQUIRED",
            f"확인할 칸이 {evaluation.check_count}개 남아 있습니다",
        )

    if not evaluation.all_match and (body is None or not body.reason.strip()):
        return error_response(400, "REASON_REQUIRED", "예외 사유를 입력해 주세요")
    if evaluation.all_match:
        apply_stock(db, inspection, evaluation)
        inspection.status = INSPECTION_STOCK_APPLIED
    else:
        inspection.status = INSPECTION_OWNER_APPROVAL
        # 최종 금액이 발주의 금액 경고 기준을 넘은 예외 건은 사장님에게
        # 능동적으로 알린다 (2026-11-16 멘토 데모 피드백 팀 결정의 "알람을
        # 준다" 부분. 그 밖의 예외 사유는 알림을 만들지 않는다)
        if evaluation.amount_over_limit:
            owners = db.scalars(
                select(StoreUser).where(
                    StoreUser.store_id == user.store_id, StoreUser.role == "사장님"
                )
            ).all()
            for owner in owners:
                db.add(
                    Notification(
                        user_id=owner.id,
                        inspection_id=inspection.id,
                        message="최종 금액이 한도를 넘어 승인이 필요합니다",
                    )
                )
    db.add(
        ChangeHistory(
            inspection_id=inspection.id,
            changed_by=user.id,
            kind="직원 확정",
            old_value={"status": INSPECTION_STAFF_REVIEW},
            new_value={
                "status": inspection.status,
                "reason": body.reason if body else None,
            },
        )
    )
    if evaluation.all_match:
        for check in evaluation.lines:
            db.add(
                ChangeHistory(
                    inspection_id=inspection.id,
                    changed_by=user.id,
                    kind="재고 반영",
                    new_value={
                        "product_id": check.product.id,
                        "quantity": check.base_quantity,
                    },
                )
            )
    db.commit()
    db.refresh(inspection)
    return _to_out(db, inspection)


@router.get("/{inspection_id}/history")
def inspection_history(
    inspection_id: int,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if _find(db, inspection_id, user) is None:
        return _not_found()
    denied = forbidden_unless_role(
        user, "사장님", message="사장님만 조회할 수 있습니다"
    )
    if denied is not None:
        return denied
    rows = db.scalars(
        select(ChangeHistory)
        .where(ChangeHistory.inspection_id == inspection_id)
        .order_by(ChangeHistory.changed_at, ChangeHistory.id)
    ).all()
    return [
        {
            "id": r.id,
            "changed_by": r.changed_by,
            "changed_at": r.changed_at,
            "kind": r.kind,
            "old_value": r.old_value,
            "new_value": r.new_value,
        }
        for r in rows
    ]


@router.get("/{inspection_id}/reading-logs")
def reading_logs(
    inspection_id: int,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if _find(db, inspection_id, user) is None:
        return _not_found()
    denied = forbidden_unless_role(
        user, "사장님", message="사장님만 조회할 수 있습니다"
    )
    if denied is not None:
        return denied
    rows = db.scalars(
        select(ReadingLog)
        .where(ReadingLog.inspection_id == inspection_id)
        .order_by(ReadingLog.id)
    ).all()
    return [
        {
            "id": r.id,
            "document_id": r.document_id,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "cost": r.cost,
            "elapsed_seconds": r.elapsed_seconds,
            "outcome": r.outcome,
        }
        for r in rows
    ]


@router.get("/{inspection_id}/metrics")
def inspection_metrics(
    inspection_id: int,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """판독 원본값과 직원 확정값을 비교한 필드별 정확도·고친 줄 비율·
    행 누락률·업로드~확정 시간 (US-07, 미팅1 피드백 8).

    - 품목·수량·단위·단가·금액은 직원이 PATCH lines/{line_id}로 고칠 수 있는
      필드라 판독 원본(candidates[0]·read_quantity·read_unit·read_unit_price·
      read_amount)과 비교해 정확도를 잰다.
    - 행 누락률(직원이 추가한 줄 비율)은 '판독 원본' 이력에 없는 line_no를
      센다. 지금은 직원이 줄을 추가하는 API가 없어 항상 0이지만, 생기면
      이 계산은 바로 맞게 작동한다.
    """
    inspection = _find(db, inspection_id, user)
    if inspection is None:
        return _not_found()
    denied = forbidden_unless_role(
        user, "사장님", message="사장님만 조회할 수 있습니다"
    )
    if denied is not None:
        return denied

    lines = db.scalars(
        select(InspectionLine).where(InspectionLine.inspection_id == inspection_id)
    ).all()
    total = len(lines)

    original_line_nos = {
        h.new_value["line_no"]
        for h in db.scalars(
            select(ChangeHistory).where(
                ChangeHistory.inspection_id == inspection_id,
                ChangeHistory.kind == "판독 원본",
            )
        ).all()
        if h.new_value
    }

    item_matches = quantity_matches = unit_matches = 0
    unit_price_matches = amount_matches = corrected = added = 0
    for line in lines:
        top_candidate = line.candidates[0]["product_id"] if line.candidates else None
        if line.product_id == top_candidate:
            item_matches += 1
        if line.quantity == line.read_quantity:
            quantity_matches += 1
        if line.unit == line.read_unit:
            unit_matches += 1
        if line.unit_price == line.read_unit_price:
            unit_price_matches += 1
        if line.amount == line.read_amount:
            amount_matches += 1
        if (
            line.product_id != top_candidate
            or line.quantity != line.read_quantity
            or line.unit != line.read_unit
            or line.unit_price != line.read_unit_price
            or line.amount != line.read_amount
        ):
            corrected += 1
        if line.line_no not in original_line_nos:
            added += 1

    def ratio(count: int) -> float | None:
        return None if total == 0 else count / total

    confirm_entry = db.scalar(
        select(ChangeHistory)
        .where(
            ChangeHistory.inspection_id == inspection_id,
            ChangeHistory.kind == "직원 확정",
        )
        .order_by(ChangeHistory.id.desc())
    )
    document = latest_document(db, inspection_id)
    upload_to_confirm_seconds = None
    if confirm_entry is not None and document is not None:
        upload_to_confirm_seconds = max(
            0,
            (
                confirm_entry.changed_at.replace(tzinfo=timezone.utc)
                - document.uploaded_at.replace(tzinfo=timezone.utc)
            ).total_seconds(),
        )

    return {
        "line_count": total,
        "field_accuracy": {
            "품목": ratio(item_matches),
            "수량": ratio(quantity_matches),
            "단위": ratio(unit_matches),
            "단가": ratio(unit_price_matches),
            "금액": ratio(amount_matches),
        },
        "corrected_line_ratio": ratio(corrected),
        "added_line_ratio": ratio(added),
        "upload_to_confirm_seconds": upload_to_confirm_seconds,
    }


@router.post("/{inspection_id}/exception-photos")
def upload_exception_photo(
    inspection_id: int,
    file: UploadFile = File(...),
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    inspection = _find(db, inspection_id, user, lock=True)
    if inspection is None:
        return _not_found()
    if (denied := _forbidden_unless_assigned(user, inspection)) is not None:
        return denied
    if inspection.status != INSPECTION_STAFF_REVIEW:
        return _invalid_status(inspection)
    content_type = (file.content_type or "").lower()
    if content_type not in {"image/jpeg", "image/png", "image/heic"}:
        return error_response(400, "UNSUPPORTED_FILE_TYPE", "사진만 올릴 수 있습니다")
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if not data or len(data) > MAX_UPLOAD_BYTES:
        return error_response(400, "INVALID_FILE_SIZE", "사진은 10MB 이하이어야 합니다")
    photo = ExceptionPhoto(
        inspection_id=inspection_id,
        uploaded_by=user.id,
        filename=file.filename or "photo",
        content_type=content_type,
        data=data,
    )
    db.add(photo)
    db.flush()
    db.add(
        ChangeHistory(
            inspection_id=inspection_id,
            changed_by=user.id,
            kind="예외 사진 추가",
            new_value={"photo_id": photo.id},
        )
    )
    db.commit()
    return {
        "id": photo.id,
        "filename": photo.filename,
        "content_type": photo.content_type,
    }


@router.get("/{inspection_id}/exception-photos")
def list_exception_photos(
    inspection_id: int,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if _find(db, inspection_id, user) is None:
        return _not_found()
    photos = db.scalars(
        select(ExceptionPhoto)
        .where(ExceptionPhoto.inspection_id == inspection_id)
        .order_by(ExceptionPhoto.id)
    ).all()
    return [
        {
            "id": p.id,
            "filename": p.filename,
            "content_type": p.content_type,
            "uploaded_at": p.uploaded_at,
        }
        for p in photos
    ]


@router.get("/{inspection_id}/exception-photos/{photo_id}")
def get_exception_photo(
    inspection_id: int,
    photo_id: int,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if _find(db, inspection_id, user) is None:
        return _not_found()
    photo = db.scalar(
        select(ExceptionPhoto).where(
            ExceptionPhoto.id == photo_id, ExceptionPhoto.inspection_id == inspection_id
        )
    )
    if photo is None:
        return error_response(404, "PHOTO_NOT_FOUND", "사진을 찾을 수 없습니다")
    return Response(
        content=photo.data,
        media_type=photo.content_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/{inspection_id}/{action}", response_model=InspectionOut)
def owner_action(
    inspection_id: int,
    action: str,
    body: ReasonInput | None = None,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    inspection = _find(db, inspection_id, user, lock=True)
    if inspection is None:
        return _not_found()
    transitions = {
        "approve": (INSPECTION_OWNER_APPROVAL, INSPECTION_STOCK_APPLIED, "사장님"),
        "reject": (INSPECTION_OWNER_APPROVAL, "반려", "사장님"),
        "cancel-confirmation": (
            INSPECTION_OWNER_APPROVAL,
            INSPECTION_STAFF_REVIEW,
            "직원",
        ),
        "reinspect": ("반려", INSPECTION_STAFF_REVIEW, "직원"),
        "close": ("반려", "검수 종료", "사장님"),
    }
    if action not in transitions:
        return error_response(404, "NOT_FOUND", "요청한 작업을 찾을 수 없습니다")
    before, after, role = transitions[action]
    if (denied := forbidden_unless_role(user, role)) is not None:
        return denied
    if (denied := _forbidden_unless_assigned(user, inspection)) is not None:
        return denied
    if inspection.status != before:
        return _invalid_status(inspection)
    if action == "reject" and (body is None or not body.reason.strip()):
        return error_response(400, "REASON_REQUIRED", "반려 사유를 입력해 주세요")
    if action == "approve":
        evaluation = evaluate(db, inspection)
        if evaluation.check_count:
            return error_response(
                400, "CHECK_REQUIRED", "확인이 필요한 항목이 있습니다"
            )
        apply_stock(db, inspection, evaluation)
        for check in evaluation.lines:
            db.add(
                ChangeHistory(
                    inspection_id=inspection.id,
                    changed_by=user.id,
                    kind="재고 반영",
                    new_value={
                        "product_id": check.product.id,
                        "quantity": check.base_quantity,
                    },
                )
            )
    inspection.status = after
    db.add(
        ChangeHistory(
            inspection_id=inspection.id,
            changed_by=user.id,
            kind=action,
            old_value={"status": before},
            new_value={"status": after, "reason": body.reason if body else None},
        )
    )
    db.commit()
    return _to_out(db, inspection)
