# 직원 알림 목록·읽음 표시 (US-03). 지금은 판독 실패 알림만 만든다.

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.notification import Notification
from app.models.user import StoreUser
from app.routers.products import error_response, get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _out(notification: Notification) -> dict:
    return {
        "id": notification.id,
        "inspection_id": notification.inspection_id,
        "message": notification.message,
        "created_at": notification.created_at,
        "read_at": notification.read_at,
    }


@router.get("")
def list_notifications(
    unread: bool | None = None,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """내 알림 목록. ?unread=true면 아직 읽지 않은 것만."""
    query = (
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.id)
    )
    if unread:
        query = query.where(Notification.read_at.is_(None))
    return [_out(n) for n in db.scalars(query).all()]


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: int,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """내 알림만 읽음 표시할 수 있다 (다른 사람 알림은 없는 것과 똑같이 다룬다)."""
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        return error_response(404, "NOTIFICATION_NOT_FOUND", "알림을 찾을 수 없습니다")
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        db.commit()
    return _out(notification)
