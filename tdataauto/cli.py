from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from tdataauto.config import Settings, ensure_data_dirs
from tdataauto.core.account_profile import build_account_profile
from tdataauto.core.admin_chats import list_admin_chats
from tdataauto.core.batch import run_batch
from tdataauto.core.pipeline import run_for_tdata
from tdataauto.core.session import client_from_tdata, find_tdata_root


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
    run.add_argument("--json", action="store_true", help="Печатать итог строкой TDATA_RESULT {json}")
    run.add_argument("-v", "--verbose", action="store_true")

    batch = sub.add_parser("run-batch", help="Обработать пул tdata")
    batch.add_argument(
        "--tdata",
        type=Path,
        action="append",
        required=True,
        help="Путь к tdata (можно указать несколько раз)",
    )
    batch.add_argument("--link", type=str, help="Ссылка на пост канала")
    batch.add_argument("--passcode", type=str, default=None)
    batch.add_argument("--json", action="store_true")
    batch.add_argument("-v", "--verbose", action="store_true")

    scan = sub.add_parser("scan-admins", help="Список чатов/каналов с админ-правами")
    scan.add_argument("--tdata", type=Path, required=True)
    scan.add_argument("--passcode", type=str, default=None)
    scan.add_argument("--json", action="store_true")
    scan.add_argument("-v", "--verbose", action="store_true")

    inspect = sub.add_parser("inspect-account", help="Профиль аккаунта из tdata")
    inspect.add_argument("--tdata", type=Path, required=True)
    inspect.add_argument("--passcode", type=str, default=None)
    inspect.add_argument("--json", action="store_true")
    inspect.add_argument("-v", "--verbose", action="store_true")

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
    passcode = args.passcode or os.getenv("TDATA_PASSCODE") or None
    proxy_url = os.getenv("TDATA_PROXY") or None
    report = await run_for_tdata(
        args.tdata,
        session_file,
        link,
        sell_mode=settings.sell_mode,
        resell_price=settings.resell_price,
        keep_stars=settings.keep_stars,
        max_paid_reaction_batch=settings.max_paid_reaction_batch,
        passcode=passcode,
        proxy_url=proxy_url,
    )
    payload = {
        "converted": report.gifts.converted,
        "listed": report.gifts.listed_for_resale,
        "skipped": report.gifts.skipped,
        "errors": report.gifts.errors or [],
        "stars_before": report.stars_before,
        "stars_sent": report.stars_sent,
        "stars_after": report.stars_after,
    }
    if args.json:
        print("TDATA_RESULT " + json.dumps(payload, ensure_ascii=False), flush=True)
    else:
        print(
            f"Конвертировано: {payload['converted']}, "
            f"выставлено на продажу: {payload['listed']}, "
            f"пропущено: {payload['skipped']}, "
            f"звёзд отправлено на канал: {payload['stars_sent']}, "
            f"остаток: {payload['stars_after']}"
        )
        if payload["errors"]:
            print("Ошибки:", *payload["errors"], sep="\n  ")
    return 0


def _report_payload(report) -> dict:
    return {
        "converted": report.gifts.converted,
        "listed": report.gifts.listed_for_resale,
        "skipped": report.gifts.skipped,
        "errors": report.gifts.errors or [],
        "stars_before": report.stars_before,
        "stars_sent": report.stars_sent,
        "stars_after": report.stars_after,
    }


async def _cmd_run_batch(args: argparse.Namespace) -> int:
    settings = Settings.load()
    _, sessions, _ = ensure_data_dirs(settings.data_dir)
    link = args.link or settings.channel_post_url
    if not link:
        print("Укажите --link или CHANNEL_POST_URL в .env", file=sys.stderr)
        return 2
    passcode = args.passcode or os.getenv("TDATA_PASSCODE") or None
    proxy_url = os.getenv("TDATA_PROXY") or None
    roots = [Path(item) for item in args.tdata]
    batch = await run_batch(
        roots,
        sessions,
        link,
        sell_mode=settings.sell_mode,
        resell_price=settings.resell_price,
        keep_stars=settings.keep_stars,
        max_paid_reaction_batch=settings.max_paid_reaction_batch,
        passcode=passcode,
        proxy_url=proxy_url,
    )
    payload = {
        "loaded": batch.loaded,
        "succeeded": batch.succeeded,
        "failed": batch.loaded - batch.succeeded,
        "stars_sent": batch.stars_sent,
        "gifts_converted": batch.gifts_converted,
        "nft_listed": batch.nft_listed,
        "accounts": [
            {
                "name": item.name,
                "tdata_path": item.tdata_path,
                "ok": item.ok,
                "error": item.error,
                "result": _report_payload(item.report) if item.report else None,
            }
            for item in batch.results
        ],
    }
    if args.json:
        print("TDATA_BATCH_RESULT " + json.dumps(payload, ensure_ascii=False), flush=True)
    else:
        print(
            f"Аккаунтов: {payload['loaded']}, успешно: {payload['succeeded']}, "
            f"звёзд отправлено: {payload['stars_sent']}, NFT на витрине: {payload['nft_listed']}"
        )
    return 0 if payload["succeeded"] else 1


async def _client_for_tdata(args: argparse.Namespace, session_prefix: str):
    settings = Settings.load()
    _, sessions, _ = ensure_data_dirs(settings.data_dir)
    passcode = args.passcode or os.getenv("TDATA_PASSCODE") or None
    proxy_url = os.getenv("TDATA_PROXY") or None
    tdata_path = find_tdata_root(args.tdata)
    session_file = sessions / f"{session_prefix}_{tdata_path.name}.session"
    client = await client_from_tdata(
        tdata_path,
        session_file,
        passcode=passcode,
        proxy_url=proxy_url,
    )
    return client, tdata_path


async def _cmd_scan_admins(args: argparse.Namespace) -> int:
    client, _tdata_path = await _client_for_tdata(args, "scan")
    try:
        me = await client.get_me()
        chats = await list_admin_chats(client)
        payload = {
            "account": {
                "id": me.id,
                "username": me.username,
                "name": me.first_name,
            },
            "chats": chats,
        }
        if args.json:
            print("TDATA_ADMIN_CHATS " + json.dumps(payload, ensure_ascii=False), flush=True)
        else:
            for chat in chats:
                user = f"@{chat['username']}" if chat.get("username") else str(chat["id"])
                print(f"{chat['type']}\t{chat['title']}\t{user}\t{chat['rights']}")
        return 0
    finally:
        await client.disconnect()


async def _cmd_inspect_account(args: argparse.Namespace) -> int:
    from datetime import datetime, timezone

    client, _tdata_path = await _client_for_tdata(args, "inspect")
    try:
        profile = await build_account_profile(client)
        payload = {
            **profile,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }
        if args.json:
            print("TDATA_ACCOUNT_PROFILE " + json.dumps(payload, ensure_ascii=False), flush=True)
        else:
            acc = payload["account"]
            user = f"@{acc['username']}" if acc.get("username") else str(acc["id"])
            print(
                f"{acc.get('name') or user}\t{user}\tpremium={acc.get('premium')}\t"
                f"stars={payload['stars']}\tnft={payload['gifts']['nft']}\t"
                f"admin_chats={payload['admin_chats']}\tadmin_channels={payload['admin_channels']}\t"
                f"bots={len(payload['bots'])}"
            )
        return 0
    finally:
        await client.disconnect()


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
    if args.command == "run-batch":
        return asyncio.run(_cmd_run_batch(args))
    if args.command == "scan-admins":
        return asyncio.run(_cmd_scan_admins(args))
    if args.command == "inspect-account":
        return asyncio.run(_cmd_inspect_account(args))
    if args.command == "bot":
        return asyncio.run(_cmd_bot(args))
    parser.error(f"Неизвестная команда: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
