from aiogram.fsm.state import State, StatesGroup


class BotFlow(StatesGroup):
    waiting_link = State()
    waiting_passcode = State()
    ready = State()
