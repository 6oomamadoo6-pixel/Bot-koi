from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ForceReply,
    ChatMember
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.error import TelegramError

import sqlite3
from datetime import datetime
import random
import string


# =========================
# تنظیمات
# =========================

BOT_TOKEN = "8965685820:AAGuwWH9XkeIkrydQoJPnrkaUOFK5G9_V58a"

ADMIN_ID = 6078875175

CHANNEL = "@hidemychatRobot0"


# =========================
# Database
# =========================

def init_db():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()

    # جدول کاربران
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            link_code TEXT UNIQUE,
            anon_code TEXT UNIQUE,
            created_at TEXT
        )
    ''')

    # جدول بلاک‌ها
    c.execute('''
        CREATE TABLE IF NOT EXISTS blocks (
            blocker_id INTEGER,
            blocked_id INTEGER,
            unblock_code TEXT UNIQUE,
            PRIMARY KEY (blocker_id, blocked_id)
        )
    ''')

    # اگر دیتابیس قدیمی باشد و ستون unblock_code نداشته باشد
    c.execute("PRAGMA table_info(blocks)")
    columns = [row[1] for row in c.fetchall()]

    if "unblock_code" not in columns:
        c.execute("ALTER TABLE blocks ADD COLUMN unblock_code TEXT")

        # برای بلاک‌های قدیمی کد بساز
        c.execute("""
            SELECT blocker_id, blocked_id
            FROM blocks
            WHERE unblock_code IS NULL
        """)

        old_blocks = c.fetchall()

        for blocker_id, blocked_id in old_blocks:
            code = generate_unblock_code()

            while True:
                c.execute(
                    "SELECT 1 FROM blocks WHERE unblock_code = ?",
                    (code,)
                )

                if not c.fetchone():
                    break

                code = generate_unblock_code()

            c.execute("""
                UPDATE blocks
                SET unblock_code = ?
                WHERE blocker_id = ? AND blocked_id = ?
            """, (code, blocker_id, blocked_id))

    conn.commit()
    conn.close()


# =========================
# Generators
# =========================

def generate_anon_code():
    return ''.join(random.choices(string.digits, k=7))


def generate_unblock_code():
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=10))


# =========================
# User
# =========================

def get_or_create_user(user_id, username, full_name):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()

    c.execute(
        "SELECT link_code, anon_code FROM users WHERE user_id = ?",
        (user_id,)
    )

    row = c.fetchone()

    if row:
        conn.close()
        return row[0], row[1]

    link_code = str(user_id)

    anon_code = generate_anon_code()

    while True:
        c.execute(
            "SELECT 1 FROM users WHERE anon_code = ?",
            (anon_code,)
        )

        if not c.fetchone():
            break

        anon_code = generate_anon_code()

    c.execute("""
        INSERT INTO users
        (
            user_id,
            username,
            full_name,
            link_code,
            anon_code,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        username,
        full_name,
        link_code,
        anon_code,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()

    return link_code, anon_code


# =========================
# Block system
# =========================

def is_blocked(blocker_id, blocked_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()

    c.execute("""
        SELECT 1
        FROM blocks
        WHERE blocker_id = ?
        AND blocked_id = ?
    """, (blocker_id, blocked_id))

    result = c.fetchone()

    conn.close()

    return bool(result)


def block_user(blocker_id, blocked_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()

    # بررسی اینکه قبلاً بلاک نشده باشد
    c.execute("""
        SELECT unblock_code
        FROM blocks
        WHERE blocker_id = ?
        AND blocked_id = ?
    """, (blocker_id, blocked_id))

    existing = c.fetchone()

    if existing:
        conn.close()
        return existing[0]

    unblock_code = generate_unblock_code()

    while True:
        c.execute(
            "SELECT 1 FROM blocks WHERE unblock_code = ?",
            (unblock_code,)
        )

        if not c.fetchone():
            break

        unblock_code = generate_unblock_code()

    c.execute("""
        INSERT INTO blocks
        (
            blocker_id,
            blocked_id,
            unblock_code
        )
        VALUES (?, ?, ?)
    """, (
        blocker_id,
        blocked_id,
        unblock_code
    ))

    conn.commit()
    conn.close()

    return unblock_code


def unblock_user(blocker_id, unblock_code):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()

    c.execute("""
        SELECT blocked_id
        FROM blocks
        WHERE blocker_id = ?
        AND unblock_code = ?
    """, (
        blocker_id,
        unblock_code
    ))

    row = c.fetchone()

    if not row:
        conn.close()
        return False

    c.execute("""
        DELETE FROM blocks
        WHERE blocker_id = ?
        AND unblock_code = ?
    """, (
        blocker_id,
        unblock_code
    ))

    conn.commit()
    conn.close()

    return True


def get_blocked_users(blocker_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()

    c.execute("""
        SELECT
            blocks.blocked_id,
            users.anon_code,
            blocks.unblock_code
        FROM blocks
        LEFT JOIN users
        ON users.user_id = blocks.blocked_id
        WHERE blocks.blocker_id = ?
    """, (blocker_id,))

    rows = c.fetchall()

    conn.close()

    return rows


# =========================
# Membership
# =========================

async def is_member(bot, user_id):
    try:
        member = await bot.get_chat_member(
            chat_id=CHANNEL,
            user_id=user_id
        )

        return member.status in [
            ChatMember.MEMBER,
            ChatMember.ADMINISTRATOR,
            ChatMember.OWNER
        ]

    except TelegramError:
        return False


# =========================
# Join message
# =========================

async def send_join_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        [
            InlineKeyboardButton(
                "کانال اجباری",
                url="https://t.me/hidemychatRobot0"
            )
        ],
        [
            InlineKeyboardButton(
                "جوین شدم✅",
                callback_data="check_join"
            )
        ]
    ]

    text = (
        "درود و عرض ادب !\n"
        "خوش اومدی 🌹\n\n"
        "برای ادامه استفاده از ربات زحمت بکش "
        "توی کانال زیر جوین شو"
    )

    if update.message:

        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    else:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


# =========================
# Main panel
# =========================

async def send_main_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        [
            InlineKeyboardButton(
                "دریافت لینک ناشناس 🔗",
                callback_data="copy_link"
            )
        ],
        [
            InlineKeyboardButton(
                "لیست مسدودی 🔴",
                callback_data="block_list"
            )
        ],
        [
            InlineKeyboardButton(
                "چنل پشتیبانی ✅",
                url="https://t.me/hidemychatRobot0"
            )
        ],
        [
            InlineKeyboardButton(
                "راهنما 🤔",
                callback_data="help"
            )
        ]
    ]

    text = (
        "درودد مجدد 👋\n"
        "ممنون که ربات مارو انتخاب کردی ❤️\n\n"
        "میتونی با پنل شیشه ای زیر "
        "از قابلیت های ربات ما استفاده کنی:"
    )

    if update.message:

        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    else:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


# =========================
# Back button
# =========================

def back_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "بازگشت 🔙",
                callback_data="back_main"
            )
        ]
    ])


# =========================
# /start
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    link_code, anon_code = get_or_create_user(
        user.id,
        user.username,
        user.full_name
    )

    # اگر لینک ناشناس باز شده
    if context.args:

        if not await is_member(context.bot, user.id):
            await send_join_message(update, context)
            return

        target_code = context.args[0]

        conn = sqlite3.connect("bot.db")
        c = conn.cursor()

        c.execute("""
            SELECT user_id, full_name
            FROM users
            WHERE link_code = ?
        """, (target_code,))

        target = c.fetchone()

        conn.close()

        if not target:

            await update.message.reply_text(
                "لینک نامعتبر است."
            )

            return

        target_id = target[0]

        # =========================
        # ارسال پیام به خودش
        # =========================

        if target_id == user.id:

            bot_username = (await context.bot.get_me()).username

            my_link = (
                f"https://t.me/"
                f"{bot_username}"
                f"?start={link_code}"
            )

            text = (
                "به خودت که نمیتونی پیام بفرستی عزیز 🥹\n\n"
                "ولی منتظر بمون و لینکتو بیشتر به اشتراک بزار "
                "و منتظر پیام ناشناست باش😍\n\n"
                "لینک خودت:\n"
                f"{my_link}"
            )

            await update.message.reply_text(
                text,
                reply_markup=back_keyboard()
            )

            return

        # =========================
        # ارسال پیام به شخص دیگر
        # =========================

        context.user_data["target_id"] = target_id

        await update.message.reply_text(
            "شما در حال ارسال پیام ناشناس هستید.\n\n"
            "پیام خود را بنویسید:",
            reply_markup=ForceReply(selective=True)
        )

        return

    # =========================
    # ورود معمولی
    # =========================

    if not await is_member(context.bot, user.id):

        await send_join_message(
            update,
            context
        )

        return

    await send_main_panel(
        update,
        context
    )


# =========================
# Message handler
# =========================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    text = update.message.text

    # دستور رفع بلاک
    if text.startswith("unblock_"):

        unblock_code = text[len("unblock_"):].strip()

        if unblock_user(user.id, unblock_code):

            await update.message.reply_text(
                "✅ کاربر با موفقیت از لیست مسدودی حذف شد."
            )

        else:

            await update.message.reply_text(
                "❌ کد رفع مسدودی نامعتبر است."
            )

        return

    # عضویت
    if not await is_member(context.bot, user.id):

        await send_join_message(
            update,
            context
        )

        return

    # =========================
    # پیام ناشناس
    # =========================

    if "target_id" in context.user_data:

        target_id = context.user_data["target_id"]

        # بررسی بلاک
        if is_blocked(target_id, user.id):

            await update.message.reply_text(
                "شما توسط این کاربر بلاک شده‌اید."
            )

            context.user_data.clear()

            return

        # کد ناشناس فرستنده
        conn = sqlite3.connect("bot.db")
        c = conn.cursor()

        c.execute("""
            SELECT anon_code
            FROM users
            WHERE user_id = ?
        """, (user.id,))

        row = c.fetchone()

        anon_code = row[0] if row else "0000000"

        conn.close()

        keyboard = [[
            InlineKeyboardButton(
                "پاسخ",
                callback_data=f"reply_{user.id}"
            ),
            InlineKeyboardButton(
                "بلاک",
                callback_data=f"block_{user.id}"
            )
        ]]

        try:

            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    f"کاربر {anon_code} "
                    f"برای شما پیام ناشناسی ارسال کرد :\n\n"
                    f"{text}"
                ),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

            await update.message.reply_text(
                "✅ پیام ناشناس با موفقیت ارسال شد."
            )

        except TelegramError:

            await update.message.reply_text(
                "❌ خطا در ارسال پیام."
            )

        context.user_data.clear()

        return

    # =========================
    # پاسخ ناشناس
    # =========================

    if "reply_to" in context.user_data:

        target_id = context.user_data["reply_to"]

        try:

            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    "💬 پاسخ ناشناس:\n\n"
                    f"{text}"
                )
            )

            await update.message.reply_text(
                "✅ پاسخ ارسال شد."
            )

        except TelegramError:

            await update.message.reply_text(
                "❌ خطا در ارسال پاسخ."
            )

        context.user_data.clear()

        return


# =========================
# Button handler
# =========================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    data = query.data

    user_id = query.from_user.id

    await query.answer()

    # =========================
    # Back
    # =========================

    if data == "back_main":

        await send_main_panel(
            update,
            context
        )

        return

    # =========================
    # Check join
    # =========================

    if data == "check_join":

        if await is_member(
            context.bot,
            user_id
        ):

            await send_main_panel(
                update,
                context
            )

        else:

            await query.answer(
                "هنوز عضو کانال نشدی ❌",
                show_alert=True
            )

            await send_join_message(
                update,
                context
            )

        return

    # =========================
    # Copy link
    # =========================

    if data == "copy_link":

        bot_username = (
            await context.bot.get_me()
        ).username

        link_code, _ = get_or_create_user(
            user_id,
            query.from_user.username,
            query.from_user.full_name
        )

        link = (
            f"https://t.me/"
            f"{bot_username}"
            f"?start={link_code}"
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "بازگشت 🔙",
                    callback_data="back_main"
                )
            ]
        ]

        await query.edit_message_text(
            "🔗 لینک اختصاصی شما:\n\n"
            f"`{link}`\n\n"
            "این لینک رو برای دیگران بفرست "
            "تا به صورت ناشناس برات پیام بفرستن.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return

    # =========================
    # Help
    # =========================

    if data == "help":

        keyboard = [
            [
                InlineKeyboardButton(
                    "بازگشت 🔙",
                    callback_data="back_main"
                )
            ]
        ]

        await query.edit_message_text(
            "📖 راهنما:\n\n"
            "۱. لینک ناشناست رو بگیر و به بقیه بده\n\n"
            "۲. بقیه می‌تونن برات پیام ناشناس بفرستن\n\n"
            "۳. می‌تونی جواب بدی یا بلاک کنی\n\n"
            "۴. کاربران بلاک‌شده رو می‌تونی "
            "از قسمت لیست مسدودی رفع بلاک کنی.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return

    # =========================
    # Block list
    # =========================

    if data == "block_list":

        blocked_users = get_blocked_users(
            user_id
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "بازگشت 🔙",
                    callback_data="back_main"
                )
            ]
        ]

        # هیچ کاربری بلاک نشده
        if not blocked_users:

            await query.edit_message_text(
                "🔴 لیست مسدودی شما خالی است.\n\n"
                "در حال حاضر هیچ کاربری را بلاک نکرده‌اید.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

            return

        # ساخت متن لیست
        parts = []

        for blocked_id, anon_code, unblock_code in blocked_users:

            anon_code = anon_code or "نامشخص"

            parts.append(
                f"کاربر {anon_code} در لیست مسدودی شما است.\n"
                f"رفع مسدودی : unblock_{unblock_code}"
            )

        text = (
            "🔴 لیست مسدودی شما:\n\n"
            + "\n\n____\n\n".join(parts)
            + "\n\n"
            "برای رفع مسدودی، دستور مربوط به همان کاربر "
            "را ارسال کنید."
        )

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return

    # =========================
    # Reply
    # =========================

    if data.startswith("reply_"):

        target_id = int(
            data.split("_")[1]
        )

        context.user_data["reply_to"] = target_id

        await query.message.reply_text(
            "پاسخ خود را بنویسید:",
            reply_markup=ForceReply(selective=True)
        )

        return

    # =========================
    # Block
    # =========================

    if data.startswith("block_"):

        blocked_id = int(
            data.split("_")[1]
        )

        unblock_code = block_user(
            user_id,
            blocked_id
        )

        await query.edit_message_text(
            "🚫 کاربر با موفقیت بلاک شد.\n\n"
            f"کد رفع مسدودی این کاربر:\n"
            f"unblock_{unblock_code}"
        )

        return


# =========================
# Main
# =========================

def main():

    init_db()

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print("ربات روشن شد...")

    app.run_polling()


# =========================

if __name_
