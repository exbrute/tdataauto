from __future__ import annotations

import logging

from telethon.tl.types import Channel, Chat

logger = logging.getLogger(__name__)


def _rights_label(entity: Channel) -> str:
    if entity.creator:
        return "creator"
    rights = entity.admin_rights
    if not rights:
        return "admin"
    bits = []
    for name in (
        "change_info",
        "post_messages",
        "edit_messages",
        "delete_messages",
        "ban_users",
        "invite_users",
        "pin_messages",
        "add_admins",
        "manage_call",
    ):
        if getattr(rights, name, False):
            bits.append(name)
    return ", ".join(bits) if bits else "admin"


async def list_admin_chats(client) -> list[dict]:
    """Чаты и каналы, где текущая сессия состоит и имеет админ-права."""
    items: list[dict] = []
    seen: set[int] = set()

    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, Channel):
            if not (entity.creator or entity.admin_rights):
                continue
            if entity.id in seen:
                continue
            seen.add(entity.id)
            items.append(
                {
                    "id": entity.id,
                    "title": entity.title or dialog.name,
                    "username": entity.username,
                    "type": "channel" if entity.broadcast else "supergroup",
                    "rights": _rights_label(entity),
                    "members": getattr(entity, "participants_count", None),
                }
            )
        elif isinstance(entity, Chat) and getattr(entity, "admin_rights", None):
            if entity.id in seen:
                continue
            seen.add(entity.id)
            items.append(
                {
                    "id": entity.id,
                    "title": entity.title or dialog.name,
                    "username": None,
                    "type": "group",
                    "rights": "admin",
                    "members": getattr(entity, "participants_count", None),
                }
            )

    items.sort(key=lambda row: (row["type"], row["title"].lower()))
    logger.info("Найдено админ-чатов: %s", len(items))
    return items
