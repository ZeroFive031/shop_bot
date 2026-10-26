"""Оплата через Telegram и история заказов покупателя.

Как устроена оплата в Telegram:
1. Бот присылает счёт (send_invoice). Деньги пока не списаны.
2. Человек жмёт «Оплатить», Telegram спрашивает бота: «можно?» (pre_checkout_query).
   Здесь в последний раз проверяем заказ и остатки. На ответ даётся 10 секунд.
3. Если можно — деньги списываются, и бот получает сообщение successful_payment.
   Только после него заказ считается оплаченным.
"""
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import LabeledPrice, Message, PreCheckoutQuery

import keyboards as kb
import texts
from config import Settings
from db import Database, Order
from handlers.utils import notify_admins
from pricing import invoice_amount, parse_payload

router = Router()


async def send_invoice(message: Message, order: Order, settings: Settings):
    currency, amount = invoice_amount(order.total, settings.star_rate)
    items = ", ".join(f"{i.name} × {i.qty}" for i in order.items)
    await message.answer_invoice(
        title=f"Заказ №{order.id}",
        description=items[:255],
        payload=f"order:{order.id}",  # по нему узнаем заказ, когда придёт оплата
        currency=currency,
        prices=[LabeledPrice(label=f"Заказ №{order.id}", amount=amount)],
        provider_token=settings.payment_token,  # пустая строка — оплата звёздами
    )


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery, db: Database):
    order_id = parse_payload(query.invoice_payload)
    order = await db.order(order_id) if order_id else None
    if not order or order.status != "new" or order.user_id != query.from_user.id:
        await query.answer(ok=False, error_message="Этот счёт уже оплачен или устарел. Оформи заказ заново.")
        return
    short = await db.check_stock(order.id)
    if short:
        await query.answer(ok=False, error_message="Пока ты оформлял заказ, закончилось: " + ", ".join(short))
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def paid(message: Message, db: Database, settings: Settings, bot: Bot):
    payment = message.successful_payment
    order_id = parse_payload(payment.invoice_payload)
    result = await db.mark_paid(order_id, payment.telegram_payment_charge_id)
    if result.already:
        return  # повтор уведомления — всё уже сделано

    order = await db.order(order_id)
    await message.answer(
        f"✅ Оплата прошла, заказ №{order.id} принят!\n"
        "Напишем, когда отправим. Статус — в «📦 Мои заказы».",
        reply_markup=kb.main_menu(),
    )
    alert = "🆕 Оплачен новый заказ\n\n" + texts.order_text(order, for_admin=True)
    if result.shortages:
        alert += ("\n\n❗ Товар закончился, пока клиент платил: " + ", ".join(result.shortages)
                  + "\nСвяжитесь с клиентом: довезти позже или вернуть деньги.")
    await notify_admins(bot, settings, alert)


@router.message(F.text == kb.BTN_ORDERS)
async def my_orders(message: Message, state: FSMContext, db: Database):
    await state.clear()
    orders = await db.user_orders(message.from_user.id)
    if not orders:
        await message.answer("Оплаченных заказов пока нет.")
        return
    await message.answer("\n\n".join(texts.order_text(o) for o in orders))
