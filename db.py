"""Работа с базой SQLite: каталог, корзина, заказы.

Тот же подход, что в боте барбершопа: стандартный sqlite3, каждый запрос
в отдельном потоке через asyncio.to_thread, своё соединение на операцию.
"""
import asyncio
import sqlite3
from dataclasses import dataclass, field

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price       INTEGER NOT NULL CHECK (price > 0),   -- в рублях
    -- Главная защита от продажи того, чего нет: остаток не может уйти в минус.
    -- Если два человека оплатят последний товар одновременно, база пропустит
    -- списание только для одного.
    stock       INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    photo_id    TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS cart (
    user_id    INTEGER NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products(id),
    qty        INTEGER NOT NULL CHECK (qty > 0),
    PRIMARY KEY (user_id, product_id)
);

CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    user_name   TEXT,
    name        TEXT NOT NULL,
    phone       TEXT NOT NULL,
    address     TEXT NOT NULL,
    total       INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'new',   -- new / paid / shipped / done
    charge_id   TEXT UNIQUE,                   -- id платежа от Telegram
    stock_issue INTEGER NOT NULL DEFAULT 0,    -- при оплате не хватило товара
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    paid_at     TEXT
);

-- Цена и название копируются в заказ: если потом поменять товар,
-- старые заказы останутся такими, какими их оплатили.
CREATE TABLE IF NOT EXISTS order_items (
    order_id   INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL,
    name       TEXT NOT NULL,
    price      INTEGER NOT NULL,
    qty        INTEGER NOT NULL
);
"""

DEFAULT_CATALOG = {
    "Кофе в зёрнах": [
        ("Эфиопия Иргачеффе", "Цитрус и жасмин, светлая обжарка, 250 г", 890, 20),
        ("Колумбия Супремо", "Шоколад и орех, средняя обжарка, 250 г", 750, 15),
        ("Бразилия Сантос", "Карамель, тёмная обжарка, 1 кг", 2200, 5),
    ],
    "Аксессуары": [
        ("Ручная кофемолка", "Керамические жернова, 25 ступеней помола", 2490, 3),
        ("Воронка V60", "Пластик, размер 02", 690, 10),
    ],
}


class OutOfStock(Exception):
    """Товара на складе меньше, чем просят."""

    def __init__(self, names: list[str]):
        super().__init__(", ".join(names))
        self.names = names


class EmptyCart(Exception):
    """Нечего заказывать."""


@dataclass
class Product:
    id: int
    category_id: int
    name: str
    description: str
    price: int
    stock: int
    photo_id: str | None
    is_active: bool


@dataclass
class CartItem:
    product_id: int
    name: str
    price: int
    qty: int
    stock: int


@dataclass
class OrderItem:
    product_id: int
    name: str
    price: int
    qty: int


@dataclass
class Order:
    id: int
    user_id: int
    user_name: str | None
    name: str
    phone: str
    address: str
    total: int
    status: str
    charge_id: str | None
    stock_issue: int
    created_at: str
    paid_at: str | None
    items: list[OrderItem] = field(default_factory=list)


@dataclass
class PaidResult:
    already: bool             # заказ уже был оплачен раньше, ничего не делали
    shortages: list[str]      # товары, которых не хватило на складе


def _product(row) -> Product:
    return Product(**{**dict(row), "is_active": bool(row["is_active"])})


def _load_order(c: sqlite3.Connection, row) -> Order:
    items = c.execute(
        "SELECT product_id, name, price, qty FROM order_items WHERE order_id = ? ORDER BY rowid",
        (row["id"],),
    ).fetchall()
    return Order(**dict(row), items=[OrderItem(**dict(i)) for i in items])


class Database:
    def __init__(self, path: str):
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _run(self, fn):
        # Своё соединение на каждую операцию: просто и безопасно для потоков.
        def wrapper():
            conn = self._connect()
            try:
                with conn:  # автоматически commit / rollback
                    return fn(conn)
            finally:
                conn.close()
        return asyncio.to_thread(wrapper)

    # ---------- инициализация ----------
    async def init(self) -> None:
        def fn(c):
            c.executescript(SCHEMA)
            if c.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
                for category, items in DEFAULT_CATALOG.items():
                    cat_id = c.execute("INSERT INTO categories(name) VALUES (?)", (category,)).lastrowid
                    c.executemany(
                        "INSERT INTO products(category_id, name, description, price, stock) "
                        "VALUES (?, ?, ?, ?, ?)",
                        [(cat_id, *item) for item in items],
                    )
        await self._run(fn)

    # ---------- каталог ----------
    async def categories(self) -> list[sqlite3.Row]:
        """Разделы, в которых есть хотя бы один видимый товар."""
        return await self._run(lambda c: c.execute(
            "SELECT id, name FROM categories c WHERE EXISTS "
            "(SELECT 1 FROM products p WHERE p.category_id = c.id AND p.is_active = 1) ORDER BY id"
        ).fetchall())

    async def all_categories(self) -> list[sqlite3.Row]:
        return await self._run(lambda c: c.execute("SELECT id, name FROM categories ORDER BY id").fetchall())

    async def add_category(self, name: str) -> int:
        def fn(c):
            c.execute("INSERT OR IGNORE INTO categories(name) VALUES (?)", (name,))
            return c.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()["id"]
        return await self._run(fn)

    async def products(self, category_id: int) -> list[Product]:
        rows = await self._run(lambda c: c.execute(
            "SELECT * FROM products WHERE category_id = ? AND is_active = 1 ORDER BY id", (category_id,)
        ).fetchall())
        return [_product(r) for r in rows]

    async def all_products(self) -> list[Product]:
        rows = await self._run(lambda c: c.execute(
            "SELECT * FROM products ORDER BY category_id, id"
        ).fetchall())
        return [_product(r) for r in rows]

    async def product(self, product_id: int) -> Product | None:
        row = await self._run(lambda c: c.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone())
        return _product(row) if row else None

    async def add_product(self, category_id, name, description, price, stock, photo_id) -> int:
        return await self._run(lambda c: c.execute(
            "INSERT INTO products(category_id, name, description, price, stock, photo_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (category_id, name, description, price, stock, photo_id),
        ).lastrowid)

    async def set_active(self, product_id: int, active: bool) -> None:
        await self._run(lambda c: c.execute(
            "UPDATE products SET is_active = ? WHERE id = ?", (int(active), product_id)
        ))

    async def set_stock(self, product_id: int, stock: int) -> None:
        await self._run(lambda c: c.execute(
            "UPDATE products SET stock = ? WHERE id = ?", (stock, product_id)
        ))

    # ---------- корзина ----------
    async def cart_items(self, user_id: int) -> list[CartItem]:
        rows = await self._run(lambda c: c.execute(
            "SELECT p.id AS product_id, p.name, p.price, c.qty, p.stock "
            "FROM cart c JOIN products p ON p.id = c.product_id "
            "WHERE c.user_id = ? ORDER BY p.name",
            (user_id,),
        ).fetchall())
        return [CartItem(**dict(r)) for r in rows]

    async def change_qty(self, user_id: int, product_id: int, delta: int) -> int:
        """Изменить количество товара в корзине. Возвращает новое количество (0 — убран)."""
        def fn(c):
            p = c.execute("SELECT name, stock, is_active FROM products WHERE id = ?", (product_id,)).fetchone()
            row = c.execute(
                "SELECT qty FROM cart WHERE user_id = ? AND product_id = ?", (user_id, product_id)
            ).fetchone()
            qty = (row["qty"] if row else 0) + delta
            if qty <= 0:
                c.execute("DELETE FROM cart WHERE user_id = ? AND product_id = ?", (user_id, product_id))
                return 0
            # Уменьшать можно всегда, увеличивать — только в пределах остатка
            if delta > 0 and (p is None or not p["is_active"] or qty > p["stock"]):
                raise OutOfStock([p["name"] if p else "товар"])
            c.execute(
                "INSERT INTO cart(user_id, product_id, qty) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id, product_id) DO UPDATE SET qty = excluded.qty",
                (user_id, product_id, qty),
            )
            return qty
        return await self._run(fn)

    async def add_to_cart(self, user_id: int, product_id: int) -> int:
        return await self.change_qty(user_id, product_id, 1)

    async def clear_cart(self, user_id: int) -> None:
        await self._run(lambda c: c.execute("DELETE FROM cart WHERE user_id = ?", (user_id,)))

    # ---------- заказы ----------
    async def create_order(self, user_id, user_name, name, phone, address) -> int:
        """Сделать заказ из корзины. Корзина очищается только после оплаты."""
        def fn(c):
            items = c.execute(
                "SELECT p.id, p.name, p.price, p.stock, p.is_active, c.qty "
                "FROM cart c JOIN products p ON p.id = c.product_id WHERE c.user_id = ?",
                (user_id,),
            ).fetchall()
            if not items:
                raise EmptyCart()
            short = [r["name"] for r in items if not r["is_active"] or r["qty"] > r["stock"]]
            if short:
                raise OutOfStock(short)
            total = sum(r["price"] * r["qty"] for r in items)
            order_id = c.execute(
                "INSERT INTO orders(user_id, user_name, name, phone, address, total) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, user_name, name, phone, address, total),
            ).lastrowid
            c.executemany(
                "INSERT INTO order_items(order_id, product_id, name, price, qty) VALUES (?, ?, ?, ?, ?)",
                [(order_id, r["id"], r["name"], r["price"], r["qty"]) for r in items],
            )
            return order_id
        return await self._run(fn)

    async def order(self, order_id: int) -> Order | None:
        def fn(c):
            row = c.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            return _load_order(c, row) if row else None
        return await self._run(fn)

    async def check_stock(self, order_id: int) -> list[str]:
        """Товары заказа, которых сейчас не хватает (или которые сняты с продажи)."""
        rows = await self._run(lambda c: c.execute(
            "SELECT i.name FROM order_items i LEFT JOIN products p ON p.id = i.product_id "
            "WHERE i.order_id = ? AND (p.id IS NULL OR p.is_active = 0 OR p.stock < i.qty)",
            (order_id,),
        ).fetchall())
        return [r["name"] for r in rows]

    async def mark_paid(self, order_id: int, charge_id: str) -> PaidResult:
        """Отметить оплату, списать товар со склада и убрать купленное из корзины.

        Всё в одной транзакции. Повторный вызов для того же заказа ничего не меняет:
        Telegram может прислать уведомление об оплате ещё раз.
        """
        def fn(c):
            order = c.execute("SELECT user_id FROM orders WHERE id = ?", (order_id,)).fetchone()
            updated = c.execute(
                "UPDATE orders SET status = 'paid', charge_id = ?, paid_at = datetime('now') "
                "WHERE id = ? AND status = 'new'",
                (charge_id, order_id),
            ).rowcount
            if not order or not updated:
                return PaidResult(already=True, shortages=[])

            shortages = []
            items = c.execute(
                "SELECT product_id, name, qty FROM order_items WHERE order_id = ?", (order_id,)
            ).fetchall()
            for item in items:
                try:
                    c.execute("UPDATE products SET stock = stock - ? WHERE id = ?",
                              (item["qty"], item["product_id"]))
                except sqlite3.IntegrityError:
                    # Сработал CHECK (stock >= 0): товар успел купить кто-то другой.
                    # Деньги уже списаны, поэтому заказ остаётся оплаченным,
                    # а мастер получит предупреждение и решит: довезти позже или вернуть деньги.
                    shortages.append(item["name"])
            if shortages:
                c.execute("UPDATE orders SET stock_issue = 1 WHERE id = ?", (order_id,))

            c.execute(
                "DELETE FROM cart WHERE user_id = ? AND product_id IN "
                "(SELECT product_id FROM order_items WHERE order_id = ?)",
                (order["user_id"], order_id),
            )
            return PaidResult(already=False, shortages=shortages)
        return await self._run(fn)

    async def user_orders(self, user_id: int, limit: int = 10) -> list[Order]:
        """Оплаченные заказы покупателя, свежие сверху. Неоплаченные не показываем."""
        def fn(c):
            rows = c.execute(
                "SELECT * FROM orders WHERE user_id = ? AND status != 'new' ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
            return [_load_order(c, r) for r in rows]
        return await self._run(fn)

    async def orders_by_status(self, status: str) -> list[Order]:
        def fn(c):
            rows = c.execute("SELECT * FROM orders WHERE status = ? ORDER BY id", (status,)).fetchall()
            return [_load_order(c, r) for r in rows]
        return await self._run(fn)

    async def set_status(self, order_id: int, new: str, expected: str) -> bool:
        """Сменить статус, только если заказ всё ещё в ожидаемом статусе."""
        return await self._run(lambda c: c.execute(
            "UPDATE orders SET status = ? WHERE id = ? AND status = ?", (new, order_id, expected)
        ).rowcount > 0)
