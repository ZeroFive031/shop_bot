"""Тексты сообщений. Всё, что ввёл человек, экранируем: бот шлёт сообщения в режиме HTML,
и без этого имя вида «<b>Вася» сломало бы разметку."""
from html import escape

from db import CartItem, Order, Product
from pricing import rub

STATUS = {
    "new": "⏳ Ждёт оплаты",
    "paid": "💳 Оплачен",
    "shipped": "🚚 Отправлен",
    "done": "✅ Получен",
}
# Куда мастер может перевести заказ из текущего статуса
NEXT_STATUS = {"paid": "shipped", "shipped": "done"}


def product_text(p: Product) -> str:
    stock = f"В наличии: {p.stock} шт." if p.stock > 0 else "Нет в наличии"
    description = f"\n{escape(p.description)}" if p.description else ""
    return (f"<b>{escape(p.name)}</b>{description}\n\n"
            f"Цена: <b>{rub(p.price)}</b>\n{stock}")


def admin_product_text(p: Product) -> str:
    return (product_text(p) + "\n\n"
            + ("👁 Виден покупателям" if p.is_active else "🙈 Скрыт") + "\n"
            + ("📷 Есть фото" if p.photo_id else "Без фото"))


def cart_text(items: list[CartItem]) -> str:
    if not items:
        return "Корзина пуста. Загляни в «🛍 Каталог»."
    lines = [f"• {escape(i.name)} × {i.qty} = {rub(i.price * i.qty)}" for i in items]
    total = sum(i.price * i.qty for i in items)
    return "<b>Корзина</b>\n" + "\n".join(lines) + f"\n\nИтого: <b>{rub(total)}</b>"


def order_text(o: Order, for_admin: bool = False) -> str:
    lines = [f"<b>Заказ №{o.id}</b> — {STATUS[o.status]}"]
    lines += [f"• {escape(i.name)} × {i.qty} = {rub(i.price * i.qty)}" for i in o.items]
    lines.append(f"Итого: <b>{rub(o.total)}</b>")
    if for_admin:
        lines.append(f"\n👤 {escape(o.name)}, {escape(o.phone)}\n📍 {escape(o.address)}")
        if o.stock_issue:
            lines.append("⚠️ При оплате не хватило товара на складе")
    return "\n".join(lines)
