from __future__ import annotations

import logging
import os
import shutil
import zipfile
from pathlib import Path

from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from tdataauto.bot.formatting import format_batch_report, format_pool_summary, format_profile_message
from tdataauto.bot.keyboard import (
    BTN_CANCEL,
    BTN_CLEAR,
    BTN_CLEARPASS,
    BTN_LINK,
    BTN_PASS,
    BTN_POOL,
    BTN_RUN,
    BTN_STATUS,
    BUTTONS,
    main_keyboard,
)
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
    proxy_line = (
        f"\nПрокси: <code>{proxy}</code>"
        if proxy
        else "\nПрокси не задан — если Telegram недоступен, укажите TDATA_PROXY в .env"
    )
    return (
        "Весь сценарий на кнопках внизу.\n\n"
        "1️⃣ «Ссылка на пост» — куда слать ⭐\n"
        "2️⃣ ZIP с <code>tdata</code> — скан и добавление в пул (можно несколько)\n"
        "3️⃣ «Запустить» — продажа подарков и перевод звёзд по всему пулу\n\n"
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
    kb = main_keyboard()

    async def reply(message: Message, text: str, **kwargs) -> Message:
        return await message.answer(text, reply_markup=kb, **kwargs)

    async def go_ready(message: Message, state: FSMContext) -> None:
        await state.set_state(BotFlow.ready)
        pool_size = len(load_pool(settings.data_dir, message.from_user.id))
        extra = (
            f"\n\n📦 В пуле: {pool_size}. Пришлите ещё ZIP или нажмите «Запустить»."
            if pool_size
            else "\n\nПришлите ZIP с tdata."
        )
        await reply(message, "Готов принимать архивы." + extra)

    async def show_status(message: Message, state: FSMContext) -> None:
        link = await _resolve_link(state, settings)
        await reply(
            message,
            f"SELL_MODE={settings.sell_mode}\n"
            f"RESELL_PRICE={settings.resell_price}\n"
            f"KEEP_STARS={settings.keep_stars}\n"
            f"Пост: {link or '(не задан)'}\n"
            f"Прокси: {_proxy_url() or '(не задан)'}\n"
            f"Passcode: {'задан' if await _passcode(state) else 'нет'}",
        )

    async def show_pool(message: Message) -> None:
        items = load_pool(settings.data_dir, message.from_user.id)
        await reply(message, format_pool_summary(items), parse_mode="HTML")

    async def do_clear_pool(message: Message) -> None:
        clear_pool(settings.data_dir, message.from_user.id)
        await reply(message, "Пул очищен.")

    async def do_clear_pass(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        data.pop("tdata_passcode", None)
        await state.set_data(data)
        if await _resolve_link(state, settings):
            await state.set_state(BotFlow.ready)
        await reply(message, "Passcode сброшен.")

    async def do_run(message: Message, state: FSMContext) -> None:
        user_id = message.from_user.id
        items = load_pool(settings.data_dir, user_id)
        if not items:
            await reply(message, "Пул пуст. Сначала пришлите ZIP с tdata.")
            return
        link = await _resolve_link(state, settings)
        if not link:
            await state.set_state(BotFlow.waiting_link)
            await reply(message, "Сначала укажите ссылку на пост канала.")
            return

        roots: list[Path] = []
        for item in items:
            extracted = entry_extracted_dir(settings.data_dir, user_id, item["entry_id"])
            try:
                roots.append(find_tdata_root(extracted))
            except FileNotFoundError:
                await reply(message, f"❌ tdata не найден для {item.get('file_name', item['entry_id'])}")
                return

        status_msg = await reply(message, f"Обрабатываю пул ({len(roots)} акк.)…")
        try:
            batch = await run_batch(
                roots,
                sessions,
                link,
                sell_mode=settings.sell_mode,
                resell_price=settings.resell_price,
                keep_stars=settings.keep_stars,
                max_paid_reaction_batch=settings.max_paid_reaction_batch,
                passcode=await _passcode(state),
                proxy_url=_proxy_url(),
            )
            await status_msg.edit_text(format_batch_report(batch), parse_mode="HTML")
            if batch.succeeded:
                clear_pool(settings.data_dir, user_id)
        except Exception as exc:
            logger.exception("run batch")
            await status_msg.edit_text(f"❌ Ошибка: {exc}")

    async def do_cancel(message: Message, state: FSMContext) -> None:
        if await _resolve_link(state, settings):
            await go_ready(message, state)
        else:
            await state.set_state(BotFlow.waiting_link)
            await reply(message, "Шаг отменён. Пул сохранён. Нажмите «Ссылка на пост».")

    @dp.message(CommandStart())
    async def start(message: Message, state: FSMContext) -> None:
        await reply(message, _help_text(settings), parse_mode="HTML")
        if await _resolve_link(state, settings):
            await go_ready(message, state)
        else:
            await state.set_state(BotFlow.waiting_link)
            await reply(message, "Нажмите «Ссылка на пост» и пришлите https://t.me/…/123")

    @dp.message(F.text == BTN_STATUS)
    async def on_status(message: Message, state: FSMContext) -> None:
        await show_status(message, state)

    @dp.message(F.text == BTN_POOL)
    async def on_pool(message: Message) -> None:
        await show_pool(message)

    @dp.message(F.text == BTN_CLEAR)
    async def on_clear(message: Message) -> None:
        await do_clear_pool(message)

    @dp.message(F.text == BTN_CLEARPASS)
    async def on_clearpass(message: Message, state: FSMContext) -> None:
        await do_clear_pass(message, state)

    @dp.message(F.text == BTN_RUN)
    async def on_run(message: Message, state: FSMContext) -> None:
        await do_run(message, state)

    @dp.message(F.text == BTN_CANCEL)
    async def on_cancel(message: Message, state: FSMContext) -> None:
        await do_cancel(message, state)

    @dp.message(F.text == BTN_LINK)
    async def on_ask_link(message: Message, state: FSMContext) -> None:
        await state.set_state(BotFlow.waiting_link)
        await reply(message, "Пришлите ссылку на пост: https://t.me/канал/123")

    @dp.message(F.text == BTN_PASS)
    async def on_ask_pass(message: Message, state: FSMContext) -> None:
        await state.set_state(BotFlow.waiting_passcode)
        await reply(message, "Пришлите локальный пароль Telegram Desktop одним сообщением.")

    @dp.message(BotFlow.waiting_passcode, F.text)
    async def on_passcode(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if text in BUTTONS:
            return
        await state.update_data(tdata_passcode=text)
        await reply(message, "Passcode сохранён.")
        if await _resolve_link(state, settings):
            await go_ready(message, state)
        else:
            await state.set_state(BotFlow.waiting_link)

    @dp.message(BotFlow.waiting_link, F.text)
    async def on_link(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if text in BUTTONS:
            return
        try:
            parse_channel_post_url(text)
        except ValueError as exc:
            await reply(message, str(exc))
            return
        await state.update_data(channel_link=text)
        await go_ready(message, state)

    @dp.message(F.document)
    async def on_archive(message: Message, state: FSMContext) -> None:
        link = await _resolve_link(state, settings)
        if not link:
            await state.set_state(BotFlow.waiting_link)
            await reply(message, "Сначала укажите ссылку на пост кнопкой «Ссылка на пост».")
            return
        await state.set_state(BotFlow.ready)

        doc = message.document
        if not doc or not doc.file_name:
            await reply(message, "Не удалось прочитать файл.")
            return
        if not doc.file_name.lower().endswith(".zip"):
            await reply(message, "Нужен ZIP-архив с папкой tdata.")
            return

        user_id = message.from_user.id
        entry_id, work_dir = allocate_entry_dir(settings.data_dir, user_id)
        archive_path = work_dir / doc.file_name
        extracted = work_dir / "extracted"

        status_msg = await reply(message, "Скачиваю архив…")
        try:
            await bot.download(doc, destination=archive_path)
            _extract_archive(archive_path, extracted)
            session_file = sessions / f"bot_{user_id}_{entry_id}.session"
            await status_msg.edit_text("Сканирую аккаунт (⭐, NFT, админки, боты)…")
            profile, scan_error = await inspect_tdata_path(
                extracted,
                session_file,
                passcode=await _passcode(state),
                proxy_url=_proxy_url(),
            )
            entry = new_pool_entry(
                entry_id=entry_id,
                file_name=doc.file_name,
                profile=profile,
                scan_error=scan_error,
            )
            items = append_entry(settings.data_dir, user_id, entry)
            text = format_profile_message(profile, scan_error=scan_error)
            text += f"\n\n📦 В пуле: <b>{len(items)}</b>. Ещё ZIP или «Запустить»"
            await status_msg.edit_text(text, parse_mode="HTML")
        except Exception as exc:
            logger.exception("upload")
            shutil.rmtree(work_dir, ignore_errors=True)
            await status_msg.edit_text(f"❌ Ошибка: {exc}")

    @dp.message(BotFlow.ready, F.text)
    async def on_text_ready(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if text in BUTTONS:
            return
        try:
            parse_channel_post_url(text)
        except ValueError:
            await reply(message, "Пришлите ZIP или нажмите кнопку внизу.")
            return
        await state.update_data(channel_link=text)
        await reply(message, "Ссылка на пост обновлена.")

    @dp.message()
    async def fallback(message: Message) -> None:
        await reply(message, "Нажмите кнопку внизу или пришлите ZIP с tdata.")

    logger.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_bot(verbose=True))
