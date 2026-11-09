# 상품 모델 (DATA-MODEL.md 상품 필드 그대로, US-08 / F-01)
# 필수 여부가 '미정'인 필드는 빈 값을 허용해 둔다. 필수값이 정해지면 nullable을 바꾼다.

from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Product(Base):
    __tablename__ = "products"
    # 상품 코드는 매장 안에서 중복 불가 (US-08)
    __table_args__ = (
        UniqueConstraint("store_id", "product_code", name="uq_products_store_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    spec: Mapped[str | None] = mapped_column(String, nullable=True)
    base_unit: Mapped[str | None] = mapped_column(String, nullable=True)
    pack_unit: Mapped[str | None] = mapped_column(String, nullable=True)
    # 포장 단위 1개당 기준 단위 수. 입력하면 0보다 커야 한다 (US-08).
    # 미등록 허용 (US-05)
    conversion_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 기준 단가 (원)
    base_unit_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
