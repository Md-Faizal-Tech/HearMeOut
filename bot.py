from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, filters, CallbackQueryHandler
)
import asyncio
import os

TOKEN = os.getenv("BOT_TOKEN")

waiting_users = []
active_chats = {}
continue_votes = {}
user_choices = {}
reports = {}
BANNED_USERS = set()
REPORT_LIMIT = 3
chat_tasks = {}

# 🔧 FULL CLEANUP (used for report/exit)
def cleanup_session(user1, user2):
    active_chats.pop(user1, None)
    active_chats.pop(user2, None)

    continue_votes.pop(user1, None)
    continue_votes.pop(user2, None)

    user_choices.pop(user1, None)
    user_choices.pop(user2, None)

    cancel_timer(user1, user2)

# 🔧 ONLY CHAT CLEANUP (used for timer)
def cleanup_chat_only(user1, user2):
    active_chats.pop(user1, None)
    active_chats.pop(user2, None)

    cancel_timer(user1, user2)

# 🔧 TIMER CANCEL
def cancel_timer(user1, user2):
    task1 = chat_tasks.pop(user1, None)
    task2 = chat_tasks.pop(user2, None)

    if task1:
        task1.cancel()
    if task2 and task2 != task1:
        task2.cancel()


# START
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hey.\n\nThis is a space where you can talk to someone — no profiles, no pressure.\n\nTap /talk when you're ready."
    )

# HELP
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/talk - Find someone\n/exit - Leave chat\n/report - Report user"
    )

# TALK
async def talk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id in BANNED_USERS:
        await update.message.reply_text("You are blocked from using this service.")
        return

    if user_id in active_chats:
        await update.message.reply_text("You're already in a chat.")
        return

    if user_id in waiting_users:
        await update.message.reply_text("Still finding someone...")
        return

    waiting_users.append(user_id)
    await update.message.reply_text("Finding someone for you...")

    if len(waiting_users) >= 2:
        user1 = waiting_users.pop(0)
        user2 = waiting_users.pop(0)

        active_chats[user1] = user2
        active_chats[user2] = user1

        await context.bot.send_message(user1, "Connected. Say hi.")
        await context.bot.send_message(user2, "Connected. Say hi.")

        start_timer(user1, user2, context)

# RELAY
async def relay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id in active_chats:
        partner = active_chats[user_id]
        await context.bot.send_message(partner, update.message.text)
    else:
        await update.message.reply_text("Use /talk to start chatting.")

# EXIT
async def exit_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id in active_chats:
        partner = active_chats[user_id]
        cleanup_session(user_id, partner)

        await context.bot.send_message(partner, "User left the chat.")
        await update.message.reply_text("You left the chat.")
    else:
        await update.message.reply_text("You're not in a chat.")

# 🔥 END CHAT (FIXED)
async def end_chat(user1, user2, context):
    if active_chats.get(user1) != user2:
        return

    # store continuation FIRST
    continue_votes[user1] = user2
    continue_votes[user2] = user1

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Yes", callback_data="continue_yes"),
            InlineKeyboardButton("No", callback_data="continue_no")
        ]
    ])

    try:
        await context.bot.send_message(user1, "Chat ended. Continue with this person?", reply_markup=keyboard)
        await context.bot.send_message(user2, "Chat ended. Continue with this person?", reply_markup=keyboard)
    except Exception as e:
        print("Send error:", e)

    # clean ONLY chat
    cleanup_chat_only(user1, user2)

# TIMER START
def start_timer(user1, user2, context):
    task = asyncio.create_task(chat_timer(user1, user2, context))
    chat_tasks[user1] = task
    chat_tasks[user2] = task

# TIMER
async def chat_timer(user1, user2, context):
    try:
        await asyncio.sleep(20)

        if active_chats.get(user1) == user2:
            await end_chat(user1, user2, context)

    except asyncio.CancelledError:
        pass

# CONTINUE
async def handle_continue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    choice = query.data

    if user_id in BANNED_USERS:
        await query.edit_message_text("You are banned.")
        return

    if user_id not in continue_votes:
        await query.edit_message_text("Session expired.")
        return

    partner = continue_votes[user_id]
    user_choices[user_id] = choice

    await query.edit_message_text("Choice recorded.")

    if partner in user_choices:

        if user_choices[user_id] == "continue_yes" and user_choices[partner] == "continue_yes":

            if partner in BANNED_USERS:
                await context.bot.send_message(user_id, "User unavailable.")
                return

            active_chats[user_id] = partner
            active_chats[partner] = user_id

            await context.bot.send_message(user_id, "Reconnected. Continue chatting.")
            await context.bot.send_message(partner, "Reconnected. Continue chatting.")

            start_timer(user_id, partner, context)

        else:
            await context.bot.send_message(user_id, "Looking for a new person...")
            await context.bot.send_message(partner, "Looking for a new person...")

        continue_votes.pop(user_id, None)
        continue_votes.pop(partner, None)
        user_choices.pop(user_id, None)
        user_choices.pop(partner, None)

# REPORT
async def report_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in active_chats:
        await update.message.reply_text("You're not in a chat.")
        return

    partner = active_chats[user_id]

    reports[partner] = reports.get(partner, 0) + 1

    cleanup_session(user_id, partner)

    await update.message.reply_text("User reported. You left the chat.")
    await context.bot.send_message(partner, "You have been reported. Chat ended.")

    if reports[partner] >= REPORT_LIMIT:
        BANNED_USERS.add(partner)
        await context.bot.send_message(partner, "You have been banned due to multiple reports.")

# APP
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_command))
app.add_handler(CommandHandler("talk", talk))
app.add_handler(CommandHandler("exit", exit_chat))
app.add_handler(CommandHandler("report", report_user))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, relay))
app.add_handler(CallbackQueryHandler(handle_continue))

print("Bot running...")
app.run_polling()