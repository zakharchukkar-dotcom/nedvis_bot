import asyncio
import logging
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

import sheets

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("realty_bot")

# ------------------------- Конфигурация -------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")
TZ = ZoneInfo(os.getenv("TZ", "Asia/Yekaterinburg"))  # Тюмень = UTC+5

router = Router()


# ------------------------- Состояния анкеты -------------------------
class Survey(StatesGroup):
    goal = State()
    budget = State()
    urgency = State()
    name = State()
    phone = State()


# ------------------------- Варианты ответов -------------------------
GOALS = {
    "g1": "Для собственного проживания",
    "g2": "Для инвестиций",
    "g3": "Рассматриваю оба варианта",
}
BUDGETS = {
    "b1": "3–5 млн ₽",
    "b2": "5–7 млн ₽",
    "b3": "7–10 млн ₽",
    "b4": "Более 10 млн ₽",
}
URGENCY = {
    "u1": "Рассматриваю покупку на перспективу",
    "u2": "Готов(а) к покупке при появлении подходящего варианта",
    "u3": "Планирую выйти на сделку в ближайшее время",
}


# ------------------------- Клавиатуры -------------------------
def kb_from(options: dict) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=text, callback_data=key)]
        for key, text in options.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


START_KB = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Начать", callback_data="start_survey")]
    ]
)

PHONE_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📱 Отправить номер телефона", request_contact=True)]
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
    input_field_placeholder="Или введите номер вручную",
)

WELCOME = (
    "Добро пожаловать! Поможем подобрать недвижимость для жизни или инвестиций. "
    "Ответьте на несколько вопросов, чтобы мы могли предложить наиболее "
    "подходящие варианты."
)


# ------------------------- /start -------------------------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(WELCOME, reply_markup=START_KB)


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    """Служебная команда: показывает chat_id (для настройки ADMIN_CHAT_ID)."""
    await message.answer(f"Ваш chat_id: <code>{message.chat.id}</code>")


@router.callback_query(F.data == "start_survey")
async def start_survey(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Survey.goal)
    await call.message.answer(
        "С какой целью вы рассматриваете покупку недвижимости?",
        reply_markup=kb_from(GOALS),
    )
    await call.answer()


# ------------------------- Шаг 1: цель -------------------------
@router.callback_query(Survey.goal, F.data.in_(set(GOALS.keys())))
async def got_goal(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(goal=GOALS[call.data])
    await state.set_state(Survey.budget)
    await call.message.answer(
        "Какой бюджет покупки вы планируете?",
        reply_markup=kb_from(BUDGETS),
    )
    await call.answer()


# ------------------------- Шаг 2: бюджет -------------------------
@router.callback_query(Survey.budget, F.data.in_(set(BUDGETS.keys())))
async def got_budget(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(budget=BUDGETS[call.data])
    await state.set_state(Survey.urgency)
    await call.message.answer(
        "Насколько срочно вам необходим объект?",
        reply_markup=kb_from(URGENCY),
    )
    await call.answer()


# ------------------------- Шаг 3: срочность -------------------------
@router.callback_query(Survey.urgency, F.data.in_(set(URGENCY.keys())))
async def got_urgency(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(urgency=URGENCY[call.data])
    await state.set_state(Survey.name)
    await call.message.answer("Напишите ваше имя")
    await call.answer()


# ------------------------- Шаг 4: имя -------------------------
@router.message(Survey.name, F.text)
async def got_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Пожалуйста, напишите ваше имя 🙏")
        return
    await state.update_data(name=name)
    await state.set_state(Survey.phone)
    await message.answer("Укажите номер телефона", reply_markup=PHONE_KB)


@router.message(Survey.name)
async def name_invalid(message: Message) -> None:
    await message.answer("Пожалуйста, напишите ваше имя текстом 🙏")


# ------------------------- Шаг 5: телефон -------------------------
def normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits[0] in ("7", "8"):
        return "+7" + digits[1:]
    if len(digits) == 10:
        return "+7" + digits
    return None


@router.message(Survey.phone, F.contact)
async def got_contact(message: Message, state: FSMContext, bot: Bot) -> None:
    await finish(message, state, bot, message.contact.phone_number)


@router.message(Survey.phone, F.text)
async def got_phone_text(message: Message, state: FSMContext, bot: Bot) -> None:
    phone = normalize_phone(message.text)
    if not phone:
        await message.answer(
            "Не удалось распознать номер. Введите его в формате +7XXXXXXXXXX "
            "или нажмите кнопку ниже 📱",
            reply_markup=PHONE_KB,
        )
        return
    await finish(message, state, bot, phone)


@router.message(Survey.phone)
async def phone_invalid(message: Message) -> None:
    await message.answer(
        "Пожалуйста, отправьте номер телефона кнопкой или введите вручную 📱",
        reply_markup=PHONE_KB,
    )


# ------------------------- Защита от пустых ответов на шагах с кнопками -------
@router.message(StateFilter(Survey.goal, Survey.budget, Survey.urgency))
async def use_buttons(message: Message) -> None:
    await message.answer("Пожалуйста, выберите вариант кнопками выше 👆")


# ------------------------- Завершение анкеты -------------------------
async def finish(message: Message, state: FSMContext, bot: Bot, phone: str) -> None:
    data = await state.get_data()
    now = datetime.now(TZ)
    lead = {
        "datetime": now.strftime("%d.%m.%Y %H:%M"),
        "goal": data.get("goal", ""),
        "budget": data.get("budget", ""),
        "urgency": data.get("urgency", ""),
        "name": data.get("name", ""),
        "phone": phone,
    }

    await message.answer(
        "Спасибо за ответы! В ближайшее время с вами свяжется специалист "
        "по подбору недвижимости.",
        reply_markup=ReplyKeyboardRemove(),
    )

    # Сохранение в Google Sheets (в отдельном потоке, чтобы не блокировать бота)
    try:
        await asyncio.to_thread(sheets.append_lead, lead)
    except Exception:
        logger.exception("Не удалось сохранить заявку в Google Sheets")

    # Уведомление администратору
    try:
        await notify_admin(bot, lead)
    except Exception:
        logger.exception("Не удалось отправить уведомление администратору")

    await state.clear()


async def notify_admin(bot: Bot, lead: dict) -> None:
    if not ADMIN_CHAT_ID:
        logger.warning("ADMIN_CHAT_ID не задан — уведомление не отправлено")
        return
    text = (
        "🔔 <b>Новая заявка</b>\n\n"
        f"Цель: {lead['goal']}\n"
        f"Бюджет: {lead['budget']}\n"
        f"Срочность: {lead['urgency']}\n"
        f"Имя: {lead['name']}\n"
        f"Телефон: {lead['phone']}\n"
        f"Дата: {lead['datetime']}"
    )
    await bot.send_message(ADMIN_CHAT_ID, text)


# ------------------------- Запуск -------------------------
async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN (см. файл .env)")
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
