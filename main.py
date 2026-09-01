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


# =========================================================
# SETTINGS
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

ADMIN_ID = 6078875175

CHANNEL = "@hidemychatRobot0"

CHANNEL_URL = "https://t.me/hidemychatRobot0"


# =========================================================
# DATABASE
# =========================================================

DB_NAME = "bot.db"


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():

    conn = get_connection()
    c = conn.cursor()

    # -------------------------
    # Users
    # -------------------------

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            link_code TEXT UNIQUE,
            anon_code TEXT UNIQUE,
            created_at TEXT
        )
    """)

    # -------------------------
    # Blocks
    # -------------------------

    c.execute("""
        CREATE TABLE IF NOT EXISTS blocks (
            blocker_id INTEGER NOT NULL,
            blocked_id INTEGER NOT NULL,
            unblock_code TEXT UNIQUE,
            PRIMARY KEY (blocker_id, blocked_id)
        )
    """)

    # -------------------------
    # Migration for old DB
    # -------------------------

    c.execute("PRAGMA table_info(blocks)")
    columns = [row[1] for row in c.fetchall()]

    if "unblock_code" not in columns:

        c.execute(
            "ALTER TABLE blocks ADD COLUMN unblock_code TEXT"
        )

        c.execute("""
            SELECT blocker_id, blocked_id
            FROM blocks
            WHERE unblock_code IS NULL
        """)

        old_blocks = c.fetchall()

        for blocker_id, blocked_id in old_blocks:

            code = generate_unblock_code()

            while True:

                c.execute("""
                    SELECT 1
                    FROM blocks
                    WHERE unblock_code = ?
                """, (code,))

                if not c.fetchone():
                    break

                code = generate_unblock_code()

            c.execute("""
                UPDATE blocks
                SET unblock_code = ?
                WHERE blocker_id = ?
                AND blocked_id = ?
            """, (
                code,
                blocker_id,
                blocked_id
            ))

    conn.commit()
    conn.close()


# =========================================================
# RANDOM CODES
# =========================================================

def generate_anon_code():

    return "".join(
        random.choices(
            string.digits,
            k=7
        )
    )


def generate_unblock_code():

    chars = string.ascii_letters + string.digits

    return "".join(
        random.choices(
            chars,
            k=10
        )
    )


# =========================================================
# USER SYSTEM
# =========================================================

def get_or_create_user(
    user_id,
    username,
    full_name
):

    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        SELECT link_code, anon_code
        FROM users
        WHERE user_id = ?
    """, (user_id,))

    row = c.fetchone()

    if row:

        # Update username/name if changed
        c.execute("""
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

    # User ID is used as private link code
    link_code = str(user_id)

    # Generate unique anonymous code
    while True:

        anon_code = generate_anon_code()

        c.execute("""
            SELECT 1
            FROM users
            WHERE anon_code = ?
        """, (anon_code,))

        if not c.fetchone():
            break

    c.execute("""
        INSERT INTO users (
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


def get_anon_code(user_id):

    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        SELECT anon_code
        FROM users
        WHERE user_id = ?
    """, (user_id,))

    row = c.fetchone()

    conn.close()

    if row:
        return row[0]

    return "0000000"


# =========================================================
# BLOCK SYSTEM
# =========================================================

def is_blocked(
    blocker_id,
    blocked_id
):

    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        SELECT 1
        FROM blocks
        WHERE blocker_id = ?
        AND blocked_id = ?
    """, (
        blocker_id,
        blocked_id
    ))

    result = c.fetchone()

    conn.close()

    return result is not None


def block_user(
    blocker_id,
    blocked_id
):

    conn = get_connection()
    c = conn.cursor()

    # Already blocked?
    c.execute("""
        SELECT unblock_code
        FROM blocks
        WHERE blocker_id = ?
        AND blocked_id = ?
    """, (
        blocker_id,
        blocked_id
    ))

    existing = c.fetchone()

    if existing:

        conn.close()

        return existing[0]

    # Generate unique unblock code
    while True:

        unblock_code = generate_unblock_code()

        c.execute("""
            SELECT 1
            FROM blocks
            WHERE unblock_code = ?
        """, (unblock_code,))

        if not c.fetchone():
            break

    c.execute("""
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

    return unblock_code


def unblock_user(
    blocker_id,
    unblock_code
):

    conn = get_connection()
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

    conn = get_connection()
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
        ORDER BY blocks.blocked_id DESC
    """, (blocker_id,))

    rows = c.fetchall()

    conn.close()

    return rows


# =========================================================
# MEMBERSHIP
# =========================================================

async def is_member(
    bot,
    user_id
):

    try:

        member = await bot.get_chat_member(
            chat_id=CHANNEL,
            user_id=user_id
        )

        return member.status in (
            ChatMember.MEMBER,
            ChatMember.ADMINISTRATOR,
            ChatMember.OWNER
        )

    except TelegramError:

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
                "کانال اجباری",
                url=CHANNEL_URL
            )
        ],
        [
            InlineKeyboardButton(
                "جوین شدم✅",
                callback_data="check_join"
            )
        ]
    ])


# =========================================================
# JOIN MESSAGE
# =========================================================

async def send_join_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = (
        "درود و عرض ادب! 👋\n"
        "خوش اومدی 🌹\n\n"
        "برای ادامه استفاده از ربات، "
        "لطفاً ابتدا در کانال زیر عضو شو."
    )

    markup = join_keyboard()

    if update.message:

        await update.message.reply_text(
            text,
            reply_markup=markup
        )

    elif update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=markup
        )


# =========================================================
# MAIN PANEL
# =========================================================

async def send_main_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

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
                url=CHANNEL_URL
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
        "میتونی با پنل شیشه‌ای زیر "
        "از قابلیت‌های ربات ما استفاده کنی:"
    )

    markup = InlineKeyboardMarkup(keyboard)

    if update.message:

        await update.message.reply_text(
            text,
            reply_markup=markup
        )

    elif update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=markup
        )


# =========================================================
# /START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    link_code, anon_code = get_or_create_user(
        user.id,
        user.username,
        user.full_name
    )

    # -----------------------------------------------------
    # Someone opened an anonymous link
    # -----------------------------------------------------

    if context.args:

        if not await is_member(
            context.bot,
            user.id
        ):

            await send_join_message(
                update,
                context
            )

            return

        target_code = context.args[0].strip()

        conn = get_connection()
        c = conn.cursor()

        c.execute("""
            SELECT user_id
            FROM users
            WHERE link_code = ?
        """, (target_code,))

        target = c.fetchone()

        conn.close()

        # Invalid link
        if not target:

            await update.message.reply_text(
                "❌ لینک نامعتبر است.",
                reply_markup=back_keyboard()
            )

            return

        target_id = target[0]

        # -------------------------------------------------
        # User opened his own link
        # -------------------------------------------------

        if target_id == user.id:

            bot_username = (
                await context.bot.get_me()
            ).username

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

        # -------------------------------------------------
        # Check if target blocked sender
        # -------------------------------------------------

        if is_blocked(
            target_id,
            user.id
        ):

            await update.message.reply_text(
                "❌ شما توسط این کاربر بلاک شده‌اید.",
                reply_markup=back_keyboard()
            )

            return

        # -------------------------------------------------
        # Start anonymous message
        # -------------------------------------------------

        context.user_data.clear()

        context.user_data["target_id"] = target_id

        await update.message.reply_text(
            "شما در حال ارسال پیام ناشناس هستید. 🕵️\n\n"
            "پیام خود را بنویسید:",
            reply_markup=ForceReply(
                selective=True
            )
        )

        return

    # -----------------------------------------------------
    # Normal /start
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
# MESSAGE HANDLER
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    user = update.effective_user

    text = update.message.text.strip()

    # =====================================================
    # UNBLOCK COMMAND
    # Supports:
    # unblock_xxxxxxxxxx
    # /unblock_xxxxxxxxxx
    # =====================================================

    clean_text = text

    if clean_text.startswith("/"):
        clean_text = clean_text[1:]

    if clean_text.startswith("unblock_"):

        unblock_code = clean_text[
            len("unblock_"):
        ].strip()

        if unblock_user(
            user.id,
            unblock_code
        ):

            await update.message.reply_text(
                "✅ کاربر با موفقیت از لیست "
                "مسدودی شما حذف شد.",
                reply_markup=back_keyboard()
            )

        else:

            await update.message.reply_text(
                "❌ کد رفع مسدودی نامعتبر است.",
                reply_markup=back_keyboard()
            )

        return

    # =====================================================
    # MEMBERSHIP
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
    # SEND ANONYMOUS MESSAGE
    # =====================================================

    if "target_id" in context.user_data:

        target_id = context.user_data[
            "target_id"
        ]

        # Check block
        if is_blocked(
            target_id,
            user.id
        ):

            await update.message.reply_text(
                "❌ شما توسط این کاربر بلاک شده‌اید.",
                reply_markup=back_keyboard()
            )

            context.user_data.clear()

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
                    "برای شما پیام ناشناسی ارسال کرد:\n\n"
                    f"{text}"
                ),
                reply_markup=keyboard
            )

            await update.message.reply_text(
                "✅ پیام ناشناس با موفقیت ارسال شد.",
                reply_markup=back_keyboard()
            )

        except TelegramError:

            await update.message.reply_text(
                "❌ خطا در ارسال پیام.",
                reply_markup=back_keyboard()
            )

        context.user_data.clear()

        return

    # =====================================================
    # ANONYMOUS REPLY
    # =====================================================

    if "reply_to" in context.user_data:

        target_id = context.user_data[
            "reply_to"
        ]

        # If target blocked the sender
        if is_blocked(
            target_id,
            user.id
        ):

            await update.message.reply_text(
                "❌ ارسال پاسخ ممکن نیست.",
                reply_markup=back_keyboard()
            )

            context.user_data.clear()

            return

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

        except TelegramError:

            await update.message.reply_text(
                "❌ خطا در ارسال پاسخ.",
                reply_markup=back_keyboard()
            )

        context.user_data.clear()

        return


# =========================================================
# CALLBACK BUTTONS
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    data = query.data

    user_id = query.from_user.id

    await query.answer()

    # =====================================================
    # BACK
    # =====================================================

    if data == "back_main":

        context.user_data.clear()

        await send_main_panel(
            update,
            context
        )

        return

    # =====================================================
    # CHECK JOIN
    # =====================================================

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

        return

    # =====================================================
    # COPY LINK
    # =======================
