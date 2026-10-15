from __future__ import annotations

import logging
from pathlib import Path

from opentele.api import API, UseCurrentSession
from opentele.td import TDesktop
from opentele.tl import TelegramClient

from tdataauto.core.tdata_paths import find_tdata_root

logger = logging.getLogger(__name__)

__all__ = ["find_tdata_root", "client_from_tdata"]


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
