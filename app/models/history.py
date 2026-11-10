# 변경 이력·판독 로그·알림 모델 (US-07 / US-03)
#
# - ChangeLog: 판독 원본값·직원 수정값·검수 결과·사장 승인·반려·재고 반영이 생길 때마다
#   한 줄씩 남긴다 (DATA-MODEL.md 변경 이력). 기록한 줄은 누구도 고치거나 지울 수 없다.
#   ORM에서 UPDATE·DELETE를 하면 오류를 낸다. 고치거나 지우는 API도 없다.
# - ReadingLog: 판독 1번마다 LLM 토큰 수·비용·걸린 시간 (DATA-MODEL.md 판독 로그)
# - Notification: 직원에게 보내는 알림. 지금은 판독 실패 때만 만든다 (US-03).
#   푸시·문자 같은 발송 방식은 미정이라 화면이 목록 API로 가져간다.

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ChangeLog(Base):
    __tablename__ = "change_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inspection_id: Mapped[int] = mapped_column(
        ForeignKey("inspections.id"), nullable=False, index=True
    )
    # 변경자. 시스템이 한 일(판독·재고 반영)은 그 일을 일으킨 사용자로 남긴다
    changed_by: Mapped[int] = mapped_column(
        ForeignKey("store_users.id"), nullable=False
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 무엇을 했는지 (예: 판독, 줄 수정, 확정, 승인, 반려, 재고 반영)
    action: Mapped[str] = mapped_column(String, nullable=False)
    # 어느 값이 바뀌었는지 (예: status, line 1 quantity). DATA-MODEL.md 미정 항목 [제안]
    field: Mapped[str | None] = mapped_column(String, nullable=True)
    old_value: Mapped[str | None] = mapped_column(String, nullable=True)
    new_value: Mapped[str | None] = mapped_column(String, nullable=True)


class ImmutableHistoryError(Exception):
    pass


@event.listens_for(ChangeLog, "before_update")
def _block_update(*_):
    raise ImmutableHistoryError("변경 이력은 고칠 수 없습니다")


@event.listens_for(ChangeLog, "before_delete")
def _block_delete(*_):
    raise ImmutableHistoryError("변경 이력은 지울 수 없습니다")


class ReadingLog(Base):
    __tablename__ = "reading_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inspection_id: Mapped[int] = mapped_column(
        ForeignKey("inspections.id"), nullable=False, index=True
    )
    file_id: Mapped[int] = mapped_column(
        ForeignKey("inspection_files.id"), nullable=False
    )
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    # 통화 단위 미정 (DATA-MODEL.md). 지금 정리기는 LLM을 부르지 않아 0이다
    cost: Mapped[float] = mapped_column(Float, nullable=False)
    # 업로드부터 판독이 끝날 때(`직원 확인 대기` 또는 실패)까지 걸린 초
    elapsed_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("store_users.id"), nullable=False, index=True
    )
    inspection_id: Mapped[int | None] = mapped_column(
        ForeignKey("inspections.id"), nullable=True
    )
    message: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
