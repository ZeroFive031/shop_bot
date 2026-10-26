"""Корзина и оформление заказа: имя → телефон → адрес → подтверждение → счёт."""
import re
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import keyboards as kb
import texts
from config import Settings
from db import Database, EmptyCart, OutOfStock
from handlers.payments import send_invoice
from handlers.utils import replace

router = Router()

PHONE_RE = re.compile(r"^\+?[\d\s\-()]{10,18}$")


class Checkout(StatesGroup):
    name = State()
    phone = State()
    address = State()
    confirm = State()


async def render_cart(user_id: int, db: Database):
    items = await db.cart_items(user_id)
    return texts.cart_text(items), (kb.cart_kb(items) if items else None)


# ---------- корзина ----------
@router.message(F.text == kb.BTN_CART)
async def cart(message: Message, state: FSMContext, db: Database):
    await state.clear()
    text, markup = await render_cart(message.from_user.id, db)
    await message.answer(text, reply_markup=markup)


@router.callback_query(kb.CartCb.filter(F.action == "show"))
async def cart_show(call: CallbackQuery, db: Database):
    text, markup = await render_cart(call.from_user.id, db)
    await replace(call, text, markup)
    await call.answer()


@router.callback_query(kb.CartCb.filter(F.action.in_({"inc", "dec"})))
async def cart_change(call: CallbackQuery, callback_data: kb.CartCb, db: Database):
    delta = 1 if callback_data.action == "inc" else -1
    try:
        await db.change_qty(call.from_user.id, callback_data.id, delta)
    except OutOfStock:
        await call.answer("Больше нет в наличии", show_alert=True)
        return
    text, markup = await render_cart(call.from_user.id, db)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()


@router.callback_query(kb.CartCb.filter(F.action == "clear"))
async def cart_clear(call: CallbackQuery, db: Database):
    await db.clear_cart(call.from_user.id)
    await call.message.edit_text(texts.cart_text([]))
    await call.answer("Корзина очищена")


# ---------- оформление ----------
@router.callback_query(kb.CartCb.filter(F.action == "checkout"))
async def checkout(call: CallbackQuery, state: FSMContext, db: Database):
    items = await db.cart_items(call.from_user.id)
    if not items:
        await call.answer("Корзина пуста", show_alert=True)
        return
    await state.set_state(Checkout.name)
    await call.message.edit_text(texts.cart_text(items))  # убираем кнопки, чтобы корзину не меняли на ходу
    await call.message.answer("Оформляем заказ. Как тебя зовут?\n<i>Передумал — /cancel</i>")
    await call.answer()


@router.message(Checkout.name, F.text)
async def got_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not 2 <= len(name) <= 64:
        await message.answer("Напиши имя, от 2 до 64 символов.")
        return
    await state.update_data(name=name)
    await state.set_state(Checkout.phone)
    await message.answer("Телефон для связи: кнопкой ниже или сообщением.", reply_markup=kb.phone_kb())


@router.message(Checkout.phone, F.contact)
async def got_contact(message: Message, state: FSMContext):
    await ask_address(message, state, message.contact.phone_number)


@router.message(Checkout.phone, F.text)
async def got_phone_text(message: Message, state: FSMContext):
    if not PHONE_RE.match(message.text.strip()):
        await message.answer("Не похоже на номер. Пример: +7 999 123-45-67")
        return
    await ask_address(message, state, message.text.strip())


async def ask_address(message: Message, state: FSMContext, phone: str):
    await state.update_data(phone=phone)
    await state.set_state(Checkout.address)
    await message.answer("Адрес доставки: город, улица, дом, квартира.", reply_markup=kb.main_menu())


@router.message(Checkout.address, F.text)
async def got_address(message: Message, state: FSMContext, db: Database):
    address = message.text.strip()
    if len(address) < 5:
        await message.answer("Слишком коротко. Напиши адрес полностью.")
        return
    await state.update_data(address=address)
    await state.set_state(Checkout.confirm)
    data = await state.get_data()
    items = await db.cart_items(message.from_user.id)
    await message.answer(
        texts.cart_text(items)
        + f"\n\n👤 {escape(data['name'])}, {escape(data['phone'])}\n📍 {escape(address)}\n\nВсё верно?",
        reply_markup=kb.confirm_kb(),
    )


@router.callback_query(Checkout.confirm, kb.ConfirmCb.filter())
async def confirm(call: CallbackQuery, callback_data: kb.ConfirmCb, state: FSMContext,
                  db: Database, settings: Settings):
    data = await state.get_data()
    await state.clear()
    if not callback_data.yes:
        await call.message.edit_text("Оформление отменено. Товары остались в корзине.")
        await call.answer()
        return

    try:
        order_id = await db.create_order(call.from_user.id, call.from_user.full_name,
                                         data["name"], data["phone"], data["address"])
    except EmptyCart:
        await call.message.edit_text("Корзина пуста, оформлять нечего.")
        await call.answer()
        return
    except OutOfStock as e:
        await call.message.edit_text(
            f"Не хватает на складе: {escape(', '.join(e.names))}.\n"
            "Поправь количество в «🛒 Корзина» и оформи заново."
        )
        await call.answer()
        return

    order = await db.order(order_id)
    await call.message.edit_text(texts.order_text(order) + "\n\nОсталось оплатить 👇")
    await send_invoice(call.message, order, settings)
    await call.answer()
