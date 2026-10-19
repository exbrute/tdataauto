from __future__ import annotations

import logging
from pathlib import Path

from tdataauto.core.account_profile import build_account_profile
from tdataauto.core.session import client_from_tdata, find_tdata_root

logger = logging.getLogger(__name__)


async def inspect_tdata_path(
    base_path: Path,
    session_file: Path,
    *,
    passcode: str | None,
    proxy_url: str | None,
) -> tuple[dict | None, str | None]:
    """Возвращает (profile, error)."""
    try:
        tdata_root = find_tdata_root(base_path)
    except FileNotFoundError as exc:
        return None, str(exc)

    client = None
    try:
        client = await client_from_tdata(
            tdata_root,
            session_file,
            passcode=passcode,
            proxy_url=proxy_url,
        )
        profile = await build_account_profile(client)
        return profile, None
    except ConnectionError as exc:
        return None, str(exc)
    except Exception as exc:
        logger.exception("inspect_tdata_path")
        return None, str(exc)
    finally:
        if client:
            await client.disconnect()
