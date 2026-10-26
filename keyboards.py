"""Клавиатуры и данные для кнопок."""
from aiogram.filters.callback_data import CallbackData
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from pricing import rub
from texts import NEXT_STATUS, STATUS

BTN_CATALOG = "🛍 Каталог"
BTN_CART = "🛒 Корзина"
BTN_ORDERS = "📦 Мои заказы"


# ---------- данные кнопок покупателя ----------
class CatCb(CallbackData, prefix="cat"):
    id: int


class ProductCb(CallbackData, prefix="prod"):
    id: int


class AddCb(CallbackData, prefix="add"):
    id: int


class NavCb(CallbackData, prefix="nav"):
    to: str  # cats


class CartCb(CallbackData, prefix="cart"):
    action: str  # show / inc / dec / clear / checkout
    id: int = 0


class ConfirmCb(CallbackData, prefix="ok"):
    yes: bool


# ---------- данные кнопок админки ----------
# Одна схема на всю админку: action говорит, что делать, id и arg — с чем.
class AdminCb(CallbackData, prefix="adm"):
    action: str  # menu / orders / order / status / products / product / toggle / stock / new / newcat
    id: int = 0
    arg: str = ""


def _short(text: str, n: int = 22) -> str:
    return text if len(text) <= n else text[:n - 1] + "…"


# ---------- покупатель ----------
def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CATALOG), KeyboardButton(text=BTN_CART)],
                  [KeyboardButton(text=BTN_ORDERS)]],
        resize_keyboard=True,
    )


def phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def categories_kb(categories):
    kb = InlineKeyboardBuilder()
    for c in categories:
        kb.button(text=c["name"], callback_data=CatCb(id=c["id"]))
    kb.adjust(1)
    return kb.as_markup()


def products_kb(products):
    kb = InlineKeyboardBuilder()
    for p in products:
        sold_out = "" if p.stock > 0 else " (нет в наличии)"
        kb.button(text=f"{p.name} — {rub(p.price)}{sold_out}", callback_data=ProductCb(id=p.id))
    kb.button(text="← Разделы", callback_data=NavCb(to="cats"))
    kb.adjust(1)
    return kb.as_markup()


def product_kb(p):
    kb = InlineKeyboardBuilder()
    if p.stock > 0:
        kb.button(text="➕ В корзину", callback_data=AddCb(id=p.id))
    kb.button(text="🛒 Корзина", callback_data=CartCb(action="show"))
    kb.button(text="← Назад", callback_data=CatCb(id=p.category_id))
    kb.adjust(1, 2)
    return kb.as_markup()


def cart_kb(items):
    kb = InlineKeyboardBuilder()
    for i in items:
        kb.button(text="➖", callback_data=CartCb(action="dec", id=i.product_id))
        kb.button(text=f"{_short(i.name)} × {i.qty}", callback_data=ProductCb(id=i.product_id))
        kb.button(text="➕", callback_data=CartCb(action="inc", id=i.product_id))
    kb.button(text="🗑 Очистить", callback_data=CartCb(action="clear"))
    kb.button(text="✅ Оформить заказ", callback_data=CartCb(action="checkout"))
    kb.adjust(*[3] * len(items), 2)
    return kb.as_markup()


def confirm_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Всё верно, к оплате", callback_data=ConfirmCb(yes=True))
    kb.button(text="✖️ Отмена", callback_data=ConfirmCb(yes=False))
    kb.adjust(1)
    return kb.as_markup()


# ---------- админка ----------
def admin_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text=STATUS["paid"], callback_data=AdminCb(action="orders", arg="paid"))
    kb.button(text=STATUS["shipped"], callback_data=AdminCb(action="orders", arg="shipped"))
    kb.button(text="📦 Товары", callback_data=AdminCb(action="products"))
    kb.button(text="➕ Добавить товар", callback_data=AdminCb(action="new"))
    kb.adjust(2)
    return kb.as_markup()


def admin_orders_kb(orders):
    kb = InlineKeyboardBuilder()
    for o in orders:
        kb.button(text=f"№{o.id} — {rub(o.total)} — {_short(o.name, 16)}",
                  callback_data=AdminCb(action="order", id=o.id))
    kb.button(text="← Меню", callback_data=AdminCb(action="menu"))
    kb.adjust(1)
    return kb.as_markup()


def admin_order_kb(o):
    kb = InlineKeyboardBuilder()
    nxt = NEXT_STATUS.get(o.status)
    if nxt:
        kb.button(text=f"→ {STATUS[nxt]}", callback_data=AdminCb(action="status", id=o.id, arg=nxt))
    kb.button(text="← К списку", callback_data=AdminCb(action="orders", arg=o.status))
    kb.adjust(1)
    return kb.as_markup()


def admin_products_kb(products):
    kb = InlineKeyboardBuilder()
    for p in products:
        hidden = "" if p.is_active else "🙈 "
        kb.button(text=f"{hidden}{_short(p.name)} — {p.stock} шт.",
                  callback_data=AdminCb(action="product", id=p.id))
    kb.button(text="← Меню", callback_data=AdminCb(action="menu"))
    kb.adjust(1)
    return kb.as_markup()


def admin_product_kb(p):
    kb = InlineKeyboardBuilder()
    kb.button(text="🙈 Скрыть" if p.is_active else "👁 Показать",
              callback_data=AdminCb(action="toggle", id=p.id))
    kb.button(text="✏️ Остаток", callback_data=AdminCb(action="stock", id=p.id))
    kb.button(text="← К товарам", callback_data=AdminCb(action="products"))
    kb.adjust(2, 1)
    return kb.as_markup()


def admin_categories_kb(categories):
    kb = InlineKeyboardBuilder()
    for c in categories:
        kb.button(text=c["name"], callback_data=AdminCb(action="newcat", id=c["id"]))
    kb.button(text="➕ Новый раздел", callback_data=AdminCb(action="newcat", id=0))
    kb.button(text="← Меню", callback_data=AdminCb(action="menu"))
    kb.adjust(1)
    return kb.as_markup()
