"""Настройки бота. Всё берётся из файла .env (см. .env.example)."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _ids(raw: str) -> set[int]:
    return {int(x) for x in raw.replace(" ", "").split(",") if x}


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: set[int]
    shop_name: str
    payment_token: str          # токен платёжки из @BotFather; пустой — оплата звёздами
    star_rate: float | None     # сколько рублей стоит одна звезда; None — оплата картой
    db_path: str


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "")
    if not token:
        raise RuntimeError("Не задан BOT_TOKEN в .env")
    payment_token = os.getenv("PAYMENT_TOKEN", "").strip()
    return Settings(
        bot_token=token,
        admin_ids=_ids(os.getenv("ADMIN_IDS", "")),
        shop_name=os.getenv("SHOP_NAME", "Кофейная лавка"),
        payment_token=payment_token,
        star_rate=None if payment_token else float(os.getenv("STAR_RATE_RUB", "1.5")),
        db_path=os.getenv("DB_PATH", "shop.db"),
    )
