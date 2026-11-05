#!/usr/bin/env bash
# Запуск демо: ./run.sh  → http://localhost:8000
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
[ -f .env ] || { cp .env.example .env; echo "Создан .env — впишите YANDEX_API_KEY и YANDEX_FOLDER_ID и запустите снова"; exit 1; }
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
