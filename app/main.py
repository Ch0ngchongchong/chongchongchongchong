# 딱 재고 백엔드 앱 진입점
# 라우트는 first-feature.md에서 정한 기능을 만들 때 추가한다.

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import models  # noqa: F401  create_all()이 테이블을 알도록 모델을 불러온다
from app.db import Base, engine
from app.routers import products


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 테이블 생성: 오늘은 create_all()로 단순화 (Alembic 도입 여부는 팀 확인 필요)
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="딱 재고 API", lifespan=lifespan)
app.include_router(products.router)
