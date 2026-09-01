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

# کانال 1
CHANNEL_1 = "@hidemychatRobot0"
CHANNEL_1_URL = "https://t.me/hidemychatRobot0"

# کانال 2
CHANNEL_2 = "@DoNi0r"
CHANNEL_2_URL = "https://t.me/DoNi0r"

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

    # Users
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            link_code TEXT UNIQUE NOT NULL,
            anon_code TEXT UNIQUE NOT NULL,
            display_name TEXT,
            created_at TEXT NOT NULL
        )
    """)

    # Blocks
    cur.execute("""
        CREATE TABLE IF NOT EXISTS blocks (
            blocker_id INTEGER NOT NULL,
            blocked_id INTEGER NOT NULL,
            unblock_code TEXT UNIQUE NOT NULL,
            PRIMARY KEY (blocker_id, blocked_id)
        )
    """)

    # Migration برای دیتابیس قدیمی
    cur.execute("PRAGMA table_info(users)")
    columns = {row[1] for row in cur.fetchall()}

    if "display_name" not in columns:
        cur.execute(
            "ALTER TABLE users ADD COLUMN display_name TEXT"
        )

    conn.commit()
    conn.close()


# =========================================================
# CODE GENERATORS
# =========================================================

def generate_anon_code():

    conn = get_db()
    cur = conn.cursor()

    try:
        while True:

            code = "".join(
                random.choices(
                    string.digits,
                    k=7
                )
            )

            cur.execute(
                "SELECT 1 FROM users WHERE anon_code = ?",
                (code,)
            )

            if cur.fetchone() is None:
                return code

    finally:
        conn.close()


def generate_unblock_code():

    conn = get_db()
    cur = conn.cursor()

    chars = string.ascii_lowercase + string.digits

    try:
        while True:

            code = "".join(
                random.choices(
                    chars,
                    k=10
                )
            )

            cur.execute(
                "SELECT 1 FROM blocks WHERE unblock_code = ?",
                (code,)
            )

            if cur.fetchone() is None:
                return code

    finally:
        conn.close()


# =========================================================
# USERS
# =========================================================

def get_or_create_user(user):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            link_code,
            anon_code,
            display_name
        FROM users
        WHERE user_id = ?
    """, (
        user.id,
    ))

    row = cur.fetchone()

    # کاربر قبلی
    if row:

        cur.execute("""
            UPDATE users
            SET
                username = ?,
                full_name = ?
            WHERE user_id = ?
        """, (
            user.username,
            user.full_name,
            user.id
        ))

        conn.commit()
        conn.close()

        return (
            row[0],
            row[1],
            row[2]
        )

    # کاربر جدید
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
            display_name,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        user.id,
        user.username,
        user.full_name,
        link_code,
        anon_code,
        None,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()

    return (
        link_code,
        anon_code,
        None
    )


def get_user_by_link(link_code):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            user_id,
            full_name,
            anon_code,
            display_name
        FROM users
        WHERE link_code = ?
    """, (
        link_code,
    ))

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
    """, (
        user_id,
    ))

    row = cur.fetchone()

    conn.close()

    if row:
        return row[0]

    return "0000000"


def get_display_name(user_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            display_name,
            full_name
        FROM users
        WHERE user_id = ?
    """, (
        user_id,
    ))

    row = cur.fetchone()

    conn.close()

    if not row:
        return "کاربر"

    if row[0]:
        return row[0]

    if row[1]:
        return row[1]

    return "کاربر"


def set_display_name(user_id, name):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET display_name = ?
        WHERE user_id = ?
    """, (
        name,
        user_id
    ))

    conn.commit()
    conn.close()


# =========================================================
# BLOCK SYSTEM
# =========================================================

def is_blocked(blocker_id, blocked_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT 1
        FROM blocks
        WHERE
            blocker_id = ?
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
        WHERE
            blocker_id = ?
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
        WHERE
            blocker_id = ?
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
        WHERE
            blocker_id = ?
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
    """, (
        blocker_id,
    ))

    rows = cur.fetchall()

    conn.close()

    return rows


# =========================================================
# FORCE JOIN
# =========================================================

async def is_member(bot, user_id):

    valid_statuses = (
        "member",
        "administrator",
        "creator"
    )

    try:

        member_1 = await bot.get_chat_member(
            chat_id=CHANNEL_1,
            user_id=user_id
        )

        member_2 = await bot.get_chat_member(
            chat_id=CHANNEL_2,
            user_id=user_id
        )

        channel_1_ok = (
            member_1.status in valid_statuses
        )

        channel_2_ok = (
            member_2.status in valid_statuses
        )

        return (
            channel_1_ok
            and
            channel_2_ok
        )

    except TelegramError as e:

        print(
            "FORCE JOIN ERROR:",
            repr(e)
        )

        return False


# =========================================================
# KEYBOARDS
# =========================================================

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


# =========================================================
# MAIN PANEL
# =========================================================

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
        "درود و عرض ادب! 👋\n"
        "به گلدن چت خوش اومدی ❤️\n\n"
        "برای استفاده از ربات ابتدا "
        "در هر دو کانال زیر عضو شو 👇"
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


# =========================================================
# MAIN PANEL MESSAGE
# =========================================================

async def send_main_panel(update, context):

    text = (
        "درودد مجدد 👋\n"
        "ممنون که گلدن چت رو انتخاب کردی ❤️\n\n"
        "از پنل شیشه‌ای زیر استفاده کن 👇"
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

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    get_or_create_user(user)

    # =====================================================
    # START WITH LINK
    # =====================================================

    if context.args:

        target_code = context.args[0].strip()

        # جوین اجباری
        if not await is_member(
            context.bot,
            user.id
        ):

            await send_join_message(
                update,
                context
            )

            return

        target = get_user_by_link(
            target_code
        )

        if not target:

            await update.message.reply_text(
                "❌ این لینک نامعتبر است.",
                reply_markup=back_keyboard()
            )

            return

        target_id = target[0]

        display_name = target[3]

        # =================================================
        # SELF LINK
        # =================================================

        if target_id == user.id:

            bot_info = await context.bot.get_me()

            link_code, _, _ = get_or_create_user(
                user
            )

            my_link = (
                f"https://t.me/"
                f"{bot_info.username}"
                f"?start={link_code}"
            )

            await update.message.reply_text(

                "به خودت که نمیتونی پیام بفرستی عزیز 🥹\n\n"

                "ولی منتظر بمون و لینکتو بیشتر به اشتراک "
                "بزار و منتظر پیام ناشناست باش😍\n\n"

                "لینک خودت:\n"

                f"{my_link}",

                reply_markup=back_keyboard()
            )

            return

        # =================================================
        # BLOCK CHECK
        # =================================================

        if is_blocked(
            target_id,
            user.id
        ):

            await update.message.reply_text(

                "❌ شما توسط این کاربر بلاک شده‌اید.",

                reply_markup=back_keyboard()
            )

            return

        # =================================================
        # TARGET NAME
        # =================================================

        target_name = (
            display_name
            if display_name
            else "کاربر"
        )

        # =================================================
        # SAVE TARGET
        # =================================================

        context.user_data.clear()

        context.user_data[
            "target_id"
        ] = target_id

        # =================================================
        # SEND SCREEN
        # =================================================

        await update.message.reply_text(

            f"شما در حال ارسال پیام ناشناس به "
            f"{target_name} هستید.\n\n"
            "پیام خود را بنویسید: 💤",

            reply_markup=cancel_send_keyboard()
        )

        return

    # =====================================================
    # NORMAL START
    # =====================================================

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

    text = (
        update.message.text or ""
    ).strip()

    if not text:
        return

    # =====================================================
    # UNBLOCK
    # =====================================================

    normalized = text

    if normalized.startswith("/"):
        normalized = normalized[1:]

    if normalized.startswith("unblock_"):

        code = normalized[
            len("unblock_"):
        ].strip()

        if unblock_user(
            user.id,
            code
        ):

            await update.message.reply_text(

                "✅ کاربر با موفقیت "
                "از لیست مسدودی حذف شد.",

                reply_markup=back_keyboard()
            )

        else:

            await update.message.reply_text(

                "❌ کد رفع مسدودی نامعتبر است.",

                reply_markup=back_keyboard()
            )

        return

    # =====================================================
    # FORCE JOIN
    # =====================================================

    if not await is_member(
        context.bot,
        user.id
    ):

        await send_join_message(
            update,
            context
        )

        return

    # =====================================================
    # SET NAME
    # =====================================================

    if context.user_data.get(
        "setting_name"
    ):

        name = text.strip()

        if len(name) < 1:

            await update.message.reply_text(

                "❌ اسم نمی‌تواند خالی باشد.\n\n"
                "دوباره اسم موردنظرت را بفرست:",

                reply_markup=back_keyboard()
            )

            return

        if len(name) > 30:

            await update.message.reply_text(

                "❌ اسم حداکثر باید ۳۰ کاراکتر باشد.\n\n"
                "دوباره ارسال کن:",

                reply_markup=back_keyboard()
            )

            return

        set_display_name(
            user.id,
            name
        )

        context.user_data.clear()

        await update.message.reply_text(

            f"✅ اسم شما با موفقیت روی "
            f"«{name}» تنظیم شد.",

            reply_markup=back_keyboard()
        )

        return

    # =====================================================
    # ANONYMOUS MESSAGE
    # =====================================================

    if "target_id" in context.user_data:

        target_id = context.user_data[
            "target_id"
        ]

        # دوباره بررسی بلاک
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

        anon_code = get_anon_code(
            user.id
        )

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
   
