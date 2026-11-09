# PostgreSQL 연결 설정 (SQLAlchemy 2.0, 동기 방식)
# 접속 주소는 환경변수 DATABASE_URL에서만 읽는다. 값은 코드에 쓰지 않는다.
# 형식: postgresql+psycopg://사용자:비밀번호@호스트:포트/DB이름

import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("환경변수 DATABASE_URL이 설정되지 않았습니다.")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    """모든 모델이 상속하는 기본 클래스. 모델은 DATA-MODEL.md를 확정한 뒤 만든다."""


def get_db() -> Iterator[Session]:
    """라우트에서 Depends(get_db)로 받아 쓰는 DB 세션. 요청이 끝나면 닫는다."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
