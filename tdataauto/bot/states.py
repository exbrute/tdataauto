from aiogram.fsm.state import State, StatesGroup


class BotFlow(StatesGroup):
    waiting_link = State()
    ready = State()
