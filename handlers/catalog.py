"""Каталог: разделы → товары → карточка товара → в корзину."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import keyboards as kb
import texts
from db import Database, OutOfStock
from handlers.utils import replace

router = Router()


@router.message(F.text == kb.BTN_CATALOG)
async def catalog(message: Message, state: FSMContext, db: Database):
    await state.clear()
    categories = await db.categories()
    if not categories:
        await message.answer("Каталог пока пуст, загляни позже.")
        return
    await message.answer("Выбери раздел:", reply_markup=kb.categories_kb(categories))


@router.callback_query(kb.NavCb.filter(F.to == "cats"))
async def back_to_categories(call: CallbackQuery, db: Database):
    await replace(call, "Выбери раздел:", kb.categories_kb(await db.categories()))
    await call.answer()


@router.callback_query(kb.CatCb.filter())
async def show_category(call: CallbackQuery, callback_data: kb.CatCb, db: Database):
    products = await db.products(callback_data.id)
    if not products:
        await call.answer("В этом разделе пока пусто", show_alert=True)
        return
    await replace(call, "Выбери товар:", kb.products_kb(products))
    await call.answer()


@router.callback_query(kb.ProductCb.filter())
async def show_product(call: CallbackQuery, callback_data: kb.ProductCb, db: Database):
    p = await db.product(callback_data.id)
    if not p or not p.is_active:
        await call.answer("Этот товар больше не продаётся", show_alert=True)
        return
    text, markup = texts.product_text(p), kb.product_kb(p)
    if p.photo_id:
        await call.message.delete()
        await call.message.answer_photo(p.photo_id, caption=text, reply_markup=markup)
    else:
        await replace(call, text, markup)
    await call.answer()


@router.callback_query(kb.AddCb.filter())
async def add_to_cart(call: CallbackQuery, callback_data: kb.AddCb, db: Database):
    try:
        qty = await db.add_to_cart(call.from_user.id, callback_data.id)
    except OutOfStock:
        await call.answer("Больше нет в наличии 😔", show_alert=True)
        return
    await call.answer(f"Добавлено! В корзине: {qty} шт.")
