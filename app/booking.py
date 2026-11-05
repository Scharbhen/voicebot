"""Расписание, слоты и записи. Для демо — SQLite; в проде заменяется на календарь/CRM клиента."""
from __future__ import annotations

import re
import sqlite3
import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import config

TZ = ZoneInfo(config.TIMEZONE)

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
WEEKDAYS_ACC = ["понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
              "августа", "сентября", "октября", "ноября", "декабря"]

_lock = threading.Lock()


def now() -> datetime:
    return datetime.now(TZ)


def _connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number TEXT UNIQUE,
                slot TEXT NOT NULL,
                service TEXT,
                client_name TEXT,
                phone TEXT,
                company TEXT,
                comment TEXT,
                status TEXT DEFAULT 'confirmed',
                channel TEXT DEFAULT 'web',
                created_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS ux_active_slot
                ON bookings(slot) WHERE status = 'confirmed';
            CREATE TABLE IF NOT EXISTS callbacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name TEXT,
                phone TEXT,
                topic TEXT,
                summary TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                started_at TEXT,
                ended_at TEXT,
                transcript TEXT,
                summary TEXT
            );
            """
        )


# ---------- форматирование ----------

def human_date(d: date) -> str:
    today = now().date()
    prefix = ""
    if d == today:
        prefix = "сегодня, "
    elif d == today + timedelta(days=1):
        prefix = "завтра, "
    return f"{prefix}{WEEKDAYS[d.weekday()]}, {d.day} {MONTHS_GEN[d.month - 1]}"


def human_slot(dt: datetime) -> str:
    return f"{human_date(dt.date())}, в {dt.strftime('%H:%M')}"


def slot_id(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")


def parse_slot(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip()[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=TZ)
    except (ValueError, AttributeError):
        return None


# ---------- слоты ----------

def _taken() -> set[str]:
    with _connect() as c:
        rows = c.execute("SELECT slot FROM bookings WHERE status='confirmed'").fetchall()
    return {r["slot"] for r in rows}


def _day_slots(d: date) -> list[datetime]:
    if d.weekday() >= 5:  # выходные
        return []
    out = []
    t = datetime(d.year, d.month, d.day, config.WORK_START_HOUR, 0, tzinfo=TZ)
    end = datetime(d.year, d.month, d.day, config.WORK_END_HOUR, 0, tzinfo=TZ)
    while t + timedelta(minutes=config.SLOT_MINUTES) <= end:
        if t.hour != config.LUNCH_HOUR:
            out.append(t)
        t += timedelta(minutes=config.SLOT_MINUTES)
    return out


PARTS = {"утро": (0, 12), "день": (12, 16), "вечер": (16, 24)}


def available_slots(on_date: str | None = None, part_of_day: str | None = None, limit: int = 6) -> dict:
    """Свободные слоты: на конкретную дату или ближайшие."""
    current = now()
    earliest = current + timedelta(hours=2)  # не записываем «через 5 минут»
    taken = _taken()
    part = PARTS.get((part_of_day or "").strip().lower())

    requested: date | None = None
    if on_date:
        try:
            requested = date.fromisoformat(on_date.strip()[:10])
        except ValueError:
            requested = None
        # модель по привычке подставляет прошлый год — переносим дату на ближайший такой же день в будущем
        if requested and requested < current.date():
            for y in (current.year, current.year + 1):
                try:
                    fixed = requested.replace(year=y)
                except ValueError:
                    continue
                if fixed >= current.date():
                    requested = fixed
                    break

    def free_on(d: date) -> list[datetime]:
        res = []
        for s in _day_slots(d):
            if s < earliest or slot_id(s) in taken:
                continue
            if part and not (part[0] <= s.hour < part[1]):
                continue
            res.append(s)
        return res

    result: list[datetime] = []
    note = ""
    if requested:
        if requested < current.date():
            note = "Запрошенная дата уже прошла. Ниже ближайшие свободные слоты."
        elif requested.weekday() >= 5:
            note = f"{human_date(requested).capitalize()} — выходной. Ниже ближайшие свободные слоты."
        else:
            result = free_on(requested)
            if not result and part:
                # в эту часть дня занято — показываем остальное время того же дня, а не другой день
                part = None
                result = free_on(requested)
                if result:
                    note = (f"На {human_date(requested)} в эту часть дня свободного времени нет, "
                            "но есть другое время в тот же день — предложи его.")
            if not result:
                note = f"На {human_date(requested)} свободных слотов нет. Ниже ближайшие свободные."
    if not result:
        start = max(requested or current.date(), current.date())
        for i in range(config.BOOKING_HORIZON_DAYS + 1):
            d = start + timedelta(days=i)
            day = free_on(d)
            # для «ближайших» берём не больше 3 слотов в день — так варианты разнообразнее
            result.extend(day[:3] if not requested else day)
            if len(result) >= limit:
                break

    slots = [{"slot_id": slot_id(s), "label": human_slot(s)} for s in result[:limit]]
    return {
        "note": note,
        "slots": slots,
        "hint": ("Если клиент назвал конкретное время и его нет в slots — прямо скажи, что на это время записи нет "
                 f"(приём с {config.WORK_START_HOUR} до {config.WORK_END_HOUR}), и предложи ближайшие варианты. "
                 "Никогда не подставляй другое время молча. Для записи используй slot_id."),
    }


# ---------- записи ----------

def normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits[0] in "78":
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    else:
        return None
    return f"+{digits}"


_UNITS = {"ноль": 0, "нуль": 0, "один": 1, "одна": 1, "раз": 1, "два": 2, "две": 2, "три": 3, "четыре": 4,
          "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9}
_TEENS = {"десять": 10, "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14,
          "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19}
_TENS = {"двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50, "шестьдесят": 60, "семьдесят": 70,
         "восемьдесят": 80, "девяносто": 90}
_HUNDREDS = {"сто": 100, "двести": 200, "триста": 300, "четыреста": 400, "пятьсот": 500, "шестьсот": 600,
             "семьсот": 700, "восемьсот": 800, "девятьсот": 900}


def _num_runs(text: str) -> list[str]:
    """Последовательности чисел из фразы: «семь восемьсот двенадцать раз два» → ['78121', ...].
    Числа, сказанные подряд, склеиваются в одну строку цифр; любое другое слово разрывает последовательность."""
    runs, run, cur, place = [], "", None, 0
    def flush():
        nonlocal run, cur, place
        if cur is not None:
            run += str(cur)
        cur, place = None, 0
    for tok in re.findall(r"[а-яё]+|\d+|[^\sа-яё\d]", (text or "").lower()):
        if tok.isdigit():
            flush(); run += tok; continue
        if tok in _HUNDREDS: v, p = _HUNDREDS[tok], 3
        elif tok in _TENS: v, p = _TENS[tok], 2
        elif tok in _TEENS: v, p = _TEENS[tok], 1.5
        elif tok in _UNITS: v, p = _UNITS[tok], 1
        elif tok in ("-", "+", "(", ")", ",", "и"):
            continue
        else:
            flush()
            if run: runs.append(run)
            run = ""; continue
        # «восемьсот двенадцать» — одно число; «семь восемьсот» — два; ноль всегда отдельная цифра
        joinable = cur is not None and tok not in ("ноль", "нуль") and (
            (place == 3 and p < 3) or (place == 2 and p == 1))
        if joinable:
            cur += v; place = p
        else:
            flush(); cur, place = v, p
    flush()
    if run: runs.append(run)
    return runs


def phone_from_speech(texts: list[str]) -> str | None:
    """Номер телефона из последних реплик клиента (как распознал Яндекс), без пересказа моделью."""
    for t in reversed(texts):
        for r in reversed(_num_runs(t)):
            n = normalize_phone(r)
            if n:
                return n
    return None


def pretty_phone(p: str) -> str:
    d = p.lstrip("+")
    return f"+{d[0]} ({d[1:4]}) {d[4:7]}-{d[7:9]}-{d[9:11]}" if len(d) == 11 else p


def check(slot: str, client_name: str, phone: str) -> dict:
    """Проверить данные записи, ничего не записывая."""
    dt = parse_slot(slot)
    if dt is None:
        return {"ok": False, "error": "Некорректный slot_id. Сначала вызови get_available_slots."}
    if dt not in _day_slots(dt.date()) or dt < now():
        return {"ok": False, "error": "Такого слота нет в расписании. Предложи клиенту слоты из get_available_slots."}
    if slot_id(dt) in _taken():
        return {"ok": False, "error": "Это время уже занято. Вызови get_available_slots и предложи другие варианты."}
    norm = normalize_phone(phone)
    if not norm:
        return {"ok": False, "error": "Номер похож на неполный. Повтори клиенту номер, как его расслышала, и попроси поправить. Имя и время не переспрашивай."}
    if not (client_name or "").strip():
        return {"ok": False, "error": "Не указано имя клиента. Спроси, как к нему обращаться."}
    return {"ok": True, "slot": slot_id(dt), "label": human_slot(dt), "phone": norm,
            "phone_spoken": pretty_phone(norm), "name": client_name.strip()}


def book(slot: str, client_name: str, phone: str, service: str,
         company: str = "", comment: str = "", channel: str = "web") -> dict:
    dt = parse_slot(slot)
    if not dt:
        return {"ok": False, "error": "Некорректный slot_id. Сначала вызови get_available_slots."}
    if dt not in _day_slots(dt.date()) or dt < now():
        return {"ok": False, "error": "Такого слота нет в расписании. Предложи клиенту слоты из get_available_slots."}
    norm = normalize_phone(phone)
    if not norm:
        return {"ok": False, "error": "Номер похож на неполный. Повтори клиенту номер, как его расслышала, и попроси поправить. Имя и время не переспрашивай."}
    if not (client_name or "").strip():
        return {"ok": False, "error": "Не указано имя клиента. Спроси, как к нему обращаться."}

    with _lock, _connect() as c:
        try:
            cur = c.execute(
                "INSERT INTO bookings(slot, service, client_name, phone, company, comment, channel, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (slot_id(dt), service.strip(), client_name.strip(), norm, company.strip(),
                 comment.strip(), channel, now().isoformat(timespec="seconds")),
            )
        except sqlite3.IntegrityError:
            return {"ok": False, "error": "Этот слот только что заняли. Вызови get_available_slots и предложи другие варианты."}
        number = f"{config.BOOKING_PREFIX}-{1000 + cur.lastrowid}"
        c.execute("UPDATE bookings SET number=? WHERE id=?", (number, cur.lastrowid))

    return {"ok": True, "booking": get_booking(number)}


def _row_to_booking(r: sqlite3.Row) -> dict:
    dt = parse_slot(r["slot"])
    return {
        "number": r["number"],
        "slot": r["slot"],
        "when": human_slot(dt) if dt else r["slot"],
        "date_iso": dt.isoformat() if dt else None,
        "duration_min": config.SLOT_MINUTES,
        "service": r["service"],
        "client_name": r["client_name"],
        "phone": pretty_phone(r["phone"]),
        "company": r["company"],
        "comment": r["comment"],
        "status": r["status"],
        "channel": r["channel"],
        "created_at": r["created_at"],
    }


def get_booking(number: str) -> dict | None:
    with _connect() as c:
        r = c.execute("SELECT * FROM bookings WHERE number=?", (number.strip().upper(),)).fetchone()
    return _row_to_booking(r) if r else None


def cancel(number: str, phone: str) -> dict:
    norm = normalize_phone(phone)
    b = get_booking(number or "")
    if not b or b["status"] != "confirmed":
        return {"ok": False, "error": "Запись с таким номером не найдена. Уточни номер записи."}
    if not norm or pretty_phone(norm) != b["phone"]:
        return {"ok": False, "error": "Телефон не совпадает с указанным при записи. Уточни номер телефона."}
    with _lock, _connect() as c:
        c.execute("UPDATE bookings SET status='cancelled' WHERE number=?", (b["number"],))
    b["status"] = "cancelled"
    return {"ok": True, "booking": b}


def add_callback(client_name: str, phone: str, topic: str, summary: str) -> dict:
    norm = normalize_phone(phone) or phone
    with _connect() as c:
        c.execute(
            "INSERT INTO callbacks(client_name, phone, topic, summary, created_at) VALUES (?,?,?,?,?)",
            (client_name, norm, topic, summary, now().isoformat(timespec="seconds")),
        )
    return {"ok": True}


def save_conversation(session_id: str, started_at: str, transcript: list[dict], summary: str = "") -> None:
    import json
    with _connect() as c:
        c.execute(
            "INSERT INTO conversations(session_id, started_at, ended_at, transcript, summary) VALUES (?,?,?,?,?)",
            (session_id, started_at, now().isoformat(timespec="seconds"),
             json.dumps(transcript, ensure_ascii=False), summary),
        )


def list_all() -> dict:
    with _connect() as c:
        bookings = [_row_to_booking(r) for r in c.execute("SELECT * FROM bookings ORDER BY id DESC LIMIT 200")]
        callbacks = [dict(r) for r in c.execute("SELECT * FROM callbacks ORDER BY id DESC LIMIT 200")]
        convs = [dict(r) for r in c.execute(
            "SELECT id, session_id, started_at, ended_at, transcript, summary FROM conversations ORDER BY id DESC LIMIT 50")]
    for cb in callbacks:
        cb["phone"] = pretty_phone(cb["phone"] or "")
    return {"bookings": bookings, "callbacks": callbacks, "conversations": convs}


def calendar(days: int | None = None) -> list[dict]:
    """Рабочие дни на горизонт записи: слоты со статусом (свободно / запись / прошло)."""
    days = days or config.BOOKING_HORIZON_DAYS
    with _connect() as c:
        rows = c.execute("SELECT * FROM bookings WHERE status='confirmed'").fetchall()
    by_slot = {r["slot"]: _row_to_booking(r) for r in rows}
    cur = now()
    out = []
    for i in range(days + 1):
        d = cur.date() + timedelta(days=i)
        slots = _day_slots(d)
        if not slots:
            continue
        items = []
        for sl in slots:
            sid = slot_id(sl)
            b = by_slot.get(sid)
            items.append({
                "time": sl.strftime("%H:%M"),
                "status": "booked" if b else ("past" if sl < cur else "free"),
                "booking": b,
            })
        out.append({"date": d.isoformat(), "label": human_date(d), "slots": items})
    return out


def to_ics(b: dict) -> str:
    dt = parse_slot(b["slot"])
    start = dt.astimezone(ZoneInfo("UTC"))
    end = start + timedelta(minutes=b["duration_min"])
    fmt = "%Y%m%dT%H%M%SZ"
    desc = f"Запись {b['number']}. {b['service']}. Контакт: {b['phone']}"
    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//voicebot-demo//RU", "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        f"UID:{b['number']}@voicebot-demo",
        f"DTSTAMP:{datetime.now(ZoneInfo('UTC')).strftime(fmt)}",
        f"DTSTART:{start.strftime(fmt)}",
        f"DTEND:{end.strftime(fmt)}",
        f"SUMMARY:Консультация {config.COMPANY_NAME}: {b['service']}",
        f"DESCRIPTION:{desc}",
        "END:VEVENT", "END:VCALENDAR", "",
    ])
