#!/usr/bin/env bash
# Запуск демо у себя на компьютере. Docker, если он есть, иначе Python.
set -e
cd "$(dirname "$0")"
[ -f .env ] || { cp .env.example .env; echo "Создан .env — впишите YANDEX_API_KEY и YANDEX_FOLDER_ID и запустите снова"; exit 1; }
mkdir -p data
if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
  # Docker Hub из России работает с перебоями — пробуем зеркала по очереди
  built=""
  for img in python:3.12-slim mirror.gcr.io/library/python:3.12-slim dockerhub.timeweb.cloud/library/python:3.12-slim; do
    echo "→ Собираю на базе $img"
    if BASE_IMAGE="$img" docker compose build; then built="$img"; break; fi
  done
  [ -n "$built" ] || { echo "Не удалось скачать базовый образ ни из одного источника. Запустите без Docker: ./run.sh"; exit 1; }
  docker compose up -d
  echo "✓ Запущено: http://localhost:8000   менеджер: http://localhost:8000/admin?token=$(grep ^ADMIN_TOKEN= .env | cut -d= -f2)"
  echo "  Логи: docker compose logs -f     Остановить: docker compose down"
else
  echo "Docker не найден — запускаю через Python (Ctrl+C для остановки)"
  echo "✓ http://localhost:8000   менеджер: http://localhost:8000/admin?token=$(grep ^ADMIN_TOKEN= .env | cut -d= -f2)"
  exec ./run.sh
fi
