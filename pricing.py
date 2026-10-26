"""Деньги: формат цены и сумма для счёта Telegram. Чистые функции без Telegram — их легко тестировать."""
import math


def rub(amount: int) -> str:
    """1500 -> '1 500 ₽'"""
    return f"{amount:,}".replace(",", " ") + " ₽"


def invoice_amount(total_rub: int, star_rate: float | None) -> tuple[str, int]:
    """Валюта и сумма для счёта.

    Telegram принимает сумму в минимальных единицах валюты: для рублей это копейки.
    Если star_rate задан, оплата идёт звёздами Telegram (валюта XTR),
    сумму в звёздах округляем вверх, чтобы магазин не терял на округлении.
    """
    if star_rate is None:
        return "RUB", total_rub * 100
    return "XTR", max(1, math.ceil(total_rub / star_rate))


def parse_payload(payload: str) -> int | None:
    """'order:15' -> 15. Всё остальное -> None."""
    prefix, _, number = payload.partition(":")
    return int(number) if prefix == "order" and number.isdigit() else None
