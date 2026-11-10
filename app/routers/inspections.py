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

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.inspection import Inspection
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
from app.routers.products import error_response, get_current_user
from app.schemas.inspection import InspectionLineUpdate, InspectionOut
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


def _upload_dir() -> Path:
    # 원본 파일을 저장할 곳. 환경변수 UPLOAD_DIR, 없으면 ./uploads
    return Path(os.environ.get("UPLOAD_DIR", "uploads"))


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


def _to_out(db: Session, inspection: Inspection) -> dict:
    document = latest_document(db, inspection.id)
    evaluation = evaluate(db, inspection)
    return {
        "id": inspection.id,
        "purchase_order_id": inspection.purchase_order_id,
        "status": inspection.status,
        "ai_draft": inspection.status == INSPECTION_STAFF_REVIEW,
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
                    "quantity": c.line.read_quantity,
                    "unit": c.line.read_unit,
                    "unit_price": c.line.read_unit_price,
                    "amount": c.line.read_amount,
                },
                "candidates": c.line.candidates,
                "product_id": c.line.product_id,
                "quantity": c.line.quantity,
                "unit": c.line.unit,
                # 재고 반영이 끝난 건은 그때 저장한 값을 보여 준다
                "base_quantity": c.line.applied_base_quantity
                if c.line.applied_base_quantity is not None
                else c.base_quantity,
                "order_quantity": c.order_quantity,
                "match_status": c.status,
            }
            for c in evaluation.lines
        ],
        "missing_order_lines": [
            {"product_id": m.product_id, "order_quantity": m.order_quantity}
            for m in evaluation.missing
        ],
        "check_count": evaluation.check_count,
        "all_match": evaluation.all_match,
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

    folder = _upload_dir() / str(inspection.id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}{Path(file.filename or '').suffix.lower()}"
    path.write_bytes(data)

    db.add(
        InspectionDocument(
            inspection_id=inspection.id,
            uploaded_by=user.id,
            filename=file.filename or path.name,
            content_type=content_type,
            stored_path=str(path),
        )
    )
    inspection.status = INSPECTION_READING
    db.commit()
    db.refresh(inspection)

    background_tasks.add_task(run_reading, inspection.id)
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
    if "quantity" in changes and changes["quantity"] is not None:
        if changes["quantity"] <= 0:
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
    for field, value in changes.items():
        setattr(line, field, value)
    db.commit()
    return _to_out(db, inspection)


@router.post("/{inspection_id}/confirm", response_model=InspectionOut)
def confirm_inspection(
    inspection_id: int,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """직원 확정 (데모 4~5단계, US-04).
    - 확인할 칸이 남아 있으면 확정하지 않는다
    - 발주와 모두 같으면: 재고에 반영하고 `재고 반영 완료`, 발주는 `입고 완료` (R3)
    - 다른 줄이 있으면: `사장 승인 대기`로 가고 재고는 그대로다 (US-06)"""
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
        apply_stock(db, inspection, evaluation)
        inspection.status = INSPECTION_STOCK_APPLIED
    else:
        inspection.status = INSPECTION_OWNER_APPROVAL
    db.commit()
    db.refresh(inspection)
    return _to_out(db, inspection)
