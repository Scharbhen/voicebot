"""Уведомления: Telegram менеджеру и email клиенту. Оба канала опциональны."""
from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

import aiohttp

from . import booking, config

log = logging.getLogger("notify")


async def telegram(text: str) -> None:
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        async with aiohttp.ClientSession(trust_env=True) as s:
            async with s.post(url, json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text},
                              timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    log.warning("telegram %s: %s", r.status, await r.text())
    except Exception as e:  # noqa: BLE001 — уведомление не должно ронять разговор
        log.warning("telegram error: %s", e)


async def booking_created(b: dict) -> None:
    await telegram(
        f"🟢 Новая запись {b['number']}\n{b['when']}\n{b['service']}\n"
        f"{b['client_name']}, {b['phone']}" + (f"\n{b['company']}" if b.get("company") else "")
        + (f"\nКомментарий: {b['comment']}" if b.get("comment") else "")
    )


async def booking_cancelled(b: dict) -> None:
    await telegram(f"🔴 Отмена записи {b['number']}\n{b['when']}\n{b['client_name']}, {b['phone']}")


async def callback_requested(d: dict) -> None:
    await telegram(
        f"📞 Заявка на обратный звонок\n{d.get('client_name', '')}, {d.get('phone', '')}\n"
        f"Тема: {d.get('topic', '')}\n{d.get('summary', '')}"
    )


def smtp_enabled() -> bool:
    return bool(config.SMTP_HOST and config.SMTP_USER and config.SMTP_PASSWORD)


def _send_email_sync(to: str, b: dict) -> None:
    msg = EmailMessage()
    msg["Subject"] = f"Запись на консультацию {b['number']} — {config.COMPANY_NAME}"
    msg["From"] = config.SMTP_FROM
    msg["To"] = to
    msg.set_content(
        f"Здравствуйте, {b['client_name']}!\n\n"
        f"Вы записаны на консультацию в {config.COMPANY_NAME}.\n\n"
        f"Номер записи: {b['number']}\n"
        f"Когда: {b['when']} (МСК)\n"
        f"Тема: {b['service']}\n"
        f"Телефон для связи: {b['phone']}\n\n"
        f"Файл для календаря во вложении. Чтобы отменить или перенести запись, "
        f"напишите в ответ на это письмо или поговорите с ассистентом на сайте.\n"
    )
    msg.add_attachment(booking.to_ics(b).encode(), maintype="text", subtype="calendar",
                       filename=f"{b['number']}.ics")
    if config.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as s:
            s.login(config.SMTP_USER, config.SMTP_PASSWORD)
            s.send_message(msg)
    else:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as s:
            s.starttls()
            s.login(config.SMTP_USER, config.SMTP_PASSWORD)
            s.send_message(msg)


async def send_confirmation_email(to: str, b: dict) -> None:
    await asyncio.to_thread(_send_email_sync, to, b)
