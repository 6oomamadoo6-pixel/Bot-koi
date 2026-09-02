import os
import random
import string
import asyncio
from datetime import datetime

import psycopg2
from psycopg2 import OperationalError

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
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

DATABASE_URL = os.getenv("DATABASE_URL")


# =========================================================
# DATABASE
# =========================================================

def db():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set."
        )

    try:
        return psycopg2.connect(
            DATABASE_URL,
            connect_timeout=10
        )

    except OperationalError as e:
        print("PostgreSQL connection error:")
        print(repr(e))
        raise RuntimeError(
            "Could not connect to PostgreSQL. "
            "Check DATABASE_URL in Railway."
        ) from e


def init_db():
    conn = db()
    cur = conn.cursor()

    # -----------------------------------------------------
    # USERS
    # -----------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            link_code TEXT UNIQUE,
            anon_code TEXT UNIQUE,
            display_name TEXT,
            created_at TIMESTAMP
        )
    """)

    # -----------------------------------------------------
    # BLOCKS
    # -----------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS blocks (
            blocker_id BIGINT NOT NULL,
            blocked_id BIGINT NOT NULL,
            unblock_code TEXT UNIQUE,
            PRIMARY KEY (blocker_id, blocked_id)
        )
    """)

    # -----------------------------------------------------
    # ANONYMOUS MESSAGES
    # -----------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS anonymous_messages (
            id BIGSERIAL PRIMARY KEY,
            sender_id BIGINT NOT NULL,
            receiver_id BIGINT NOT NULL,
            message_text TEXT NOT NULL,
            created_at TIMESTAMP
        )
    """)

    # -----------------------------------------------------
    # MIGRATIONS
    # -----------------------------------------------------

    cur.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS display_name TEXT
    """)

    cur.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMP
    """)

    cur.execute("""
        ALTER TABLE blocks
        ADD COLUMN IF NOT EXISTS unblock_code TEXT
    """)

    cur.execute("""
        ALTER TABLE anonymous_messages
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMP
    """)

    conn.commit()

    cur.close()
    conn.close()

    fill_missing_unblock_codes()


# =========================================================
# CODE GENERATORS
# =========================================================

def generate_code(length=10):
    chars = string.ascii_letters + string.digits

    return "".join(
        random.choices(chars, k=length)
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
            """
            SELECT 1
            FROM users
            WHERE anon_code = %s
            """,
            (code,)
        )

        exists = cur.fetchone()

        cur.close()
        conn.close()

        if not exists:
            return code


def generate_unblock_code():
    while True:

        code = generate_code(10)

        conn = db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT 1
            FROM blocks
            WHERE unblock_code = %s
            """,
            (code,)
        )

        exists = cur.fetchone()

        cur.close()
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
            SET unblock_code = %s
            WHERE blocker_id = %s
            AND blocked_id = %s
        """, (
            code,
            blocker_id,
            blocked_id
        ))

    conn.commit()

    cur.close()
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
        WHERE user_id = %s
    """, (
        user_id,
    ))

    row = cur.fetchone()

    if row:

        cur.execute("""
            UPDATE users
            SET username = %s,
                full_name = %s
            WHERE user_id = %s
        """, (
            username,
            full_name,
            user_id
        ))

        conn.commit()

        cur.close()
        conn.close()

        return row[0], row[1]

    # -----------------------------------------------------
    # NEW USER
    # -----------------------------------------------------

    link_code = str(user_id)

    anon_code = generate_anon_code()

    display_name = full_name or "کاربر"

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
        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s
        )
    """, (
        user_id,
        username,
        full_name,
        link_code,
        anon_code,
        display_name,
        datetime.now()
    ))

    conn.commit()

    cur.close()
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
        WHERE user_id = %s
    """, (
        user_id,
    ))

    row = cur.fetchone()

    cur.close()
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
        WHERE link_code = %s
    """, (
        link_code,
    ))

    row = cur.fetchone()

    cur.close()
    conn.close()

    return row


def get_display_name(user_id):

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            display_name,
            full_name
        FROM users
        WHERE user_id = %s
    """, (
        user_id,
    ))

    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:
        return "کاربر"

    return (
        row[0]
        or row[1]
        or "کاربر"
    )


def set_display_name(
    user_id,
    name
):

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET display_name = %s
        WHERE user_id = %s
    """, (
        name,
        user_id
    ))

    conn.commit()

    cur.close()
    conn.close()


def get_all_user_ids():

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT user_id
        FROM users
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return [
        row[0]
        for row in rows
    ]


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
        VALUES (
            %s,
            %s,
            %s,
            %s
        )
        RETURNING id
    """, (
        sender_id,
        receiver_id,
        message_text,
        datetime.now()
    ))

    message_id = cur.fetchone()[0]

    conn.commit()

    cur.close()
    conn.close()

    return message_id


def get_anonymous_message(
    message_id
):

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
        WHERE id = %s
    """, (
        message_id,
    ))

    row = cur.fetchone()

    cur.close()
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
        WHERE blocker_id = %s
        AND blocked_id = %s
    """, (
        blocker_id,
        blocked_id
    ))

    result = cur.fetchone()

    cur.close()
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
        WHERE blocker_id = %s
        AND blocked_id = %s
    """, (
        blocker_id,
        blocked_id
    ))

    if cur.fetchone():

        cur.close()
        conn.close()

        return False

    unblock_code = generate_unblock_code()

    cur.execute("""
        INSERT INTO blocks (
            blocker_id,
            blocked_id,
            unblock_code
        )
        VALUES (
            %s,
            %s,
            %s
        )
    """, (
        blocker_id,
        blocked_id,
        unblock_code
    ))

    conn.commit()

    cur.close()
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
        WHERE blocker_id = %s
        AND unblock_code = %s
    """, (
        user_id,
        code
    ))

    row = cur.fetchone()

    if not row:

        cur.close()
        conn.close()

        return False

    cur.execute("""
        DELETE FROM blocks
        WHERE blocker_id = %s
        AND unblock_code = %s
    """, (
        user_id,
        code
    ))

    conn.commit()

    cur.close()
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
        WHERE blocks.blocker_id = %s
        ORDER BY blocks.unblock_code DESC
    """, (
        user_id,
    ))

    rows = cur.fetchall()

    cur.close()
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

def main_reply_keyboard():

    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(
                    "ارسال پیام ناشناس به کاربر دلخواه"
                )
            ]
        ],
        resize_keyboard=True
    )


def back_reply_keyboard():

    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(
                    "بازگشت 🔙"
                )
            ]
        ],
        resize_keyboard=True
    )


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

    if update.message:

        await update.message.reply_text(
            text,
            reply_markup=main_keyboard()
        )

        await update.message.reply_text(
            "منوی پایین:",
            reply_markup=main_reply_keyboard()
        )

    elif update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=main_keyboard()
        )

        await update.callback_query.message.reply_text(
            "منوی پایین:",
            reply_markup=main_reply_keyboard()
        )


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user or not update.message:
        return

    # ذخیره / بروزرسانی اطلاعات کاربر
    get_or_create_user(
        user.id,
        user.username,
        user.full_name
    )

    # -----------------------------------------------------
    # START PARAMETER
    # -----------------------------------------------------

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

        if target_id == user.id:

            bot = await context.bot.get_me()

            own_link = (
                f"https://t.me/{bot.username}"
                f"?start={user.id}"
            )

            await update.message.reply_text(
                "به خودت که نمیتونی پیام بفرستی عزیز 🥹\n\n"
                "ولی منتظر بمون و لینکتو بیشتر به اشتراک "
                "بزار و منتظر پیام ناشناست باش😍\n\n"
                f"لینک خودت :\n{own_link}",
                reply_markup=back_keyboard()
            )

            return

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

        await update.message.reply_text(
            f"شما در حال ارسال پیام ناشناس به "
            f"{target_name} هستید.\n\n"
            "پیام خود را بنویسید : 💤",
            reply_markup=cancel_keyboard()
        )

        return

    # -----------------------------------------------------
    # NORMAL START
    # -----------------------------------------------------

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
# BROADCAST
# =========================================================

async def broadcast_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user or user.id != ADMIN_ID:
        return

    context.user_data.clear()

    context.user_data["waiting_broadcast"] = True

    await update.message.reply_text(
        "📢 حالت ارسال پیام همگانی فعال شد.\n\n"
        "پیامی که می‌خوای برای همه کاربران ارسال بشه رو بفرست.\n\n"
        "برای لغو بنویس:\n"
        "/cancel"
    )


async def cancel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user or user.id != ADMIN_ID:
        return

    context.user_data.clear()

    await update.message.reply_text(
        "❌ عملیات لغو شد."
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

    await update.callback_query.edit_message_text(
        "🔗 لینک اختصاصی شما:\n\n"
        f"{link}\n\n"
        "لینک خود را با دیگران به اشتراک بگذارید "
        "تا بتوانند به صورت ناشناس برای شما پیام بفرستند.",
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

    await update.callback_query.edit_message_text(
        "⚙️ تنظیمات نام\n\n"
        f"نام فعلی شما:\n"
        f"{current_name}\n\n"
        "این نام هنگام پاسخ به پیام ناشناس "
        "به فرستنده نمایش داده می‌شود.",
        reply_markup=name_settings_keyboard()
    )


async def change_name(
    update,
    context
):

    context.user_data.clear()

    context.user_data["changing_name"] = True

    await update.callback_query.edit_message_text(
        "✏️ نام جدید خود را ارسال کنید.\n\n"
        "مثلاً:\n"
        "محمد\n"
        "Golden Chat\n"
        "کاربر ویژه 🤠",
        reply_markup=back_keyboard()
    )


# =========================================================
# ADS
# =========================================================

async def ads_page(
    update,
    context
):

    await update.callback_query.edit_message_text(
        "📢 تبلیغات فعال نیست.\n\n"
        "به زودی...",
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
            f"کاربر {anon_code} "
            "در لیست مسدودی شما است.\n"
            f"رفع مسدودی : "
            f"unblock_{unblock_code}/"
        )

        if index != len(rows) - 1:
            parts.append("____")

    parts.append(
        "\n\nدستور مربوط به کاربر را ارسال کنید "
        "تا رفع مسدودی انجام شود."
    )

    await update.callback_query.edit_message_text(
        "\n".join(parts),
        reply_markup=back_keyboard()
    )


# =========================================================
# HELP
# =========================================================

async def help_page(
    update,
    context
):

    await update.callback_query.edit_message_text(
        "🤔 راهنمای گلدن چت\n\n"
        "🔗 دریافت لینک ناشناس:\n"
        "لینک اختصاصی خودت را دریافت کن و "
        "برای دیگران بفرست.\n\n"
        "⚙️ تنظیمات نام:\n"
        "نامی که هنگام پاسخ به پیام ناشناس "
        "نمایش داده می‌شود را تغییر بده.\n\n"
        "🔴 لیست مسدودی:\n"
        "کاربرانی که بلاک کرده‌ای در این بخش هستند.\n\n"
        "📢 تبلیغات:\n"
        "این بخش در حال حاضر فعال نیست.",
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

    await query.answer()

    # -----------------------------------------------------
    # CHECK JOIN
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # BACK
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # CANCEL
    # -----------------------------------------------------

    if data == "cancel_send":

        context.user_data.clear()

        await query.edit_message_text(
            "❌ عملیات لغو شد.",
            reply_markup=back_keyboard()
        )

        return

    # -----------------------------------------------------
    # LINK
    # -----------------------------------------------------

    if data == "copy_link":

        await show_link(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # NAME
    # -----------------------------------------------------

    if data == "name_settings":

        await name_settings(
            update,
            context
        )

        return

    if data == "change_name":

        await change_name(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # ADS
    # -----------------------------------------------------

    if data == "ads":

        await ads_page(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # BLOCK LIST
    # -----------------------------------------------------

    if data == "block_list":

        await block_list_page(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # HELP
    # -----------------------------------------------------

    if data == "help":

        await help_page(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # REPLY
    # -----------------------------------------------------

    if data.startswith("reply:"):

        try:

            anonymous_message_id = int(
                data.split(":", 1)[1]
            )

        except (ValueError, IndexError):

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

    # -----------------------------------------------------
    # BLOCK
    # -----------------------------------------------------

    if data.startswith("block:"):

        try:

            blocked_id = int(
                data.split(":", 1)[1]
            )

        except (ValueError, IndexError):

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
    # BROADCAST
    # باید قبل از FORCE JOIN باشد
    # =====================================================

    if (
        context.user_data.get("waiting_broadcast")
        and user.id == ADMIN_ID
    ):

        users = get_all_user_ids()

        success = 0

        failed = 0

        status_msg = await message.reply_text(
            f"⏳ در حال ارسال پیام همگانی "
            f"به {len(users)} کاربر...\n"
            "لطفاً صبر کن."
        )

        for uid in users:

            try:

                await context.bot.send_message(
                    chat_id=uid,
                    text=text
                )

                success += 1

            except Exception as e:

                print(
                    f"Broadcast error {uid}: {e}"
                )

                failed += 1

            await asyncio.sleep(0.05)

        context.user_data.clear()

        await status_msg.edit_text(
            "✅ ارسال پیام همگانی تمام شد.\n\n"
            f"موفق: {success}\n"
            f"ناموفق: {failed}\n"
            f"کل کاربران: {len(users)}"
        )

        return

    # =====================================================
    # UNBLOCK
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
                "🟢 کاربر با موفقیت از لیست "
                "مسدودی شما خارج شد."
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
    # TARGET BUTTON
    # =====================================================

    if text == "ارسال پیام ناشناس به کاربر دلخواه":

        context.user_data.clear()

        context.user_data["waiting_target"] = True

        await message.reply_text(
            "آیدی کاربر یا آیدی عددی کاربر رو بفرست.\n\n"
            "در صورت عضو بودن در ربات میتونی "
            "به صورت ناشناس براش پیام ارسال کنی ⚡\n\n"
            "آیدی یا آیدی عددی کاربر رو بفرست :",
            reply_markup=back_reply_keyboard()
        )

        return

    # =====================================================
    # BACK
    # =====================================================

    if text == "بازگشت 🔙":

        context.user_data.clear()

        await send_main_panel(
            update,
            context
        )

        return

    # =====================================================
    # WAITING TARGET
    # =====================================================

    if context.user_data.get("waiting_target"):

        found = find_user_by_input(
            text
        )

        if not found:

            await message.reply_text(
                "کاربر توی ربات ما عضو نیست ❌\n"
                "پس نمیتونی براش پیام بفرستی."
            )

            return

        target_id = found[0]

        if target_id == user.id:

            await message.reply_text(
                "نمی تونی به خودت پیام بفرستی."
            )

            return

        if is_blocked(
            target_id,
            user.id
        ):

            await message.reply_text(
                "❌ شما توسط این کاربر بلاک شده‌اید."
            )

            context.user_data.clear()

            return

        context.user_data.clear()

        context.user_data["target_id"] = target_id

        context.user_data["sending_anonymous"] = True

        await message.reply_text(
            "کاربر توی ربات عضو هست. ✅\n"
            "حالا پیامت رو بنویس تا براش بفرستم :",
            reply_markup=cancel_keyboard()
        )

        return

    # =====================================================
    # CHANGE NAME
    # =====================================================

    if context.user_data.get("changing_name"):

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
    # REPLY
    # =====================================================

    if context.user_data.get("replying"):

        anonymous_message_id = (
            context.user_data.get(
                "reply_message_id"
            )
        )

        sender_id = (
            context.user_data.get(
                "reply_sender_id"
            )
        )

        if not anonymous_message_id or not sender_id:

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

        if (
            receiver_id != user.id
            or original_sender_id != sender_id
        ):

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
            "به پیام شما پاسخ داد. 🤠\n\n"
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
    # SEND ANONYMOUS
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

        anon_code = (
            row[4]
            if row
            else "0000000"
        )

        keyboard = anonymous_message_keyboard(
            anonymous_message_id,
            user.id
        )

        try:

            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    f"کاربر {anon_code} "
                    "برای شما پیام ناشناسی ارسال کرد :\n\n"
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
            "BOT_TOKEN environment variable "
            "is not set."
        )

    if not DATABASE_URL:

        raise RuntimeError(
            "DATABASE_URL environment variable "
            "is not set."
        )

    print(
        "Connecting to PostgreSQL..."
    )

    init_db()

    print(
        "PostgreSQL connected successfully."
    )

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "broadcast",
            broadcast_command
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel_command
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT,
            handle_message
        )
    )

    application.add_error_handler(
        error_handler
    )

    print(
        "ربات روشن شد..."
    )

    application.run_polling(
        drop_pending_updates=False
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
