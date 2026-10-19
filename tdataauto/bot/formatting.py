from __future__ import annotations

import html

from tdataauto.core.batch import BatchReport


def _esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""))


def format_profile_message(profile: dict | None, *, scan_error: str | None = None) -> str:
    if not profile:
        err = scan_error or "Не удалось прочитать аккаунт"
        return f"❌ <b>Скан</b>\n{_esc(err)}"
    acc = profile.get("account") or {}
    gifts = profile.get("gifts") or {}
    bots = profile.get("bots") or []
    bot_line = ", ".join(f"@{_esc(b.get('username', ''))}" for b in bots[:20]) or "—"
    if len(bots) > 20:
        bot_line += f" … (+{len(bots) - 20})"
    username = f"@{acc['username']}" if acc.get("username") else "—"
    premium = "Да" if acc.get("premium") else "Нет"
    name = acc.get("name") or acc.get("first_name") or "Аккаунт"
    return (
        f"📋 <b>{_esc(name)}</b>\n"
        f"Username: {_esc(username)}\n"
        f"Premium: {premium}\n"
        f"⭐ Звёзды: {_esc(profile.get('stars', 0))}\n"
        f"🎁 NFT: {_esc(gifts.get('nft', 0))} · обычных: {_esc(gifts.get('regular', 0))}\n"
        f"👥 Админ-чаты: {_esc(profile.get('admin_chats', 0))} · "
        f"каналы: {_esc(profile.get('admin_channels', 0))}\n"
        f"🤖 Боты (BotFather): {bot_line}"
    )


def format_pool_summary(items: list[dict]) -> str:
    if not items:
        return "Пул пуст. Пришлите ZIP с tdata."
    lines = [f"📦 В пуле: <b>{len(items)}</b> аккаунт(ов)\n"]
    for index, item in enumerate(items, start=1):
        profile = item.get("profile") or {}
        acc = profile.get("account") or {}
        label = acc.get("name") or acc.get("username") or item.get("file_name") or item.get("entry_id")
        stars = profile.get("stars", "—")
        err = item.get("scan_error")
        suffix = f" ⚠️ {_esc(err)}" if err and not profile else ""
        lines.append(f"{index}. {_esc(label)} · ⭐ {stars}{suffix}")
    lines.append("\nКнопка «Запустить» — продать подарки и отправить звёзды по всему пулу")
    return "\n".join(lines)


def format_batch_report(batch: BatchReport) -> str:
    lines = [
        "✅ <b>Пакетная обработка</b>",
        f"Аккаунтов: {batch.loaded} · успешно: {batch.succeeded}",
        f"⭐ Отправлено на канал: {batch.stars_sent}",
        f"🎁 Конвертировано подарков: {batch.gifts_converted}",
        f"🖼 NFT на витрине: {batch.nft_listed}",
        "",
    ]
    for item in batch.results:
        if item.ok and item.report:
            lines.append(
                f"• {_esc(item.name)}: ⭐ {item.report.stars_sent}, "
                f"nft {item.report.gifts.listed_for_resale}, gifts {item.report.gifts.converted}"
            )
        else:
            lines.append(f"• {_esc(item.name)}: ❌ {_esc(item.error or 'ошибка')}")
    text = "\n".join(lines)
    if len(text) > 3900:
        return text[:3900] + "\n…"
    return text
