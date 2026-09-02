import os
import sqlite3
import random
import string
import json
import threading
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatMember,
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
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

ADMIN_ID = 6078875175

CHANNEL_1 = "@hidemychatRobot0"
CHANNEL_1_URL = "https://t.me/hidemychatRobot0"

CHANNEL_2 = "@DoNi0r"
CHANNEL_2_URL = "https://t.me/DoNi0r"

# ---------------------------------------------------------
# DATABASE
# ---------------------------------------------------------

# اگر بعداً Railway Volume ساختی می‌توانی این متغیر را
# در Railway تنظیم کنی.
#
# اگر تنظیم نشده باشد همان bot.db قبلی استفاده می‌شود.

DB_NAME = os.getenv("DB_PATH", "bot.db")

# ---------------------------------------------------------
# ADMIN API
# ---------------------------------------------------------

# این مقدار را در Railway به صورت Environment Variable بساز:
#
# ADMIN_API_KEY
#
# یک مقدار خیلی طولانی و تصادفی قرار بده.
#
# مثال:
# ADMIN_API_KEY=your-long-random-secret
#
# این کلید را به هیچ‌کس نده.

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")

# پورت Railway
API_PORT = int(os.getenv("PORT", "8080"))


# =========================================================
# BROADCAST STATE
# =========================================================

broadcast_lock = threading.Lock()

broadcast_running = False
broadcast_stop_requested = False

broadcast_stats = {
    "total": 0,
    "success": 0,
    "failed": 0,
    "blocked": 0,
}


# =========================================================
# DATABASE
# =========================================================

def db():
    conn = sqlite3.connect(
        DB_NAME,
        timeout=30
    )

    conn.execute(
        "PRAGMA busy_timeout = 30000"
    )

    return conn


def backup_database():
    """
    قبل از هر Migration از دیتابیس Backup می‌گیرد.

    این تابع فقط Backup می‌سازد و دیتابیس اصلی را
    حذف یا جایگزین نمی‌کند.
    """

    if not os.path.exists(DB_NAME):
        return

    try:
        backup_name = (
            DB_NAME
            + ".backup-"
            + datetime.now().strftime(
                "%Y%m%d-%H%M%S"
            )
        )

        source = sqlite3.connect(
            DB_NAME,
            timeout=30
        )

        destination = sqlite3.connect(
            backup_name
        )

        with destination:
            source.backup(destination)

        destination.close()
        source.close()

        print(
            f"Database backup created: {backup_name}"
        )

    except Exception as e:
        print(
            f"Database backup error: {e}"
        )


def init_db():
    """
    دیتابیس را ایجاد/بررسی می‌کند.

    بسیار مهم:
    هیچ جدول قبلی DROP نمی‌شود.
    اطلاعات قبلی حذف نمی‌شود.
    """

    database_exists = os.path.exists(DB_NAME)

    if database_exists:
        backup_database()

    conn = db()
    cur = conn.cursor()

    # =====================================================
    # USERS
    # =====================================================

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

    # =====================================================
    # BLOCKS
    # =====================================================

    cur.execute("""
        CREATE TABLE IF NOT EXISTS blocks (
            blocker_id INTEGER NOT NULL,
            blocked_id INTEGER NOT NULL,
            unblock_code TEXT UNIQUE,
            PRIMARY KEY (blocker_id, blocked_id)
        )
    """)

    # =====================================================
    # ANONYMOUS MESSAGES
    # =====================================================

    cur.execute("""
        CREATE TABLE IF NOT EXISTS anonymous_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            message_text TEXT NOT NULL,
            created_at TEXT
        )
    """)

    # =====================================================
    # USERS MIGRATION
    # =====================================================

    cur.execute(
        "PRAGMA table_info(users)"
    )

    user_columns = [
        row[1]
        for row in cur.fetchall()
    ]

    if "display_name" not in user_columns:
        print(
            "Adding missing column: users.display_name"
        )

        cur.execute(
            "ALTER TABLE users ADD COLUMN display_name TEXT"
        )

    # =====================================================
    # BLOCKS MIGRATION
    # =====================================================

    cur.execute(
        "PRAGMA table_info(blocks)"
    )

    block_columns = [
        row[1]
        for row in cur.fetchall()
    ]

    if "unblock_code" not in block_columns:
        print(
            "Adding missing column: blocks.unblock_code"
        )

        cur.execute(
            "ALTER TABLE blocks ADD COLUMN unblock_code TEXT"
        )

    conn.commit()
    conn.close()

    # فقط برای رکوردهایی که از قبل unblock_code نداشته‌اند
    # کد جدید ساخته می‌شود.
    #
    # anon_code و link_code دست نمی‌خورند.

    fill_missing_unblock_codes()


# =========================================================
# CODE GENERATORS
# =========================================================

def generate_code(length=10):
    chars = string.ascii_letters + string.digits

    return "".join(
        random.choices(
            chars,
            k=length
        )
    )


def generate_anon_code():
    while True:

        code = "".join(
            random.choices(
                string.digits,
                k=7
            )
        )

        conn = db()
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
    while True:

        code = generate_code(10)

        conn = db()
        cur = conn.cursor()

        cur.execute(
            "SELECT 1 FROM blocks WHERE unblock_code = ?",
            (code,)
        )

        exists = cur.fetchone()

        conn.close()

        if not exists:
            return code


# =========================================================
# BLOCK CODE MIGRATION
# =========================================================

def fill_missing_unblock_codes():

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT blocker_id, blocked_id
        FROM blocks
        WHERE unblock_code IS NULL
        OR unblock_code = ''
    """)

    rows = cur.fetchall()

    for blocker_id, blocked_id in rows:

        code = generate_unblock_code()

        cur.execute("""
            UPDATE blocks
            SET unblock_code = ?
            WHERE blocker_id = ?
            AND blocked_id = ?
            AND (
                unblock_code IS NULL
                OR unblock_code = ''
            )
        """, (
            code,
            blocker_id,
            blocked_id
        ))

    conn.commit()
    conn.close()


# =========================================================
# USER FUNCTIONS
# =========================================================

def get_or_create_user(
    user_id,
    username,
    full_name
):

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT link_code, anon_code
        FROM users
        WHERE user_id = ?
    """, (
        user_id,
    ))

    row = cur.fetchone()

    # =====================================================
    # EXISTING USER
    # =====================================================

    if row:

        # بسیار مهم:
        #
        # link_code و anon_code اصلاً UPDATE نمی‌شوند.
        #
        # فقط username و full_name به‌روزرسانی می‌شوند.

        cur.execute("""
            UPDATE users
            SET username = ?,
                full_name = ?
            WHERE user_id = ?
        """, (
            username,
            full_name,
            user_id
        ))

        conn.commit()
        conn.close()

        return row[0], row[1]

    # =====================================================
    # NEW USER
    # =====================================================

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
        full_name or "کاربر",
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()

    return link_code, anon_code


def get_user(user_id):

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            user_id,
            username,
            full_name,
            link_code,
            anon_code,
            display_name
        FROM users
        WHERE user_id = ?
    """, (
        user_id,
    ))

    row = cur.fetchone()

    conn.close()

    return row


def get_user_by_link(link_code):

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            user_id,
            full_name,
            display_name,
            anon_code
        FROM users
        WHERE link_code = ?
    """, (
        link_code,
    ))

    row = cur.fetchone()

    conn.close()

    return row


def get_display_name(user_id):

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT display_name, full_name
        FROM users
        WHERE user_id = ?
    """, (
        user_id,
    ))

    row = cur.fetchone()

    conn.close()

    if not row:
        return "کاربر"

    return row[0] or row[1] or "کاربر"


def set_display_name(
    user_id,
    name
):

    conn = db()
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
# ANONYMOUS MESSAGE FUNCTIONS
# =========================================================

def save_anonymous_message(
    sender_id,
    receiver_id,
    message_text
):

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO anonymous_messages (
            sender_id,
            receiver_id,
            message_text,
            created_at
        )
        VALUES (?, ?, ?, ?)
    """, (
        sender_id,
        receiver_id,
        message_text,
        datetime.now().isoformat()
    ))

    message_id = cur.lastrowid

    conn.commit()
    conn.close()

    return message_id


def get_anonymous_message(message_id):

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            sender_id,
            receiver_id,
            message_text,
            created_at
        FROM anonymous_messages
        WHERE id = ?
    """, (
        message_id,
    ))

    row = cur.fetchone()

    conn.close()

    return row


# =========================================================
# BLOCK FUNCTIONS
# =========================================================

def is_blocked(
    blocker_id,
    blocked_id
):

    conn = db()
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


def block_user(
    blocker_id,
    blocked_id
):

    if blocker_id == blocked_id:
        return False

    conn = db()
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

    if cur.fetchone():

        conn.close()

        return False

    unblock_code = generate_unblock_code()

    cur.execute("""
        INSERT INTO blocks (
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

    return True


def unblock_by_code(
    user_id,
    code
):

    conn = db()
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

        return False

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

    return True


def get_block_list(user_id):

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            users.anon_code,
            blocks.unblock_code
        FROM blocks
        JOIN users
        ON users.user_id = blocks.blocked_id
        WHERE blocks.blocker_id = ?
        ORDER BY blocks.rowid DESC
    """, (
        user_id,
    ))

    rows = cur.fetchall()

    conn.close()

    return rows


# =========================================================
# MEMBERSHIP
# =========================================================

async def check_channel_member(
    bot,
    channel,
    user_id
):

    try:

        member = await bot.get_chat_member(
            chat_id=channel,
            user_id=user_id
        )

        return member.status in (
            ChatMember.MEMBER,
            ChatMember.ADMINISTRATOR,
            ChatMember.OWNER,
        )

    except TelegramError as e:

        print(
            f"Membership error "
            f"{channel} / {user_id}: {e}"
        )

        return False


async def is_member(
    bot,
    user_id
):

    first = await check_channel_member(
        bot,
        CHANNEL_1,
        user_id
    )

    second = await check_channel_member(
        bot,
        CHANNEL_2,
        user_id
    )

    return first and second


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


def cancel_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "لغو ارسال پیام ❌",
                callback_data="cancel_send"
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


def name_settings_keyboard():

    return InlineKeyboardMarkup([
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


def anonymous_message_keyboard(
    message_id,
    sender_id
):

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "پاسخ 🤠",
                callback_data=f"reply:{message_id}"
            ),
            InlineKeyboardButton(
                "بلاک 🔴",
                callback_data=f"block:{sender_id}"
            )
        ]
    ])


# =========================================================
# JOIN MESSAGE
# =========================================================

async def send_join_message(
    update,
    context
):

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

async def send_main_panel(
    update,
    context
):

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
# START COMMAND
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user or not update.message:
        return

    get_or_create_user(
        user.id,
        user.username,
        user.full_name
    )

    # =====================================================
    # LINK START
    # =====================================================

    if context.args:

        target_code = context.args[0]

        target = get_user_by_link(
            target_code
        )

        if not target:

            await update.message.reply_text(
                "❌ لینک نامعتبر است."
            )

            return

        target_id = target[0]

        # =================================================
        # SELF LINK
        # =================================================

        if target_id == user.id:

            bot = await context.bot.get_me()

            own_link = (
                f"https://t.me/{bot.username}"
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

        # =================================================
        # FORCE JOIN
        # =================================================

        if not await is_member(
            context.bot,
            user.id
        ):

            await send_join_message(
                update,
                context
            )

            return

        target_name = (
            target[2]
            or target[1]
            or "کاربر"
        )

        context.user_data.clear()

        context.user_data["target_id"] = target_id
        context.user_data["sending_anonymous"] = True

        text = (
            f"شما در حال ارسال پیام ناشناس به "
            f"{target_name} هستید.\n\n"
            "پیام خود را بنویسید : 💤"
        )

        await update.message.reply_text(
            text,
            reply_markup=cancel_keyboard()
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
# SHOW LINK
# =========================================================

async def show_link(
    update,
    context
):

    user = update.effective_user

    get_or_create_user(
        user.id,
        user.username,
        user.full_name
    )

    bot = await context.bot.get_me()

    link = (
        f"https://t.me/{bot.username}"
        f"?start={user.id}"
    )

    text = (
        "🔗 لینک اختصاصی شما:\n\n"
        f"{link}\n\n"
        "لینک خود را با دیگران به اشتراک بگذارید "
        "تا بتوانند به صورت ناشناس برای شما پیام بفرستند."
    )

    await update.callback_query.edit_message_text(
        text,
        reply_markup=back_keyboard()
    )


# =========================================================
# NAME SETTINGS
# =========================================================

async def name_settings(
    update,
    context
):

    user = update.effective_user

    current_name = get_display_name(
        user.id
    )

    text = (
        "⚙️ تنظیمات نام\n\n"
        f"نام فعلی شما:\n"
        f"{current_name}\n\n"
        "این نام هنگام ارسال پیام ناشناس "
        "به فرستنده نمایش داده می‌شود."
    )

    await update.callback_query.edit_message_text(
        text,
        reply_markup=name_settings_keyboard()
    )


async def change_name(
    update,
    context
):

    context.user_data.clear()

    context.user_data["changing_name"] = True

    text = (
        "✏️ نام جدید خود را ارسال کنید.\n\n"
        "مثلاً:\n"
        "محمد\n"
        "Golden Chat\n"
        "کاربر ویژه 🤠"
    )

    await update.callback_query.edit_message_text(
        text,
        reply_markup=back_keyboard()
    )


# =========================================================
# ADS
# =========================================================

async def ads_page(
    update,
    context
):

    text = (
        "📢 تبلیغات فعال نیست.\n\n"
        "به زودی..."
    )

    await update.callback_query.edit_message_text(
        text,
        reply_markup=back_keyboard()
    )


# =========================================================
# BLOCK LIST
# =========================================================

async def block_list_page(
    update,
    context
):

    user = update.effective_user

    rows = get_block_list(
        user.id
    )

    if not rows:

        await update.callback_query.edit_message_text(
            "🔴 لیست مسدودی شما خالی است.",
            reply_markup=back_keyboard()
        )

        return

    parts = [
        "🔴 لیست مسدودی شما:\n"
    ]

    for index, row in enumerate(rows):

        anon_code = row[0]
        unblock_code = row[1]

        parts.append(
            f"کاربر {anon_code} در لیست مسدودی شما است.\n"
            f"رفع مسدودی : unblock_{unblock_code}/"
        )

        if index != len(rows) - 1:
            parts.append("____")

    parts.append(
        "\n\nدستور مربوط به کاربر را ارسال کنید "
        "تا رفع مسدودی انجام شود."
    )

    text = "\n".join(parts)

    await update.callback_query.edit_message_text(
        text,
        reply_markup=back_keyboard()
    )


# =========================================================
# HELP
# =========================================================

async def help_page(
    update,
    context
):

    text = (
        "🤔 راهنمای گلدن چت\n\n"
        "🔗 دریافت لینک ناشناس:\n"
        "لینک اختصاصی خودت را دریافت کن و "
        "برای دیگران بفرست.\n\n"
        "⚙️ تنظیمات نام:\n"
        "نامی که هنگام باز شدن لینک به "
        "فرستنده نمایش داده می‌شود را تغییر بده.\n\n"
        "🔴 لیست مسدودی:\n"
        "کاربرانی که بلاک کرده‌ای در این بخش هستند.\n\n"
        "📢 تبلیغات:\n"
        "این بخش در حال حاضر فعال نیست."
    )

    await update.callback_query.edit_message_text(
        text,
        reply_markup=back_keyboard()
    )


# =========================================================
# CALLBACK HANDLER
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    if not query:
        return

    data = query.data

    user = query.from_user

    user_id = user.id

    # اول فقط acknowledge عادی
    await query.answer()

    # =====================================================
    # CHECK JOIN
    # =====================================================

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
                "هنوز در هر دو کانال جوین نشده‌ای ❌",
                show_alert=True
            )

        return

    # =====================================================
    # BACK
    # =====================================================

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

    # =====================================================
    # CANCEL ANONYMOUS SEND
    # =====================================================

    if data == "cancel_send":

        context.user_data.clear()

        await query.edit_message_text(
            "❌ ارسال پیام ناشناس لغو شد.",
            reply_markup=back_keyboard()
        )

        return

    # =====================================================
    # COPY LINK
    # =====================================================

    if data == "copy_link":

        await show_link(
            update,
            context
        )

        return

    # =====================================================
    # NAME SETTINGS
    # =====================================================

    if data == "name_settings":

        await name_settings(
            update,
            context
        )

        return

    # =====================================================
    # CHANGE NAME
    # =====================================================

    if data == "change_name":

        await change_name(
            update,
            context
        )

        return

    # =====================================================
    # ADS
    # =====================================================

    if data == "ads":

        await ads_page(
            update,
            context
        )

        return

    # =====================================================
    # BLOCK LIST
    # =====================================================

    if data == "block_list":

        await block_list_page(
            update,
            context
        )

        return

    # =====================================================
    # HELP
    # =====================================================

    if data == "help":

        await help_page(
            update,
            context
        )

        return

    # =====================================================
    # REPLY TO ANONYMOUS MESSAGE
    # =====================================================

    if data.startswith("reply:"):

        try:

            anonymous_message_id = int(
                data.split(":", 1)[1]
            )

        except (
            ValueError,
            IndexError
        ):

            await query.answer(
                "پیام نامعتبر است ❌",
                show_alert=True
            )

            return

        anonymous_message = get_anonymous_message(
            anonymous_message_id
        )

        if not anonymous_message:

            await query.answer(
                "این پیام دیگر موجود نیست ❌",
                show_alert=True
            )

            return

        message_id = anonymous_message[0]
        sender_id = anonymous_message[1]
        receiver_id = anonymous_message[2]

        if receiver_id != user_id:

            await query.answer(
                "این پیام متعلق به شما نیست ❌",
                show_alert=True
            )

            return

        if is_blocked(
            user_id,
            sender_id
        ):

            await query.answer(
                "این کاربر را بلاک کرده‌ای.",
                show_alert=True
            )

            return

        context.user_data.clear()

        context.user_data["reply_message_id"] = message_id
        context.user_data["reply_sender_id"] = sender_id
        context.user_data["replying"] = True

        await query.message.reply_text(
            "پاسخ خود را بنویسید: ✍️",
            reply_markup=cancel_keyboard()
        )

        return

    # =====================================================
    # BLOCK USER
    # =====================================================

    if data.startswith("block:"):

        try:

            blocked_id = int(
                data.split(":", 1)[1]
            )

        except (
            ValueError,
            IndexError
        ):

            await query.answer(
                "کاربر نامعتبر است ❌",
                show_alert=True
            )

            return

        if blocked_id == user_id:

            await query.answer(
                "نمی‌توانی خودت را بلاک کنی 😅",
                show_alert=True
            )

            return

        success = block_user(
            user_id,
            blocked_id
        )

        if success:

            await query.edit_message_text(
                "🔴 کاربر با موفقیت بلاک شد.",
                reply_markup=back_keyboard()
            )

        else:

            await query.answer(
                "این کاربر قبلاً بلاک شده است.",
                show_alert=True
            )

        return


# =========================================================
# MESSAGE HANDLER
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    message = update.message

    if not user or not message:
        return

    if not message.text:
        return

    text = message.text.strip()

    if not text:
        return

    # =====================================================
    # UNBLOCK COMMAND
    # =====================================================

    if (
        text.startswith("unblock_")
        and text.endswith("/")
    ):

        code = text[
            len("unblock_"):-1
        ]

        if not code:

            await message.reply_text(
                "❌ کد رفع مسدودی نامعتبر است."
            )

            return

        success = unblock_by_code(
            user.id,
            code
        )

        if success:

            await message.reply_text(
                "🟢 کاربر با موفقیت از لیست مسدودی "
                "شما خارج شد."
            )

        else:

            await message.reply_text(
                "❌ کد رفع مسدودی نامعتبر است "
                "یا قبلاً استفاده شده."
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
    # CHANGE NAME
    # =====================================================

    if context.user_data.get(
        "changing_name"
    ):

        if len(text) > 50:

            await message.reply_text(
                "❌ نام خیلی طولانی است.\n"
                "حداکثر ۵۰ کاراکتر وارد کنید."
            )

            return

        set_display_name(
            user.id,
            text
        )

        context.user_data.clear()

        await message.reply_text(
            f"✅ نام شما با موفقیت تغییر کرد.\n\n"
            f"نام جدید: {text}",
            reply_markup=back_keyboard()
        )

        return

    # =====================================================
    # REPLY TO ANONYMOUS MESSAGE
    # =====================================================

    if context.user_data.get(
        "replying"
    ):

        anonymous_message_id = context.user_data.get(
            "reply_message_id"
        )

        sender_id = context.user_data.get(
            "reply_sender_id"
        )

        if (
            not anonymous_message_id
            or not sender_id
        ):

            context.user_data.clear()

            await message.reply_text(
                "❌ اطلاعات پیام پیدا نشد.",
                reply_markup=back_keyboard()
            )

            return

        anonymous_message = get_anonymous_message(
            anonymous_message_id
        )

        if not anonymous_message:

            context.user_data.clear()

            await message.reply_text(
                "❌ پیام اصلی پیدا نشد.",
                reply_markup=back_keyboard()
            )

            return

        original_sender_id = anonymous_message[1]
        receiver_id = anonymous_message[2]
        original_text = anonymous_message[3]

        if receiver_id != user.id:

            context.user_data.clear()

            await message.reply_text(
                "❌ این پیام متعلق به شما نیست."
            )

            return

        if original_sender_id != sender_id:

            context.user_data.clear()

            await message.reply_text(
                "❌ خطا در اطلاعات پیام."
            )

            return

        if is_blocked(
            user.id,
            sender_id
        ):

            context.user_data.clear()

            await message.reply_text(
                "❌ این کاربر را بلاک کرده‌اید."
            )

            return

        sender_name = get_display_name(
            user.id
        )

        reply_text = (
            f"کاربر {sender_name} "
            f"به پیام شما پاسخ داد. 🤠\n\n"
            f"پیام شما :\n"
            f"{original_text}\n\n"
            f"پیام پاسخ داده شده :\n"
            f"{text}"
        )

        try:

            await context.bot.send_message(
                chat_id=sender_id,
                text=reply_text
            )

            await message.reply_text(
                "✅ پاسخ شما با موفقیت ارسال شد.",
                reply_markup=back_keyboard()
            )

        except TelegramError as e:

            print(
                f"Reply send error: {e}"
            )

            await message.reply_text(
                "❌ ارسال پاسخ با خطا مواجه شد."
            )

        context.user_data.clear()

        return

    # =====================================================
    # SEND ANONYMOUS MESSAGE
    # =====================================================

    if context.user_data.get(
        "sending_anonymous"
    ):

        target_id = context.user_data.get(
            "target_id"
        )

        if not target_id:

            context.user_data.clear()

            await message.reply_text(
                "❌ مقصد پیام پیدا نشد.",
                reply_markup=back_keyboard()
            )

            return

        if target_id == user.id:

            context.user_data.clear()

            await message.reply_text(
                "❌ نمی‌توانی به خودت پیام بفرستی.",
                reply_markup=back_keyboard()
            )

            return

        if is_blocked(
            target_id,
            user.id
        ):

            context.user_data.clear()

            await message.reply_text(
                "❌ شما توسط این کاربر بلاک شده‌اید.",
                reply_markup=back_keyboard()
            )

            return

        anonymous_message_id = save_anonymous_message(
            sender_id=user.id,
            receiver_id=target_id,
            message_text=text
        )

        row = get_user(
            user.id
        )

        if row:

            anon_code = row[4]

        else:

            anon_code = "0000000"

        keyboard = anonymous_message_keyboard(
            anonymous_message_id,
            user.id
        )

        try:

            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    f"کاربر {anon_code} "
                    f"برای شما پیام ناشناسی ارسال کرد :\n\n"
                    f"{text}"
                ),
                reply_markup=keyboard
            )

            await message.reply_text(
                "✅ پیام ناشناس با موفقیت ارسال شد.",
                reply_markup=back_keyboard()
            )

        except TelegramError as e:

            print(
                f"Anonymous message error: {e}"
            )

            await message.reply_text(
                "❌ خطا در ارسال پیام."
            )

        context.user_data.clear()

        return


# =========================================================
# TELEGRAM API HELPER
# =========================================================

def telegram_api(
    method,
    data
):

    url = (
        f"https://api.telegram.org/bot"
        f"{BOT_TOKEN}/{method}"
    )

    encoded = urllib.parse.urlencode(
        data
    ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=encoded,
        method="POST"
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            raw = response.read().decode(
                "utf-8"
            )

            return json.loads(raw)

    except Exception as e:

        print(
            f"Telegram API error: {e}"
        )

        return None


# =========================================================
# BROADCAST DATABASE FUNCTIONS
# =========================================================

def get_all_user_ids():

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT user_id
        FROM users
        ORDER BY user_id
    """)

    rows = cur.fetchall()

    conn.close()

    return [
        row[0]
        for row in rows
    ]


def mark_user_as_unreachable(
    user_id
):
    """
    فعلاً اطلاعات کاربر را حذف نمی‌کنیم.

    اگر کاربر ربات را Block کرده باشد،
    فقط در آمار Broadcast حساب می‌شود.

    خود رکورد users باقی می‌ماند.
    """

    return


# =========================================================
# BROADCAST WORKER
# =========================================================

def broadcast_text_worker(
    text
):

    global broadcast_running
    global broadcast_stop_requested
    global broadcast_stats

    with broadcast_lock:

        if broadcast_running:

            print(
                "Broadcast already running."
            )

            return

        broadcast_running = True
        broadcast_stop_requested = False

        broadcast_stats = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "blocked": 0,
        }

    try:

        users = get_all_user_ids()

        broadcast_stats["total"] = len(users)

        print(
            f"Broadcast started for "
            f"{len(users)} users."
        )

        for user_id in users:

            with broadcast_lock:

                if broadcast_stop_requested:

                    print(
                        "Broadcast stop requested."
                    )

                    break

            result = telegram_api(
                "sendMessage",
                {
                    "chat_id": user_id,
                    "text": text,
                }
            )

            if result and result.get("ok"):

                broadcast_stats["success"] += 1

            else:

                broadcast_stats["failed"] += 1

                description = ""

                if result:
                    description = result.get(
                        "description",
                        ""
                    )

                if (
                    "bot was blocked"
                    in description.lower()
                    or "user is deactivated"
                    in description.lower()
                    or "chat not found"
                    in description.lower()
                ):

                    broadcast_stats[
                        "blocked"
                    ] += 1

                    mark_user_as_unreachable(
                        user_id
                    )

            # فاصله بین پیام‌ها
            #
            # برای جلوگیری از ارسال خیلی سریع.
            #
            # این مقدار را فعلاً محافظه‌کارانه
            # گذاشته‌ایم.

            import time

            time.sleep(0.05)

    except Exception as e:

        print(
            f"Broadcast worker error: {e}"
        )

    finally:

        with broadcast_lock:

            broadcast_running = False

            broadcast_stop_requested = False

        print(
            "Broadcast finished."
        )


def start_broadcast(
    text
):

    global broadcast_running

    with broadcast_lock:

        if broadcast_running:

            return False

    worker = threading.Thread(
        target=broadcast_text_worker,
        args=(text,),
        daemon=True
    )

    worker.start()

    return True


def stop_broadcast():

    global broadcast_stop_requested

    with broadcast_lock:

        if not broadcast_running:

            return False

        broadcast_stop_requested = True

        return True


# =========================================================
# API RESPONSE
# =========================================================

def send_json(
    handler,
    status_code,
    data
):

    body = json.dumps(
        data,
        ensure_ascii=False
    ).encode("utf-8")

    handler.send_response(
        status_code
    )

    handler.send_header(
        "Content-Type",
        "application/json; charset=utf-8"
    )

    handler.send_header(
        "Content-Length",
        str(len(body))
    )

    handler.end_headers()

    handler.wfile.write(
        body
    )


# =========================================================
# API AUTH
# =========================================================

def api_authorized(handler):

    if not ADMIN_API_KEY:

        return False

    received_key = (
        handler.headers.get(
            "X-API-Key",
            ""
        )
    )

    return (
        received_key
        and received_key == ADMIN_API_KEY
    )


# =========================================================
# API SERVER
# =========================================================

class APIHandler(
    BaseHTTPRequestHandler
):

    def log_message(
        self,
        format,
        *args
    ):

        return

    def do_GET(self):

        # -------------------------------------------------
        # HEALTH CHECK
        # -------------------------------------------------

        if self.path == "/":

            send_json(
                self,
                200,
                {
                    "ok": True,
                    "service": "anonymous-bot-api"
                }
            )

            return

        # -------------------------------------------------
        # STATS
        # -------------------------------------------------

        if self.path == "/stats":

            if not api_authorized(self):

                send_json(
                    self,
                    401,
                    {
                        "ok": False,
                        "error": "Unauthorized"
                    }
                )

                return

            conn = db()
            cur = conn.cursor()

            cur.execute(
                "SELECT COUNT(*) FROM users"
            )

            total_users = cur.fetchone()[0]

            cur.execute(
                "SELECT COUNT(*) FROM blocks"
            )

            total_blocks = cur.fetchone()[0]

            cur.execute(
                "SELECT COUNT(*) FROM anonymous_messages"
            )

            total_messages = cur.fetchone()[0]

            conn.close()

            with broadcast_lock:

                running = broadcast_running

                current_stats = dict(
                    broadcast_stats
                )

            send_json(
                self,
                200,
                {
                    "ok": True,
                    "users": total_users,
                    "blocks": total_blocks,
                    "anonymous_messages": total_messages,
                    "broadcast_running": running,
                    "broadcast": current_stats,
                }
            )

            return

        send_json(
            self,
            404,
            {
                "ok": False,
                "error": "Not found"
            }
        )

    def do_POST(self):

        # -------------------------------------------------
        # AUTH
        # -------------------------------------------------

        if not api_authorized(self):

            send_json(
                self,
                401,
                {
                    "ok": False,
                    "error": "Unauthorized"
                }
            )

            return

        # -------------------------------------------------
        # READ BODY
        # -------------------------------------------------

        try:

            content_length = int(
                self.headers.get(
                    "Content-Length",
                    "0"
                )
            )

            body = self.rfile.read(
                content_length
            )

            data = json.loads(
                body.decode("utf-8")
            )

        except Exception:

            send_json(
                self,
                400,
                {
                    "ok": False,
                    "error": "Invalid JSON"
                }
            )

            return

        # -------------------------------------------------
        # START BROADCAST
        # -------------------------------------------------

        if self.path == "/broadcast":

            text = data.get(
                "text"
            )

            if not isinstance(
                text,
                str
            ):

                send_json(
                    self,
                    400,
                    {
                        "ok": False,
                        "error": "text is required"
                    }
                )

                return

            text = text.strip()

            if not text:

                send_json(
                    self,
                    400,
                    {
                        "ok": False,
                        "error": "text is empty"
                    }
                )

                return

            if len(text) > 4096:

                send_json(
                    self,
                    400,
                    {
                        "ok": False,
                        "error": "text is too long"
                    }
                )

                return

            success = start_broadcast(
                text
            )

            if not success:

                send_json(
                    self,
                    409,
                    {
                        "ok": False,
                        "error": "Broadcast already running"
                    }
                )

                return

            send_json(
                self,
                200,
                {
                    "ok": True,
                    "message": "Broadcast started"
                }
            )

            return

        # -------------------------------------------------
        # STOP BROADCAST
        # -------------------------------------------------

        if self.path == "/broadcast/stop":

            success = stop_broadcast()

            if success:

                send_json(
                    self,
                    200,
                    {
                        "ok": True,
                        "message": "Stop requested"
                    }
                )

            else:

                send_json(
                    self,
                    409,
                    {
                        "ok": False,
                        "error": "No broadcast is running"
                    }
                )

            return

        send_json(
            self,
            404,
            {
                "ok": False,
                "error": "Not found"
            }
        )


# =========================================================
# START API SERVER
# =========================================================

def start_api_server():

    if not ADMIN_API_KEY:

        print(
            "WARNING: ADMIN_API_KEY is not set."
        )

        print(
            "Admin API will NOT be started."
        )

        return

    try:

        server = ThreadingHTTPServer(
            ("0.0.0.0", API_PORT),
            APIHandler
        )

        print(
            f"Admin API running on port "
            f"{API_PORT}"
        )

        thread = threading.Thread(
            target=server.serve_forever,
            daemon=True
        )

        thread.start()

    except Exception as e:

        print(
            f"API server error: {e}"
        )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update,
    context
):

    print(
        "BOT ERROR:",
        repr(context.error)
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN environment variable is not set."
        )

    # -----------------------------------------------------
    # DATABASE
    # -----------------------------------------------------

    init_db()

    # -----------------------------------------------------
    # API
    # -----------------------------------------------------

    start_api_server()

    # -----------------------------------------------------
    # TELEGRAM APPLICATION
    # -----------------------------------------------------

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # -----------------------------------------------------
    # HANDLERS
    # -----------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    application.add_error_handler(
        error_handler
    )

    print(
        "ربات روشن شد..."
    )

    # -----------------------------------------------------
    # POLLING
    # -----------------------------------------------------

    application.run_polling(
        drop_pending_updates=False
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
