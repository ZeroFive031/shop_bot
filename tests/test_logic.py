"""Тесты логики магазина без Telegram: python -m unittest -v"""
import os
import tempfile
import unittest

from db import Database, EmptyCart, OutOfStock
from pricing import invoice_amount, parse_payload, rub

USER, OTHER = 1, 2


class PricingTest(unittest.TestCase):
    def test_rub_format(self):
        self.assertEqual(rub(1500), "1 500 ₽")
        self.assertEqual(rub(890), "890 ₽")

    def test_invoice_in_kopecks(self):
        self.assertEqual(invoice_amount(890, None), ("RUB", 89000))

    def test_invoice_in_stars_rounds_up(self):
        self.assertEqual(invoice_amount(100, 1.5), ("XTR", 67))

    def test_parse_payload(self):
        self.assertEqual(parse_payload("order:15"), 15)
        self.assertIsNone(parse_payload("order:abc"))
        self.assertIsNone(parse_payload("hack:15"))


class ShopTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.tmp.name, "test.db"))
        await self.db.init()
        self.cat = await self.db.add_category("Тест")
        self.pid = await self.db.add_product(self.cat, "Кружка", "", 500, 2, None)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def order_for(self, user_id):
        return await self.db.create_order(user_id, "Тестер", "Иван", "+79990000000", "Москва, ул. Тестовая, 1")

    async def test_seed_catalog(self):
        names = [c["name"] for c in await self.db.categories()]
        self.assertIn("Кофе в зёрнах", names)

    async def test_cart_respects_stock(self):
        self.assertEqual(await self.db.add_to_cart(USER, self.pid), 1)
        self.assertEqual(await self.db.add_to_cart(USER, self.pid), 2)
        with self.assertRaises(OutOfStock):
            await self.db.add_to_cart(USER, self.pid)

    async def test_decrease_to_zero_removes(self):
        await self.db.add_to_cart(USER, self.pid)
        self.assertEqual(await self.db.change_qty(USER, self.pid, -1), 0)
        self.assertEqual(await self.db.cart_items(USER), [])

    async def test_empty_cart_order(self):
        with self.assertRaises(EmptyCart):
            await self.order_for(USER)

    async def test_order_snapshot_and_total(self):
        await self.db.add_to_cart(USER, self.pid)
        await self.db.add_to_cart(USER, self.pid)
        order = await self.db.order(await self.order_for(USER))
        self.assertEqual(order.total, 1000)
        self.assertEqual(order.status, "new")
        self.assertEqual([(i.name, i.qty) for i in order.items], [("Кружка", 2)])

    async def test_order_fails_when_stock_dropped(self):
        await self.db.add_to_cart(USER, self.pid)
        await self.db.add_to_cart(USER, self.pid)
        await self.db.set_stock(self.pid, 1)
        with self.assertRaises(OutOfStock):
            await self.order_for(USER)

    async def test_hidden_product_not_shown(self):
        await self.db.set_active(self.pid, False)
        self.assertEqual(await self.db.products(self.cat), [])
        self.assertNotIn(self.cat, [c["id"] for c in await self.db.categories()])

    async def test_mark_paid_writes_off_stock_and_cart(self):
        await self.db.add_to_cart(USER, self.pid)
        order_id = await self.order_for(USER)
        result = await self.db.mark_paid(order_id, "charge-1")
        self.assertFalse(result.already)
        self.assertEqual(result.shortages, [])
        self.assertEqual((await self.db.product(self.pid)).stock, 1)
        self.assertEqual(await self.db.cart_items(USER), [])
        self.assertEqual((await self.db.order(order_id)).status, "paid")

    async def test_mark_paid_twice_changes_nothing(self):
        await self.db.add_to_cart(USER, self.pid)
        order_id = await self.order_for(USER)
        await self.db.mark_paid(order_id, "charge-1")
        again = await self.db.mark_paid(order_id, "charge-1")
        self.assertTrue(again.already)
        self.assertEqual((await self.db.product(self.pid)).stock, 1)

    async def test_last_item_race(self):
        """Двое оформили последний товар; оплатил второй — склад не уходит в минус."""
        await self.db.set_stock(self.pid, 1)
        await self.db.add_to_cart(USER, self.pid)
        await self.db.add_to_cart(OTHER, self.pid)
        first = await self.order_for(USER)
        second = await self.order_for(OTHER)

        self.assertEqual((await self.db.mark_paid(first, "c1")).shortages, [])
        self.assertEqual(await self.db.check_stock(second), ["Кружка"])
        late = await self.db.mark_paid(second, "c2")
        self.assertEqual(late.shortages, ["Кружка"])
        self.assertEqual((await self.db.product(self.pid)).stock, 0)
        self.assertEqual((await self.db.order(second)).stock_issue, 1)

    async def test_status_flow_and_user_orders(self):
        await self.db.add_to_cart(USER, self.pid)
        order_id = await self.order_for(USER)
        self.assertEqual(await self.db.user_orders(USER), [])  # неоплаченный не показываем
        await self.db.mark_paid(order_id, "c1")
        self.assertTrue(await self.db.set_status(order_id, "shipped", "paid"))
        self.assertFalse(await self.db.set_status(order_id, "shipped", "paid"))  # второе нажатие
        self.assertEqual([o.status for o in await self.db.user_orders(USER)], ["shipped"])


if __name__ == "__main__":
    unittest.main()
