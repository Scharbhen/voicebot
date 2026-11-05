"""Промпт агента, описание функций (tools) и их выполнение."""
from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable

from . import booking, config, notify

# ---------- база знаний ----------

def load_kb() -> str:
    parts = []
    for p in sorted(config.KB_DIR.glob("*.md")):
        text = re.sub(r"<!--.*?-->", "", p.read_text(encoding="utf-8"), flags=re.S).strip()
        parts.append(text)
    return "\n\n".join(parts)


# ---------- промпт ----------

def build_instructions() -> str:
    n = booking.now()
    today = f"{booking.WEEKDAYS[n.weekday()]}, {n.day} {booking.MONTHS_GEN[n.month - 1]} {n.year}, {n.strftime('%H:%M')} (МСК)"
    t = (n + __import__("datetime").timedelta(days=1)).date()
    tomorrow = f"{booking.WEEKDAYS[t.weekday()]}, {t.day} {booking.MONTHS_GEN[t.month - 1]} {t.year} ({t.isoformat()})"
    kb = load_kb()
    kb_block = (
        "Подробные ответы ищи через функцию file_search. Краткая справка:\n" + kb[:3000]
        if config.VECTOR_STORE_ID else kb
    )
    return f"""Ты — Ирина, голосовой ассистент компании «{config.COMPANY_NAME}» (метрология: поверка, калибровка, аттестация).
Клиент говорит с тобой голосом через виджет на сайте, ты отвечаешь голосом. Сейчас {today} ({n.date().isoformat()}). Завтра — {tomorrow}.
Сейчас {n.year} год: в датах для функций всегда используй {n.year} год (или следующий, если месяц уже прошёл).

ЗАЧЕМ ТЫ ЗДЕСЬ
Отвечать на вопросы об услугах по базе знаний ниже и записывать на бесплатную консультацию к специалисту.
Если вопрос сложный или клиент хочет поговорить с человеком — оставь заявку на обратный звонок.

КАК ГОВОРИТЬ
- Как живой приветливый администратор: коротко (1–2 предложения), просто, своими словами, без канцелярита.
- Сначала по-человечески реагируй на то, что сказал клиент, потом двигай разговор дальше.
- Один вопрос за реплику. Не повторяй свои прошлые фразы — каждый раз говори иначе.
- Твой текст озвучивается: никаких списков, цифр через тире, markdown. Время и даты называй словами.
- Не выдумывай факты, цены, адреса и сроки, которых нет в базе знаний — предложи уточнить у специалиста на консультации.
- На вопросы о себе отвечай честно: ты ИИ-ассистент компании. На светские вопросы («как дела») ответь коротко и тепло.
- На посторонние темы скажи, что с этим не поможешь, и предложи вернуться к делу.

ЗАПИСЬ НА КОНСУЛЬТАЦИЮ — порядок
1. Клиент хочет записаться → сразу вызови get_available_slots (с датой, если он её назвал).
   Если клиент уже назвал конкретное время и оно есть в ответе — сразу подтверди именно его, не предлагай выбор.
   Если названного времени нет или клиент время не назвал — предложи два-три варианта из ответа.
   Если ему подходит любое время — предложи ближайший. Даты и время бери только из ответа функции.
2. Когда время выбрано, узнай тему консультации, если клиент её ещё не назвал. Не хочет уточнять — тема «Консультация».
3. Спроси имя и телефон. Имя записывай ровно так, как назвал клиент («Вася» — значит «Вася»): не превращай его
   в полное, не додумывай отчество и фамилию. Не расслышала — переспроси. Дослушай номер до конца, не перебивай и не комментируй, пока клиент диктует.
   Когда клиент закончил, НЕ задавай отдельный вопрос про номер — сразу переходи к шагу 4.
4. Когда есть время, имя и телефон — вызови book_appointment. Функция вернёт, что зачитать клиенту для проверки:
   зачитай одной фразой и спроси «всё верно?». Клиент согласился — вызови book_appointment ещё раз с теми же данными.
   Поправил — вызови с исправленными. Сама подтверждение до вызова функции не проводи.
5. Только когда функция вернула ok, скажи, что клиент записан, назови номер записи и скажи, что подтверждение на экране.
   Если вернулась ошибка — спроси только то, чего не хватает.
Не задавай вопросы из следующих шагов раньше времени и не переспрашивай то, что клиент уже сказал.

ДРУГОЕ
- Отмена: номер записи и телефон → cancel_appointment. Обратный звонок: имя, телефон, тема → request_callback.
- Клиент прощается или просит закончить («стоп», «хватит») → вызови end_conversation, затем коротко попрощайся.

ШУМ И ОБРЫВКИ
Рядом с клиентом могут говорить другие люди. Если реплика бессвязная, непонятная или явно не тебе — не додумывай
смысл и не делай вид, что поняла: коротко скажи «простите, не расслышала» и продолжи с того места, где остановились
(в начале разговора — спроси, чем помочь). Если обрывок похож на
продолжение прошлой фразы клиента — объедини их по смыслу. Здоровайся только один раз — в начале.

ФУНКЦИИ
Вызывай функцию сразу и молча, говори только после результата. Никогда не произноси названия функций, slot_id и JSON.
Не больше одной функции за раз.

НАЧАЛО РАЗГОВОРА: поздоровайся, представься и спроси, чем помочь — одной фразой.

БАЗА ЗНАНИЙ
{kb_block}
"""


# ---------- описание функций ----------

def _fn(name: str, description: str, props: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": props,
            "required": required,
            "additionalProperties": False,
        },
    }


def tool_schemas() -> list[dict]:
    tools = [
        _fn(
            "get_available_slots",
            "Получить свободное время для консультации. Вызывай перед тем, как предлагать клиенту время.",
            {
                "date": {"type": "string", "description": f"Желаемая дата в формате YYYY-MM-DD, текущий год — {booking.now().year}. Пусто — ближайшие свободные."},
                "part_of_day": {"type": "string",
                                "description": "Желаемая часть дня, если клиент её назвал: утро, день или вечер."},
            },
            [],
        ),
        _fn(
            "book_appointment",
            "Записать клиента на консультацию. Вызывай только после явного подтверждения клиентом всех данных.",
            {
                "slot_id": {"type": "string", "description": "slot_id из ответа get_available_slots"},
                "client_name": {"type": "string", "description": "Имя клиента"},
                "phone": {"type": "string", "description": "Телефон клиента цифрами"},
                "service": {"type": "string", "description": "Тема консультации: услуга или тип приборов"},
                "company": {"type": "string", "description": "Организация клиента, если назвал"},
                "comment": {"type": "string", "description": "Важные детали из разговора"},
            },
            ["slot_id", "client_name", "phone", "service"],
        ),
        _fn(
            "cancel_appointment",
            "Отменить существующую запись по её номеру и телефону.",
            {
                "booking_number": {"type": "string", "description": f"Номер записи, например {config.BOOKING_PREFIX}-1001"},
                "phone": {"type": "string", "description": "Телефон, указанный при записи"},
            },
            ["booking_number", "phone"],
        ),
        _fn(
            "request_callback",
            "Оставить заявку на обратный звонок менеджера.",
            {
                "client_name": {"type": "string"},
                "phone": {"type": "string"},
                "topic": {"type": "string", "description": "Тема обращения"},
                "summary": {"type": "string", "description": "Краткое содержание разговора для менеджера"},
            },
            ["client_name", "phone", "topic"],
        ),
        _fn(
            "end_conversation",
            "Завершить разговор, когда клиент попрощался.",
            {"summary": {"type": "string", "description": "Итог разговора в 1–2 предложениях"}},
            ["summary"],
        ),
    ]
    if config.VECTOR_STORE_ID:
        # встроенный инструмент поиска по базе знаний Yandex AI Studio
        tools.append({"type": "function", "name": "file_search",
                      "description": config.VECTOR_STORE_ID, "parameters": {}})
    return tools


# ---------- выполнение ----------

Emit = Callable[[dict], Awaitable[None]]


async def run_tool(name: str, args: dict[str, Any], emit: Emit, ctx: dict) -> dict:
    """Выполнить функцию. emit — отправить событие в браузер (карточка записи и т.п.)."""
    if name == "get_available_slots":
        return booking.available_slots(args.get("date") or None, args.get("part_of_day") or None)

    if name == "book_appointment":
        # Записываем только после того, как клиент услышал время, имя и номер и ответил.
        # Первый вызов с новыми данными ничего не записывает — возвращает текст для подтверждения.
        # Номер берём из распознанной речи клиента: модель путает цифры, пересказывая их
        heard = booking.phone_from_speech(ctx.get("user_texts", [])[-6:])
        if heard and booking.normalize_phone(args.get("phone", "")) != heard:
            args = {**args, "phone": heard}
        chk = booking.check(args.get("slot_id", ""), args.get("client_name", ""), args.get("phone", ""))
        if not chk.get("ok"):
            return chk
        key = (chk["slot"], chk["name"].lower(), chk["phone"])
        turns = ctx.get("user_turns", 0)
        pend = ctx.get("pending_booking")
        # Ассистент уже сам зачитал данные с вопросом «верно?», и клиент после этого ответил — второй раз не спрашиваем
        la_text, la_turn = ctx.get("last_agent", ("", turns))
        la = la_text.lower()
        said_back = (la_turn < turns and chk["name"].lower()[:4] in la
                     and any(w in la for w in ("верно", "подтвер", "правильно")))
        confirmed = said_back or (pend and pend["key"] == key and pend["turn"] < turns)
        if not confirmed:
            ctx["pending_booking"] = {"key": key, "turn": turns}
            return {"ok": False, "need_confirmation": True,
                    "say": (f"Ещё не записано. Зачитай клиенту одной фразой: {chk['label']}, имя {chk['name']}, "
                            f"телефон {chk['phone_spoken']} (цифры группами, словами) — и спроси «всё верно?». "
                            "Если клиент подтвердит — вызови book_appointment ещё раз с теми же данными. "
                            "Если поправит — вызови с исправленными данными.")}
        ctx.pop("pending_booking", None)
        res = booking.book(
            slot=args.get("slot_id", ""),
            client_name=args.get("client_name", ""),
            phone=args.get("phone", ""),
            service=args.get("service", "Консультация"),
            company=args.get("company", "") or "",
            comment=args.get("comment", "") or "",
            channel=ctx.get("channel", "web"),
        )
        if res.get("ok"):
            b = res["booking"]
            ctx.setdefault("bookings", []).append(b["number"])
            await emit({"type": "booking", "booking": b})
            await notify.booking_created(b)
            confirm = ("Подтверждение показано на экране." if ctx.get("channel", "web") == "web"
                       else "Менеджер свяжется для подтверждения накануне.")
            return {"ok": True, "booking_number": b["number"], "when": b["when"],
                    "say": f"Запись оформлена, номер {b['number']}. {confirm}"}
        return res

    if name == "cancel_appointment":
        res = booking.cancel(args.get("booking_number", ""), args.get("phone", ""))
        if res.get("ok"):
            await emit({"type": "booking_cancelled", "booking": res["booking"]})
            await notify.booking_cancelled(res["booking"])
            return {"ok": True, "say": "Запись отменена."}
        return res

    if name == "request_callback":
        res = booking.add_callback(args.get("client_name", ""), args.get("phone", ""),
                                   args.get("topic", ""), args.get("summary", ""))
        await emit({"type": "callback", "data": args})
        await notify.callback_requested(args)
        return {**res, "say": "Заявка передана менеджеру, он перезвонит в рабочее время."}

    if name == "end_conversation":
        ctx["summary"] = args.get("summary", "")
        ctx["end_requested"] = True
        return {"ok": True, "say": "Попрощайся с клиентом одной короткой фразой."}

    return {"ok": False, "error": f"Неизвестная функция {name}"}


def parse_args(raw: str | None) -> dict:
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {}
    except json.JSONDecodeError:
        return {}
