from __future__ import annotations

import asyncio
import logging
import os
import shutil
import zipfile
from pathlib import Path

from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from tdataauto.config import Settings, ensure_data_dirs
from tdataauto.core.links import parse_channel_post_url
from tdataauto.core.pipeline import run_for_tdata
from tdataauto.bot.states import UploadFlow

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


async def run_bot(*, verbose: bool = False) -> None:
    settings = Settings.load()
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN не задан в .env")

    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s")

    incoming, sessions, tmp = ensure_data_dirs(settings.data_dir)
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()
    dp.message.middleware(AdminGate())

    @dp.message(CommandStart())
    async def start(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer(
            "Привет! Я обрабатываю tdata:\n"
            "1️⃣ Отправь ссылку на пост канала (куда переводить звёзды).\n"
            "2️⃣ Отправь ZIP с папкой <code>tdata</code> из Telegram Desktop.\n\n"
            "Команды:\n"
            "/cancel — отмена\n"
            "/status — текущие настройки из .env",
            parse_mode="HTML",
        )
        await state.set_state(UploadFlow.waiting_link)

    @dp.message(Command("cancel"))
    async def cancel(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Отменено. Нажми /start чтобы начать снова.")

    @dp.message(Command("status"))
    async def status(message: Message) -> None:
        await message.answer(
            f"SELL_MODE={settings.sell_mode}\n"
            f"RESELL_PRICE={settings.resell_price}\n"
            f"KEEP_STARS={settings.keep_stars}\n"
            f"CHANNEL_POST_URL={settings.channel_post_url or '(задаётся в чате)'}"
        )

    @dp.message(UploadFlow.waiting_link, F.text)
    async def on_link(message: Message, state: FSMContext) -> None:
        try:
            parse_channel_post_url(message.text or "")
        except ValueError as exc:
            await message.answer(str(exc))
            return
        await state.update_data(channel_link=message.text.strip())
        await state.set_state(UploadFlow.waiting_archive)
        await message.answer("Ок. Теперь пришли ZIP-архив с tdata.")

    @dp.message(UploadFlow.waiting_archive, F.document)
    async def on_archive(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        link = data.get("channel_link") or settings.channel_post_url
        if not link:
            await message.answer("Сначала пришли ссылку на пост канала.")
            return

        doc = message.document
        if not doc or not doc.file_name:
            await message.answer("Не удалось прочитать файл.")
            return

        work_dir = tmp / f"{message.from_user.id}_{doc.file_unique_id}"
        work_dir.mkdir(parents=True, exist_ok=True)
        archive_path = work_dir / doc.file_name

        status_msg = await message.answer("Скачиваю архив…")
        try:
            await bot.download(doc, destination=archive_path)
            extracted = _extract_archive(archive_path, work_dir / "extracted")
            session_file = sessions / f"user_{message.from_user.id}_{doc.file_unique_id}.session"

            await status_msg.edit_text("Обрабатываю tdata (продажа подарков и перевод звёзд)…")
            report = await run_for_tdata(
                extracted,
                session_file,
                link,
                sell_mode=settings.sell_mode,
                resell_price=settings.resell_price,
                keep_stars=settings.keep_stars,
                max_paid_reaction_batch=settings.max_paid_reaction_batch,
            )
            text = (
                "✅ Готово\n"
                f"• Конвертировано подарков: {report.gifts.converted}\n"
                f"• Выставлено на перепродажу (NFT): {report.gifts.listed_for_resale}\n"
                f"• Пропущено: {report.gifts.skipped}\n"
                f"• Звёзд на балансе было: {report.stars_before}\n"
                f"• Отправлено на канал: {report.stars_sent}\n"
                f"• Остаток: {report.stars_after}"
            )
            if report.gifts.errors:
                text += "\n\n⚠️ Ошибки:\n" + "\n".join(report.gifts.errors[:10])
            await status_msg.edit_text(text)
        except Exception as exc:
            logger.exception("Ошибка обработки tdata")
            await status_msg.edit_text(f"❌ Ошибка: {exc}")
        finally:
            await state.clear()
            shutil.rmtree(work_dir, ignore_errors=True)

    @dp.message(UploadFlow.waiting_archive)
    async def need_zip(message: Message) -> None:
        await message.answer("Пришли ZIP-архив с папкой tdata (файлом, не текстом).")

    logger.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(run_bot(verbose=True))
