# 입고 검수 건 엔드포인트
# (US-03 판독, US-04 확정, US-05 환산, US-06 예외 건, US-07 이력)
# API.md에 아직 항목이 없다. 경로·오류 코드·HTTP 상태 코드는 기존 API와 같은 규칙으로
# 맞춘 [제안]이며 PM이 API.md에 옮겨야 한다.
#
#   업로드 대기 ─document─▶ 판독 중 ─(판독)─▶ 직원 확인 대기
#   직원 확인 대기 ─confirm─▶ 재고 반영 완료 (일반 건)
#                           ▶ 사장 승인 대기 (예외 건)
#   사장 승인 대기 ─cancel-confirm─▶ 직원 확인 대기
#                  ─approve─▶ 승인 ▶ 재고 반영 완료
#                  ─reject─▶ 반려 ─recheck─▶ 직원 확인 대기
#                                 ─close─▶ 검수 종료
#
# 승인·반려·검수 종료는 사장님만. 업로드·수정·확정·확정 취소·재검수를 직원만 할 수
# 있는지는 정하지 않아 역할로 막지 않는다.

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.history import ChangeLog, ReadingLog
from app.models.inspection import Inspection
from app.models.product import Product
from app.models.purchase_order import ORDER_AWAITING_DELIVERY, PurchaseOrder
from app.models.receiving import (
    FILE_EXCEPTION_PHOTO,
    FILE_STATEMENT,
    INSPECTION_APPROVED,
    INSPECTION_CLOSED,
    INSPECTION_OWNER_APPROVAL,
    INSPECTION_READING,
    INSPECTION_REJECTED,
    INSPECTION_STAFF_REVIEW,
    INSPECTION_STATUS_UPLOAD_WAITING,
    INSPECTION_STOCK_APPLIED,
    InspectionDetail,
    InspectionFile,
    InspectionLine,
)
from app.models.user import StoreUser
from app.routers.products import error_response, get_current_user
from app.routers.purchase_orders import OWNER
from app.schemas.inspection import (
    ConfirmRequest,
    HistoryOut,
    InspectionCreate,
    InspectionLineUpdate,
    InspectionOut,
    RejectRequest,
    SummaryUpdate,
)
from app.services import history
from app.services.reading import (
    apply_stock,
    evaluate,
    get_detail,
    latest_statement,
    run_reading,
)

router = APIRouter(prefix="/inspections", tags=["inspections"])

PHOTO_TYPES = {"image/jpeg", "image/png", "image/heic"}
# 명세서는 사진·PDF만 (US-03 실패·거절)
STATEMENT_TYPES = PHOTO_TYPES | {"application/pdf"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # [제안] 10MB


def _statement_types() -> set[str]:
    # ALLOW_TEXT_UPLOAD=1 이면 text/plain도 받는다 (데모 OCR 리허설·테스트용).
    # 기본은 사진·PDF만이다.
    if os.environ.get("ALLOW_TEXT_UPLOAD") == "1":
        return STATEMENT_TYPES | {"text/plain"}
    return STATEMENT_TYPES


def _upload_dir() -> Path:
    # 원본 파일을 저장할 곳. 환경변수 UPLOAD_DIR, 없으면 ./uploads
    return Path(os.environ.get("UPLOAD_DIR", "uploads"))


# ---------- 공통 ----------


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


def _owner_only(user: StoreUser):
    # 예외 건 승인·반려·검수 종료는 사장님만 (US-06 권한)
    if user.role != OWNER:
        return error_response(403, "FORBIDDEN_ROLE", "사장님만 할 수 있습니다")
    return None


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _file_out(file: InspectionFile) -> dict:
    return {
        "id": file.id,
        "filename": file.filename,
        "content_type": file.content_type,
        "uploaded_at": file.uploaded_at,
    }


def _gap_out(gap) -> dict:
    return {
        "product_id": gap.product_id,
        "order_quantity": gap.order_quantity,
        "received_quantity": gap.received_quantity,
        "short_quantity": gap.short_quantity,
    }


def _line_out(check) -> dict:
    line = check.line
    return {
        "id": line.id,
        "line_no": line.line_no,
        "read": {
            "name": line.read_name,
            "spec": line.read_spec,
            "quantity": line.read_quantity,
            "unit": line.read_unit,
            "unit_price": line.read_unit_price,
            "amount": line.read_amount,
        },
        "candidates": line.candidates,
        "uncertain_fields": line.uncertain_fields,
        "product_id": line.product_id,
        "quantity": line.quantity,
        "unit": line.unit,
        "manual_base_quantity": line.manual_base_quantity,
        "damaged": line.damaged,
        "checked": line.checked,
        # 재고 반영이 끝난 건은 그때 반영한 값을 보여 준다
        "base_quantity": line.applied_base_quantity
        if line.applied_base_quantity is not None
        else check.base_quantity,
        "order_quantity": check.order_quantity,
        "open_checks": check.open_checks,
        "match_status": check.status,
        "applied_unit_price": line.applied_unit_price,
    }


def _to_out(db: Session, inspection: Inspection) -> dict:
    document = latest_statement(db, inspection.id)
    photos = db.scalars(
        select(InspectionFile)
        .where(
            InspectionFile.inspection_id == inspection.id,
            InspectionFile.kind == FILE_EXCEPTION_PHOTO,
        )
        .order_by(InspectionFile.id)
    ).all()
    detail = db.get(InspectionDetail, inspection.id)
    evaluation = evaluate(db, inspection)
    summary = None
    if detail is not None and evaluation.lines:
        summary = {
            "document_date": detail.document_date,
            "total_amount": detail.total_amount,
            "line_amount_sum": evaluation.line_amount_sum,
            "uncertain_fields": detail.uncertain_fields,
            "checked": detail.summary_checked,
            "open_checks": evaluation.summary_open_checks,
        }
    return {
        "id": inspection.id,
        "purchase_order_id": inspection.purchase_order_id,
        "status": inspection.status,
        "ai_draft": inspection.status == INSPECTION_STAFF_REVIEW,
        "document": None
        if document is None
        else {**_file_out(document), "read_error": document.read_error},
        "exception_photos": [_file_out(p) for p in photos],
        "summary": summary,
        "lines": [_line_out(c) for c in evaluation.lines],
        "missing_order_lines": [_gap_out(g) for g in evaluation.missing],
        "short_order_lines": [_gap_out(g) for g in evaluation.short],
        "check_count": evaluation.check_count,
        "exception_types": evaluation.exception_types,
        "all_match": evaluation.all_match,
        "exception_reason": detail.exception_reason if detail else None,
        "reject_reason": detail.reject_reason if detail else None,
    }


def _read_upload(file: UploadFile, allowed: set[str], type_message: str):
    """올린 파일을 검사하고 ((content_type, bytes), None) 또는 (None, 오류 응답)."""
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in allowed:
        return None, error_response(400, "UNSUPPORTED_FILE_TYPE", type_message)
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        return None, error_response(400, "EMPTY_FILE", "빈 파일입니다")
    if len(data) > MAX_UPLOAD_BYTES:
        return None, error_response(
            400, "FILE_TOO_LARGE", "10MB 이하 파일만 올릴 수 있습니다"
        )
    return (content_type, data), None


def _save_file(db, inspection, user, kind, file, content_type, data) -> InspectionFile:
    folder = _upload_dir() / str(inspection.id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}{Path(file.filename or '').suffix.lower()}"
    path.write_bytes(data)
    saved = InspectionFile(
        inspection_id=inspection.id,
        kind=kind,
        uploaded_by=user.id,
        filename=file.filename or path.name,
        content_type=content_type,
        stored_path=str(path),
        uploaded_at=datetime.now(UTC),
    )
    db.add(saved)
    db.flush()
    return saved


def _done(db: Session, inspection: Inspection) -> dict:
    db.commit()
    db.refresh(inspection)
    return _to_out(db, inspection)


# ---------- 조회·생성 ----------


@router.get("", response_model=list[InspectionOut])
def list_inspections(
    status: str | None = None,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """내 매장 검수 건 목록. ?status=사장 승인 대기 처럼 상태로 거를 수 있다."""
    query = (
        select(Inspection)
        .join(PurchaseOrder, PurchaseOrder.id == Inspection.purchase_order_id)
        .where(PurchaseOrder.store_id == user.store_id)
        .order_by(Inspection.id)
    )
    if status is not None:
        query = query.where(Inspection.status == status)
    return [_to_out(db, inspection) for inspection in db.scalars(query).all()]


@router.post("", response_model=InspectionOut)
def create_inspection(
    body: InspectionCreate,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """`검수 종료` 뒤 다시 납품되면 같은 발주에 새 검수 건을 `업로드 대기`로 만든다
    (US-06). 발주가 `입고 대기`이고 그 발주의 검수 건이 모두 `검수 종료`일 때만 된다."""
    order = db.scalar(
        select(PurchaseOrder)
        .where(
            PurchaseOrder.id == body.purchase_order_id,
            PurchaseOrder.store_id == user.store_id,
        )
        .with_for_update()
    )
    if order is None:
        return error_response(
            404, "PURCHASE_ORDER_NOT_FOUND", "발주를 찾을 수 없습니다"
        )
    if order.status != ORDER_AWAITING_DELIVERY:
        return error_response(
            400,
            "INVALID_STATUS_TRANSITION",
            f"지금 발주 상태({order.status})에서는 할 수 없습니다",
        )
    open_exists = db.scalar(
        select(Inspection.id).where(
            Inspection.purchase_order_id == order.id,
            Inspection.status != INSPECTION_CLOSED,
        )
    )
    if open_exists is not None:
        return error_response(
            400, "OPEN_INSPECTION_EXISTS", "아직 끝나지 않은 검수 건이 있습니다"
        )
    inspection = Inspection(
        purchase_order_id=order.id, status=INSPECTION_STATUS_UPLOAD_WAITING
    )
    db.add(inspection)
    db.flush()
    history.record(
        db,
        inspection.id,
        user.id,
        "검수 건 생성",
        "status",
        None,
        INSPECTION_STATUS_UPLOAD_WAITING,
    )
    return _done(db, inspection)


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


@router.get("/{inspection_id}/history", response_model=HistoryOut)
def get_history(
    inspection_id: int,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """변경 이력(시간순)과 판독 로그 (US-07). 이력을 고치거나 지우는 API는 없다.
    열람 범위가 미정이라 역할로 막지 않는다."""
    inspection = _find(db, inspection_id, user)
    if inspection is None:
        return _not_found()
    changes = db.scalars(
        select(ChangeLog)
        .where(ChangeLog.inspection_id == inspection.id)
        .order_by(ChangeLog.changed_at, ChangeLog.id)
    ).all()
    logs = db.scalars(
        select(ReadingLog)
        .where(ReadingLog.inspection_id == inspection.id)
        .order_by(ReadingLog.id)
    ).all()
    return {
        "inspection_id": inspection.id,
        "changes": [
            {
                "id": c.id,
                "changed_by": c.changed_by,
                "changed_at": c.changed_at,
                "action": c.action,
                "field": c.field,
                "old_value": c.old_value,
                "new_value": c.new_value,
            }
            for c in changes
        ],
        "reading_logs": [
            {
                "id": r.id,
                "file_id": r.file_id,
                "succeeded": r.succeeded,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "cost": r.cost,
                "elapsed_seconds": r.elapsed_seconds,
                "created_at": r.created_at,
            }
            for r in logs
        ],
    }


@router.get("/{inspection_id}/files/{file_id}")
def download_file(
    inspection_id: int,
    file_id: int,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """명세서 원본·예외 사진 보기 (US-06 사장님 화면). 같은 매장만 볼 수 있다."""
    inspection = _find(db, inspection_id, user)
    if inspection is None:
        return _not_found()
    file = db.scalar(
        select(InspectionFile).where(
            InspectionFile.id == file_id, InspectionFile.inspection_id == inspection.id
        )
    )
    if file is None or not Path(file.stored_path).exists():
        return error_response(404, "FILE_NOT_FOUND", "파일을 찾을 수 없습니다")
    return FileResponse(
        file.stored_path, media_type=file.content_type, filename=file.filename
    )


# ---------- US-03 업로드 ----------


@router.post("/{inspection_id}/document", response_model=InspectionOut)
def upload_document(
    inspection_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """명세서 사진·PDF를 올린다: `업로드 대기` → `판독 중` (US-03).
    판독은 응답 뒤 백그라운드에서 돈다."""
    inspection = _find(db, inspection_id, user, lock=True)
    if inspection is None:
        return _not_found()
    if inspection.status != INSPECTION_STATUS_UPLOAD_WAITING:
        return _invalid_status(inspection)
    checked, error = _read_upload(
        file, _statement_types(), "사진(JPG·PNG·HEIC) 또는 PDF만 올릴 수 있습니다"
    )
    if error is not None:
        return error
    content_type, data = checked

    saved = _save_file(db, inspection, user, FILE_STATEMENT, file, content_type, data)
    history.record(
        db, inspection.id, user.id, "업로드", "document", None, saved.filename
    )
    history.record_status(db, inspection, user.id, "업로드", INSPECTION_READING)
    out = _done(db, inspection)
    background_tasks.add_task(run_reading, inspection.id)
    return out


# ---------- US-04·US-05 직원 확인 ----------


@router.patch("/{inspection_id}/lines/{line_id}", response_model=InspectionOut)
def update_line(
    inspection_id: int,
    line_id: int,
    body: InspectionLineUpdate,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """직원이 줄을 고치거나 강조된 칸을 확인한다. `직원 확인 대기`에서만 된다.
    고치거나 확인하면 그 줄의 강조 칸(후보 여러 개·불확실한 값·금액 규칙)을
    확인한 것으로 본다. 재고는 바뀌지 않는다 (R3)."""
    inspection = _find(db, inspection_id, user, lock=True)
    if inspection is None:
        return _not_found()
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
        value = changes.get(name)
        if value is not None and value <= 0:
            return error_response(400, "INVALID_QUANTITY", "수량은 1 이상이어야 합니다")
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
    for name in ("damaged", "checked"):
        if name in changes and changes[name] is None:
            changes.pop(name)
    changes.setdefault("checked", True)

    for name, value in changes.items():
        old = getattr(line, name)
        if old == value:
            continue
        setattr(line, name, value)
        history.record(
            db,
            inspection.id,
            user.id,
            "줄 수정",
            f"line {line.line_no} {name}",
            old,
            value,
        )
    return _done(db, inspection)


@router.patch("/{inspection_id}/summary", response_model=InspectionOut)
def update_summary(
    inspection_id: int,
    body: SummaryUpdate,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """명세서 전체 칸(합계 불일치·불확실한 값)을 확인했다고 표시한다 (US-04)."""
    inspection = _find(db, inspection_id, user, lock=True)
    if inspection is None:
        return _not_found()
    if inspection.status != INSPECTION_STAFF_REVIEW:
        return _invalid_status(inspection)
    detail = get_detail(db, inspection.id)
    if detail.summary_checked != body.checked:
        history.record(
            db,
            inspection.id,
            user.id,
            "줄 수정",
            "summary checked",
            detail.summary_checked,
            body.checked,
        )
        detail.summary_checked = body.checked
    return _done(db, inspection)


@router.post("/{inspection_id}/exception-photos", response_model=InspectionOut)
def upload_exception_photo(
    inspection_id: int,
    file: UploadFile = File(...),
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """예외 사진(파손 등)을 올린다. `직원 확인 대기`에서만 된다 (US-06).
    예외 사진은 LLM에 보내지 않는다."""
    inspection = _find(db, inspection_id, user, lock=True)
    if inspection is None:
        return _not_found()
    if inspection.status != INSPECTION_STAFF_REVIEW:
        return _invalid_status(inspection)
    checked, error = _read_upload(
        file, PHOTO_TYPES, "사진(JPG·PNG·HEIC)만 올릴 수 있습니다"
    )
    if error is not None:
        return error
    content_type, data = checked
    saved = _save_file(
        db, inspection, user, FILE_EXCEPTION_PHOTO, file, content_type, data
    )
    history.record(
        db, inspection.id, user.id, "예외 사진", "exception_photo", None, saved.filename
    )
    return _done(db, inspection)


@router.post("/{inspection_id}/confirm", response_model=InspectionOut)
def confirm_inspection(
    inspection_id: int,
    body: ConfirmRequest | None = None,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """직원 확정 (US-04).
    - 확인할 칸이 남아 있으면 확정하지 않는다
    - 일반 건(발주와 모두 같음): 재고에 반영하고 `재고 반영 완료`, 발주는 `입고 완료`
    - 예외 건: 예외 사유가 있어야 하고 `사장 승인 대기`로 간다. 재고는 그대로 (US-06)"""
    inspection = _find(db, inspection_id, user, lock=True)
    if inspection is None:
        return _not_found()
    if inspection.status != INSPECTION_STAFF_REVIEW:
        return _invalid_status(inspection)

    evaluation = evaluate(db, inspection)
    if evaluation.check_count > 0:
        return error_response(
            400,
            "CHECK_REQUIRED",
            f"확인할 칸이 {evaluation.check_count}개 남아 있습니다",
        )

    if evaluation.all_match:
        history.record(db, inspection.id, user.id, "확정", "result", None, "일반 건")
        apply_stock(db, inspection, evaluation, user.id)
        history.record_status(db, inspection, user.id, "확정", INSPECTION_STOCK_APPLIED)
        return _done(db, inspection)

    reason = body.exception_reason if body else None
    if _blank(reason):
        return error_response(
            400, "EXCEPTION_REASON_REQUIRED", "예외 사유를 적어 주세요"
        )
    detail = get_detail(db, inspection.id)
    history.record(
        db,
        inspection.id,
        user.id,
        "확정",
        "result",
        None,
        {"예외 건": evaluation.exception_types},
    )
    history.record(
        db,
        inspection.id,
        user.id,
        "확정",
        "exception_reason",
        detail.exception_reason,
        reason.strip(),
    )
    detail.exception_reason = reason.strip()
    history.record_status(db, inspection, user.id, "확정", INSPECTION_OWNER_APPROVAL)
    return _done(db, inspection)


@router.post("/{inspection_id}/cancel-confirm", response_model=InspectionOut)
def cancel_confirm(
    inspection_id: int,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """사장님이 처리하기 전이면 직원이 확정을 취소한다:
    `사장 승인 대기` → `직원 확인 대기` (US-06). 승인·반려 뒤에는 할 수 없다."""
    inspection = _find(db, inspection_id, user, lock=True)
    if inspection is None:
        return _not_found()
    if inspection.status != INSPECTION_OWNER_APPROVAL:
        return _invalid_status(inspection)
    history.record_status(db, inspection, user.id, "확정 취소", INSPECTION_STAFF_REVIEW)
    return _done(db, inspection)


# ---------- US-06 사장님 처리 ----------


@router.post("/{inspection_id}/approve", response_model=InspectionOut)
def approve_inspection(
    inspection_id: int,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """사장님 승인: `사장 승인 대기` → `승인` → `재고 반영 완료` (US-06).
    `승인` 다음은 시스템이 바로 반영하므로 한 요청에서 두 단계를 처리한다.
    직원이 확정한 수량·단가로 재고를 반영하고 발주는 `입고 완료`가 된다.
    모자란 수량은 short_order_lines로 보인다 (발주 건에 남길 필드는 미정)."""
    if (denied := _owner_only(user)) is not None:
        return denied
    inspection = _find(db, inspection_id, user, lock=True)
    if inspection is None:
        return _not_found()
    if inspection.status != INSPECTION_OWNER_APPROVAL:
        return _invalid_status(inspection)
    evaluation = evaluate(db, inspection)
    if evaluation.check_count > 0:
        # 확정 뒤 상품 정보(환산값 등)가 바뀌어 수량을 다시 계산할 수 없는 경우
        return error_response(
            400,
            "CHECK_REQUIRED",
            f"확인할 칸이 {evaluation.check_count}개 남아 있습니다. "
            "직원이 확정을 취소하고 다시 확인해야 합니다",
        )
    history.record_status(db, inspection, user.id, "승인", INSPECTION_APPROVED)
    apply_stock(db, inspection, evaluation, user.id)
    history.record_status(db, inspection, user.id, "승인", INSPECTION_STOCK_APPLIED)
    return _done(db, inspection)


@router.post("/{inspection_id}/reject", response_model=InspectionOut)
def reject_inspection(
    inspection_id: int,
    body: RejectRequest | None = None,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """사장님 반려: `사장 승인 대기` → `반려`.
    반려 사유가 꼭 있어야 하고 재고는 그대로다."""
    if (denied := _owner_only(user)) is not None:
        return denied
    inspection = _find(db, inspection_id, user, lock=True)
    if inspection is None:
        return _not_found()
    if inspection.status != INSPECTION_OWNER_APPROVAL:
        return _invalid_status(inspection)
    reason = body.reject_reason if body else None
    if _blank(reason):
        return error_response(400, "REJECT_REASON_REQUIRED", "반려 사유를 적어 주세요")
    detail = get_detail(db, inspection.id)
    history.record(
        db,
        inspection.id,
        user.id,
        "반려",
        "reject_reason",
        detail.reject_reason,
        reason.strip(),
    )
    detail.reject_reason = reason.strip()
    history.record_status(db, inspection, user.id, "반려", INSPECTION_REJECTED)
    return _done(db, inspection)


@router.post("/{inspection_id}/recheck", response_model=InspectionOut)
def recheck_inspection(
    inspection_id: int,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """반려된 건을 직원이 재검수한다: `반려` → `직원 확인 대기` (US-06)."""
    inspection = _find(db, inspection_id, user, lock=True)
    if inspection is None:
        return _not_found()
    if inspection.status != INSPECTION_REJECTED:
        return _invalid_status(inspection)
    history.record_status(db, inspection, user.id, "재검수", INSPECTION_STAFF_REVIEW)
    return _done(db, inspection)


@router.post("/{inspection_id}/close", response_model=InspectionOut)
def close_inspection(
    inspection_id: int,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """반려된 건을 사장님이 닫는다: `반려` → `검수 종료` (끝 상태, US-06).
    공급처 반품·정정 요청은 사장님이 직접 한다. 다시 납품되면 POST /inspections."""
    if (denied := _owner_only(user)) is not None:
        return denied
    inspection = _find(db, inspection_id, user, lock=True)
    if inspection is None:
        return _not_found()
    if inspection.status != INSPECTION_REJECTED:
        return _invalid_status(inspection)
    history.record_status(db, inspection, user.id, "검수 종료", INSPECTION_CLOSED)
    return _done(db, inspection)
