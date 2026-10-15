from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from tdataauto.config import Settings, ensure_data_dirs
from tdataauto.core.pipeline import run_for_tdata


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Продажа Telegram-подарков за звёзды из tdata и перевод звёзд на пост канала.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Обработать одну папку tdata")
    run.add_argument(
        "--tdata",
        type=Path,
        required=True,
        help="Путь к папке tdata или архиву/каталогу, где лежит tdata",
    )
    run.add_argument(
        "--link",
        type=str,
        help="Ссылка на пост канала (иначе CHANNEL_POST_URL из .env)",
    )
    run.add_argument("--passcode", type=str, default=None, help="Локальный пароль Telegram Desktop")
    run.add_argument("-v", "--verbose", action="store_true")

    bot = sub.add_parser("bot", help="Запустить Telegram-бота для загрузки tdata")
    bot.add_argument("-v", "--verbose", action="store_true")

    return parser


async def _cmd_run(args: argparse.Namespace) -> int:
    settings = Settings.load()
    _, sessions, _ = ensure_data_dirs(settings.data_dir)
    link = args.link or settings.channel_post_url
    if not link:
        print("Укажите --link или CHANNEL_POST_URL в .env", file=sys.stderr)
        return 2

    session_file = sessions / f"{args.tdata.resolve().name}.session"
    report = await run_for_tdata(
        args.tdata,
        session_file,
        link,
        sell_mode=settings.sell_mode,
        resell_price=settings.resell_price,
        keep_stars=settings.keep_stars,
        max_paid_reaction_batch=settings.max_paid_reaction_batch,
        passcode=args.passcode,
    )
    print(
        f"Конвертировано: {report.gifts.converted}, "
        f"выставлено на продажу: {report.gifts.listed_for_resale}, "
        f"пропущено: {report.gifts.skipped}, "
        f"звёзд отправлено на канал: {report.stars_sent}, "
        f"остаток: {report.stars_after}"
    )
    if report.gifts.errors:
        print("Ошибки:", *report.gifts.errors, sep="\n  ")
    return 0


async def _cmd_bot(args: argparse.Namespace) -> int:
    from tdataauto.bot.app import run_bot

    await run_bot(verbose=args.verbose)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(getattr(args, "verbose", False))

    if args.command == "run":
        return asyncio.run(_cmd_run(args))
    if args.command == "bot":
        return asyncio.run(_cmd_bot(args))
    parser.error(f"Неизвестная команда: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
