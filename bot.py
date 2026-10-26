"""Точка входа: python bot.py"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import load_settings
from db import Database
from handlers import admin, cart, catalog, common, payments


async def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    db = Database(settings.db_path)
    await db.init()
    if settings.star_rate:
        logging.warning("PAYMENT_TOKEN не задан: оплата пойдёт в Telegram Stars, это настоящие звёзды")

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    # Всё, что положено в dp, aiogram передаёт в хендлеры по имени аргумента
    dp["db"] = db
    dp["settings"] = settings

    # Порядок важен: общие команды первыми, чтобы /start и /cancel работали на любом шаге;
    # оплата раньше админки, чтобы сообщение об оплате не перехватил шаг добавления товара
    dp.include_routers(common.router, payments.router, admin.router, catalog.router, cart.router)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
