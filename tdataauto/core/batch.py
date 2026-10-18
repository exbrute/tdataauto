from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from tdataauto.core.pipeline import RunReport, run_for_tdata

logger = logging.getLogger(__name__)


@dataclass
class AccountRunResult:
    name: str
    tdata_path: str
    ok: bool
    report: RunReport | None = None
    error: str = ""


@dataclass
class BatchReport:
    results: list[AccountRunResult] = field(default_factory=list)

    @property
    def loaded(self) -> int:
        return len(self.results)

    @property
    def succeeded(self) -> int:
        return sum(1 for item in self.results if item.ok)

    @property
    def stars_sent(self) -> int:
        return sum(item.report.stars_sent for item in self.results if item.ok and item.report)

    @property
    def gifts_converted(self) -> int:
        return sum(item.report.gifts.converted for item in self.results if item.ok and item.report)

    @property
    def nft_listed(self) -> int:
        return sum(item.report.gifts.listed_for_resale for item in self.results if item.ok and item.report)


async def run_batch(
    tdata_roots: list[Path],
    sessions_dir: Path,
    channel_post_url: str,
    *,
    sell_mode: str,
    resell_price: int,
    keep_stars: int,
    max_paid_reaction_batch: int,
    passcode: str | None = None,
    proxy_url: str | None = None,
) -> BatchReport:
    batch = BatchReport()
    for index, root in enumerate(tdata_roots, start=1):
        label = root.name or f"tdata-{index}"
        session_file = sessions_dir / f"pool_{index}_{label}.session"
        logger.info("Пул %s/%s: %s", index, len(tdata_roots), root)
        try:
            report = await run_for_tdata(
                root,
                session_file,
                channel_post_url,
                sell_mode=sell_mode,
                resell_price=resell_price,
                keep_stars=keep_stars,
                max_paid_reaction_batch=max_paid_reaction_batch,
                passcode=passcode,
                proxy_url=proxy_url,
            )
            batch.results.append(
                AccountRunResult(name=label, tdata_path=str(root), ok=True, report=report)
            )
        except Exception as exc:
            logger.exception("Ошибка аккаунта %s", label)
            batch.results.append(
                AccountRunResult(name=label, tdata_path=str(root), ok=False, error=str(exc))
            )
    return batch
