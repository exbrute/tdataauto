from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Iterable

from telethon import functions, types
from telethon.errors import RPCError
from telethon.tl.types import StarGiftUnique

logger = logging.getLogger(__name__)


@dataclass
class GiftActionResult:
    converted: int = 0
    listed_for_resale: int = 0
    skipped: int = 0
    errors: list[str] | None = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


def _saved_gift_input(gift: types.SavedStarGift) -> types.TypeInputSavedStarGift:
    if gift.msg_id is not None:
        return types.InputSavedStarGiftUser(msg_id=gift.msg_id)
    if gift.saved_id is not None:
        return types.InputSavedStarGiftChat(
            peer=types.InputPeerSelf(),
            saved_id=gift.saved_id,
        )
    raise ValueError("У подарка нет msg_id и saved_id")


def _is_unique(gift: types.SavedStarGift) -> bool:
    return isinstance(gift.gift, StarGiftUnique)


def _resell_price_for(gift: types.SavedStarGift, configured: int) -> int | None:
    if configured > 0:
        return configured
    raw = gift.gift
    if isinstance(raw, StarGiftUnique) and raw.resell_amount:
        for amount in raw.resell_amount:
            if getattr(amount, "amount", 0) > 0:
                return int(amount.amount)
    if hasattr(raw, "resell_min_stars") and raw.resell_min_stars:
        return int(raw.resell_min_stars)
    return None


async def _iter_saved_gifts(client, peer) -> Iterable[types.SavedStarGift]:
    offset = ""
    while True:
        page = await client(
            functions.payments.GetSavedStarGiftsRequest(
                peer=peer,
                offset=offset,
                limit=100,
            )
        )
        for item in page.gifts:
            yield item
        if not page.next_offset:
            break
        offset = page.next_offset


async def count_saved_gifts(client) -> dict[str, int]:
    me = await client.get_me()
    peer = await client.get_input_entity(me)
    nft = 0
    regular = 0
    async for saved in _iter_saved_gifts(client, peer):
        if _is_unique(saved):
            nft += 1
        else:
            regular += 1
    return {"nft": nft, "regular": regular, "total": nft + regular}


async def process_gifts(
    client,
    *,
    sell_mode: str,
    resell_price: int,
) -> GiftActionResult:
    result = GiftActionResult()
    me = await client.get_me()
    peer = await client.get_input_entity(me)

    now = int(time.time())
    convert_enabled = sell_mode in ("convert", "both")
    resell_enabled = sell_mode in ("resell", "both")

    async for saved in _iter_saved_gifts(client, peer):
        try:
            stargift_input = _saved_gift_input(saved)
        except ValueError as exc:
            result.skipped += 1
            result.errors.append(str(exc))
            continue

        if _is_unique(saved):
            if not resell_enabled:
                result.skipped += 1
                continue
            if saved.can_resell_at and saved.can_resell_at > now:
                result.skipped += 1
                logger.info("NFT-подарок ещё нельзя продать (can_resell_at=%s)", saved.can_resell_at)
                continue
            price = _resell_price_for(saved, resell_price)
            if price is None:
                result.skipped += 1
                result.errors.append("Не удалось определить цену перепродажи NFT-подарка")
                continue
            try:
                await client(
                    functions.payments.UpdateStarGiftPriceRequest(
                        stargift=stargift_input,
                        resell_amount=types.StarsAmount(amount=price, nanos=0),
                    )
                )
                result.listed_for_resale += 1
                logger.info("Выставлен на продажу NFT-подарок за %s ⭐", price)
            except RPCError as exc:
                result.errors.append(f"resell: {exc}")
                result.skipped += 1
            continue

        if not convert_enabled:
            result.skipped += 1
            continue

        convert_stars = saved.convert_stars or getattr(saved.gift, "convert_stars", 0) or 0
        if convert_stars <= 0:
            result.skipped += 1
            continue

        try:
            await client(
                functions.payments.ConvertStarGiftRequest(stargift=stargift_input)
            )
            result.converted += 1
            logger.info("Конвертирован подарок → ~%s ⭐", convert_stars)
        except RPCError as exc:
            if "STARGIFT_ALREADY_CONVERTED" in str(exc):
                result.skipped += 1
            else:
                result.errors.append(f"convert: {exc}")
                result.skipped += 1

    return result
