from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str | None
    api_id: int | None
    api_hash: str | None
    channel_post_url: str | None
    sell_mode: str
    resell_price: int
    keep_stars: int
    max_paid_reaction_batch: int
    data_dir: Path

    @classmethod
    def load(cls) -> Settings:
        api_id_raw = os.getenv("API_ID", "").strip()
        api_hash = os.getenv("API_HASH", "").strip() or None
        return cls(
            bot_token=os.getenv("BOT_TOKEN", "").strip() or None,
            api_id=int(api_id_raw) if api_id_raw.isdigit() else None,
            api_hash=api_hash,
            channel_post_url=os.getenv("CHANNEL_POST_URL", "").strip() or None,
            sell_mode=os.getenv("SELL_MODE", "both").strip().lower(),
            resell_price=int(os.getenv("RESELL_PRICE", "0") or 0),
            keep_stars=int(os.getenv("KEEP_STARS", "0") or 0),
            max_paid_reaction_batch=int(os.getenv("MAX_PAID_REACTION_BATCH", "2500") or 2500),
            data_dir=Path(os.getenv("DATA_DIR", "./data")),
        )


def ensure_data_dirs(base: Path) -> tuple[Path, Path, Path]:
    incoming = base / "incoming"
    sessions = base / "sessions"
    tmp = base / "tmp"
    for path in (incoming, sessions, tmp):
        path.mkdir(parents=True, exist_ok=True)
    return incoming, sessions, tmp
