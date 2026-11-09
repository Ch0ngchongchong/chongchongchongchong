# 테스트 공통 설정 (US-08부터)
# 테스트는 실제 PostgreSQL에서 돌린다 (STACK.md: DB는 PostgreSQL).
# 테스트마다 테이블을 지우고 다시 만들기 때문에, 개발용 DB와 다른 DB를
# 환경변수 TEST_DATABASE_URL로 따로 지정해야 한다. 값은 코드에 쓰지 않는다.
# 형식: postgresql+psycopg://사용자:비밀번호@호스트:포트/DB이름

import os

import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    raise pytest.UsageError(
        "환경변수 TEST_DATABASE_URL이 설정되지 않았습니다. "
        "개발용 DB와 다른 테스트 전용 DB 주소를 넣어 주세요."
    )

# app.db는 불러올 때 DATABASE_URL을 읽으므로, app을 불러오기 전에 테스트 DB로 바꿔 둔다.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import StoreUser  # noqa: E402

# DATA-MODEL.md 시드 #1: (가) store 1 사장님 / (나) store 1 직원 / (다) store 2 사장님
SEED_USERS = [
    {"id": 1, "store_id": 1, "role": "사장님"},
    {"id": 2, "store_id": 1, "role": "직원"},
    {"id": 3, "store_id": 2, "role": "사장님"},
]

# 테스트에서 store=1, store=2로 부를 때 쓰는 사용자 (각 매장의 사장님)
OWNER_ID_BY_STORE = {1: 1, 2: 3}


@pytest.fixture
def client():
    """테스트마다 빈 테이블 + 시드 사용자로 시작하는 테스트 클라이언트."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.add_all(StoreUser(**user) for user in SEED_USERS)
        db.commit()
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)
