from __future__ import annotations

import logging
import urllib.parse
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


def parse_proxy(proxy_url: str | None) -> dict | None:
    if not proxy_url:
        return None
    parsed = urllib.parse.urlparse(proxy_url.strip())
    if parsed.scheme not in {"socks5", "socks4", "http"} or not parsed.hostname or not parsed.port:
        raise RuntimeError("Прокси должен быть вида socks5://host:port или http://user:pass@host:port")
    return {
        "proxy_type": parsed.scheme,
        "addr": parsed.hostname,
        "port": parsed.port,
        "username": urllib.parse.unquote(parsed.username) if parsed.username else None,
        "password": urllib.parse.unquote(parsed.password) if parsed.password else None,
        "rdns": True,
    }


async def client_from_tdata(
    tdata_path: Path,
    session_file: Path,
    *,
    passcode: str | None = None,
    proxy_url: str | None = None,
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
    proxy = parse_proxy(proxy_url)
    if proxy:
        client.set_proxy(proxy)
        logger.info("Прокси %s://%s:%s", proxy["proxy_type"], proxy["addr"], proxy["port"])
    else:
        logger.warning(
            "Прокси не задан (TDATA_PROXY). Если Telegram недоступен напрямую, "
            "укажите SOCKS5 на вкладке «Прокси» и выберите его для пула."
        )
    if hasattr(client, "_connection_retries"):
        client._connection_retries = 2
    if hasattr(client, "_timeout"):
        client._timeout = 10
    try:
        await client.connect()
    except (ConnectionError, OSError, TimeoutError) as exc:
        hint = (
            "Не удалось подключиться к Telegram через прокси. Проверьте тип (SOCKS5), хост и порт."
            if proxy
            else "Не удалось подключиться к Telegram. Скорее всего нужен SOCKS5/HTTP прокси "
            "(вкладка «Прокси» → выберите в «Прокси для пула» на «Аккаунтах»)."
        )
        raise ConnectionError(f"{hint} ({exc})") from exc
    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError("Сессия из tdata не авторизована в Telegram.")
    me = await client.get_me()
    logger.info("Подключён аккаунт %s (id=%s)", me.username or me.first_name, me.id)
    return client
