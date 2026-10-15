from aiogram.fsm.state import State, StatesGroup


class UploadFlow(StatesGroup):
    waiting_link = State()
    waiting_archive = State()
