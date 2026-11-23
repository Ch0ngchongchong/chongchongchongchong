# 변경 이력 기록 도우미 (US-07). 커밋은 부른 쪽에서 상태 변경과 함께 한다.
# 상태가 바뀌는 곳·값이 바뀌는 곳마다 여기를 거쳐 한 줄씩 남긴다.

import json

from sqlalchemy.orm import Session

from app.models.history import ChangeLog


def _text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def record(
    db: Session,
    inspection_id: int,
    changed_by: int,
    action: str,
    field: str | None = None,
    old=None,
    new=None,
) -> None:
    db.add(
        ChangeLog(
            inspection_id=inspection_id,
            changed_by=changed_by,
            action=action,
            field=field,
            old_value=_text(old),
            new_value=_text(new),
        )
    )


def record_status(db: Session, inspection, changed_by: int, action: str, new: str):
    """검수 건 상태를 바꾸고 이력을 남긴다."""
    old = inspection.status
    inspection.status = new
    record(db, inspection.id, changed_by, action, "status", old, new)
