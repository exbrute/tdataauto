from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from telethon import functions

from tdataauto.core.admin_chats import list_admin_chats
from tdataauto.core.gifts import count_saved_gifts
from tdataauto.core.transfer import get_stars_balance

logger = logging.getLogger(__name__)

BOTFATHER = "BotFather"
_USERNAME_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_]{3,31})\b")


def _display_name(first: str | None, last: str | None) -> str:
    return " ".join(part for part in (first or "", last or "") if part).strip()


def _collect_usernames(text: str, skip: set[str]) -> list[str]:
    found: list[str] = []
    for match in _USERNAME_RE.finditer(text or ""):
        name = match.group(1)
        if name.lower() in skip:
            continue
        if name not in found:
            found.append(name)
    return found


async def list_botfather_bots(client) -> list[dict[str, Any]]:
    """Боты, созданные через @BotFather (история + /mybots)."""
    skip = {"botfather", "telegram", "premiumbot"}
    candidates: list[str] = []

    async for message in client.iter_messages(BOTFATHER, limit=350):
        text = message.message or ""
        for name in _collect_usernames(text, skip):
            if name not in candidates:
                candidates.append(name)

    try:
        anchor = await client.send_message(BOTFATHER, "/mybots")
        await asyncio.sleep(1.8)
        mybots_names: list[str] = []
        async for message in client.iter_messages(BOTFATHER, min_id=anchor.id - 1, limit=12):
            text = message.message or ""
            for name in _collect_usernames(text, skip):
                if name not in mybots_names:
                    mybots_names.append(name)
            if message.buttons:
                for row in message.buttons:
                    for button in row:
                        label = getattr(button, "text", "") or ""
                        for name in _collect_usernames(label, skip):
                            if name not in mybots_names:
                                mybots_names.append(name)
        if mybots_names:
            candidates = mybots_names
    except Exception as exc:
        logger.warning("Не удалось запросить /mybots: %s", exc)

    return [{"username": name} for name in candidates]


async def build_account_profile(client) -> dict[str, Any]:
    me = await client.get_me()
    full = await client(functions.users.GetFullUserRequest(me))
    full_user = full.full_user
    premium = bool(getattr(me, "premium", False) or getattr(full_user, "premium", False))

    stars = await get_stars_balance(client)
    gifts = await count_saved_gifts(client)
    admin_items = await list_admin_chats(client)
    admin_channels = sum(1 for row in admin_items if row.get("type") == "channel")
    admin_chats = sum(1 for row in admin_items if row.get("type") in ("supergroup", "group"))
    bots = await list_botfather_bots(client)

    first = me.first_name or ""
    last = me.last_name or ""
    return {
        "account": {
            "id": me.id,
            "first_name": first,
            "last_name": last,
            "name": _display_name(first, last),
            "username": me.username,
            "premium": premium,
        },
        "stars": stars,
        "gifts": gifts,
        "admin_channels": admin_channels,
        "admin_chats": admin_chats,
        "bots": bots,
    }
