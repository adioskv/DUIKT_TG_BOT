"""
telegram_shop_bot.py

Універсальний чат-бот-магазин для Telegram на Python з використанням
PyTelegramBotAPI (TelebotAPI).

Функціонал (відповідає технічному завданню):
- /start, /help, /info, /catalog, /order, /feedback
- інтерактивний каталог товарів (inline-кнопки)
- оформлення замовлень та сповіщення адміністраторів
- просте "адмін-меню": /admin, /add_item, /remove_item, /orders
- reply-клавіатура для основних команд
- валідація введених даних (ціна товару)
- імітація платіжної системи: рахунок, попереднє замовлення,
  підтвердження / відміна оплати
- логування дій користувачів

Перед запуском:
1. Встановіть бібліотеку:
   pip install pyTelegramBotAPI

2. Створіть бота через @BotFather і отримайте токен.

3. Найзручніше передати токен через змінну середовища:
   export TELEGRAM_BOT_TOKEN="ВАШ_ТОКЕН"

   або впишіть токен прямо в константу TOKEN нижче (не для продакшну).

4. За бажанням вкажіть ID адміністраторів у множині ADMIN_IDS.
"""

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Set

import telebot
import threading
from telebot import types

# ===================== Налаштування бота =====================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE")

# Список адміністраторів (chat_id).
ADMIN_IDS: Set[int] = {
    880923657, # @lfmane TELEGRAM
}

app = Flask(__name__)


if TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
    # Для зручності в навчальному режимі можна просто залишити попередження
    print("УВАГА: Необхідно встановити TELEGRAM_BOT_TOKEN або вписати токен у змінну TOKEN.")
    # Скрипт все одно створиться, але запускати його без реального токена не можна.


# Ініціалізуємо бота
bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("shop_bot")


# ===================== Моделі даних =====================

@dataclass
class CatalogItem:
    item_id: int
    name: str
    price: float
    description: str


@dataclass
class Order:
    order_id: int
    user_id: int
    username: Optional[str]
    full_name: str
    item: CatalogItem
    created_at: datetime
    status: str = "pending"  # pending -> waiting_payment -> paid / cancelled


# Пам'ять у процесі (для навчального проєкту цього достатньо)
CATALOG: Dict[int, CatalogItem] = {}
ORDERS: Dict[int, Order] = {}
USER_STATE: Dict[int, Dict] = {}  # стан користувачів для multi-step діалогів

_next_item_id = 1
_next_order_id = 1


def get_next_item_id() -> int:
    global _next_item_id
    item_id = _next_item_id
    _next_item_id += 1
    return item_id


def get_next_order_id() -> int:
    global _next_order_id
    order_id = _next_order_id
    _next_order_id += 1
    return order_id


def get_user_state(user_id: int) -> Dict:
    """Отримати стан користувача, при необхідності створити."""
    if user_id not in USER_STATE:
        USER_STATE[user_id] = {"mode": None}
    return USER_STATE[user_id]


# ===================== Допоміжні функції =====================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def format_item(item: CatalogItem) -> str:
    return (
        f"<b>{item.name}</b>\n"
        f"Ціна: <b>{item.price:.2f} грн</b>\n\n"
        f"{item.description}"
    )


def format_order(order: Order) -> str:
    return (
        f"🧾 <b>Замовлення #{order.order_id}</b>\n"
        f"Користувач: {order.full_name} (@{order.username})\n"
        f"ID: <code>{order.user_id}</code>\n\n"
        f"Товар: <b>{order.item.name}</b>\n"
        f"Ціна: <b>{order.item.price:.2f} грн</b>\n"
        f"Статус: <b>{order.status}</b>\n"
        f"Створено: {order.created_at.strftime('%Y-%m-%d %H:%M:%S')}"
    )


def send_to_admins(text: str) -> None:
    """Надіслати службове повідомлення всім адміністраторам."""
    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(admin_id, text)
        except Exception as e:
            logger.warning("Не вдалося надіслати повідомлення адміну %s: %s", admin_id, e)


def build_main_menu() -> types.ReplyKeyboardMarkup:
    """Reply-клавіатура для основних команд."""
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("/catalog", "/info")
    kb.row("/help", "/feedback")
    return kb


def build_catalog_keyboard() -> Optional[types.InlineKeyboardMarkup]:
    """Inline-клавіатура для списку товарів."""
    if not CATALOG:
        return None
    kb = types.InlineKeyboardMarkup()
    for item in CATALOG.values():
        btn = types.InlineKeyboardButton(
            text=f"{item.name} – {item.price:.0f} грн",
            callback_data=f"item:{item.item_id}",
        )
        kb.add(btn)
    return kb


def build_item_keyboard(item_id: int) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("🛒 Замовити", callback_data=f"buy:{item_id}"),
    )
    kb.add(
        types.InlineKeyboardButton("⬅️ Назад до каталогу", callback_data="catalog")
    )
    return kb


def build_order_confirm_keyboard(order_id: int) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Підтвердити замовлення", callback_data=f"confirm:{order_id}")
    )
    kb.add(
        types.InlineKeyboardButton("❌ Скасувати", callback_data=f"cancel:{order_id}")
    )
    return kb


def build_payment_keyboard(order_id: int) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("💸 Підтвердити оплату", callback_data=f"pay_ok:{order_id}")
    )
    kb.add(
        types.InlineKeyboardButton("🚫 Відмінити оплату", callback_data=f"pay_cancel:{order_id}")
    )
    return kb


# ===================== Команди користувачів =====================

@bot.message_handler(commands=["start"])
def cmd_start(message: telebot.types.Message) -> None:
    chat_id = message.chat.id
    user = message.from_user
    logger.info("Користувач %s (%s) виконав /start", user.id, user.username)

    welcome = (
        "Вітаю! 👋\n"
        "Я чат-бот магазину для демонстрації можливостей TelebotAPI.\n\n"
        "Я можу:\n"
        "• показувати каталог товарів\n"
        "• оформлювати замовлення\n"
        "• надсилати замовлення адміністраторам\n"
        "• приймати відгуки від користувачів\n\n"
        "Скористайтесь кнопками нижче або командами /help та /catalog."
    )
    bot.send_message(chat_id, welcome, reply_markup=build_main_menu())


@bot.message_handler(commands=["help"])
def cmd_help(message: telebot.types.Message) -> None:
    text = (
        "🆘 <b>Доступні команди</b>\n\n"
        "/start – перезапустити бота\n"
        "/help – список команд\n"
        "/info – інформація про бота\n"
        "/catalog – каталог товарів\n"
        "/order – показати ваші замовлення\n"
        "/feedback – залишити відгук\n\n"
        "Адміністраторам доступні:\n"
        "/admin – меню адміністратора\n"
        "/add_item – додати товар\n"
        "/remove_item – видалити товар\n"
        "/orders – список усіх замовлень"
    )
    bot.send_message(message.chat.id, text)


@bot.message_handler(commands=["info"])
def cmd_info(message: telebot.types.Message) -> None:
    text = (
        "ℹ️ <b>Про бота</b>\n\n"
        "Цей бот створений як навчальний проєкт.\n"
        "Технології: Python + PyTelegramBotAPI.\n"
        "Функціонал: каталог товарів, оформлення замовлень, "
        "адмін-меню, відгуки, імітація оплати."
    )
    bot.send_message(message.chat.id, text)


@bot.message_handler(commands=["catalog"])
def cmd_catalog(message: telebot.types.Message) -> None:
    chat_id = message.chat.id
    if not CATALOG:
        bot.send_message(
            chat_id,
            "Каталог поки що порожній 🕳\n"
            "Адміністратор може додати товари командою /add_item.",
        )
        return

    kb = build_catalog_keyboard()
    text = "🛍 <b>Каталог товарів</b>\nОберіть товар, щоб переглянути деталі:"
    bot.send_message(chat_id, text, reply_markup=kb)


@bot.message_handler(commands=["order"])
def cmd_order(message: telebot.types.Message) -> None:
    """Показати користувачу його замовлення."""
    user_id = message.from_user.id
    user_orders = [o for o in ORDERS.values() if o.user_id == user_id]

    if not user_orders:
        bot.send_message(message.chat.id, "У вас поки що немає замовлень 🧾")
        return

    lines = ["Ваші замовлення:"]
    for o in sorted(user_orders, key=lambda x: x.created_at, reverse=True)[:10]:
        lines.append(
            f"#{o.order_id} – {o.item.name} ({o.item.price:.0f} грн) – статус: {o.status}"
        )

    bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(commands=["feedback"])
def cmd_feedback(message: telebot.types.Message) -> None:
    """Попросити користувача надіслати відгук наступним повідомленням."""
    user_id = message.from_user.id
    state = get_user_state(user_id)
    state["mode"] = "feedback"
    bot.send_message(
        message.chat.id,
        "✉️ Напишіть, будь ласка, свій відгук одним або кількома повідомленнями.\n"
        "Щоб скасувати, надішліть /cancel.",
    )


@bot.message_handler(commands=["cancel"])
def cmd_cancel(message: telebot.types.Message) -> None:
    """Скинення будь-якого режиму користувача."""
    user_id = message.from_user.id
    state = get_user_state(user_id)
    prev_mode = state.get("mode")
    state["mode"] = None
    state.pop("data", None)

    if prev_mode:
        bot.send_message(message.chat.id, "Поточну дію скасовано ✅")
    else:
        bot.send_message(message.chat.id, "Немає активних дій для скасування.")


# ===================== Адмінські команди =====================

@bot.message_handler(commands=["admin"])
def cmd_admin(message: telebot.types.Message) -> None:
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.send_message(message.chat.id, "⛔ У вас немає прав адміністратора.")
        return

    text = (
        "🔐 <b>Адмін-меню</b>\n\n"
        "/add_item – додати товар до каталогу\n"
        "/remove_item – видалити товар з каталогу\n"
        "/orders – переглянути всі замовлення"
    )
    bot.send_message(message.chat.id, text)


@bot.message_handler(commands=["add_item"])
def cmd_add_item(message: telebot.types.Message) -> None:
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.send_message(message.chat.id, "⛔ Лише адміністратор може додавати товари.")
        return

    state = get_user_state(user_id)
    state["mode"] = "add_item"
    bot.send_message(
        message.chat.id,
        "➕ Додавання товару.\n\n"
        "Надішліть дані у форматі:\n"
        "<code>Назва;ціна;опис</code>\n\n"
        "Наприклад:\n"
        "<code>Футболка з логотипом;499;Чорна футболка з білим логотипом</code>",
    )


@bot.message_handler(commands=["remove_item"])
def cmd_remove_item(message: telebot.types.Message) -> None:
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.send_message(message.chat.id, "⛔ Лише адміністратор може видаляти товари.")
        return

    if not CATALOG:
        bot.send_message(message.chat.id, "Каталог порожній, немає що видаляти.")
        return

    state = get_user_state(user_id)
    state["mode"] = "remove_item"
    # Показуємо список товарів з ID
    lines = ["🔻 Вкажіть ID товару для видалення:", ""]
    for item in CATALOG.values():
        lines.append(f"{item.item_id}: {item.name} ({item.price:.0f} грн)")
    bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(commands=["orders"])
def cmd_admin_orders(message: telebot.types.Message) -> None:
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.send_message(message.chat.id, "⛔ Лише адміністратор може переглядати замовлення.")
        return

    if not ORDERS:
        bot.send_message(message.chat.id, "Замовлень поки що немає 🧾")
        return

    lines: List[str] = ["📋 <b>Останні замовлення</b>\n"]
    for o in sorted(ORDERS.values(), key=lambda x: x.created_at, reverse=True)[:20]:
        lines.append(
            f"#{o.order_id}: {o.item.name} – {o.item.price:.0f} грн – "
            f"{o.full_name} (@{o.username}) – статус: {o.status}"
        )

    bot.send_message(message.chat.id, "\n".join(lines))


# ===================== Inline-кнопки (catalog / order / payment) =====================

@bot.callback_query_handler(func=lambda call: call.data == "catalog")
def cb_show_catalog(call: telebot.types.CallbackQuery) -> None:
    """Повернення до каталогу."""
    kb = build_catalog_keyboard()
    if not kb:
        bot.answer_callback_query(call.id, "Каталог порожній")
        bot.edit_message_text(
            "Каталог поки що порожній 🕳",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
        )
        return

    bot.edit_message_text(
        "🛍 <b>Каталог товарів</b>\nОберіть товар:",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=kb,
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("item:"))
def cb_view_item(call: telebot.types.CallbackQuery) -> None:
    """Перегляд деталей товару."""
    try:
        item_id = int(call.data.split(":", 1)[1])
    except ValueError:
        bot.answer_callback_query(call.id, "Помилка ID товару")
        return

    item = CATALOG.get(item_id)
    if not item:
        bot.answer_callback_query(call.id, "Товар не знайдено")
        return

    bot.edit_message_text(
        format_item(item),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=build_item_keyboard(item_id),
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("buy:"))
def cb_buy_item(call: telebot.types.CallbackQuery) -> None:
    """Створення попереднього замовлення та запит підтвердження."""
    user = call.from_user
    try:
        item_id = int(call.data.split(":", 1)[1])
    except ValueError:
        bot.answer_callback_query(call.id, "Помилка ID товару")
        return

    item = CATALOG.get(item_id)
    if not item:
        bot.answer_callback_query(call.id, "Товар не знайдено")
        return

    order_id = get_next_order_id()
    order = Order(
        order_id=order_id,
        user_id=user.id,
        username=user.username,
        full_name=f"{user.first_name or ''} {user.last_name or ''}".strip() or "Без імені",
        item=item,
        created_at=datetime.now(),
        status="pending",
    )
    ORDERS[order_id] = order

    logger.info("Створено попереднє замовлення #%s від користувача %s", order_id, user.id)

    bot.edit_message_text(
        format_item(item)
        + "\n\nПідтвердити замовлення цього товару?",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=build_order_confirm_keyboard(order_id),
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm:"))
def cb_confirm_order(call: telebot.types.CallbackQuery) -> None:
    """Підтвердження попереднього замовлення (створення рахунку)."""
    try:
        order_id = int(call.data.split(":", 1)[1])
    except ValueError:
        bot.answer_callback_query(call.id, "Помилка ID замовлення")
        return

    order = ORDERS.get(order_id)
    if not order:
        bot.answer_callback_query(call.id, "Замовлення не знайдено")
        return

    order.status = "waiting_payment"

    invoice_text = (
        f"✅ Замовлення #{order.order_id} підтверджено.\n\n"
        f"Товар: <b>{order.item.name}</b>\n"
        f"Сума до оплати: <b>{order.item.price:.2f} грн</b>\n\n"
        f"Номер рахунку: <code>{order.order_id:06d}</code>\n\n"
        "Після здійснення оплати натисніть кнопку нижче, щоб підтвердити оплату "
        "або скасувати замовлення."
    )

    bot.edit_message_text(
        invoice_text,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=build_payment_keyboard(order.order_id),
    )

    # Надсилаємо замовлення адміністраторам
    send_to_admins("📩 <b>Нове замовлення</b>\n" + format_order(order))
    bot.answer_callback_query(call.id, "Замовлення підтверджено, рахунок створено.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("cancel:"))
def cb_cancel_order(call: telebot.types.CallbackQuery) -> None:
    """Скасування попереднього замовлення."""
    try:
        order_id = int(call.data.split(":", 1)[1])
    except ValueError:
        bot.answer_callback_query(call.id, "Помилка ID замовлення")
        return

    order = ORDERS.get(order_id)
    if not order:
        bot.answer_callback_query(call.id, "Замовлення не знайдено")
        return

    order.status = "cancelled"
    bot.edit_message_text(
        f"Замовлення #{order.order_id} скасовано.",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
    )
    bot.answer_callback_query(call.id, "Замовлення скасовано.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_ok:"))
def cb_pay_ok(call: telebot.types.CallbackQuery) -> None:
    """Підтвердження оплати (імітація)."""
    try:
        order_id = int(call.data.split(":", 1)[1])
    except ValueError:
        bot.answer_callback_query(call.id, "Помилка ID замовлення")
        return

    order = ORDERS.get(order_id)
    if not order:
        bot.answer_callback_query(call.id, "Замовлення не знайдено")
        return

    order.status = "paid"
    bot.edit_message_text(
        f"🎉 Дякуємо за оплату! Замовлення #{order.order_id} має статус <b>оплачено</b>.\n"
        "Наш менеджер зв'яжеться з вами для уточнення деталей.",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
    )

    send_to_admins("💸 <b>Оплата підтверджена</b>\n" + format_order(order))
    bot.answer_callback_query(call.id, "Оплату підтверджено.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_cancel:"))
def cb_pay_cancel(call: telebot.types.CallbackQuery) -> None:
    """Відміна оплати (по суті скасування замовлення)."""
    try:
        order_id = int(call.data.split(":", 1)[1])
    except ValueError:
        bot.answer_callback_query(call.id, "Помилка ID замовлення")
        return

    order = ORDERS.get(order_id)
    if not order:
        bot.answer_callback_query(call.id, "Замовлення не знайдено")
        return

    order.status = "cancelled"
    bot.edit_message_text(
        f"Оплату для замовлення #{order.order_id} скасовано.\n"
        "Якщо ви передумаєте, можете зробити нове замовлення через /catalog.",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
    )
    send_to_admins("🚫 <b>Оплату скасовано</b>\n" + format_order(order))
    bot.answer_callback_query(call.id, "Оплату скасовано.")


# ===================== Обробка текстових повідомлень (стани + FAQ) =====================

@bot.message_handler(content_types=["text"])
def handle_text(message: telebot.types.Message) -> None:
    user_id = message.from_user.id
    state = get_user_state(user_id)
    mode = state.get("mode")

    # 1) Адмінський режим додавання товару
    if mode == "add_item" and is_admin(user_id):
        process_add_item(message, state)
        return

    # 2) Адмінський режим видалення товару
    if mode == "remove_item" and is_admin(user_id):
        process_remove_item(message, state)
        return

    # 3) Режим збору feedback
    if mode == "feedback":
        process_feedback(message, state)
        return

    # 4) Простеньке FAQ за ключовими словами
    text_lower = message.text.lower()

    if "товар" in text_lower or "каталог" in text_lower:
        bot.send_message(
            message.chat.id,
            "Щоб переглянути доступні товари, скористайтесь командою /catalog.",
        )
        return

    if "як зробити замовлення" in text_lower or "як замовити" in text_lower:
        bot.send_message(
            message.chat.id,
            "Щоб зробити замовлення:\n"
            "1) Відкрийте /catalog\n"
            "2) Оберіть товар та натисніть «Замовити»\n"
            "3) Підтвердіть замовлення та оплату за підказками бота.",
        )
        return

    if message.text.strip().lower() in ("привіт", "добрий день", "добрий вечір"):
        bot.send_message(message.chat.id, "Привіт! 😊 Чим можу допомогти?")
        return

    # Якщо нічого не підійшло – стандартна відповідь
    bot.send_message(
        message.chat.id,
        "Я поки що не розумію це повідомлення 😔\n"
        "Спробуйте скористатися командами /help або /catalog.",
    )


def process_add_item(message: telebot.types.Message, state: Dict) -> None:
    """Обробка введення нового товару адміністратором."""
    text = message.text.strip()
    parts = [p.strip() for p in text.split(";", 2)]
    if len(parts) != 3:
        bot.send_message(
            message.chat.id,
            "⚠️ Невірний формат.\n"
            "Надішліть у форматі: <code>Назва;ціна;опис</code>",
        )
        return

    name, price_str, description = parts
    try:
        price = float(price_str.replace(",", "."))
        if price <= 0:
            raise ValueError
    except ValueError:
        bot.send_message(
            message.chat.id,
            "⚠️ Ціна має бути додатним числом. Спробуйте ще раз.",
        )
        return

    item_id = get_next_item_id()
    item = CatalogItem(item_id=item_id, name=name, price=price, description=description)
    CATALOG[item_id] = item
    state["mode"] = None

    bot.send_message(
        message.chat.id,
        f"✅ Товар додано до каталогу:\n\n{format_item(item)}",
    )
    logger.info("Адмін %s додав товар %s (#%s)", message.from_user.id, name, item_id)


def process_remove_item(message: telebot.types.Message, state: Dict) -> None:
    """Видалення товару за ID."""
    text = message.text.strip()
    try:
        item_id = int(text)
    except ValueError:
        bot.send_message(
            message.chat.id,
            "⚠️ ID має бути числом. Введіть ID товару ще раз."
        )
        return

    item = CATALOG.pop(item_id, None)
    state["mode"] = None

    if not item:
        bot.send_message(message.chat.id, "Товар з таким ID не знайдено.")
        return

    bot.send_message(
        message.chat.id,
        f"🗑 Товар <b>{item.name}</b> (#{item.item_id}) видалено з каталогу.",
    )
    logger.info("Адмін %s видалив товар #%s", message.from_user.id, item_id)


def process_feedback(message: telebot.types.Message, state: Dict) -> None:
    """Обробка відгуку користувача."""
    user = message.from_user
    state["mode"] = None

    text = (
        "📝 <b>Новий відгук</b>\n\n"
        f"Від: {user.first_name or ''} {user.last_name or ''} (@{user.username})\n"
        f"ID: <code>{user.id}</code>\n\n"
        f"Текст:\n{message.text}"
    )
    send_to_admins(text)

    bot.send_message(
        message.chat.id,
        "Дякуємо за ваш відгук! 💚\n"
        "Ваше повідомлення надіслано адміністраторам.",
    )


# ===================== Початкове наповнення каталогу =====================

def seed_catalog() -> None:
    """Додати кілька тестових товарів у каталог при старті бота."""
    if CATALOG:
        return  # вже ініціалізовано

    items = [
        ("Футболка з логотипом", 499, "Чорна футболка з білим логотипом бота."),
        ("Кружка 'AI Inside'", 299, "Керамічна кружка для любителів Python та ШІ."),
        ("Еко-торба 'Telegram Shop'", 199, "Зручна торба для покупок з брендингом."),
    ]

    for name, price, desc in items:
        item_id = get_next_item_id()
        CATALOG[item_id] = CatalogItem(
            item_id=item_id,
            name=name,
            price=float(price),
            description=desc,
        )

    logger.info("Каталог ініціалізовано тестовими товарами (%s шт.)", len(CATALOG))


# ===================== Точка входу =====================
@app.route("/")
def index():
    return "Bot is running"

def run_bot():
    seed_catalog()
    logger.info("Bot is starting...")
    bot.infinity_polling(skip_pending=True)

if __name__ == "__main__":
    t = threading.Thread(target=run_bot)
    t.daemon = True
    t.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
