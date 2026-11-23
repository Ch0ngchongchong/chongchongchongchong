# 딱 재고 백엔드 앱 진입점
# 라우트는 first-feature.md에서 정한 기능을 만들 때 추가한다.

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text

from app import models  # noqa: F401  create_all()이 테이블을 알도록 모델을 불러온다
from app.db import Base, engine
from app.routers import (
    inspections,
    inventory,
    notifications,
    products,
    purchase_orders,
)
from app.routers.products import error_response
from app.schemas.product import REQUIRED_PRODUCT_FIELDS


@asynccontextmanager
async def lifespan(_: FastAPI):
    with engine.begin() as connection:
        Base.metadata.create_all(bind=connection)
        # create_all은 이미 배포된 테이블에 새 열을 만들지 않는다.
        connection.execute(text("""
            ALTER TABLE inspection_documents
                ADD COLUMN IF NOT EXISTS kind VARCHAR NOT NULL DEFAULT '명세서';
            ALTER TABLE inspection_lines
                ADD COLUMN IF NOT EXISTS read_spec VARCHAR,
                ADD COLUMN IF NOT EXISTS uncertain_fields JSON NOT NULL DEFAULT '[]',
                ADD COLUMN IF NOT EXISTS manual_base_quantity INTEGER,
                ADD COLUMN IF NOT EXISTS damaged BOOLEAN NOT NULL DEFAULT false,
                ADD COLUMN IF NOT EXISTS checked BOOLEAN NOT NULL DEFAULT false;
            ALTER TABLE reading_logs
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE
                NOT NULL DEFAULT now();
            SELECT setval(pg_get_serial_sequence('inspection_documents', 'id'), id)
            FROM (SELECT max(id) AS id FROM exception_photos) AS legacy
            WHERE id > coalesce(pg_sequence_last_value(
                pg_get_serial_sequence('inspection_documents', 'id')::regclass
            ), 0);
        """))
    yield


app = FastAPI(title="딱 재고 API", lifespan=lifespan)
app.include_router(products.router)
app.include_router(purchase_orders.router)
app.include_router(inspections.router)
app.include_router(inventory.router)
app.include_router(notifications.router)


def _is_empty(error: dict) -> bool:
    if error.get("type") == "missing":
        return True
    value = error.get("input")
    return value is None or (isinstance(value, str) and not value.strip())


@app.exception_handler(RequestValidationError)
async def required_field_missing_handler(request: Request, exc: RequestValidationError):
    """API.md 항목 1 실패 응답 ②: 필수값이 비면 공통 오류 형식으로 돌려준다.
    HTTP 상태 코드는 API.md에 없어 ①·③과 같은 400을 쓴다 [제안].
    필수값 누락이 아닌 검증 오류(타입이 틀림 등)는 API.md에 정해진 것이 없어
    FastAPI 기본 응답(422)을 그대로 둔다."""
    for error in exc.errors():
        loc = error.get("loc", ())
        if (
            len(loc) >= 2
            and loc[0] == "body"
            and loc[1] in REQUIRED_PRODUCT_FIELDS
            and _is_empty(error)
        ):
            return error_response(
                400, "REQUIRED_FIELD_MISSING", f"필수값이 비어 있습니다: {loc[1]}"
            )
    return await request_validation_exception_handler(request, exc)
