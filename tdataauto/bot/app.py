from __future__ import annotations

import logging
import os
import shutil
import zipfile
from pathlib import Path

from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from tdataauto.bot.formatting import format_batch_report, format_pool_summary, format_profile_message
from tdataauto.bot.pool import (
    allocate_entry_dir,
    append_entry,
    clear_pool,
    entry_extracted_dir,
    load_pool,
    new_pool_entry,
)
from tdataauto.bot.services import inspect_tdata_path
from tdataauto.bot.states import BotFlow
from tdataauto.config import Settings, ensure_data_dirs
from tdataauto.core.batch import run_batch
from tdataauto.core.links import parse_channel_post_url
from tdataauto.core.session import find_tdata_root

logger = logging.getLogger(__name__)


def _admin_ids() -> set[int]:
    raw = os.getenv("ADMIN_IDS", "")
    return {int(part) for part in raw.split(",") if part.strip().isdigit()}


class AdminGate(BaseMiddleware):
    async def __call__(self, handler, event, data):
        allowed = _admin_ids()
        user = getattr(event, "from_user", None)
        if allowed and user and user.id not in allowed:
            if hasattr(event, "answer"):
                await event.answer("Нет доступа.")
            return None
        return await handler(event, data)


def _extract_archive(archive_path: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(dest)
        return dest
    raise ValueError("Нужен ZIP-архив с папкой tdata внутри")


def _proxy_url() -> str | None:
    raw = os.getenv("TDATA_PROXY", "").strip()
    return raw or None


async def _resolve_link(state: FSMContext, settings: Settings) -> str | None:
    data = await state.get_data()
    link = (data.get("channel_link") or settings.channel_post_url or "").strip()
    return link or None


async def _passcode(state: FSMContext) -> str | None:
    data = await state.get_data()
    return (data.get("tdata_passcode") or os.getenv("TDATA_PASSCODE") or "").strip() or None


def _help_text(settings: Settings) -> str:
    proxy = _proxy_url()
    proxy_line = f"\nПрокси (TDATA_PROXY): <code>{proxy}</code>" if proxy else (
        "\nПрокси не задан — если Telegram недоступен, укажите <code>TDATA_PROXY=socks5://host:port</code> в .env"
    )
    return (
        "Привет! Весь сценарий теперь в боте:\n\n"
        "1️⃣ Ссылка на пост канала — команда /link или текст после /start\n"
        "2️⃣ ZIP с <code>tdata</code> — автоматически сканирую профиль и кладу в пул\n"
        "3️⃣ Можно прислать несколько ZIP подряд\n"
        "4️⃣ /run — продажа подарков и перевод ⭐ на пост для <b>всего пула</b>\n\n"
        "<b>Команды</b>\n"
        "/pool — что в пуле\n"
        "/run — обработать пул\n"
        "/clearpool — очистить пул\n"
        "/link URL — пост канала\n"
        "/passcode пароль — локальный passcode Telegram Desktop\n"
        "/clearpass — сброс passcode\n"
        "/status — настройки .env\n"
        "/cancel — сброс шага (пул не трогаю)\n\n"
        f"SELL_MODE={settings.sell_mode}, KEEP_STARS={settings.keep_stars}{proxy_line}"
    )


async def run_bot(*, verbose: bool = False) -> None:
    settings = Settings.load()
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN не задан в .env")

    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s")

    _incoming, sessions, _tmp = ensure_data_dirs(settings.data_dir)
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()
    dp.message.middleware(AdminGate())

    async def go_ready(message: Message, state: FSMContext) -> None:
        await state.set_state(BotFlow.ready)
        pool_size = len(load_pool(settings.data_dir, message.from_user.id))
        extra = f"\n\n📦 В пуле сейчас: {pool_size}. Пришлите ZIP или /run." if pool_size else "\n\nПришлите ZIP с tdata."
        await message.answer("Готов принимать архивы." + extra)

    @dp.message(CommandStart())
    async def start(message: Message, state: FSMContext) -> None:
        await message.answer(_help_text(settings), parse_mode="HTML")
        if await _resolve_link(state, settings):
            await go_ready(message, state)
        else:
            await state.set_state(BotFlow.waiting_link)
            await message.answer("Пришлите ссылку на пост канала (https://t.me/…/123).")

    @dp.message(Command("cancel"))
    async def cancel(message: Message, state: FSMContext) -> None:
        if await _resolve_link(state, settings):
            await go_ready(message, state)
        else:
            await state.set_state(BotFlow.waiting_link)
        await message.answer("Шаг отменён. Пул сохранён. /start — подсказки.")

    @dp.message(Command("status"))
    async def status(message: Message, state: FSMContext) -> None:
        link = await _resolve_link(state, settings)
        await message.answer(
            f"SELL_MODE={settings.sell_mode}\n"
            f"RESELL_PRICE={settings.resell_price}\n"
            f"KEEP_STARS={settings.keep_stars}\n"
            f"CHANNEL_POST_URL={link or settings.channel_post_url or '(не задан)'}\n"
            f"TDATA_PROXY={_proxy_url() or '(не задан)'}\n"
            f"Passcode в чате: {'да' if await _passcode(state) else 'нет'}",
        )

    @dp.message(Command("link"))
    async def cmd_link(message: Message, state: FSMContext) -> None:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Пример: /link https://t.me/my_channel/42")
            return
        try:
            parse_channel_post_url(parts[1])
        except ValueError as exc:
            await message.answer(str(exc))
            return
        await state.update_data(channel_link=parts[1].strip())
        await go_ready(message, state)

    @dp.message(Command("passcode"))
    async def cmd_passcode(message: Message, state: FSMContext) -> None:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Пример: /passcode 1234\nСброс: /clearpass")
            return
        await state.update_data(tdata_passcode=parts[1])
        await message.answer("Passcode сохранён для скана и /run.")

    @dp.message(Command("clearpass"))
    async def cmd_clearpass(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        data.pop("tdata_passcode", None)
        await state.set_data(data)
        await message.answer("Passcode из чата удалён.")

    @dp.message(Command("pool"))
    async def cmd_pool(message: Message) -> None:
        items = load_pool(settings.data_dir, message.from_user.id)
        await message.answer(format_pool_summary(items), parse_mode="HTML")

    @dp.message(Command("clearpool"))
    async def cmd_clearpool(message: Message) -> None:
        clear_pool(settings.data_dir, message.from_user.id)
        await message.answer("Пул очищен.")

    @dp.message(Command("run"))
    async def cmd_run(message: Message, state: FSMContext) -> None:
        user_id = message.from_user.id
        items = load_pool(settings.data_dir, user_id)
        if not items:
            await message.answer("Пул пуст. Сначала пришлите ZIP с tdata.")
            return
        link = await _resolve_link(state, settings)
        if not link:
            await message.answer("Сначала /link на пост канала (или CHANNEL_POST_URL в .env).")
            return

        roots: list[Path] = []
        for item in items:
            extracted = entry_extracted_dir(settings.data_dir, user_id, item["entry_id"])
            try:
                roots.append(find_tdata_root(extracted))
            except FileNotFoundError:
                await message.answer(f"❌ tdata не найден для {item.get('file_name', item['entry_id'])}")
                return

        status_msg = await message.answer(f"Обрабатываю пул ({len(roots)} акк.)…")
        passcode = await _passcode(state)
        proxy_url = _proxy_url()
        try:
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
            await status_msg.edit_text(format_batch_report(batch), parse_mode="HTML")
            if batch.succeeded:
                clear_pool(settings.data_dir, user_id)
        except Exception as exc:
            logger.exception("run batch")
            await status_msg.edit_text(f"❌ Ошибка: {exc}")

    @dp.message(BotFlow.waiting_link, F.text)
    async def on_link(message: Message, state: FSMContext) -> None:
        if message.text and message.text.startswith("/"):
            return
        try:
            parse_channel_post_url(message.text or "")
        except ValueError as exc:
            await message.answer(str(exc))
            return
        await state.update_data(channel_link=message.text.strip())
        await go_ready(message, state)

    @dp.message(BotFlow.ready, F.document)
    @dp.message(BotFlow.waiting_link, F.document)
    async def on_archive(message: Message, state: FSMContext) -> None:
        link = await _resolve_link(state, settings)
        if not link:
            await message.answer("Сначала ссылка на пост: текстом или /link …")
            return
        await state.set_state(BotFlow.ready)

        doc = message.document
        if not doc or not doc.file_name:
            await message.answer("Не удалось прочитать файл.")
            return
        if not doc.file_name.lower().endswith(".zip"):
            await message.answer("Нужен ZIP-архив с папкой tdata.")
            return

        user_id = message.from_user.id
        entry_id, work_dir = allocate_entry_dir(settings.data_dir, user_id)
        archive_path = work_dir / doc.file_name
        extracted = work_dir / "extracted"

        status_msg = await message.answer("Скачиваю архив…")
        try:
            await bot.download(doc, destination=archive_path)
            _extract_archive(archive_path, extracted)
            session_file = sessions / f"bot_{user_id}_{entry_id}.session"
            passcode = await _passcode(state)
            proxy_url = _proxy_url()

            await status_msg.edit_text("Сканирую аккаунт (⭐, NFT, админки, боты)…")
            profile, scan_error = await inspect_tdata_path(
                extracted,
                session_file,
                passcode=passcode,
                proxy_url=proxy_url,
            )
            entry = new_pool_entry(
                entry_id=entry_id,
                file_name=doc.file_name,
                profile=profile,
                scan_error=scan_error,
            )
            items = append_entry(settings.data_dir, user_id, entry)
            text = format_profile_message(profile, scan_error=scan_error)
            text += f"\n\n📦 В пуле: <b>{len(items)}</b>. Ещё ZIP или /run"
            await status_msg.edit_text(text, parse_mode="HTML")
        except Exception as exc:
            logger.exception("upload")
            shutil.rmtree(work_dir, ignore_errors=True)
            await status_msg.edit_text(f"❌ Ошибка: {exc}")

    @dp.message(BotFlow.ready, F.text)
    async def on_text_ready(message: Message, state: FSMContext) -> None:
        if message.text and message.text.startswith("/"):
            return
        try:
            parse_channel_post_url(message.text or "")
        except ValueError:
            await message.answer("Пришлите ZIP или команду. Ссылка: /link …")
            return
        await state.update_data(channel_link=message.text.strip())
        await message.answer("Ссылка на пост обновлена.")

    @dp.message(BotFlow.waiting_link)
    async def need_link(message: Message) -> None:
        await message.answer("Жду ссылку на пост канала (https://t.me/…/123).")

    @dp.message(BotFlow.ready)
    async def need_zip(message: Message) -> None:
        await message.answer("Пришлите ZIP с tdata или /pool, /run.")

    logger.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_bot(verbose=True))
