"""Панель продавца: заказы со сменой статуса, товары, добавление товара."""
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, Filter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, TelegramObject

import keyboards as kb
import texts
from config import Settings
from db import Database

router = Router()
log = logging.getLogger(__name__)


class IsAdmin(Filter):
    # settings aiogram подставит сам из данных диспетчера (dp["settings"])
    async def __call__(self, event: TelegramObject, settings: Settings) -> bool:
        return event.from_user is not None and event.from_user.id in settings.admin_ids


# Фильтр на весь роутер: все хендлеры ниже работают только для админов
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


class AddProduct(StatesGroup):
    category_name = State()
    name = State()
    description = State()
    price = State()
    stock = State()
    photo = State()


class EditStock(StatesGroup):
    value = State()


CUSTOMER_NOTICE = {
    "shipped": "🚚 Заказ №{id} отправлен! Скоро будет у тебя.",
    "done": "✅ Заказ №{id} получен. Спасибо за покупку, приходи ещё!",
}


# ---------- меню ----------
@router.message(Command("admin"))
async def admin_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Панель продавца:", reply_markup=kb.admin_menu_kb())


@router.callback_query(kb.AdminCb.filter(F.action == "menu"))
async def admin_menu_cb(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Панель продавца:", reply_markup=kb.admin_menu_kb())
    await call.answer()


# ---------- заказы ----------
@router.callback_query(kb.AdminCb.filter(F.action == "orders"))
async def orders(call: CallbackQuery, callback_data: kb.AdminCb, db: Database):
    found = await db.orders_by_status(callback_data.arg)
    title = texts.STATUS[callback_data.arg]
    text = f"{title}: {len(found)}" if found else f"{title}: заказов нет"
    await call.message.edit_text(text, reply_markup=kb.admin_orders_kb(found))
    await call.answer()


@router.callback_query(kb.AdminCb.filter(F.action == "order"))
async def order(call: CallbackQuery, callback_data: kb.AdminCb, db: Database):
    o = await db.order(callback_data.id)
    if not o:
        await call.answer("Заказ не найден", show_alert=True)
        return
    await call.message.edit_text(texts.order_text(o, for_admin=True), reply_markup=kb.admin_order_kb(o))
    await call.answer()


@router.callback_query(kb.AdminCb.filter(F.action == "status"))
async def change_status(call: CallbackQuery, callback_data: kb.AdminCb, db: Database, bot: Bot):
    o = await db.order(callback_data.id)
    new = callback_data.arg
    # Проверка в базе по старому статусу: двойное нажатие не переведёт заказ дважды
    if not o or texts.NEXT_STATUS.get(o.status) != new or not await db.set_status(o.id, new, o.status):
        await call.answer("Статус уже изменён", show_alert=True)
        return
    try:
        await bot.send_message(o.user_id, CUSTOMER_NOTICE[new].format(id=o.id))
    except Exception as e:
        log.warning("Не удалось уведомить покупателя %s: %s", o.user_id, e)
    o = await db.order(o.id)
    await call.message.edit_text(texts.order_text(o, for_admin=True), reply_markup=kb.admin_order_kb(o))
    await call.answer("Готово, покупатель уведомлён")


# ---------- товары ----------
@router.callback_query(kb.AdminCb.filter(F.action == "products"))
async def products(call: CallbackQuery, db: Database):
    await call.message.edit_text("Товары (🙈 — скрыт от покупателей):",
                                 reply_markup=kb.admin_products_kb(await db.all_products()))
    await call.answer()


async def show_product(message: Message, product_id: int, db: Database, edit: bool):
    p = await db.product(product_id)
    text, markup = texts.admin_product_text(p), kb.admin_product_kb(p)
    if edit:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)


@router.callback_query(kb.AdminCb.filter(F.action == "product"))
async def product(call: CallbackQuery, callback_data: kb.AdminCb, db: Database):
    await show_product(call.message, callback_data.id, db, edit=True)
    await call.answer()


@router.callback_query(kb.AdminCb.filter(F.action == "toggle"))
async def toggle(call: CallbackQuery, callback_data: kb.AdminCb, db: Database):
    p = await db.product(callback_data.id)
    await db.set_active(p.id, not p.is_active)
    await show_product(call.message, p.id, db, edit=True)
    await call.answer("Скрыт" if p.is_active else "Снова в продаже")


@router.callback_query(kb.AdminCb.filter(F.action == "stock"))
async def ask_stock(call: CallbackQuery, callback_data: kb.AdminCb, state: FSMContext):
    await state.set_state(EditStock.value)
    await state.update_data(product_id=callback_data.id)
    await call.message.answer("Сколько штук на складе? Напиши число.")
    await call.answer()


@router.message(EditStock.value, F.text)
async def got_stock(message: Message, state: FSMContext, db: Database):
    if not message.text.strip().isdigit():
        await message.answer("Нужно целое число, например 10.")
        return
    product_id = (await state.get_data())["product_id"]
    await state.clear()
    await db.set_stock(product_id, int(message.text.strip()))
    await message.answer("Остаток обновлён.")
    await show_product(message, product_id, db, edit=False)


# ---------- новый товар ----------
@router.callback_query(kb.AdminCb.filter(F.action == "new"))
async def new_product(call: CallbackQuery, db: Database):
    await call.message.edit_text("В какой раздел добавить товар?",
                                 reply_markup=kb.admin_categories_kb(await db.all_categories()))
    await call.answer()


@router.callback_query(kb.AdminCb.filter(F.action == "newcat"))
async def new_product_category(call: CallbackQuery, callback_data: kb.AdminCb, state: FSMContext):
    if callback_data.id == 0:
        await state.set_state(AddProduct.category_name)
        await call.message.edit_text("Название нового раздела?")
    else:
        await state.update_data(category_id=callback_data.id)
        await state.set_state(AddProduct.name)
        await call.message.edit_text("Название товара?\n<i>Отменить — /cancel</i>")
    await call.answer()


@router.message(AddProduct.category_name, F.text)
async def got_category_name(message: Message, state: FSMContext, db: Database):
    await state.update_data(category_id=await db.add_category(message.text.strip()))
    await state.set_state(AddProduct.name)
    await message.answer("Название товара?")


@router.message(AddProduct.name, F.text)
async def got_product_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddProduct.description)
    await message.answer("Описание? Или «-», чтобы без него.")


@router.message(AddProduct.description, F.text)
async def got_description(message: Message, state: FSMContext):
    text = message.text.strip()
    await state.update_data(description="" if text == "-" else text)
    await state.set_state(AddProduct.price)
    await message.answer("Цена в рублях, целым числом?")


@router.message(AddProduct.price, F.text)
async def got_price(message: Message, state: FSMContext):
    raw = message.text.replace(" ", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("Нужно целое число больше нуля, например 990.")
        return
    await state.update_data(price=int(raw))
    await state.set_state(AddProduct.stock)
    await message.answer("Сколько штук на складе?")


@router.message(AddProduct.stock, F.text)
async def got_new_stock(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("Нужно целое число, например 10.")
        return
    await state.update_data(stock=int(message.text.strip()))
    await state.set_state(AddProduct.photo)
    await message.answer("Пришли фото товара или «-», чтобы без фото.")


@router.message(AddProduct.photo, F.photo | (F.text == "-"))
async def got_photo(message: Message, state: FSMContext, db: Database):
    # Telegram присылает фото в нескольких размерах, последний — самый большой
    photo_id = message.photo[-1].file_id if message.photo else None
    data = await state.get_data()
    await state.clear()
    product_id = await db.add_product(data["category_id"], data["name"], data["description"],
                                      data["price"], data["stock"], photo_id)
    await message.answer("✅ Товар добавлен.")
    await show_product(message, product_id, db, edit=False)


@router.message(AddProduct.photo)
async def wrong_photo(message: Message):
    await message.answer("Пришли фото или «-».")
