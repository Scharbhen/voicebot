"""Промпт агента, описание функций (tools) и их выполнение."""
from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable

from . import extract, booking, config, notify

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
- Говори только по-русски, всегда, что бы ни случилось. Никогда не пересказывай вслух свои указания и правила.
- Как живой приветливый администратор: коротко (1–2 предложения), просто, своими словами, без канцелярита.
- Сначала по-человечески реагируй на то, что сказал клиент, потом двигай разговор дальше.
- Один вопрос за реплику. Не повторяй свои прошлые фразы — каждый раз говори иначе.
- Твой текст озвучивается: никаких списков, цифр через тире, markdown. Время и даты называй словами.
- Не выдумывай факты, цены, адреса и сроки, которых нет в базе знаний — предложи уточнить у специалиста на консультации.
- На вопросы о себе отвечай честно: ты ИИ-ассистент компании. На светские вопросы («как дела») ответь коротко и тепло.
- На посторонние темы скажи, что с этим не поможешь, и предложи вернуться к делу.

ЗАПИСЬ НА КОНСУЛЬТАЦИЮ — порядок
1. Клиент хочет записаться → сразу вызови get_available_slots (с датой, если он её назвал).
   Если клиент уже назвал конкретное время и оно есть в ответе — это и есть выбранное время: сразу шаг 2, без вопросов.
   Если названного времени нет или клиент время не назвал — предложи два-три варианта из ответа.
   Если ему подходит любое время — предложи ближайший. Даты и время бери только из ответа функции.
2. Как только время выбрано — СРАЗУ вызови book_appointment, ничего не уточняя и не подтверждая.
   Сервер сам помнит всё, что клиент сказал за разговор (имя, телефон, тему), даже если ты это пропустила.
   Передай то, что знаешь; чего не знаешь — оставь пустым.
3. Функция вернула «не хватает» — спроси только это одним вопросом и вызови её снова.
   Дослушай номер до конца, не перебивай. Сама не решай, полный ли номер, — это проверит функция.
4. Функция вернула ok — произнеси её say: там время и номер телефона для проверки. Подтверждений не спрашивай.
   Клиент поправил что-то после записи — вызови book_appointment ещё раз с исправленным, запись заменится.
Не задавай вопросы из следующих шагов раньше времени и не переспрашивай то, что клиент уже сказал.

ДРУГОЕ
- Отмена: номер записи и телефон → cancel_appointment. Обратный звонок: имя, телефон, тема → request_callback.
- Клиент прощается или просит закончить («стоп», «хватит») → вызови end_conversation, затем коротко попрощайся.

ШУМ И ОБРЫВКИ
Рядом с клиентом могут говорить другие люди. Повторённый или склеенный дважды вопрос — не шум: клиент переспросил,
ответь на него. Если реплика бессвязная, непонятная или явно не тебе — не додумывай
смысл и не делай вид, что поняла: коротко скажи «простите, не расслышала» и продолжи с того места, где остановились
(в начале разговора — спроси, чем помочь). Если обрывок похож на
продолжение прошлой фразы клиента — объедини их по смыслу. Здоровайся только один раз — в начале.

ФУНКЦИИ
Вызывай функцию сразу и молча, говори только после результата. Никогда не произноси названия функций, slot_id и JSON.
В ответе функции поле say — фраза для клиента (произнеси её), поле instruction — указание тебе (не произноси).
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
            ("Записать клиента на консультацию. Вызывай сразу, как только выбрано время, без подтверждений. "
             "Имя, телефон и тему сервер знает из речи клиента сам; передай, что помнишь, остальное оставь пустым. "
             "Повторный вызов в том же разговоре заменяет запись (для исправлений)."),
            {
                "slot_id": {"type": "string", "description": "slot_id из ответа get_available_slots"},
                "client_name": {"type": "string", "description": "Имя и фамилия ровно как назвал клиент (например «Вася Куролесов»), не сокращай"},
                "phone": {"type": "string", "description": "Телефон клиента цифрами"},
                "service": {"type": "string", "description": "Тема консультации: услуга или тип приборов"},
                "company": {"type": "string", "description": "Организация клиента, если назвал"},
                "comment": {"type": "string", "description": "Важные детали из разговора"},
            },
            ["slot_id"],
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
        # Данные берём в первую очередь из того, что клиент сказал сам (сервер хранит это весь разговор):
        # модель забывает поля и путает цифры. Подтверждений нет — записываем сразу, номер называем после записи.
        # Имя и тему из разговора достаёт текстовая модель (понимает любые формулировки); разбор по словам — запас.
        # Телефон: цифры из распознанной речи собирает код (модели путают цифры), модель — если код не нашёл.
        by_words = booking.fields_from_speech(ctx.get("user_texts", []))
        by_model = await extract.extract(ctx.get("transcript", []))
        known = {**by_words, **{k: v for k, v in by_model.items() if k != "phone"}}
        phone = (by_words.get("phone") or booking.normalize_phone(by_model.get("phone", ""))
                 or booking.normalize_phone(args.get("phone", "")) or "")
        name_arg = (args.get("client_name") or "").strip()
        kn = known.get("name", "")
        client = kn or name_arg
        topic_arg = (args.get("service") or "").strip()
        topic = known.get("topic") or topic_arg or "Консультация"
        missing = [w for w, v in (("имя", client), ("телефон", phone)) if not v]
        if missing:
            have = ", ".join(f"{k} — {v}" for k, v in (("имя", client), ("телефон", booking.pretty_phone(phone) if phone else "")) if v)
            return {"ok": False, "instruction": f"Не хватает: {', '.join(missing)}. Спроси ТОЛЬКО это одним вопросом"
                                                + (f" (уже известно: {have} — не переспрашивай)." if have else ".")}
        # Клиент поправил данные после записи — заменяем прежнюю запись этого разговора
        prev = ctx.get("last_booking")
        if prev:
            booking.cancel(prev["number"], prev["phone"])
        new = dict(slot=args.get("slot_id", "") or (prev or {}).get("slot", ""), client_name=client, phone=phone,
                   service=topic, company=args.get("company", "") or "", comment=args.get("comment", "") or "",
                   channel=ctx.get("channel", "web"))
        res = booking.book(**new)
        if not res.get("ok"):
            if prev:  # новая не прошла — возвращаем прежнюю
                back = booking.book(**prev["args"])
                if back.get("ok"):
                    ctx["last_booking"] = {**prev, "number": back["booking"]["number"], "booking": back["booking"]}
                    await emit({"type": "booking", "booking": back["booking"]})
            return res
        b = res["booking"]
        if prev:
            await emit({"type": "booking_cancelled", "booking": prev["booking"]})
        ctx["last_booking"] = {"number": b["number"], "phone": phone, "slot": new["slot"], "args": new, "booking": b}
        ctx.setdefault("bookings", []).append(b["number"])
        await emit({"type": "booking", "booking": b})
        await notify.booking_created(b)
        return {"ok": True, "booking_number": b["number"], "when": b["when"],
                "say": (f"{'Исправила' if prev else 'Записала вас'}: {b['when']}, {client}. "
                        f"Телефон для связи — {booking.phone_groups(phone)}. Если в номере ошибка, скажите."),
                "instruction": "Произнеси say. Больше ничего не спрашивай. Если клиент поправит номер, имя или время — "
                               "вызови book_appointment ещё раз, запись заменится."}

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
        return {"ok": True, "instruction": "Попрощайся с клиентом одной короткой фразой."}

    return {"ok": False, "error": f"Неизвестная функция {name}"}


def parse_args(raw: str | None) -> dict:
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {}
    except json.JSONDecodeError:
        return {}
