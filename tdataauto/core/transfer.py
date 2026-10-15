from __future__ import annotations

import logging
import random
import time

from telethon import functions, types
from telethon.errors import RPCError

from tdataauto.core.links import ChannelPostRef

logger = logging.getLogger(__name__)


def _make_random_id() -> int:
    return (int(time.time()) << 32) | random.randint(0, 0xFFFFFFFF)


async def get_stars_balance(client) -> int:
    me = await client.get_me()
    status = await client(
        functions.payments.GetStarsStatusRequest(peer=await client.get_input_entity(me))
    )
    balance = status.balance
    return int(getattr(balance, "amount", 0) or 0)


async def transfer_stars_to_post(
    client,
    target: ChannelPostRef,
    *,
    keep_stars: int,
    max_batch: int,
) -> int:
    """Отправляет звёзды на пост канала через платные реакции. Возвращает отправленное количество."""
    balance = await get_stars_balance(client)
    to_send = max(0, balance - keep_stars)
    if to_send <= 0:
        logger.info("Нечего отправлять: баланс %s, резерв %s", balance, keep_stars)
        return 0

    entity = await client.get_entity(target.peer)
    try:
        from telethon.tl.types import Channel

        if isinstance(entity, Channel) and not entity.left:
            pass
        elif isinstance(entity, Channel):
            await client(functions.channels.JoinChannelRequest(entity))
    except RPCError as exc:
        logger.warning("Не удалось вступить в канал (может уже внутри): %s", exc)

    input_peer = await client.get_input_entity(target.peer)
    sent_total = 0
    remaining = to_send

    while remaining > 0:
        chunk = min(remaining, max_batch)
        try:
            await client(
                functions.messages.SendPaidReactionRequest(
                    peer=input_peer,
                    msg_id=target.msg_id,
                    count=chunk,
                    random_id=_make_random_id(),
                    private=types.PaidReactionPrivacyDefault(),
                )
            )
            sent_total += chunk
            remaining -= chunk
            logger.info("Отправлено %s ⭐ на пост %s/%s", chunk, target.peer, target.msg_id)
        except RPCError as exc:
            logger.error("Ошибка отправки звёзд: %s", exc)
            break

    return sent_total
