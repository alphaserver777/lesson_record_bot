"""Модуль конфиг для загрузки переменных окружения."""
import os

from dotenv import load_dotenv

from config_data.messages import START_MESSAGE as DEFAULT_START_MESSAGE


# Пытаемся загрузить из файла, указанного в ENV_FILE, иначе из .env (если есть),
# но не падаем, если файл отсутствует — значения могут быть переданы через env.
env_path = os.getenv("ENV_FILE")
if env_path and os.path.exists(env_path):
    load_dotenv(env_path)
else:
    load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
START_MESSAGE = os.getenv("START_MESSAGE") or DEFAULT_START_MESSAGE
BEGINNING_WORKING_DAY = int(os.getenv("BEGINNING_WORKING_DAY"))
END_WORKING_DAY = int(os.getenv("END_WORKING_DAY"))
ADMINS_TELEGRAM_ID = [int(i) for i in os.getenv("ADMINS_TELEGRAM_ID").split()] if os.getenv("ADMINS_TELEGRAM_ID") else []
WEEKENDS = [i.capitalize() for i in os.getenv("WEEKENDS").split()] if os.getenv("WEEKENDS") else []
LOCAL_UTC = os.getenv("LOCAL_UTC")
REMINDER_TIME = os.getenv("REMINDER_TIME")
CALENDAR_TIMEZONE = os.getenv("CALENDAR_TIMEZONE", "UTC")
MINI_APP_URL = os.getenv("MINI_APP_URL", "http://localhost:5173")
