# 알림 (US-03 "판독 실패 시 직원에게 다시 올려 달라는 알림")
# 푸시·문자 같은 발송 방식은 미정이라, 화면이 이 API로 내 알림을 가져간다.
# API.md에 아직 항목이 없어 [제안]이다.

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.history import Notification
from app.models.user import StoreUser
from app.routers.products import error_response, get_current_user
from app.schemas.inspection import NotificationOut

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    unread: bool = False,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """내 알림을 최근 것부터. ?unread=true 면 읽지 않은 것만."""
    query = (
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.id.desc())
    )
    if unread:
        query = query.where(Notification.read_at.is_(None))
    return db.scalars(query).all()


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: int,
    user: StoreUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """읽음으로 표시한다. 다른 사람의 알림은 없는 것으로 다룬다."""
    notification = db.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user.id
        )
    )
    if notification is None:
        return error_response(404, "NOTIFICATION_NOT_FOUND", "알림을 찾을 수 없습니다")
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        db.commit()
        db.refresh(notification)
    return notification
