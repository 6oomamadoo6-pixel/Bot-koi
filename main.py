import os
import sqlite3
import random
import string
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ForceReply,
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from telegram.error import TelegramError


# =========================================================
# SETTINGS
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

CHANNEL = "@hidemychatRobot0"
CHANNEL_URL = "https://t.me/hidemychatRobot0"

DB_NAME = "bot.db"


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            link_code TEXT UNIQUE NOT NULL,
            anon_code TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS blocks (
            blocker_id INTEGER NOT NULL,
            blocked_id INTEGER NOT NULL,
            unblock_code TEXT UNIQUE NOT NULL,
            PRIMARY KEY (blocker_id, blocked_id)
        )
    """)

    conn.commit()
    conn.close()


# =========================================================
# CODE GENERATORS
# =========================================================

def generate_anon_code():
    conn = get_db()
    cur = conn.cursor()

    while True:
        code = "".join(random.choices(string.digits, k=7))

        cur.execute(
            "SELECT 1 FROM users WHERE anon_code = ?",
            (code,)
        )

        if cur.fetchone() is None:
            conn.close()
            return code


def generate_unblock_code():
    conn = get_db()
    cur = conn.cursor()

    chars = string.ascii_lowercase + string.digits

    while True:
        code = "".join(random.choices(chars, k=10))

        cur.execute(
            "SELECT 1 FROM blocks WHERE unblock_code = ?",
            (code,)
        )

        if cur.fetchone() is None:
            conn.close()
            return code


# =========================================================
# USERS
# =========================================================

def get_or_create_user(user):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT link_code, anon_code
        FROM users
        WHERE user_id = ?
    """, (user.id,))

    row = cur.fetchone()

    if row:
        cur.execute("""
            UPDATE users
            SET username = ?, full_name = ?
            WHERE user_id = ?
        """, (
            user.username,
            user.full_name,
            user.id
        ))

        conn.commit()
        conn.close()

        return row[0], row[1]

    link_code = str(user.id)
    anon_code = generate_anon_code()

    cur.execute("""
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
        user.id,
        user.username,
        user.full_name,
        link_code,
        anon_code,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()

    return link_code, anon_code


def get_user_by_link(link_code):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT user_id, full_name, anon_code
        FROM users
        WHERE link_code = ?
    """, (link_code,))

    row = cur.fetchone()
    conn.close()

    return row


def get_anon_code(user_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT anon_code
        FROM users
        WHERE user_id = ?
    """, (user_id,))

    row = cur.fetchone()
    conn.close()

    if row:
        return row[0]

    return "0000000"


# =========================================================
# BLOCK SYSTEM
# =========================================================

def is_blocked(blocker_id, blocked_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT 1
        FROM blocks
        WHERE blocker_id = ?
        AND blocked_id = ?
    """, (
        blocker_id,
        blocked_id
    ))

    result = cur.fetchone()
    conn.close()

    return result is not None


def block_user(blocker_id, blocked_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT unblock_code
        FROM blocks
        WHERE blocker_id = ?
        AND blocked_id = ?
    """, (
        blocker_id,
        blocked_id
    ))

    existing = cur.fetchone()

    if existing:
        conn.close()
        return existing[0]

    code = generate_unblock_code()

    cur.execute("""
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
        code
    ))

    conn.commit()
    conn.close()

    return code


def unblock_user(blocker_id, code):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT blocked_id
        FROM blocks
        WHERE blocker_id = ?
        AND unblock_code = ?
    """, (
        blocker_id,
        code
    ))

    row = cur.fetchone()

    if not row:
        conn.close()
        return False

    cur.execute("""
        DELETE FROM blocks
        WHERE blocker_id = ?
        AND unblock_code = ?
    """, (
        blocker_id,
        code
    ))

    conn.commit()
    conn.close()

    return True


def get_blocked_users(blocker_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            b.blocked_id,
            u.anon_code,
            b.unblock_code
        FROM blocks b
        LEFT JOIN users u
        ON u.user_id = b.blocked_id
        WHERE b.blocker_id = ?
        ORDER BY b.rowid DESC
    """, (blocker_id,))

    rows = cur.fetchall()
    conn.close()

    return rows


# =========================================================
# MEMBERSHIP
# =========================================================

async def is_member(bot, user_id):
    try:
        member = await bot.get_chat_member(
            chat_id=CHANNEL,
            user_id=user_id
        )

        return member.status in (
            "member",
            "administrator",
            "creator"
        )

    except TelegramError as e:
        print("MEMBERSHIP CHECK ERROR:", e)
        return False


# =========================================================
# KEYBOARDS
# =========================================================

def back_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "بازگشت 🔙",
                callback_data="back_main"
            )
        ]
    ])


def join_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "عضویت در کانال 📢",
                url=CHANNEL_URL
            )
        ],
        [
            InlineKeyboardButton(
                "جوین شدم ✅",
                callback_data="check_join"
            )
        ]
    ])


def main_keyboard():
    return InlineKeyboardMarkup([
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
                url=CHANNEL_URL
            )
        ],
        [
            InlineKeyboardButton(
                "راهنما 🤔",
                callback_data="help"
            )
        ]
    ])


# =========================================================
# MESSAGES
# =========================================================

async def send_join_message(update, context):
    text = (
        "درود و عرض ادب! 👋\n"
        "خوش اومدی 🌹\n\n"
        "برای ادامه استفاده از ربات، "
        "ابتدا داخل کانال زیر عضو شو:"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=join_keyboard()
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=join_keyboard()
        )


async def send_main_panel(update, context):
    text = (
        "درودد مجدد 👋\n"
        "ممنون که ربات ما رو انتخاب کردی ❤️\n\n"
        "میتونی با پنل شیشه‌ای زیر "
        "از قابلیت‌های ربات استفاده کنی:"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=main_keyboard()
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=main_keyboard()
        )


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    get_or_create_user(user)

    # -----------------------------------------
    # /start WITH LINK
    # -----------------------------------------

    if context.args:
        target_code = context.args[0].strip()

        if not await is_member(
            context.bot,
            user.id
        ):
            await send_join_message(
                update,
                context
            )
            return

        target = get_user_by_link(target_code)

        if not target:
            await update.message.reply_text(
                "❌ این لینک نامعتبر یا منقضی شده است.",
                reply_markup=back_keyboard()
            )
            return

        target_id = target[0]

        # -----------------------------------------
        # SELF LINK
        # -----------------------------------------

        if target_id == user.id:

            bot_info = await context.bot.get_me()

            link_code, _ = get_or_create_user(user)

            my_link = (
                f"https://t.me/"
                f"{bot_info.username}"
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

        # -----------------------------------------
        # TARGET BLOCKED USER
        # -----------------------------------------

        if is_blocked(target_id, user.id):
            await update.message.reply_text(
                "❌ شما توسط این کاربر بلاک شده‌اید.",
                reply_markup=back_keyboard()
            )

            return

        # -----------------------------------------
        # SAVE TARGET
        # -----------------------------------------

        context.user_data.clear()
        context.user_data["target_id"] = target_id

        await update.message.reply_text(
            "💬 شما در حال ارسال پیام ناشناس هستید.\n\n"
            "پیام خود را بنویسید:",
            reply_markup=ForceReply(selective=True)
        )

        return

    # -----------------------------------------
    # NORMAL /START
    # -----------------------------------------

    if not await is_member(
        context.bot,
        user.id
    ):
        await send_join_message(
            update,
            context
        )
        return

    context.user_data.clear()

    await send_main_panel(
        update,
        context
    )


# =========================================================
# MESSAGE HANDLER
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not update.message:
        return

    user = update.effective_user
    text = update.message.text

    if not text:
        return

    text = text.strip()

    # -----------------------------------------
    # UNBLOCK
    # -----------------------------------------

    normalized = text

    if normalized.startswith("/"):
        normalized = normalized[1:]

    if normalized.startswith("unblock_"):

        code = normalized[len("unblock_"):].strip()

        if not code:
            await update.message.reply_text(
                "❌ کد رفع مسدودی وارد نشده است."
            )
            return

        if unblock_user(
            user.id,
            code
        ):
            await update.message.reply_text(
                "✅ کاربر با موفقیت از لیست مسدودی حذف شد."
            )
        else:
            await update.message.reply_text(
                "❌ کد رفع مسدودی نامعتبر است."
            )

        return

    # -----------------------------------------
    # MEMBERSHIP
    # -----------------------------------------

    if not await is_member(
        context.bot,
        user.id
    ):
        await send_join_message(
            update,
            context
        )
        return

    # -----------------------------------------
    # ANONYMOUS MESSAGE
    # -----------------------------------------

    if "target_id" in context.user_data:

        target_id = context.user_data["target_id"]

        # Check block again
        if is_blocked(
            target_id,
            user.id
        ):
            context.user_data.clear()

            await update.message.reply_text(
                "❌ شما توسط این کاربر بلاک شده‌اید.",
                reply_markup=back_keyboard()
            )

            return

        anon_code = get_anon_code(user.id)

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "پاسخ 💬",
                    callback_data=f"reply_{user.id}"
                ),
                InlineKeyboardButton(
                    "بلاک 🚫",
                    callback_data=f"block_{user.id}"
                )
            ]
        ])

        try:

            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    f"کاربر {anon_code} "
                    f"برای شما پیام ناشناسی ارسال کرد:\n\n"
                    f"{text}"
                ),
                reply_markup=keyboard
            )

            await update.message.reply_text(
                "✅ پیام ناشناس با موفقیت ارسال شد.",
                reply_markup=back_keyboard()
            )

        except TelegramError as e:

            print(
                "ANONYMOUS SEND ERROR:",
                e
            )

            await update.message.reply_text(
                "❌ ارسال پیام انجام نشد."
            )

        context.user_data.clear()

        return

    # -----------------------------------------
    # ANONYMOUS REPLY
    # -----------------------------------------

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
                "✅ پاسخ ناشناس ارسال شد.",
                reply_markup=back_keyboard()
            )

        except TelegramError as e:

            print(
                "REPLY SEND ERROR:",
                e
            )

            await update.message.reply_text(
                "❌ ارسال پاسخ انجام نشد."
            )

        context.user_data.clear()

        return

    # -----------------------------------------
    # NORMAL TEXT
    # -----------------------------------------

    await update.message.reply_text(
        "از منوی ربات استفاده کن 👇",
        reply_markup=main_keyboard()
    )


# =========================================================
# BUTTON HANDLER
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not query:
        return

    await query.answer()

    data = query.data
    user_id = query.from_user.id

    # -----------------------------------------
    # BACK
    # -----------------------------------------

    if data == "back_main":

        context.user_data.clear()

        if not await is_member(
            context.bot,
            user_id
        ):
            await send_join_message(
                update,
                context
            )
            return

        await send_main_panel(
            update,
            context
        )

        return

    # -----------------------------------------
    # CHECK JOIN
    # -----------------------------------------

    if data == "check_join":

        if await is_member(
            context.bot,
            user_id
        ):

            context.user_data.clear()

            await send_main_panel(
                update,
                context
            )

        else:

            await query.answer(
                "هنوز عضو کانال نشدی ❌",
                show_alert=True
            )

        return

    # -----------------------------------------
    # COPY LINK
    # -----------------------------------------

    if data == "copy_link":

        if not await is_member(
            context.bot,
            user_id
        ):
            await send_join_message(
                update,
                context
            )
            return

        bot_info = await context.bot.get_me()

        link_code, _ = get_or_create_user(
            query.from_user
        )

        link = (
            f"https://t.me/"
            f"{bot_info.username}"
            f"?start={link_code}"
        )

        text = (
            "🔗 لینک اختصاصی شما:\n\n"
            f"{link}\n\n"
            "این لینک رو برای دیگران بفرست "
            "تا به صورت ناشناس برات پیام بفرستن."
        )

        await query.edit_message_text(
            text,
            reply_markup=back_keyboard()
        )

        return

    # -----------------------------------------
    # HELP
    # -----------------------------------------

    if data == "help":

        text = (
            "📖 راهنمای ربات\n\n"
            "۱️⃣ لینک ناشناست رو دریافت کن.\n\n"
            "۲️⃣ لینک رو برای دیگران بفرست.\n\n"
            "۳️⃣ هرکس لینک رو باز کنه می‌تونه "
            "به صورت ناشناس برات پیام بفرسته.\n\n"
            "۴️⃣ برای هر پیام می‌تونی پاسخ بدی "
            "یا فرستنده رو بلاک کنی.\n\n"
            "۵️⃣ کاربران بلاک‌شده از قسمت "
            "«لیست مسدودی» قابل مشاهده و رفع بلاک هستند."
        )

        await query.edit_message_text(
            text,
            reply_markup=back_keyboard()
        )

        return

    # -----------------------------------------
    # BLOCK LIST
    # -----------------------------------------

    if data == "block_list":

        if not await is_member(
            context.bot,
            user_id
        ):
            await send_join_message(
                update,
                context
            )
            return

        blocked_users = get_blocked_users(
            user_id
        )

        if not blocked_users:

            text = (
                "🔴 لیست مسدودی شما خالی است.\n\n"
                "در حال حاضر هیچ کاربری را بلاک 
