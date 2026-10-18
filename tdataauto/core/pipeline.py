from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from tdataauto.core.gifts import GiftActionResult, process_gifts
from tdataauto.core.links import ChannelPostRef, parse_channel_post_url
from tdataauto.core.session import client_from_tdata, find_tdata_root
from tdataauto.core.transfer import get_stars_balance, transfer_stars_to_post

logger = logging.getLogger(__name__)


@dataclass
class RunReport:
    gifts: GiftActionResult
    stars_before: int
    stars_sent: int
    stars_after: int


async def run_for_tdata(
    tdata_root: Path,
    session_file: Path,
    channel_post_url: str,
    *,
    sell_mode: str,
    resell_price: int,
    keep_stars: int,
    max_paid_reaction_batch: int,
    passcode: str | None = None,
    proxy_url: str | None = None,
) -> RunReport:
    tdata_path = find_tdata_root(tdata_root)
    target = parse_channel_post_url(channel_post_url)

    client = await client_from_tdata(
        tdata_path,
        session_file,
        passcode=passcode,
        proxy_url=proxy_url,
    )
    try:
        stars_before = await get_stars_balance(client)
        gifts_result = await process_gifts(
            client,
            sell_mode=sell_mode,
            resell_price=resell_price,
        )
        stars_mid = await get_stars_balance(client)
        stars_sent = await transfer_stars_to_post(
            client,
            target,
            keep_stars=keep_stars,
            max_batch=max_paid_reaction_batch,
        )
        stars_after = await get_stars_balance(client)
        logger.info(
            "Готово: конвертировано=%s, на продаже=%s, звёзд было=%s, отправлено=%s, осталось=%s",
            gifts_result.converted,
            gifts_result.listed_for_resale,
            stars_before,
            stars_sent,
            stars_after,
        )
        return RunReport(
            gifts=gifts_result,
            stars_before=stars_before,
            stars_sent=stars_sent,
            stars_after=stars_after,
        )
    finally:
        await client.disconnect()
