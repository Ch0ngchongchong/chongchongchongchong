# 첫 데모 준비물 시드 (DATA-MODEL.md 시드 #1·#2·#4·#5)
# 데모 0~1단계 상태를 만든다:
#   사용자 3명 / 상품 P-0123 / 발주 `입고 대기` / 검수 건 `업로드 대기` / 재고 0
#
# 실행: DATABASE_URL=... python -m scripts.seed_demo
# 주의: DATABASE_URL DB의 테이블을 모두 지우고 다시 만든다. 개발용 DB에만 쓴다.

from app import models  # noqa: F401
from app.db import Base, SessionLocal, engine
from app.models.inspection import INSPECTION_UPLOAD_WAITING, Inspection
from app.models.product import Product
from app.models.purchase_order import (
    ORDER_AWAITING_DELIVERY,
    PurchaseOrder,
    PurchaseOrderLine,
)
from app.models.user import StoreUser


def main() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        # 시드 #1: (가) 매장 1 사장님 / (나) 매장 1 직원 / (다) 매장 2 사장님
        db.add_all(
            [
                StoreUser(id=1, store_id=1, role="사장님"),
                StoreUser(id=2, store_id=1, role="직원"),
                StoreUser(id=3, store_id=2, role="사장님"),
            ]
        )
        # 시드 #2
        product = Product(
            store_id=1,
            product_code="P-0123",
            name="서울우유 1000ml",
            spec="1L",
            base_unit="개",
            pack_unit="박스",
            conversion_qty=10,
            base_unit_price=2650,
        )
        db.add(product)
        db.flush()
        # 시드 #4: [가정] 발주 수량 10의 단위는 개 (R6 미정)
        order = PurchaseOrder(
            store_id=1,
            supplier="(가상) 유제품 공급처 A",
            status=ORDER_AWAITING_DELIVERY,
            lines=[PurchaseOrderLine(product_id=product.id, quantity=10)],
        )
        db.add(order)
        db.flush()
        # 시드 #5
        inspection = Inspection(
            purchase_order_id=order.id, status=INSPECTION_UPLOAD_WAITING
        )
        db.add(inspection)
        db.commit()
        print(
            f"시드 완료: 상품 {product.id}, 발주 {order.id} (입고 대기), "
            f"검수 건 {inspection.id} (업로드 대기), 재고 0"
        )


if __name__ == "__main__":
    main()
