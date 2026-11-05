"""Загрузить kb/*.md в Vector Store Yandex AI Studio и получить VECTOR_STORE_ID для file_search.

Нужно только если база знаний большая (десятки страниц). Для небольшой базы
агент получает её целиком в промпте — это проще и быстрее.

Запуск:  python scripts/upload_kb.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from openai import OpenAI  # noqa: E402

from app import config  # noqa: E402


def main() -> None:
    client = OpenAI(api_key=config.YANDEX_API_KEY, base_url="https://ai.api.cloud.yandex.net/v1",
                    project=config.YANDEX_FOLDER_ID)
    file_ids = []
    for p in sorted(config.KB_DIR.glob("*.md")):
        f = client.files.create(file=open(p, "rb"), purpose="assistants")
        print("загружен", p.name, f.id)
        file_ids.append(f.id)
    vs = client.vector_stores.create(name=f"База знаний {config.COMPANY_NAME}", file_ids=file_ids,
                                     expires_after={"anchor": "last_active_at", "days": 30})
    while True:
        vs = client.vector_stores.retrieve(vs.id)
        print("статус:", vs.status)
        if vs.status in ("completed", "failed"):
            break
        time.sleep(2)
    print(f"\nДобавьте в .env:\nVECTOR_STORE_ID={vs.id}")


if __name__ == "__main__":
    main()
