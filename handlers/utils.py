"""Мелкие помощники для хендлеров."""
import logging

from aiogram import Bot
from aiogram.types import CallbackQuery

from config import Settings

log = logging.getLogger(__name__)


async def replace(call: CallbackQuery, text: str, markup=None):
    """Показать text на месте сообщения, под которым нажали кнопку.

    У сообщения с фото нет текста, только подпись, и превратить его в текстовое нельзя.
    Поэтому такое сообщение удаляем и присылаем новое.
    """
    if call.message.photo:
        await call.message.delete()
        await call.message.answer(text, reply_markup=markup)
    else:
        await call.message.edit_text(text, reply_markup=markup)


async def notify_admins(bot: Bot, settings: Settings, text: str):
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception as e:  # админ мог не нажать /start или заблокировать бота
            log.warning("Не удалось уведомить админа %s: %s", admin_id, e)
