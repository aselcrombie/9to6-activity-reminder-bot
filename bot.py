import datetime
import json
import os
from collections import defaultdict

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN")

DATA_FILE = "data.json"

users = {}
daily_stats = defaultdict(int)


# ---------------- СОХРАНЕНИЕ ----------------

def save_data():
    data = {
        "schema_version": 1,
        "users": users,
        "daily_stats": {
            f"{chat_id}_{date}": count
            for (chat_id, date), count in daily_stats.items()
        },
    }

    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

def load_data():
    global users, daily_stats

    if not os.path.exists(DATA_FILE):
        return

    with open(DATA_FILE, "r") as f:
        data = json.load(f)

    # Проверка версии схемы
    if data.get("schema_version") != 1:
        print("⚠️ Неизвестная версия схемы")
        return

    # Загружаем пользователей
    users_raw = data.get("users", {})
    users = {int(k): v for k, v in users_raw.items()}

    # Загружаем статистику
    daily_stats_raw = data.get("daily_stats", {})
    for key, count in daily_stats_raw.items():
        chat_id, date_str = key.split("_")
        daily_stats[(int(chat_id), datetime.date.fromisoformat(date_str))] = count


# ---------------- START ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    # новый пользователь
    if chat_id not in users:
        users[chat_id] = {"state": "waiting_gender"}
        save_data()

    # пользователь полностью настроен
    elif users[chat_id].get("state") == "active":
        await update.message.reply_text(
            "Ты уже настроена 🙂\n"
            "Используй /settings или /status"
        )
        return

    state = users[chat_id]["state"]

    # приветствие + выбор пола
    if state == "waiting_gender":
        keyboard = [
            [
                InlineKeyboardButton("👩 Женский", callback_data="gender_female"),
                InlineKeyboardButton("👨 Мужской", callback_data="gender_male"),
            ]
        ]

        await update.message.reply_text(
            "👋 Привет!\n\n"
            "Я ваш помощник, который заботится о здоровье суставов и спины 🥹\n"
            "Буду мягко напоминать о разминке в удобном для вас интервале.\n"
            "Работаю по будням с 9:00 до 18:00 по вашему часовому поясу.\n\n"
            "Для начала выберите свой пол:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # если застрял на интервале
    elif state == "waiting_interval":
        await update.message.reply_text(
            "Продолжаем настройку 🙂\n"
            "Введите интервал в минутах (1–540):"
        )

    # если застрял на таймзоне
    elif state == "waiting_timezone":
        await update.message.reply_text(
            "Продолжаем настройку 🙂\n"
            "Введите часовой пояс в формате +5 или -3"
        )

# ---------------- SETTINGS ----------------

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if chat_id not in users or users[chat_id].get("state") != "active":
        await update.message.reply_text("Сначала запустите бота через /start")
        return

    users[chat_id]["state"] = "waiting_interval"
    save_data()

    await update.message.reply_text("Введите новый интервал (1–540):")


# ---------------- ОБРАБОТКА ТЕКСТА ----------------

def get_next_weekday(user_offset):
    utc_now = datetime.datetime.utcnow()
    user_time = utc_now + datetime.timedelta(hours=user_offset)

    weekday = user_time.weekday()  # 0=Пн, 6=Вс

    # Если будний день и уже после 18:00 — стартуем завтра
    if weekday < 5 and user_time.hour >= 18:
        days_ahead = 1
    elif weekday >= 5:  # выходной
        days_ahead = 7 - weekday
    else:
        # будний день до 9 утра
        days_ahead = 0

    next_day = user_time + datetime.timedelta(days=days_ahead)

    # если вдруг попали на выходной — двигаем до понедельника
    while next_day.weekday() >= 5:
        next_day += datetime.timedelta(days=1)

    weekday_names = [
        "Понедельник",
        "Вторник",
        "Среда",
        "Четверг",
        "Пятница",
        "Суббота",
        "Воскресенье",
    ]

    return weekday_names[next_day.weekday()]

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text

    if chat_id not in users:
        return

    state = users[chat_id]["state"]

    # ----- Ввод интервала -----
    if state == "waiting_interval":

        if not text.isdigit():
            await update.message.reply_text("Введите число 1–540.")
            return

        interval = int(text)

        if not (1 <= interval <= 540):
            await update.message.reply_text("Интервал должен быть 1–540.")
            return

        users[chat_id]["interval"] = interval
        users[chat_id]["state"] = "waiting_timezone"
        save_data()

        await update.message.reply_text(
            "Введите часовой пояс в формате +5 или -3"
        )
        return


    # ----- Ввод таймзоны -----
    if state == "waiting_timezone":

        if not text.startswith(("+", "-")):
            await update.message.reply_text(
                "Введите часовой пояс в формате +5 или -3"
            )
            return

        try:
            offset = int(text)
        except ValueError:
            await update.message.reply_text("Формат: +5 или -3")
            return

        if not (-12 <= offset <= 14):
            await update.message.reply_text("Допустимо от -12 до +14")
            return

        users[chat_id]["timezone_offset"] = offset
        users[chat_id]["state"] = "active"
        save_data()

        interval = users[chat_id]["interval"]

        utc_now = datetime.datetime.utcnow()
        user_time = utc_now + datetime.timedelta(hours=offset)

        if user_time.weekday() < 5 and 9 <= user_time.hour < 18:
            await update.message.reply_text(
                f"✅ Готово!\n"
                f"Интервал: {interval} мин\n"
                f"UTC: {text}\n\n"
                "Я начинаю работу 💪"
            )
        else:
            next_weekday = get_next_weekday(offset)
            await update.message.reply_text(
                f"✅ Готово!\n"
                f"Интервал: {interval} мин\n"
                f"UTC: {text}\n\n"
                f"Супер, начинаем в ближайший будний день — {next_weekday} 💪"
            )

        if context.job_queue:
            for job in context.job_queue.get_jobs_by_name(str(chat_id)):
                job.schedule_removal()

        context.job_queue.run_repeating(
            send_reminder,
            interval=interval * 60,
            first=0,
            chat_id=chat_id,
            name=str(chat_id),
        )

        return


# ---------------- НАПОМИНАНИЕ ----------------

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    user = users.get(chat_id)

    if not user or user.get("state") != "active":
        return

    utc_now = datetime.datetime.utcnow()
    user_time = utc_now + datetime.timedelta(
        hours=user["timezone_offset"]
    )

    if user_time.weekday() >= 5:
        return

    if not (9 <= user_time.hour < 18):
        return

    button_text = "✅ Размялась" if user["gender"] == "female" else "✅ Размялся"

    keyboard = [
        [
            InlineKeyboardButton(button_text, callback_data="done"),
            InlineKeyboardButton("⏳ Попозже", callback_data="later"),
        ]
    ]

    await context.bot.send_message(
        chat_id=chat_id,
        text="Пора размяться 💪",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ---------------- КНОПКИ ----------------

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    user = users.get(chat_id)

    if query.data == "confirm_reset":
        # удалить задачи
        if context.job_queue:
            for job in context.job_queue.get_jobs_by_name(str(chat_id)):
                job.schedule_removal()

        # удалить статистику пользователя
        keys_to_delete = [
            key for key in daily_stats if key[0] == chat_id
        ]
        for key in keys_to_delete:
            del daily_stats[key]

        # удалить пользователя
        del users[chat_id]

        save_data()

        await query.edit_message_text(
            "Настройки полностью сброшены.\n"
            "Запустите бота заново через /start"
        )
        return

    if query.data == "cancel_reset":
        await query.edit_message_text("Сброс отменён 🙂")
        return


    if not user:
        return

    utc_now = datetime.datetime.utcnow()
    user_time = utc_now + datetime.timedelta(
        hours=user["timezone_offset"]
    )
    today = user_time.date()

    if query.data == "done":
        daily_stats[(chat_id, today)] += 1
        save_data()

        count = daily_stats[(chat_id, today)]

        text = (
            f"🔥 Сегодня размялась {count} раз(а)"
            if user["gender"] == "female"
            else f"🔥 Сегодня размялся {count} раз(а)"
        )

        await query.edit_message_text(text=text)

    elif query.data == "later":
        await query.edit_message_text("Окей 🙂 Напомню позже.")

# ---------------- STATUS ----------------

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if chat_id not in users or users[chat_id].get("state") != "active":
        await update.message.reply_text(
            "Вы ещё не настроены.\nИспользуйте /start"
        )
        return

    user = users[chat_id]

    interval = user["interval"]
    offset = user["timezone_offset"]
    gender = "Женский" if user["gender"] == "female" else "Мужской"

    # текущий счётчик
    utc_now = datetime.datetime.utcnow()
    user_time = utc_now + datetime.timedelta(hours=offset)
    today = user_time.date()

    count = daily_stats.get((chat_id, today), 0)

    await update.message.reply_text(
        "📊 Текущие настройки:\n\n"
        f"Пол: {gender}\n"
        f"Интервал: {interval} мин\n"
        f"UTC: {offset:+}\n"
        f"Разминок сегодня: {count}"
    )

# ---------------- RESET ----------------

async def reset_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id

    print("RESET CALLBACK:", query.data)

    if query.data == "confirm_reset":
       if context.job_queue:
           for job in context.job_queue.get_jobs_by_name(str(chat_id)):
               job.schedule_removal()
           
       users.pop(chat_id, None)
       keys_to_delete = [key for key in daily_stats if key[0] == chat_id]
       for key in keys_to_delete:
           del daily_stats[key]
       save_data()
       await query.edit_message_text(
           "Настройки полностью сброшены.\n"
           "Запустите бота заново через /start"
       )
       return

    elif query.data == "cancel_reset":
        await query.edit_message_text("🙂 Хорошо, настройки оставляем как есть.")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if chat_id not in users:
        await update.message.reply_text("Вы ещё не настроены 🙂")
        return

    keyboard = [
        [
            InlineKeyboardButton("✅ Да, сбросить", callback_data="confirm_reset"),
            InlineKeyboardButton("❌ Нет", callback_data="cancel_reset"),
        ]
    ]

    await update.message.reply_text(
        "Вы уверены, что хотите полностью сбросить настройки?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# ---------------- MAIN ----------------

def main():
    load_data()

    from telegram.ext import JobQueue

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .job_queue(JobQueue())
        .build()
    )

    # ---------- восстановление напоминаний после перезапуска ----------
    def restore_jobs():
        for chat_id, user in users.items():
            if user.get("state") == "active":
                interval = user.get("interval")
                if interval:
                    app.job_queue.run_repeating(
                        send_reminder,
                        interval=interval * 60,
                        first=5,
                        chat_id=chat_id,
                        name=str(chat_id),
                    )

    # ---------- хендлеры ----------
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("reset", reset))

    app.add_handler(CallbackQueryHandler(gender_handler, pattern="^gender_"))
    app.add_handler(
        CallbackQueryHandler(reset_handler, pattern="^(confirm_reset|cancel_reset)$")
    )
    app.add_handler(
        CallbackQueryHandler(button_handler, pattern="^(done|later)$")
    )

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # ВАЖНО — вызвать восстановление
    restore_jobs()

    app.run_polling()

async def gender_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id

    users[chat_id]["gender"] = (
        "female" if query.data == "gender_female" else "male"
    )
    users[chat_id]["state"] = "waiting_interval"
    save_data()

    await query.edit_message_text("Введите интервал в минутах (1–540):")


if __name__ == "__main__":
    main()
