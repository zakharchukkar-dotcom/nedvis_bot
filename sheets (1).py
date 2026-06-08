import json
import os

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Вариант 1 (для облака): весь JSON-ключ лежит в переменной окружения
CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
# Вариант 2 (для запуска на своём компьютере): ключ лежит файлом рядом
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
WORKSHEET_NAME = os.getenv("GOOGLE_WORKSHEET", "Заявки")

HEADERS = ["Дата и время", "Цель покупки", "Бюджет", "Срочность", "Имя", "Телефон"]

_worksheet = None


def _get_credentials():
    """Берёт ключ Google: сначала из переменной окружения, иначе из файла."""
    if CREDENTIALS_JSON:
        info = json.loads(CREDENTIALS_JSON)
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    return Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)


def _get_worksheet():
    """Открывает лист один раз и кэширует его."""
    global _worksheet
    if _worksheet is not None:
        return _worksheet

    if not SHEET_ID:
        raise RuntimeError("Не задан GOOGLE_SHEET_ID")

    client = gspread.authorize(_get_credentials())
    spreadsheet = client.open_by_key(SHEET_ID)

    try:
        ws = spreadsheet.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(
            title=WORKSHEET_NAME, rows=1000, cols=len(HEADERS)
        )

    if not ws.row_values(1):
        ws.append_row(HEADERS, value_input_option="RAW")

    _worksheet = ws
    return ws


def append_lead(lead: dict) -> None:
    """Добавляет одну заявку в таблицу."""
    ws = _get_worksheet()
    ws.append_row(
        [
            lead["datetime"],
            lead["goal"],
            lead["budget"],
            lead["urgency"],
            lead["name"],
            lead["phone"],
        ],
        value_input_option="RAW",
    )
