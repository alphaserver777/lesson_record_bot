"""Модуль хранения данных (состояний) пользователя."""
from aiogram.fsm.state import State, StatesGroup


class ServiceDateState(StatesGroup):
    """Класс ServiceDateState. Хранит информацию и данные вводимые пользователем."""

    service_date = State()
    service_time = State()
    service_cancel = State()
    service_delete = State()
    service_delete_conf = State()
    search_client = State()
    reserve_day = State()
    mailing_for_day = State()
    service_confirm_time = State()


class RegistrationState(StatesGroup):
    """Состояния регистрации нового пользователя."""

    full_name = State()
    age = State()
    phone = State()


class AdminEditState(StatesGroup):
    """Редактирование данных студента администратором."""

    edit_price = State()
    edit_balance = State()


class AdminAddSingleState(StatesGroup):
    """Добавление разового занятия администратором."""

    date = State()
    time = State()


class AdminAddRegularState(StatesGroup):
    """Добавление регулярного занятия администратором."""

    day = State()
    time = State()
    duration = State()


class AdminCancelState(StatesGroup):
    """Отмена занятий (разовых или регулярных) админом."""

    date = State()
    time = State()
    mode = State()


class AdminReserve(StatesGroup):
    """Резервирование дня администратором."""

    reserve_date = State()
    reserve_times = State()
    note = State()


class PaymentState(StatesGroup):
    """Ввод суммы оплаты администратором."""

    amount = State()
