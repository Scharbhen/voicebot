"""Настройки приложения. Все значения берутся из переменных окружения / файла .env."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# --- Yandex AI Studio ---
YANDEX_API_KEY = _env("YANDEX_API_KEY")
YANDEX_FOLDER_ID = _env("YANDEX_FOLDER_ID")
REALTIME_MODEL = _env("REALTIME_MODEL", "speech-realtime-max-tts-live/latest")
# ID голосового агента из AI Studio (необязательно). Если задан — промпт, голос и настройки речи
# берутся из агента в AI Studio, а наш промпт не отправляется. Функции записи подключаются в любом случае.
AGENT_PROMPT_ID = _env("AGENT_PROMPT_ID")
# Можно переопределить (например, на локальный мок для тестов)
REALTIME_URL = _env("REALTIME_URL") or (
    f"wss://ai.api.cloud.yandex.net/v1/realtime?model=gpt://{YANDEX_FOLDER_ID}/{REALTIME_MODEL}"
)

# --- Голос и аудио ---
VOICE = _env("VOICE")  # пусто = голос модели по умолчанию (для LiveTTS-модели подходят только LiveTTS-голоса)
VOICE_ROLE = _env("VOICE_ROLE")  # например "good"; пусто = по умолчанию
AUDIO_RATE = int(_env("AUDIO_RATE", "44100"))  # совместимость со старым .env
# Микрофон → сервер: 16 кГц хватает распознаванию и втрое легче для плохой связи (~256 кбит/с вместо ~700)
AUDIO_IN_RATE = int(_env("AUDIO_IN_RATE", "44100"))
# Голос ассистента → браузер
AUDIO_OUT_RATE = int(_env("AUDIO_OUT_RATE", str(AUDIO_RATE)))
LANGUAGE = _env("LANGUAGE", "ru-RU")
VAD_THRESHOLD = float(_env("VAD_THRESHOLD", "0.7"))
# «Шумовые ворота» в браузере: звук тише порога (пиковая амплитуда 0..1) не отправляется.
# 0 — выключено. 0.05–0.1 обычно отсекает дальние разговоры, не задевая голос у микрофона.
MIC_GATE = float(_env("MIC_GATE", "0.06"))
VAD_SILENCE_MS = int(_env("VAD_SILENCE_MS", "900"))
AGENT_SPEAKS_FIRST = _env("AGENT_SPEAKS_FIRST", "1") == "1"
# Писать в лог все события от Яндекса (кроме аудио) — для разбора нарезки реплик
DEBUG_EVENTS = _env("DEBUG_EVENTS", "0") == "1"

# --- База знаний ---
KB_DIR = BASE_DIR / "kb"
# Если задан ID поискового индекса (Vector Store) — подключаем встроенный file_search
VECTOR_STORE_ID = _env("VECTOR_STORE_ID")

# --- Компания и расписание ---
COMPANY_NAME = _env("COMPANY_NAME", "АУМСОФТ")
TIMEZONE = _env("TIMEZONE", "Europe/Moscow")
WORK_START_HOUR = int(_env("WORK_START_HOUR", "10"))
WORK_END_HOUR = int(_env("WORK_END_HOUR", "18"))
LUNCH_HOUR = int(_env("LUNCH_HOUR", "13"))  # -1 чтобы не исключать
SLOT_MINUTES = int(_env("SLOT_MINUTES", "60"))
BOOKING_HORIZON_DAYS = int(_env("BOOKING_HORIZON_DAYS", "14"))
BOOKING_PREFIX = _env("BOOKING_PREFIX", "AUM")

# --- Хранилище ---
DB_PATH = Path(_env("DB_PATH", str(BASE_DIR / "data" / "voicebot.sqlite3")))

# --- Уведомления (опционально) ---
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID")
SMTP_HOST = _env("SMTP_HOST")
SMTP_PORT = int(_env("SMTP_PORT", "465"))
SMTP_USER = _env("SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD")
SMTP_FROM = _env("SMTP_FROM") or SMTP_USER

# --- Доступ к странице менеджера ---
MCP_TOKEN = _env("MCP_TOKEN")  # токен для MCP-эндпоинта /mcp (агент в AI Studio)
ADMIN_TOKEN = _env("ADMIN_TOKEN")  # пусто = без пароля (только для локального демо)
PUBLIC_BASE_URL = _env("PUBLIC_BASE_URL", "http://localhost:8000")
