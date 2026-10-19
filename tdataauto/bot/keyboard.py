from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_POOL = "📦 Пул"
BTN_RUN = "▶️ Запустить"
BTN_CLEAR = "🗑 Очистить пул"
BTN_LINK = "🔗 Ссылка на пост"
BTN_PASS = "🔑 Passcode"
BTN_CLEARPASS = "✖ Сброс passcode"
BTN_STATUS = "ℹ️ Статус"
BTN_CANCEL = "↩️ Отмена"

BUTTONS = {
    BTN_POOL,
    BTN_RUN,
    BTN_CLEAR,
    BTN_LINK,
    BTN_PASS,
    BTN_CLEARPASS,
    BTN_STATUS,
    BTN_CANCEL,
}


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_POOL), KeyboardButton(text=BTN_RUN)],
            [KeyboardButton(text=BTN_CLEAR), KeyboardButton(text=BTN_LINK)],
            [KeyboardButton(text=BTN_PASS), KeyboardButton(text=BTN_CLEARPASS)],
            [KeyboardButton(text=BTN_STATUS), KeyboardButton(text=BTN_CANCEL)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )
