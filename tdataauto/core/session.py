from __future__ import annotations

import logging
from pathlib import Path

from opentele.api import API, UseCurrentSession
from opentele.td import TDesktop
from opentele.tl import TelegramClient

logger = logging.getLogger(__name__)


def find_tdata_root(base: Path) -> Path:
    """Найти папку tdata внутри распакованного архива или указанного пути."""
    base = base.resolve()
    if base.name.lower() == "tdata" and base.is_dir():
        return base
    candidate = base / "tdata"
    if candidate.is_dir():
        return candidate
    for path in base.rglob("tdata"):
        if path.is_dir() and any(path.iterdir()):
            return path
    raise FileNotFoundError(f"Папка tdata не найдена в {base}")


async def client_from_tdata(
    tdata_path: Path,
    session_file: Path,
    *,
    passcode: str | None = None,
) -> TelegramClient:
    tdesk = TDesktop(str(tdata_path), passcode=passcode)
    if not tdesk.isLoaded():
        raise RuntimeError(
            "Не удалось загрузить tdata. Проверьте папку, пароль локального passcode "
            "или что аккаунт уже авторизован в Telegram Desktop."
        )

    api = API.TelegramDesktop.Generate()
    session_file.parent.mkdir(parents=True, exist_ok=True)
    client = await tdesk.ToTelethon(
        session=str(session_file),
        flag=UseCurrentSession,
        api=api,
    )
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError("Сессия из tdata не авторизована в Telegram.")
    me = await client.get_me()
    logger.info("Подключён аккаунт %s (id=%s)", me.username or me.first_name, me.id)
    return client
