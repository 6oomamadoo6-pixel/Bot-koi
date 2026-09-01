import os
import sqlite3
import random
import string
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
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

ADMIN_ID = 6078875175

CHANNEL_1 = "@hidemychatRobot0"
CHANNEL_1_URL = "https://t.me/hidemychatRobot0"

CHANNEL_2 = "@DoNi0r"
CHANNEL_2_URL = "https://t.me/DoNi0r"

DB_NAME = "bot.db"


# =========================================================
# DATABASE
# =========================================================

def get_db():
    return sqlite3.connect(DB_NAME)


def generate_anon_code():
    while True:
        code = "".join(random.choices(string.digits, k=7))

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM users WHERE anon_code = ?",
            (code,)
        )
        exists = cur.fetchone()
        conn.close()

        if not exists:
            return code


def generate_unblock_code():
    chars = string.ascii_letters + string.digits

    while True:
        code = "".join(random.choices(chars, k=10))

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM blocks WHERE unblock_code = ?",
            (code,)
        )
        exists = cur.fetchone()
        conn.close()

        if not exists:
            return code


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            link_code TEXT UNIQUE,
            anon_code TEXT UNIQUE,
            display_name TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS blocks (
            blocker_id INTEGER NOT NULL,
            blocked_id INTEGER NOT NULL,
            unblock_code TEXT,
            PRIMARY KEY (blocker_id, blocked_id)
        )
    """)

    # -----------------------------------------------------
    # Migration for old database
    # -----------------------------------------------------

    cur.execute("PRAGMA table_info(users)")
    user_columns = {row[1] for row in cur.fetchall()}

    if "display_name" not in user_columns:
        cur.execute(
            "ALTER TABLE users ADD COLUMN display_name TEXT"
        )

    cur.execute("PRAGMA table_info(blocks)")
    block_columns = {row[1] for row in cur.fetchall()}

    if "unblock_code" not in block_columns:
        cur.execute(
            "ALTER TABLE blocks ADD COLUMN unblock_code TEXT"
        )

    # -----------------------------------------------------
    # Give old blocks an unblock code
    # -----------------------------------------------------

    cur.execute("""
        SELECT blocker_id, blocked_id
        FROM blocks
        WHERE unblock_code IS NULL OR unblock_code = ''
    """)

    old_blocks = cur.fetchall()

    for blocker_id, blocked_id in old_blocks:
        code = generate_unblock_code()

        cur.execute("""
            UPDATE blocks
            SET unblock_code = ?
            WHERE blocker_id = ? AND blocked_id = ?
        """, (
            code,
            blocker_id,
            blocked_id
        ))

    conn.commit()
    conn.close()


# =========================================================
# USERS
# =========================================================

def get_or_create_user(user_id, username, full_name):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT link_code, anon_code, display_name
        FROM users
        WHERE user_id = ?
    """, (user_id,))

    row = cur.fetchone()

    if row:
        link_code = row[0]
        anon_code = row[1]

        cur.execute("""
            UPDATE users
            SET username = ?, full_name = ?
            WHERE user_id = ?
        """, (
            username,
            full_name,
            user_id
        ))

        conn.commit()
        conn.close()

        return link_code, anon_code

    link_code = str(user_id)
    anon_code = generate_anon_code()

    cur.execute("""
        INSERT INTO users (
            user_id,
            username,
            full_name,
            link_code,
            anon_code,
            display_name,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        username,
        full_name,
        link_code,
        anon_code,
        full_name,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()

    return link_code, anon_code


def get_user(user_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT user_id, username, full_name, link_code,
               anon_code, display_name
        FROM users
        WHERE user_id = ?
    """, (user_id,))

    row = cur.fetchone()

    conn.close()

    return row


def get_user_by_link_code(link_code):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT user_id, full_name, display_name, anon_code
        FROM users
        WHERE link_code = ?
    """, (link_code,))

    row = cur.fetchone()

    conn.close()

    return row


def get_display_name(user_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT display_name, full_name
        FROM users
        WHERE user_id = ?
    """, (user_id,))

    row = cur.fetchone()

    conn.close()

    if not row:
        return "کاربر"

    return row[0] or row[1] or "کاربر"


# =========================================================
# BLOCK SYSTEM
# =========================================================

def is_blocked(blocker_id, blocked_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT 1
        FROM blocks
        WHERE blocker_id = ? AND blocked_id = ?
    """, (
        blocker_id,
        blocked_id
    ))

    result = cur.fetchone()

    conn.close()

    return result is not None


def block_user(blocker_id, blocked_id):
    if blocker_id == blocked_id:
        return

    conn = get_db()
    cur = conn.cursor()

    code = generate_unblock_code()

    cur.execute("""
        INSERT OR IGNORE INTO blocks (
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


def unblock_by_code(user_id, code):
    code = code.strip()

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT blocked_id
        FROM blocks
        WHERE blocker_id = ?
        AND unblock_code = ?
    """, (
        user_id,
        code
    ))

    row = cur.fetchone()

    if not row:
        conn.close()
        return None

    blocked_id = row[0]

    cur.execute("""
        DELETE FROM blocks
        WHERE blocker_id = ?
        AND unblock_code = ?
    """, (
        user_id,
        code
    ))

    conn.commit()
    conn.close()

    return blocked_id


def get_blocked_users(user_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            users.anon_code,
            blocks.unblock_code,
            blocks.blocked_id
        FROM blocks
        JOIN users
        ON users.user_id = blocks.blocked_id
        WHERE blocks.blocker_id = ?
        ORDER BY users.anon_code
    """, (user_id,))

    rows = cur.fetchall()

    conn.close()

    return rows


# =========================================================
# MEMBERSHIP
# =========================================================

async def is_member(bot, user_id):
    valid_statuses = {
        "member",
        "administrator",
        "creator"
    }

    try:
        member_1 = await bot.get_chat_member(
            chat_id=CHANNEL_1,
            user_id=user_id
        )

        member_2 = await bot.get_chat_member(
            chat_id=CHANNEL_2,
            user_id=user_id
        )

        return (
            member_1.status in valid_statuses
            and member_2.status in valid_statuses
        )

    except TelegramError as e:
        print(
            f"Membership check error for {user_id}: "
            f"{repr(e)}"
        )
        return False

    except Exception as e:
        print(
            f"Unknown membership error for {user_id}: "
            f"{repr(e)}"
        )
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


def cancel_send_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "لغو ارسال پیام ❌",
                callback_data="cancel_send"
            )
        ]
    ])


def join_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "چنل 1 : کانال رسمی گلدن چت",
                url=CHANNEL_1_URL
            )
        ],
        [
            InlineKeyboardButton(
                "چنل 2 : کانال ( اجباری ) 📢",
                url=CHANNEL_2_URL
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
                "تنظیمات نام ⚙️",
                callback_data="name_settings"
            ),
            InlineKeyboardButton(
                "تبلیغات 📢",
                callback_data="ads"
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
                url=CHANNEL_1_URL
            ),
            InlineKeyboardButton(
                "راهنما 🤔",
                callback_data="help"
            )
        ]
    ])


# =========================================================
# JOIN MESSAGE
# =========================================================

async def send_join_message(update, context):
    text = (
        "درود و عرض ادب ! 👋\n"
        "خوش اومدی\n\n"
        "برای ادامه استفاده از ربات "
        "زحمت بکش توی کانال‌های زیر جوین شو."
    )

    keyboard = join_keyboard()

    if update.message:
        await update.message.reply_text(
            text,
            reply_markup=keyboard
        )

    elif update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=keyboard
        )


# =========================================================
# MAIN PANEL
# =========================================================

async def send_main_panel(update, context):
    text = (
        "درودد مجدد 👋\n\n"
        "ممنون که ربات مارو انتخاب کردی ❤️\n\n"
        "میتونی با پنل شیشه‌ای زیر "
        "از قابلیت‌های ربات ما استفاده کنی:"
    )

    keyboard = main_keyboard()

    if update.message:
        await update.message.reply_text(
            text,
            reply_markup=keyboard
        )

    elif update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=keyboard
        )


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not user:
        return

    get_or_create_user(
        user.id,
        user.username,
        user.full_name
    )

    # -----------------------------------------------------
    # Check /start parameter
    # -----------------------------------------------------

    if context.args:
        target_code = context.args[0]

        target = get_user_by_link_code(target_code)

        if not target:
            await update.message.reply_text(
                "❌ لینک نامعتبر است."
            )
            return

        target_id = target[0]

        # -------------------------------------------------
        # Self link
        # -------------------------------------------------

        if target_id == user.id:
            me = await context.bot.get_me()

            own_link = (
                f"https://t.me/{me.username}"
                f"?start={user.id}"
            )

            text = (
                "به خودت که نمیتونی پیام بفرستی عزیز 🥹\n\n"
                "ولی منتظر بمون و لینکتو بیشتر به اشتراک "
                "بزار و منتظر پیام ناشناست باش😍\n\n"
                "لینک خودت :\n"
                f"{own_link}"
            )

            await update.message.reply_text(
                text,
                reply_markup=back_keyboard()
            )

            return

        # -------------------------------------------------
        # Forced join
        # -------------------------------------------------

        if not await is_member(context.bot, user.id):
            await send_join_message(
                update,
                context
            )
            return

        display_name = (
            target[2]
            or target[1]
            or "کاربر"
        )

        context.user_data.clear()

        context.user_data["target_id"] = target_id

        text = (
            f"شما در حال ارسال پیام ناشناس به "
            f"{display_name} هستید.\n\n"
            "پیام خود را بنویسید : 💤"
        )

        await update.message.reply_text(
            text,
            reply_markup=cancel_send_keyboard()
        )

        return

    # -----------------------------------------------------
    # Normal /start
    # -----------------------------------------------------

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


# =========================================================
# COPY LINK
# =========================================================

async def show_link(update, context):
    user = update.effective_user

    get_or_create_user(
        user.id,
        user.username,
        user.full_name
    )

    me = await context.bot.get_me()

    link = (
        f"https://t.me/{me.username}"
        f"?start={user.id}"
    )

    text = (
        "🔗 لینک ناشناس شما:\n\n"
        f"{link}\n\n"
        "لینک بالا را برای دوستانت ارسال کن "
        "تا بتوانند به صورت ناشناس برایت پیام بفرستند."
    )

    await update.callback_query.edit_message_text(
        text,
        reply_markup=back_keyboard()
    )


# =========================================================
# BLOCK LIST
# =========================================================

async def show_block_list(update, context):
    user = update.effective_user

    rows = get_blocked_users(user.id)

    if not rows:
        text = (
            "🔴 لیست مسدودی شما خالی است.\n\n"
            "هیچ کاربری را مسدود نکرده‌اید."
        )

        await update.callback_query.edit_message_text(
            text,
            reply_markup=back_keyboard()
        )

        return

    lines = [
        "🔴 لیست مسدودی شما:\n"
    ]

    for index, row in enumerate(rows):
        anon_code = row[0]
        unblock_code = row[1]

        lines.append(
            f"کاربر {anon_code} در لیست مسدودی شما است.\n"
            f"رفع مسدودی : unblock_{unblock_code}/"
        )

        if index != len(rows) - 1:
            lines.append("____")

    lines.append(
        "\n\nبرای رفع مسدودی، "
        "دستور مربوط به همان کاربر را ارسال کنید."
    )

    text = "\n".join(lines)

    await update.callback_query.edit_message_text(
        text,
        reply_markup=back_keyboard()
    )


# =========================================================
# NAME SETTINGS
# =========================================================

async def show_name_settings(update, context):
    user = update.effective_user

    current_name = get_display_name(user.id)

    text = (
        "⚙️ تنظیمات نام\n\n"
        f"نام فعلی شما:\n"
        f"{current_name}\n\n"
        "اگر می‌خواهی اسم نمایش داده شده در لینک "
        "ناشناست را تغییر بده، اسم جدیدت را همینجا ارسال کن."
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "تغییر نام ✏️",
                callback_data="change_name"
            )
        ],
        [
            InlineKeyboardButton(
                "بازگشت 🔙",
                callback_data="back_main"
            )
        ]
    ])

    await update.callback_query.edit_message_text(
        text,
        reply_markup=keyboard
    )


# =========================================================
# ADS
# =========================================================

async def show_ads(update, context):
    text = (
        "📢 تبلیغات فعال نیست.\n\n"
        "به زودی..."
    )

    await update.callback_query.edit_message_text(
        text,
        reply_markup=back_keyboard()
    )


# =========================================================
# HELP
# =========================================================

async def show_help(update, context):
    text = (
        "🤔 راهنمای گلدن چت\n\n"
        "🔗 دریافت لینک ناشناس:\n"
        "لینک اختصاصی خودت را دریافت کن و برای دیگران بفرست.\n\n"
        "⚙️ تنظیمات نام:\n"
        "نامی که دیگران هنگام ارسال پیام می‌بینند را تغییر بده.\n\n"
        "🔴 لیست مسدودی:\n"
        "کاربرانی که بلاک کرده‌ای در این قسمت نمایش داده می‌شوند.\n\n"
        "📢 تبلیغات:\n"
        "بخش تبلیغات ربات."
    )

    await update.callback_query.edit_message_text(
        text,
        reply_markup=back_keyboard()
    )


# =========================================================
# BUTTON HANDLER
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    await query.answer()

    user = update.effective_user

    # -----------------------------------------------------
    # Check Join
    # -----------------------------------------------------

    if query.data == "check_join":
        if not await is_member(
            context.bot,
            user.id
        ):
            await query.answer(
                "هنوز در هر دو کانال جوین نشده‌ای ❌",
                show_alert=True
            )
            return

        await send_main_panel(
            update,
            context
        )
        return

    # -----------------------------------------------------
    # Back
    # -----------------------------------------------------

    if query.data == "back_main":
        context.user_data.clear()

        if not await is_member(
            context.bot,
            user.id
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

    # -----------------------------------------------------
    # Cancel anonymous message
    # -----------------------------------------------------

    if query.data =
