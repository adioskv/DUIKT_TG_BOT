
import telebot
from telebot import types

TOKEN = "8473831288:AAEKqlkTqyETsh7Ui1Y7ZES12fOGdcujGmw"

ADMIN_CHAT_ID = None  

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# Стан користувача та дані замовлення зберігаємо в пам'яті
USER_STATE = {}

STATE_WAIT_NAME = "WAIT_NAME"
STATE_WAIT_CONTACT = "WAIT_CONTACT"
STATE_WAIT_TYPE = "WAIT_TYPE"
STATE_WAIT_BUDGET = "WAIT_BUDGET"
STATE_WAIT_DEADLINE = "WAIT_DEADLINE"
STATE_CONFIRMED = "CONFIRMED"


def reset_state(chat_id: int) -> None:
    """Скидання стану користувача та очищення заявки."""
    USER_STATE[chat_id] = {
        "step": STATE_WAIT_NAME,
        "order": {}
    }


@bot.message_handler(commands=["start"])
def cmd_start(message: telebot.types.Message) -> None:
    """Обробник команди /start."""
    chat_id = message.chat.id
    reset_state(chat_id)

    text = (
        "👋 <b>Вітаю!</b>\n"
        "Це бот для <b>замовлення телепродукції</b>.\n\n"
        "Я допоможу оформити заявку на:\n"
        "• ТВ-рекламу 📺\n"
        "• Промо-ролик 🎞\n"
        "• Музичний кліп 🎵\n"
        "• Інший відеопродукт 🎬\n\n"
        "Спочатку напишіть, будь ласка, <b>як до вас звертатися</b>."
    )
    bot.send_message(chat_id, text)


@bot.message_handler(commands=["help"])
def cmd_help(message: telebot.types.Message) -> None:
    """Обробник команди /help."""
    chat_id = message.chat.id
    help_text = (
        "ℹ️ <b>Як користуватися ботом</b>\n\n"
        "1. Натисніть /start, щоб почати оформлення замовлення.\n"
        "2. Відповідайте на запитання бота (імʼя, контакт, тип проекту тощо).\n"
        "3. Наприкінці перевірте заявку та напишіть <code>підтвердити</code>.\n"
        "4. Для скасування замовлення використовуйте команду /cancel.\n"
    )
    bot.send_message(chat_id, help_text)


@bot.message_handler(commands=["cancel"])
def cmd_cancel(message: telebot.types.Message) -> None:
    """Обробник команди /cancel."""
    chat_id = message.chat.id
    reset_state(chat_id)
    bot.send_message(
        chat_id,
        "❌ Поточне замовлення скасовано.\n"
        "Щоб почати нове, введіть /start."
    )


def get_user_state(chat_id: int):
    """Повертає стан користувача, якщо його немає — створює новий."""
    if chat_id not in USER_STATE:
        reset_state(chat_id)
    return USER_STATE[chat_id]


def send_type_keyboard(chat_id: int) -> None:
    """Надсилання клавіатури з варіантами типу телепродукції."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.row("ТВ-реклама", "Промо-ролик")
    markup.row("Музичний кліп", "Інше")
    bot.send_message(
        chat_id,
        "Оберіть, будь ласка, <b>тип телепродукції</b>, яку хочете замовити:",
        reply_markup=markup,
    )


@bot.message_handler(func=lambda msg: True, content_types=["text"])
def handle_text(message: telebot.types.Message) -> None:
    """Основний обробник текстових повідомлень."""
    chat_id = message.chat.id
    text = message.text.strip()

    # Ігноруємо команди, які мають окремі хендлери
    if text.startswith("/"):
        return

    user = get_user_state(chat_id)
    step = user["step"]
    order = user["order"]

    # Логіка по кроках
    if step == STATE_WAIT_NAME:
        order["name"] = text
        user["step"] = STATE_WAIT_CONTACT
        bot.send_message(
            chat_id,
            "Дякую, <b>{}</b>!\n"
            "Тепер залиште, будь ласка, <b>контакт</b>: телефон або @username.".format(
                order["name"]
            ),
        )

    elif step == STATE_WAIT_CONTACT:
        order["contact"] = text
        user["step"] = STATE_WAIT_TYPE
        send_type_keyboard(chat_id)

    elif step == STATE_WAIT_TYPE:
        order["type"] = text
        user["step"] = STATE_WAIT_BUDGET
        bot.send_message(
            chat_id,
            "Вкажіть орієнтовний <b>бюджет</b> (у гривнях).\n"
            "Можна написати суму, діапазон або <code>не знаю</code>.",
            reply_markup=types.ReplyKeyboardRemove(),
        )

    elif step == STATE_WAIT_BUDGET:
        order["budget"] = text
        user["step"] = STATE_WAIT_DEADLINE
        bot.send_message(
            chat_id,
            "Які <b>терміни</b> виконання вас цікавлять?\n"
            "Наприклад: <i>до 20 січня</i> або <i>протягом 2 тижнів</i>."
        )

    elif step == STATE_WAIT_DEADLINE:
        order["deadline"] = text
        user["step"] = STATE_CONFIRMED

        summary = (
            "✅ <b>Перевірте, будь ласка, заявку:</b>\n\n"
            f"👤 Імʼя: <b>{order.get('name')}</b>\n"
            f"📞 Контакт: <b>{order.get('contact')}</b>\n"
            f"🎬 Тип телепродукції: <b>{order.get('type')}</b>\n"
            f"💰 Бюджет: <b>{order.get('budget')}</b>\n"
            f"⏰ Дедлайн: <b>{order.get('deadline')}</b>\n\n"
            "Якщо все вірно, напишіть <code>підтвердити</code>.\n"
            "Щоб почати заново, введіть /start."
        )
        bot.send_message(chat_id, summary)

    elif step == STATE_CONFIRMED:
        if text.lower() in ["підтвердити", "confirm", "ок", "окей"]:
            # Формуємо текст заявки для адміністратора
            username = message.from_user.username
            user_link = f"@{username}" if username else f"id: {message.from_user.id}"

            admin_text = (
                "📩 <b>Нова заявка на телепродукцію</b>\n\n"
                f"👤 Імʼя: {order.get('name')}\n"
                f"📞 Контакт: {order.get('contact')}\n"
                f"🎬 Тип: {order.get('type')}\n"
                f"💰 Бюджет: {order.get('budget')}\n"
                f"⏰ Дедлайн: {order.get('deadline')}\n\n"
                f"Від користувача: {user_link}"
            )

            # Надсилаємо адміну, якщо вказаний ADMIN_CHAT_ID
            if ADMIN_CHAT_ID is not None:
                try:
                    bot.send_message(ADMIN_CHAT_ID, admin_text)
                except Exception as e:
                    print(f"Помилка надсилання адміну: {e}")

            bot.send_message(
                chat_id,
                "🎉 <b>Дякуємо!</b>\n"
                "Ваша заявка надіслана менеджеру. Ми звʼяжемося з вами найближчим часом."
            )
            reset_state(chat_id)
        else:
            bot.send_message(
                chat_id,
                "Щоб завершити оформлення, напишіть <code>підтвердити</code> "
                "або використайте /cancel для скасування."
            )
    else:
        # Невідомий стан (на всяк випадок)
        reset_state(chat_id)
        bot.send_message(chat_id, "Щось пішло не так. Спробуйте ще раз, введіть /start.")


if __name__ == "__main__":
    print("Bot is running...")
    bot.infinity_polling(skip_pending=True)
