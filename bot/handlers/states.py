from aiogram.fsm.state import State, StatesGroup


class PriceFlow(StatesGroup):
    waiting_min = State()
    waiting_max = State()


class CitiesFlow(StatesGroup):
    waiting = State()


class IntervalFlow(StatesGroup):
    waiting = State()


class AdminFlow(StatesGroup):
    grant_username = State()
    broadcast = State()
