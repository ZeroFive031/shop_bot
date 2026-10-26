"""Общие команды. Этот роутер подключается первым, чтобы /start и /cancel
срабатывали на любом шаге, даже посреди оформления заказа или добавления товара."""
from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import keyboards as kb
from config import Settings

router = Router()


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, settings: Settings):
    await state.clear()
    await message.answer(
        f"Привет, {escape(message.from_user.first_name)}! ☕\n"
        f"Это «{escape(settings.shop_name)}»: свежая обжарка и всё для заваривания.\n"
        "Выбери раздел в меню ниже.",
        reply_markup=kb.main_menu(),
    )


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=kb.main_menu())


# Telegram требует от ботов с оплатой команду для вопросов по платежам
@router.message(Command("paysupport"))
async def paysupport(message: Message):
    await message.answer(
        "Вопрос по оплате или возврату? Напиши сюда номер заказа и что случилось, "
        "мы ответим в течение дня."
    )
