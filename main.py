import os
import random
import string
import asyncio
import html
from datetime import datetime, timedelta

import psycopg2
from psycopg2 import pool

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


# =========================================================
# POSTGRESQL
# =========================================================

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set."
    )


DB_POOL = None


def create_db_pool():
    global DB_POOL

    if DB_POOL is not None:
        return

    DB_POOL = psycopg2.pool.SimpleConnectionPool(
        1,
        10,
        dsn=DATABASE_URL
    )


def db():
    global DB_POOL

    if DB_POOL is None:
        create_db_pool()

    return DB_POOL.getconn()


def release_db(conn):
    if DB_POOL is not None and conn is not None:
        DB_POOL.putconn(conn)


# =========================================================
# DATABASE INIT
# =========================================================

def init_db():

    conn = db()

    try:
        cur = conn.cursor()

        # =================================================
        # USERS
        # =================================================

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                link_code TEXT UNIQUE,
                anon_code TEXT UNIQUE,
                display_name TEXT,
                created_at TIMESTAMP,
                ban_code TEXT UNIQUE,
                ban_until TIMESTAMP,
                ban_reason TEXT
            )
        """)

        # =================================================
        # BLOCKS
        # =================================================

        cur.execute("""
            CREATE TABLE IF NOT EXISTS blocks (
                blocker_id BIGINT NOT NULL,
                blocked_id BIGINT NOT NULL,
                unblock_code TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (blocker_id, blocked_id)
            )
        """)

        # =================================================
        # ANONYMOUS MESSAGES
        # =================================================

        cur.execute("""
            CREATE TABLE IF NOT EXISTS anonymous_messages (
                id BIGSERIAL PRIMARY KEY,
                sender_id BIGINT NOT NULL,
                receiver_id BIGINT NOT NULL,
                message_text TEXT NOT NULL,
                created_at TIMESTAMP,
                seen_at TIMESTAMP
            )
        """)

        # =================================================
        # REACTIONS
        # =================================================

        cur.execute("""
            CREATE TABLE IF NOT EXISTS message_reactions (
                id BIGSERIAL PRIMARY KEY,
                message_id BIGINT NOT NULL,
                reactor_id BIGINT NOT NULL,
                reaction TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(message_id, reactor_id)
            )
        """)

        # =================================================
        # SAFE MIGRATIONS
        # =================================================

        cur.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS display_name TEXT
        """)

        cur.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS created_at TIMESTAMP
        """)

        cur.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS ban_code TEXT
        """)

        cur.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS ban_until TIMESTAMP
        """)

        cur.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS ban_reason TEXT
        """)

        cur.execute("""
            ALTER TABLE blocks
            ADD COLUMN IF NOT EXISTS unblock_code TEXT
        """)

        cur.execute("""
            ALTER TABLE blocks
            ADD COLUMN IF NOT EXISTS created_at
            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """)

        cur.execute("""
            ALTER TABLE anonymous_messages
            ADD COLUMN IF NOT EXISTS seen_at TIMESTAMP
        """)

        # =================================================
        # INDEXES
        # =================================================

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_username
            ON users(username)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_link_code
            ON users(link_code)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_anon_code
            ON users(anon_code)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_receiver
            ON anonymous_messages(receiver_id)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_sender
            ON anonymous_messages(sender_id)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_created
            ON anonymous_messages(created_at)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_reactions_message
            ON message_reactions(message_id)
        """)

        conn.commit()

    finally:
        cur.close()
        release_db(conn)

    fill_missing_codes()


# =========================================================
# CODE GENERATORS
# =========================================================

def generate_code(length=8):

    chars = string.ascii_lowercase + string.digits

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

        try:
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

        finally:
            cur.close()
            release_db(conn)

        if not exists:
            return code


def generate_unblock_code():

    while True:

        code = generate_code(8)

        conn = db()

        try:
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

        finally:
            cur.close()
            release_db(conn)

        if not exists:
            return code


def generate_ban_code():

    while True:

        code = generate_code(8)

        conn = db()

        try:
            cur = conn.cursor()

            cur.execute(
                """
                SELECT 1
                FROM users
                WHERE ban_code = %s
                """,
                (code,)
            )

            exists = cur.fetchone()

        finally:
            cur.close()
            release_db(conn)

        if not exists:
            return code


# =========================================================
# FILL MISSING CODES
# =========================================================

def fill_missing_codes():

    conn = db()

    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT user_id
            FROM users
            WHERE ban_code IS NULL
               OR ban_code = ''
        """)

        rows = cur.fetchall()

    finally:
        cur.close()
        release_db(conn)

    for row in rows:

        user_id = row[0]
        code = generate_ban_code()

        conn = db()

        try:
            cur = conn.cursor()

            cur.execute(
                """
                UPDATE users
                SET ban_code = %s
                WHERE user_id = %s
                """,
                (
                    code,
                    user_id
                )
            )

            conn.commit()

        finally:
            cur.close()
            release_db(conn)

    conn = db()

    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT blocker_id, blocked_id
            FROM blocks
            WHERE unblock_code IS NULL
               OR unblock_code = ''
        """)

        rows = cur.fetchall()

    finally:
        cur.close()
        release_db(conn)

    for blocker_id, blocked_id in rows:

        code = generate_unblock_code()

        conn = db()

        try:
            cur = conn.cursor()

            cur.execute(
                """
                UPDATE blocks
                SET unblock_code = %s
                WHERE blocker_id = %s
                  AND blocked_id = %s
                """,
                (
                    code,
                    blocker_id,
                    blocked_id
                )
            )

            conn.commit()

        finally:
            cur.close()
            release_db(conn)


# =========================================================
# USERS
# =========================================================

def get_or_create_user(
    user_id,
    username,
    full_name
):

    conn = db()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                link_code,
                anon_code,
                ban_code
            FROM users
            WHERE user_id = %s
            """,
            (user_id,)
        )

        row = cur.fetchone()

        if row:

            link_code = row[0]
            anon_code = row[1]
            ban_code = row[2]

            if not ban_code:
                ban_code = generate_ban_code()

            cur.execute(
                """
                UPDATE users
                SET username = %s,
                    full_name = %s,
                    ban_code = %s
                WHERE user_id = %s
                """,
                (
                    username,
                    full_name,
                    ban_code,
                    user_id
                )
            )

            conn.commit()

            return link_code, anon_code

        link_code = str(user_id)
        anon_code = generate_anon_code()
        ban_code = generate_ban_code()

        cur.execute(
            """
            INSERT INTO users (
                user_id,
                username,
                full_name,
                link_code,
                anon_code,
                display_name,
                created_at,
                ban_code,
                ban_until,
                ban_reason
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            """,
            (
                user_id,
                username,
                full_name,
                link_code,
                anon_code,
                full_name or "کاربر",
                datetime.now(),
                ban_code,
                None,
                None
            )
        )

        conn.commit()

        return link_code, anon_code

    finally:
        cur.close()
        release_db(conn)


def get_user(user_id):

    conn = db()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                user_id,
                username,
                full_name,
                link_code,
                anon_code,
                display_name,
                ban_code,
                ban_until,
                ban_reason
            FROM users
            WHERE user_id = %s
            """,
            (user_id,)
        )

        return cur.fetchone()

    finally:
        cur.close()
        release_db(conn)


def get_user_by_link(link_code):

    conn = db()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                user_id,
                full_name,
                display_name,
                anon_code
            FROM users
            WHERE link_code = %s
            """,
            (link_code,)
        )

        return cur.fetchone()

    finally:
        cur.close()
        release_db(conn)


def get_display_name(user_id):

    conn = db()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                display_name,
                full_name
            FROM users
            WHERE user_id = %s
            """,
            (user_id,)
        )

        row = cur.fetchone()

    finally:
        cur.close()
        release_db(conn)

    if not row:
        return "کاربر"

    return row[0] or row[1] or "کاربر"


def set_display_name(
    user_id,
    name
):

    conn = db()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            UPDATE users
            SET display_name = %s
            WHERE user_id = %s
            """,
            (
                name,
                user_id
            )
        )

        conn.commit()

    finally:
        cur.close()
        release_db(conn)


def get_all_user_ids():

    conn = db()

    try:

        cur = conn.cursor()

        cur.execute("""
            SELECT user_id
            FROM users
            ORDER BY user_id
        """)

        rows = cur.fetchall()

    finally:
        cur.close()
        release_db(conn)

    return [
        row[0]
        for row in rows
    ]


def get_all_users():

    conn = db()

    try:

        cur = conn.cursor()

        cur.execute("""
            SELECT
                user_id,
                username,
                full_name,
                anon_code,
                display_name,
                ban_code
            FROM users
            ORDER BY created_at ASC, user_id ASC
        """)

        return cur.fetchall()

    finally:
        cur.close()
        release_db(conn)


# =========================================================
# FIND USER
# =========================================================

def find_user_by_input(text):

    text = text.strip()

    conn = db()

    try:

        cur = conn.cursor()

        if text.isdigit():

            cur.execute(
                """
                SELECT
                    user_id,
                    full_name,
                    display_name
                FROM users
                WHERE user_id = %s
                """,
                (int(text),)
            )

            row = cur.fetchone()

            if row:
                return row

        username = text.lstrip("@").lower()

        cur.execute(
            """
            SELECT
                user_id,
                full_name,
                display_name
            FROM users
            WHERE lower(username) = %s
            """,
            (username,)
        )

        return cur.fetchone()

    finally:
        cur.close()
        release_db(conn)


# =========================================================
# BAN SYSTEM
# =========================================================

def get_ban_code(user_id):

    conn = db()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT ban_code
            FROM users
            WHERE user_id = %s
            """,
            (user_id,)
        )

        row = cur.fetchone()

    finally:
        cur.close()
        release_db(conn)

    if not row:
        return None

    if row[0]:
        return row[0]

    code = generate_ban_code()

    conn = db()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            UPDATE users
            SET ban_code = %s
            WHERE user_id = %s
            """,
            (
                code,
                user_id
            )
        )

        conn.commit()

    finally:
        cur.close()
        release_db(conn)

    return code


def ban_user_by_code(
    code,
    reason
):

    code = code.strip().lower()

    conn = db()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT user_id
            FROM users
            WHERE lower(ban_code) = %s
            """,
            (code,)
        )

        row = cur.fetchone()

        if not row:
            return None

        user_id = row[0]

        ban_until = datetime.now() + timedelta(days=1)

        cur.execute(
            """
            UPDATE users
            SET ban_until = %s,
                ban_reason = %s
            WHERE user_id = %s
            """,
            (
                ban_until,
                reason,
                user_id
            )
        )

        conn.commit()

        return user_id

    finally:
        cur.close()
        release_db(conn)


def unban_user_by_code(code):

    code = code.strip().lower()

    conn = db()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT user_id
            FROM users
            WHERE lower(ban_code) = %s
            """,
            (code,)
        )

        row = cur.fetchone()

        if not row:
            return None

        user_id = row[0]

        cur.execute(
            """
            UPDATE users
            SET ban_until = NULL,
                ban_reason = NULL
            WHERE user_id = %s
            """,
            (user_id,)
        )

        conn.commit()

        return user_id

    finally:
        cur.close()
        release_db(conn)


def get_ban_info(user_id):

    conn = db()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                ban_until,
                ban_reason
            FROM users
            WHERE user_id = %s
            """,
            (user_id,)
        )

        row = cur.fetchone()

    finally:
        cur.close()
        release_db(conn)

    if not row or not row[0]:
        return None

    ban_until = row[0]

    if isinstance(ban_until, str):

        try:
            ban_until = datetime.fromisoformat(
                ban_until
            )
        except ValueError:
            return None

    if datetime.now() >= ban_until:

        conn = db()

        try:

            cur = conn.cursor()

            cur.execute(
                """
                UPDATE users
                SET ban_until = NULL,
                    ban_reason = NULL
                WHERE user_id = %s
                """,
                (user_id,)
            )

            conn.commit()

        finally:
            cur.close()
            release_db(conn)

        return None

    return {
        "until": ban_until,
        "reason": row[1] or "توسط مدیریت ربات"
    }


def get_active_banned_users():

    conn = db()

    try:

        cur = conn.cursor()

        cur.execute("""
            SELECT
                user_id,
                username,
                ban_code,
                ban_until,
                ban_reason
            FROM users
            WHERE ban_until IS NOT NULL
              AND ban_until > CURRENT_TIMESTAMP
            ORDER BY ban_until ASC
        """)

        return cur.fetchall()

    finally:
        cur.close()
        release_db(conn)


async def expire_bans_loop():

    while True:

        try:

            conn = db()

            try:

                cur = conn.cursor()

                cur.execute("""
                    UPDATE users
                    SET ban_until = NULL,
                        ban_reason = NULL
                    WHERE ban_until IS NOT NULL
                      AND ban_until <= CURRENT_TIMESTAMP
                """)

                conn.commit()

            finally:
                cur.close()
                release_db(conn)

        except Exception as e:

            print(
                f"Ban expiration error: {e}"
            )

        await asyncio.sleep(30)


async def post_init(application):

    application.bot_data[
        "ban_expiration_task"
    ] = asyncio.create_task(
        expire_bans_loop()
    )


async def post_shutdown(application):

    task = application.bot_data.get(
        "ban_expiration_task"
    )

    if task:

        task.cancel()

        try:
            await task

        except asyncio.CancelledError:
            pass

    global DB_POOL

    if DB_POOL is not None:

        DB_POOL.closeall()

        DB_POOL = None


# =========================================================
# ANONYMOUS MESSAGES
# =========================================================

def save_anonymous_message(
    sender_id,
    receiver_id,
    message_text
):

    conn = db()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO anonymous_messages (
                sender_id,
                receiver_id,
                message_text,
                created_at,
                seen_at
            )
            VALUES (
                %s, %s, %s, %s, %s
            )
            RETURNING id
            """,
            (
                sender_id,
                receiver_id,
                message_text,
                datetime.now(),
                None
            )
        )

        message_id = cur.fetchone()[0]

        conn.commit()

        return message_id

    finally:
        cur.close()
        release_db(conn)


def get_anonymous_message(message_id):

    conn = db()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                id,
                sender_id,
                receiver_id,
                message_text,
                created_at,
                seen_at
            FROM anonymous_messages
            WHERE id = %s
            """,
            (message_id,)
        )

        return cur.fetchone()

    finally:
        cur.close()
        release_db(conn)


def mark_message_as_seen(
    message_id,
    receiver_id
):

    conn = db()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            UPDATE anonymous_messages
            SET seen_at = CURRENT_TIMESTAMP
            WHERE id = %s
              AND receiver_id = %s
              AND seen_at IS NULL
            RETURNING id
            """,
            (
                message_id,
                receiver_id
            )
        )

        row = cur.fetchone()

        conn.commit()

        return row is not None

    finally:
        cur.close()
        release_db(conn)


# =========================================================
# REACTION SYSTEM
# =========================================================

REACTIONS = [
    "😂",
    "😭",
    "❤️",
    "😍",
    "❤️‍🔥",
    "😉",
    "👎🏻",
    "👍🏻",
]


def save_reaction(
    message_id,
    reactor_id,
    reaction
):

    conn = db()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO message_reactions (
                message_id,
                reactor_id,
                reaction
            )
            VALUES (
                %s, %s, %s
            )
            ON CONFLICT (
                message_id,
                reactor_id
            )
            DO NOTHING
            RETURNING id
            """,
            (
                message_id,
                reactor_id,
                reaction
            )
        )

        row = cur.fetchone()

        conn.commit()

        return row is not None

    finally:
        cur.close()
        release_db(conn)


def has_reaction(
    message_id,
    reactor_id
):

    conn = db()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT reaction
            FROM message_reactions
            WHERE message_id = %s
              AND reactor_id = %s
            """,
            (
                message_id,
                reactor_id
            )
        )

        row = cur.fetchone()

        return row[0] if row else None

    finally:
        cur.close()
        release_db(conn)


# =========================================================
# BLOCK SYSTEM
# =========================================================

def is_blocked(
    blocker_id,
    blocked_id
):

    conn = db()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT 1
            FROM blocks
            WHERE blocker_id = %s
              AND blocked_id = %s
            """,
            (
                blocker_id,
                blocked_id
            )
        )

        return cur.fetchone() is not None

    finally:
        cur.close()
        release_db(conn)


def block_user(
    blocker_id,
    blocked_id
):

    if blocker_id == blocked_id:
        return False

    if is_blocked(
        blocker_id,
        blocked_id
    ):
        return False

    unblock_code = generate_unblock_code()

    conn = db()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO blocks (
                blocker_id,
                blocked_id,
                unblock_code,
                created_at
            )
            VALUES (
                %s, %s, %s, %s
            )
            ON CONFLICT (
                blocker_id,
                blocked_id
            )
            DO NOTHING
            """,
            (
                blocker_id,
                blocked_id,
                unblock_code,
                datetime.now()
            )
        )

        conn.commit()

        return cur.rowcount > 0

    finally:
        cur.close()
        release_db(conn)


def unblock_by_code(
    user_id,
    code
):

    code = code.strip().lower()

    conn = db()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM blocks
            WHERE blocker_id = %s
              AND lower(unblock_code) = %s
            RETURNING blocked_id
            """,
            (
                user_id,
                code
            )
        )

        row = cur.fetchone()

        conn.commit()

        return row is not None

    finally:
        cur.close()
        release_db(conn)


def get_block_list(user_id):

    conn = db()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                users.anon_code,
                blocks.unblock_code
            FROM blocks
            JOIN users
              ON users.user_id = blocks.blocked_id
            WHERE blocks.blocker_id = %s
            ORDER BY blocks.created_at DESC
            """,
            (user_id,)
        )

        return cur.fetchall()

    finally:
        cur.close()
        release_db(conn)


# =========================================================
# CHANNEL MEMBERSHIP
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
            ChatMember.OWNER
        )

    except TelegramError as e:

        print(
            f"Membership error {channel} / {user_id}: {e}"
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
        [[
            KeyboardButton(
                "ارسال پیام ناشناس به کاربر دلخواه"
            )
        ]],
        resize_keyboard=True
    )


def back_reply_keyboard():

    return ReplyKeyboardMarkup(
        [[
            KeyboardButton(
                "بازگشت 🔙"
            )
        ]],
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
                callback_data="check_join",
                style="success"
            )
        ]
    ])


def back_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "بازگشت 🔙",
                callback_data="back_main",
                style="danger"
            )
        ]
    ])


def cancel_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "لغو ارسال پیام ❌",
                callback_data="cancel_send",
                style="danger"
            )
        ]
    ])


def main_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "دریافت لینک اختصاصی 🔗",
                callback_data="copy_link",
                style="success"
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
                callback_data="block_list",
                style="danger"
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
                callback_data="back_main",
                style="danger"
            )
        ]
    ])


# =========================================================
# ANONYMOUS MESSAGE KEYBOARD
# =========================================================

def anonymous_message_keyboard(
    message_id,
    sender_id,
    include_reaction=True,
    include_seen=True
):

    buttons = []

    buttons.append([
        InlineKeyboardButton(
            "پاسخ 🗨️",
            callback_data=f"reply:{message_id}",
            style="success"
        ),
        InlineKeyboardButton(
            "بلاک 🛑",
            callback_data=f"block:{sender_id}",
            style="danger"
        )
    ])

    if include_seen:

        buttons.append([
            InlineKeyboardButton(
                "مشاهده شد 👁️",
                callback_data=f"seen:{message_id}",
                style="success"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "گزارش تخلف کاربر 🚨",
            callback_data=f"report:{message_id}",
            style="danger"
        )
    ])

    if include_reaction:

        buttons.append([
            InlineKeyboardButton(
                "ری اکشن :)",
                callback_data=f"reaction:{message_id}",
                style="success"
            )
        ])

    return InlineKeyboardMarkup(buttons)


# =========================================================
# REACTION KEYBOARD
# =========================================================

def reaction_keyboard(message_id):

    buttons = []

    row = []

    for index, reaction in enumerate(REACTIONS):

        row.append(
            InlineKeyboardButton(
                reaction,
                callback_data=f"react:{message_id}:{index}"
            )
        )

        if len(row) == 4:

            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton(
            "بازگشت 🔙",
            callback_data=f"reaction_back:{message_id}",
            style="danger"
        )
    ])

    return InlineKeyboardMarkup(buttons)


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
        "برای ادامه استفاده از ربات زحمت بکش "
        "توی کانال‌های زیر جوین شو."
    )

    keyboard = join_keyboard()

    if update.message:

        await update.message.reply_text(
            text,
            reply_markup=keyboard
        )

    elif update.callback_query:

        await update.callback_query.message.reply_text(
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
        "<b>درود! به پنل اصلی ربات "
        "\" گلدن چت \" خوش آمدید.⚡</b>\n\n"
        "<b>خوشحالم که ما انتخاب شما بودیم😉</b>\n\n"
        "<b>برای استفاده از ربات از پنل شیشه ای زیر "
        "استفاده کنید :</b>"
    )

    if update.message:

        await update.message.reply_text(
            text,
            reply_markup=main_keyboard(),
            parse_mode="HTML"
        )

        await update.message.reply_text(
            "برای ارسال پیام ناشناس به کاربر دلخواه "
            "از دکمه زیر استفاده کنید 👇🏻",
            reply_markup=main_reply_keyboard()
        )

    elif update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=main_keyboard(),
            parse_mode="HTML"
        )

        await update.callback_query.message.reply_text(
            "برای ارسال پیام ناشناس به کاربر دلخواه "
            "از دکمه زیر استفاده کنید 👇🏻",
            reply_markup=main_reply_keyboard()
        )


# =========================================================
# USERBOT
# =========================================================

def userbot_keyboard(page, total_pages):

    buttons = []

    navigation = []

    if page > 0:

        navigation.append(
            InlineKeyboardButton(
                "قبلی ◀️",
                callback_data=f"userbot_page:{page - 1}"
            )
        )

    if page < total_pages - 1:

        navigation.append(
            InlineKeyboardButton(
                "بعدی ▶️",
                callback_data=f"userbot_page:{page + 1}"
            )
        )

    if navigation:
        buttons.append(navigation)

    return InlineKeyboardMarkup(buttons)


def build_userbot_page(page):

    users = get_all_users()

    per_page = 5

    total = len(users)

    if total == 0:

        return (
            "📋 هیچ کاربری در ربات ثبت نشده است.",
            None,
            0
        )

    total_pages = (
        (total + per_page - 1)
        // per_page
    )

    page = max(
        0,
        min(page, total_pages - 1)
    )

    start = page * per_page
    end = start + per_page

    page_users = users[start:end]

    parts = []

    for row in page_users:

        user_id = row[0]
        username = row[1]
        full_name = row[2]
        anon_code = row[3]
        display_name = row[4]
        ban_code = row[5]

        if username:

            identifier = f"@{username}"

        else:

            identifier = str(user_id)

        display_name = (
            display_name
            or full_name
            or "کاربر"
        )

        ban_code = (
            ban_code
            or get_ban_code(user_id)
        )

        parts.append(
            f"کاربر : {identifier}\n"
            f"اسم در ربات : {display_name}\n"
            f"کد بن و رفع بن : "
            f"/ban_{ban_code} | /unban_{ban_code}\n"
            f"پیام مستقیم یه کاربر : "
            f"/massage_{ban_code}\n"
            "________________________________"
        )

    text = (
        f"📋 <b>لیست کاربران ربات</b>\n\n"
        f"صفحه {page + 1} از {total_pages}\n\n"
        + "\n\n".join(parts)
    )

    return (
        text,
        userbot_keyboard(page, total_pages),
        total_pages
    )


async def userbot_command(
    update,
    context
):

    user = update.effective_user

    if not user or user.id != ADMIN_ID:
        return

    text, keyboard, total_pages = build_userbot_page(0)

    await update.message.reply_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )


# =========================================================
# DIRECT MESSAGE
# =========================================================

async def send_direct_message_to_user(
    bot,
    target_id,
    target_name,
    admin_message
):

    safe_name = html.escape(
        target_name or "کاربر"
    )

    safe_message = html.escape(
        admin_message
    )

    text = (
        "<b>پیام از طرف مدیریت : 📢</b>\n\n"
        f"خانوم / آقا "
        f'<a href="tg://user?id={target_id}">'
        f"{safe_name}"
        f"</a>\n\n"
        f"{safe_message}"
    )

    await bot.send_message(
        chat_id=target_id,
        text=text,
        parse_mode="HTML"
    )


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user:
        return

    get_or_create_user(
        user.id,
        user.username,
        user.full_name
    )

    if user.id != ADMIN_ID:

        ban_info = get_ban_info(
            user.id
        )

        if ban_info:

            await update.message.reply_text(
                "حساب کاربری شما مسدود شده است.🟡\n"
                f"علت : {ban_info['reason']}"
            )

            return

    if context.args:

        target_code = context.args[0].strip()

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

        context.user_data[
            "target_id"
        ] = target_id

        context.user_data[
            "sending_anonymous"
        ] = True

        await update.message.reply_text(
            f"شما در حال ارسال پیام ناشناس به "
            f"{target_name} هستید.\n\n"
            "پیام خود را بنویسید : 💤",
            reply_markup=cancel_keyboard()
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

    context.user_data.clear()

    await send_main_panel(
        update,
        context
    )


# =========================================================
# BROADCAST
# =========================================================

async def broadcast_command(
    update,
    context
):

    user = update.effective_user

    if user.id != ADMIN_ID:
        return

    context.user_data.clear()

    context.user_data[
        "waiting_broadcast"
    ] = True

    await update.message.reply_text(
        "📢 حالت ارسال پیام همگانی فعال شد.\n\n"
        "پیامی که می‌خوای برای همه کاربران ارسال بشه رو بفرست.\n"
        "برای لغو بنویس: /cancel"
    )


# =========================================================
# USER BAN
# =========================================================

async def userban_command(
    update,
    context
):

    user = update.effective_user

    if user.id != ADMIN_ID:
        return

    banned_users = get_active_banned_users()

    if not banned_users:

        await update.message.reply_text(
            "🟢 در حال حاضر هیچ کاربری بن نیست."
        )

        return

    parts = []

    for row in banned_users:

        user_id = row[0]
        username = row[1]
        ban_code = row[2]

        if username:
            user_identifier = f"@{username}"
        else:
            user_identifier = str(user_id)

        parts.append(
            "کاربر با آیدی : "
            f"{user_identifier}\n\n"
            "کد رفع بنی : "
            f"/unban_{ban_code}"
        )

    text = (
        "\n\n"
        "________________________________\n\n"
    ).join(parts)

    chunks = []

    while len(text) > 3900:

        split_at = text.rfind(
            "\n\n________________________________",
            0,
            3900
        )

        if split_at == -1:
            split_at = 3900

        chunks.append(
            text[:split_at]
        )

        text = text[split_at:]

    if text:
        chunks.append(text)

    for chunk in chunks:

        await update.message.reply_text(
            chunk
        )


# =========================================================
# CANCEL
# =========================================================

async def cancel_command(
    update,
    context
):

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
        f"نام فعلی شما:\n{current_name}\n\n"
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

    context.user_data[
        "changing_name"
    ] = True

    await update.callback_query.edit_message_text(
        "✏️ نام جدید خود را ارسال کنید.\n\n"
        "مثلاً:\n"
        "محمد\n"
        "مانی\n"
        "علی",
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
            f"کاربر {anon_code} در لیست مسدودی شما است.\n"
            f"رفع مسدودی : /Unblock_{unblock_code}"
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

    text = (
        "🤔 راهنمای ربات\n\n"
        "🔗 با لینک اختصاصی خود می‌توانید "
        "پیام ناشناس دریافت کنید.\n\n"
        "🗨️ می‌توانید به پیام‌های دریافتی پاسخ دهید.\n\n"
        "🛑 می‌توانید کاربران را مسدود کنید.\n\n"
        "🚨 در صورت مشاهده تخلف، پیام را گزارش کنید.\n\n"
        "👁️ با زدن مشاهده شد، فرستنده متوجه می‌شود "
        "پیامش توسط شما دیده شده است."
    )

    await update.callback_query.edit_message_text(
        text,
        reply_markup=back_keyboard()
    )


# =========================================================
# CALLBACK HANDLER
# =========================================================

async def button_handler(
    update,
    context
):

    query = update.callback_query

    user = update.effective_user

    user_id = user.id

    data = query.data or ""

    # =====================================================
    # CHECK JOIN
    # =====================================================

    if data == "check_join":

        if not await is_member(
            context.bot,
            user_id
        ):

            await query.answer(
                "هنوز توی همه کانالا عضو نشدی🤠💔",
                show_alert=True
            )

            return

        await query.answer(
            "عضویت شما تأیید شد ✅"
        )

        context.user_data.clear()

        await send_main_panel(
            update,
            context
        )

        return

    # =====================================================
    # BACK MAIN
    # =====================================================

    if data == "back_main":

        await query.answer()

        context.user_data.clear()

        await send_main_panel(
            update,
            context
        )

        return

    # =====================================================
    # CANCEL SEND
    # =====================================================

    if data == "cancel_send":

        await query.answer(
            "لغو شد ❌"
        )

        context.user_data.clear()

        await query.message.reply_text(
            "❌ عملیات لغو شد."
        )

        await send_main_panel(
            update,
            context
        )

        return

    # =====================================================
    # USERBOT PAGE
    # =====================================================

    if data.startswith("userbot_page:"):

        if user_id != ADMIN_ID:

            await query.answer(
                "دسترسی ندارید ❌",
                show_alert=True
            )

            return

        try:

            page = int(
                data.split(":", 1)[1]
            )

        except (ValueError, IndexError):

            await query.answer(
                "صفحه نامعتبر است ❌",
                show_alert=True
            )

            return

        text, keyboard, total_pages = build_userbot_page(
            page
        )

        await query.answer()

        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        return

    # =====================================================
    # COPY LINK
    # =====================================================

    if data == "copy_link":

        await query.answer()

        await show_link(
            update,
            context
        )

        return

    # =====================================================
    # NAME SETTINGS
    # =====================================================

    if data == "name_settings":

        await query.answer()

        await name_settings(
            update,
            context
        )

        return

    # =====================================================
    # CHANGE NAME
    # =====================================================

    if data == "change_name":

        await query.answer()

        await change_name(
            update,
            context
        )

        return

    # =====================================================
    # ADS
    # =====================================================

    if data == "ads":

        await query.answer()

        await ads_page(
            update,
            context
        )

        return

    # =====================================================
    # BLOCK LIST
    # =====================================================

    if data == "block_list":

        await query.answer()

        await block_list_page(
            update,
            context
        )

        return

    # =====================================================
    # HELP
    # =====================================================

    if data == "help":

        await query.answer()

        await help_page(
            update,
            context
        )

        return

    # =====================================================
    # REACTION OPEN
    # =====================================================

    if data.startswith("reaction:"):

        try:

            message_id = int(
                data.split(":", 1)[1]
            )

        except (ValueError, IndexError):

            await query.answer(
                "پیام نامعتبر است ❌",
                show_alert=True
            )

            return

        anonymous_message = get_anonymous_message(
            message_id
        )

        if not anonymous_message:

            await query.answer(
                "این پیام دیگر موجود نیست ❌",
                show_alert=True
            )

            return

        sender_id = anonymous_message[1]
        receiver_id = anonymous_message[2]

        if receiver_id != user_id:

            await query.answer(
                "این پیام متعلق به شما نیست ❌",
                show_alert=True
            )

            return

        existing = has_reaction(
            message_id,
            user_id
        )

        if existing:

            await query.answer(
                "شما قبلاً برای این پیام ری‌اکشن فرستاده‌اید.",
                show_alert=True
            )

            return

        await query.answer()

        await query.edit_message_reply_markup(
            reply_markup=reaction_keyboard(
                message_id
            )
        )

        try:

            await query.message.reply_text(
                "ری اکشن خود را برای پیام انتخاب کنید :"
            )

        except TelegramError as e:

            print(
                f"Reaction text error: {e}"
            )

        return

    # =====================================================
    # REACTION BACK
    # =====================================================

    if data.startswith("reaction_back:"):

        try:

            message_id = int(
                data.split(":", 1)[1]
            )

        except (ValueError, IndexError):

            await query.answer(
                "پیام نامعتبر است ❌",
                show_alert=True
            )

            return

        anonymous_message = get_anonymous_message(
            message_id
        )

        if not anonymous_message:

            await query.answer(
                "پیام پیدا نشد ❌",
                show_alert=True
            )

            return

        sender_id = anonymous_message[1]
        receiver_id = anonymous_message[2]

        if receiver_id != user_id:

            await query.answer(
                "این پیام متعلق به شما نیست ❌",
                show_alert=True
            )

            return

        await query.answer()

        await query.edit_message_reply_markup(
            reply_markup=anonymous_message_keyboard(
                message_id,
                sender_id,
                include_reaction=True,
                include_seen=True
            )
        )

        return

    # =====================================================
    # REACTION SELECT
    # =====================================================

    if data.startswith("react:"):

        pieces = data.split(":")

        if len(pieces) != 3:

            await query.answer(
                "ری‌اکشن نامعتبر است ❌",
                show_alert=True
            )

            return

        try:

            message_id = int(pieces[1])
            reaction_index = int(pieces[2])

        except ValueError:

            await query.answer(
                "ری‌اکشن نامعتبر است ❌",
                show_alert=True
            )

            return

        if (
            reaction_index < 0
            or reaction_index >= len(REACTIONS)
        ):

            await query.answer(
                "ری‌اکشن نامعتبر است ❌",
                show_alert=True
            )

            return

        reaction = REACTIONS[
            reaction_index
        ]

        anonymous_message = get_anonymous_message(
            message_id
        )

        if not anonymous_message:

            await query.answer(
                "این پیام دیگر موجود نیست ❌",
                show_alert=True
            )

            return

        sender_id = anonymous_message[1]
        receiver_id = anonymous_message[2]

        if receiver_id != user_id:

            await query.answer(
                "این پیام متعلق به شما نیست ❌",
                show_alert=True
            )

            return

        existing = has_reaction(
            message_id,
            user_id
        )

        if existing:

            await query.answer(
                "شما قبلاً ری‌اکشن ارسال کرده‌اید.",
                show_alert=True
            )

            return

        saved = save_reaction(
            message_id,
            user_id,
            reaction
        )

        if not saved:

            await query.answer(
                "ری‌اکشن قبلاً ارسال شده است.",
                show_alert=True
            )

            return

        # -----------------------------------------------
        # CLOSE REACTION PANEL
        # -----------------------------------------------

        await query.edit_message_reply_markup(
            reply_markup=anonymous_message_keyboard(
                message_id,
                sender_id,
                include_reaction=False,
                include_seen=False
            )
        )

        # -----------------------------------------------
        # SUCCESS DIALOG
        # -----------------------------------------------

        await query.answer(
            "ری اکشن با موفقیت ارسال شد ⚡",
            show_alert=True
        )

        # -----------------------------------------------
        # NOTIFY ORIGINAL SENDER
        # -----------------------------------------------

        try:

            notification = (
                "<b>کاربر به پیام شما واکنشی نشون داد : "
                f"{reaction}</b>"
            )

            await context.bot.send_message(
                chat_id=sender_id,
                text=notification,
                parse_mode="HTML"
            )

        except TelegramError as e:

            print(
                f"Reaction notification error: {e}"
            )

        return

    # =====================================================
    # SEEN
    # =====================================================

    if data.startswith("seen:"):

        try:

            message_id = int(
                data.split(":", 1)[1]
            )

        except (ValueError, IndexError):

            await query.answer(
                "پیام نامعتبر است ❌",
                show_alert=True
            )

            return

        anonymous_message = get_anonymous_message(
            message_id
        )

        if not anonymous_message:

            await query.answer(
                "این پیام دیگر موجود نیست ❌",
                show_alert=True
            )

            return

        sender_id = anonymous_message[1]
        receiver_id = anonymous_message[2]

        if receiver_id != user_id:

            await query.answer(
                "این پیام متعلق به شما نیست ❌",
                show_alert=True
            )

            return

        was_seen = mark_message_as_seen(
            message_id,
            user_id
        )

        if was_seen:

            receiver_name = get_display_name(
                user_id
            )

            try:

                await context.bot.send_message(
                    chat_id=sender_id,
                    text=(
                        f"پیام شما توسط کاربر "
                        f"{receiver_name} مشاهده شد. 👁️"
                    )
                )

            except TelegramError as e:

                print(
                    f"Seen notification error: {e}"
                )

            await query.answer(
                "پیام به عنوان مشاهده‌شده ثبت شد 👁️",
                show_alert=True
            )

        else:

            await query.answer(
                "این پیام قبلاً مشاهده شده است 👁️",
                show_alert=True
            )

        return

    # =====================================================
    # REPLY
    # =====================================================

    if data.startswith("reply:"):

        try:

            message_id = int(
                data.split(":", 1)[1]
            )

        except (ValueError, IndexError):

            await query.answer(
                "پیام نامعتبر است ❌",
                show_alert=True
            )

            return

        anonymous_message = get_anonymous_message(
            message_id
        )

        if not anonymous_message:

            await query.answer(
                "این پیام دیگر موجود نیست ❌",
                show_alert=True
            )

            return

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

        await query.answer()

        context.user_data.clear()

        context.user_data[
            "reply_message_id"
        ] = message_id

        context.user_data[
            "reply_sender_id"
        ] = sender_id

        context.user_data[
            "replying"
        ] = True

        await query.message.reply_text(
            "پاسخ خود را بنویسید: 📨",
            reply_markup=cancel_keyboard()
        )

        return

    # =====================================================
    # BLOCK
    # =====================================================

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
                "نمی‌توانی خودت را بلاک کنی ❌",
                show_alert=True
            )

            return

        result = block_user(
            user_id,
            blocked_id
        )

        if result:

            await query.answer(
                "کاربر با موفقیت بلاک شد 🛑",
                show_alert=True
            )

            await query.message.reply_text(
                "🛑 این کاربر با موفقیت به لیست مسدودی شما اضافه شد."
            )

        else:

            await query.answer(
                "این کاربر قبلاً بلاک شده است.",
                show_alert=True
            )

        return

    # =====================================================
    # REPORT
    # =====================================================

    if data.startswith("report:"):

        try:

            message_id = int(
                data.split(":", 1)[1]
            )

        except (ValueError, IndexError):

            await query.answer(
                "گزارش نامعتبر است ❌",
                show_alert=True
            )

            return

        anonymous_message = get_anonymous_message(
            message_id
        )

        if not anonymous_message:

            await query.answer(
                "این پیام دیگر موجود نیست ❌",
                show_alert=True
            )

            return

        sender_id = anonymous_message[1]
        receiver_id = anonymous_message[2]
        original_text = anonymous_message[3]

        if receiver_id != user_id:

            await query.answer(
                "این پیام متعلق به شما نیست ❌",
                show_alert=True
            )

            return

        reported_user = get_user(
            sender_id
        )

        if reported_user:

            reported_username = reported_user[1]
            reported_full_name = reported_user[2]
            ban_code = reported_user[6]

        else:

            reported_username = None
            reported_full_name = "کاربر"
            ban_code = get_ban_code(
                sender_id
            )

        username_text = (
            f"@{reported_username}"
            if reported_username
            else "ندارد"
        )

        reported_full_name = (
            reported_full_name
            or "ندارد"
        )

        if not ban_code:

            ban_code = get_ban_code(
                sender_id
            )

        report_text = (
            "🚨 گزارش تخلف برای کاربر و پیام زیر ثبت شد .👇🏻\n\n"
            f"آیدی کاربر : {username_text}\n"
            f"آیدی عددی کاربر : {sender_id}\n"
            f"نام حساب کاربری تلگرام : "
            f"{reported_full_name}\n\n"
            f"پیام گزارش شده :\n"
            f"{original_text}\n\n"
            f"کد بن کاربر : /ban_{ban_code}\n"
            f"کد رفع بن : /unban_{ban_code}"
        )

        try:

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=report_text
            )

            await query.answer(
                "گزارش تخلف با موفقیت ثبت شد 🚨",
                show_alert=True
            )

            await query.message.reply_text(
                "🚨 گزارش تخلف شما با موفقیت ثبت شد.\n"
                "گزارش برای مدیریت ارسال شد."
            )

        except TelegramError as e:

            print(
                f"Report send error: {e}"
            )

            await query.answer(
                "ارسال گزارش با خطا مواجه شد ❌",
                show_alert=True
            )

        return


# =========================================================
# HANDLE MESSAGE
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

    text = message.text

    if not text.strip():
        return

    get_or_create_user(
        user.id,
        user.username,
        user.full_name
    )

    # =====================================================
    # ADMIN
    # =====================================================

    if user.id == ADMIN_ID:

        # =================================================
        # DIRECT MESSAGE STATE
        # =================================================

        if context.user_data.get(
            "waiting_direct_message"
        ):

            if text.strip().lower() == "/cancel":

                context.user_data.clear()

                await message.reply_text(
                    "❌ ارسال پیام مستقیم لغو شد."
                )

                return

            target_id = context.user_data.get(
                "direct_target_id"
            )

            target_name = context.user_data.get(
                "direct_target_name"
            )

            if not target_id:

                context.user_data.clear()

                await message.reply_text(
                    "❌ اطلاعات کاربر پیدا نشد."
                )

                return

            try:

                await send_direct_message_to_user(
                    context.bot,
                    target_id,
                    target_name,
                    text
                )

                context.user_data.clear()

                await message.reply_text(
                    "✅ پیام مستقیم با موفقیت برای کاربر ارسال شد."
                )

            except TelegramError as e:

                print(
                    f"Direct message error: {e}"
                )

                context.user_data.clear()

                await message.reply_text(
                    "❌ ارسال پیام مستقیم انجام نشد.\n"
                    "ممکن است کاربر ربات را بلاک کرده باشد."
                )

            return

        # =================================================
        # MASSAGE COMMAND
        # =================================================

        if text.lower().startswith("/massage_"):

            code = text[len("/massage_"):].strip()

            if not code:

                await message.reply_text(
                    "❌ کد پیام مستقیم نامعتبر است."
                )

                return

            conn = db()

            try:

                cur = conn.cursor()

                cur.execute(
                    """
                    SELECT
                        user_id,
                        username,
                        full_name,
                        display_name
                    FROM users
                    WHERE lower(ban_code) = %s
                    """,
                    (code.lower(),)
                )

                target = cur.fetchone()

            finally:
                cur.close()
                release_db(conn)

            if not target:

                await message.reply_text(
                    "❌ کد کاربر پیدا نشد."
                )

                return

            target_id = target[0]
            target_username = target[1]
            target_full_name = target[2]
            target_display_name = target[3]

            if target_id == ADMIN_ID:

                await message.reply_text(
                    "❌ نمی‌توانی برای خودت پیام مستقیم ارسال کنی."
                )

                return

            target_name = (
                target_full_name
                or target_display_name
                or (
                    f"@{target_username}"
                    if target_username
                    else "کاربر"
                )
            )

            context.user_data.clear()

            context.user_data[
                "waiting_direct_message"
            ] = True

            context.user_data[
                "direct_target_id"
            ] = target_id

            context.user_data[
                "direct_target_name"
            ] = target_name

            await message.reply_text(
                f"پیام مستقیمت برای کاربر "
                f"{target_name} رو ارسال کن :"
            )

            return

        # =================================================
        # WAITING BAN REASON
        # =================================================

        if context.user_data.get(
            "waiting_ban_reason"
        ):

            if text.strip().lower() == "/cancel":

                context.user_data.clear()

                await message.reply_text(
                    "❌ عملیات بن لغو شد."
                )

                return

            reason = text.strip()

            if len(reason) > 1000:

                await message.reply_text(
                    "❌ علت بن خیلی طولانی است.\n"
                    "حداکثر ۱۰۰۰ کاراکتر وارد کنید."
                )

                return

            ban_code = context.user_data.get(
                "ban_code"
            )

            target_user_id = context.user_data.get(
                "ban_target_id"
            )

            if not ban_code or not target_user_id:

                context.user_data.clear()

                await message.reply_text(
                    "❌ اطلاعات بن پیدا نشد."
                )

                return

            banned_user_id = ban_user_by_code(
                ban_code,
                reason
            )

            if not banned_user_id:

                context.user_data.clear()

                await message.reply_text(
                    "❌ کد بن پیدا نشد."
                )

                return

            if banned_user_id != target_user_id:

                context.user_data.clear()

                await message.reply_text(
                    "❌ خطایی در اطلاعات بن رخ داد."
                )

                return

            context.user_data.clear()

            try:

                await context.bot.send_message(
                    chat_id=banned_user_id,
                    text=(
                        "حساب کاربری شما مسدود شده است.🟡\n"
                        f"علت : {reason}"
                    )
                )

            except TelegramError as e:

                print(
                    f"Ban notification error: {e}"
                )

            await message.reply_text(
                "🔴 کاربر با موفقیت به مدت ۱ روز بن شد.\n\n"
                f"آیدی عددی کاربر : {banned_user_id}\n"
                f"علت بن : {reason}\n\n"
                f"کد رفع بن : /unban_{ban_code}"
            )

            return

        # =================================================
        # BAN COMMAND
        # =================================================

        if text.lower().startswith("/ban_"):

            code = text[5:].strip()

            if not code:

                await message.reply_text(
                    "❌ کد بن نامعتبر است."
                )

                return

            conn = db()

            try:

                cur = conn.cursor()

                cur.execute(
                    """
                    SELECT user_id
                    FROM users
                    WHERE lower(ban_code) = %s
                    """,
                    (code.lower(),)
                )

                row = cur.fetchone()

            finally:
                cur.close()
                release_db(conn)

            if not row:

                await message.reply_text(
                    "❌ کد بن پیدا نشد."
                )

                return

            target_user_id = row[0]

            if target_user_id == ADMIN_ID:

                await message.reply_text(
                    "❌ نمی‌توانی خودت را بن کنی."
                )

                return

            context.user_data.clear()

            context.user_data[
                "waiting_ban_reason"
            ] = True

            context.user_data[
                "ban_code"
            ] = code

            context.user_data[
                "ban_target_id"
            ] = target_user_id

            await message.reply_text(
                "علت بنی را وارد کنید :"
            )

            return

        # =================================================
        # UNBAN COMMAND
        # =================================================

        if text.lower().startswith("/unban_"):

            code = text[7:].strip()

            if not code:

                await message.reply_text(
                    "❌ کد رفع بن نامعتبر است."
                )

                return

            unbanned_user_id = unban_user_by_code(
                code
            )

            if not unbanned_user_id:

                await message.reply_text(
                    "❌ کد رفع بن پیدا نشد."
                )

                return

            await message.reply_text(
                "🟢 بن کاربر با موفقیت رفع شد.\n\n"
                f"آیدی عددی کاربر : {unbanned_user_id}"
            )

            try:

                await context.bot.send_message(
                    chat_id=unbanned_user_id,
                    text=(
                        "🟢 حساب کاربری شما از حالت بن خارج شد.\n"
                        "اکنون می‌توانید دوباره از ربات استفاده کنید."
                    )
                )

            except TelegramError as e:

                print(
                    f"Unban notification error: {e}"
                )

            return

    # =====================================================
    # BAN CHECK
    # =====================================================

    if user.id != ADMIN_ID:

        ban_info = get_ban_info(
            user.id
        )

        if ban_info:

            await message.reply_text(
                "حساب کاربری شما مسدود شده است.🟡\n"
                f"علت : {ban_info['reason']}"
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
    # BACK
    # =====================================================

    if text.strip() == "بازگشت 🔙":

        context.user_data.clear()

        await send_main_panel(
            update,
            context
        )

        return

    # =====================================================
    # BROADCAST
    # =====================================================

    if context.user_data.get(
        "waiting_broadcast"
    ):

        if text.strip().lower() == "/cancel":

            context.user_data.clear()

            await message.reply_text(
                "❌ عملیات لغو شد."
            )

            return

        users = get_all_user_ids()

        status_msg = await message.reply_text(
            "📢 ارسال پیام همگانی شروع شد..."
        )

        success = 0
        failed = 0

        for target_id in users:

            try:

                await context.bot.send_message(
                    chat_id=target_id,
                    text=text
                )

                success += 1

            except TelegramError:

                failed += 1

            await asyncio.sleep(0.03)

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

    if text.lower().startswith("/unblock_"):

        code = text[len("/unblock_"):].strip()

        if not code:

            await message.reply_text(
                "❌ کد رفع مسدودی نامعتبر است."
            )

            return

        result = unblock_by_code(
            user.id,
            code
        )

        if result:

            await message.reply_text(
                "🟢 کاربر با موفقیت از لیست مسدودی خارج شد."
            )

        else:

            await message.reply_text(
                "❌ کد رفع مسدودی پیدا نشد."
            )

        return

    # =====================================================
    # CHANGE NAME
    # =====================================================

    if context.user_data.get(
        "changing_name"
    ):

        if len(text.strip()) > 50:

            await message.reply_text(
                "❌ نام خیلی طولانی است.\n"
                "حداکثر ۵۰ کاراکتر وارد کنید."
            )

            return

        new_name = text.strip()

        if not new_name:

            await message.reply_text(
                "❌ نام نمی‌تواند خالی باشد."
            )

            return

        set_display_name(
            user.id,
            new_name
        )

        context.user_data.clear()

        await message.reply_text(
            f"✅ نام شما با موفقیت تغییر کرد.\n\n"
            f"نام جدید: {new_name}",
            reply_markup=back_keyboard()
        )

        return

    # =====================================================
    # REPLY
    # =====================================================

    if context.user_data.get(
        "replying"
    ):

        original_message_id = context.user_data.get(
            "reply_message_id"
        )

        sender_id = context.user_data.get(
            "reply_sender_id"
        )

        if (
            not original_message_id
            or not sender_id
        ):

            context.user_data.clear()

            await message.reply_text(
                "❌ اطلاعات پیام پیدا نشد.",
                reply_markup=back_keyboard()
            )

            return

        anonymous_message = get_anonymous_message(
            original_message_id
        )

        if not anonymous_message:

            context.user_data.clear()

            await message.reply_text(
                "❌ پیام اصلی پیدا نشد.",
                reply_markup=back_keyboard()
            )

            return

        original_sender_id = anonymous_message[1]
        original_receiver_id = anonymous_message[2]
        original_text = anonymous_message[3]

        if (
            original_receiver_id != user.id
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

        new_message_id = save_anonymous_message(
            sender_id=user.id,
            receiver_id=sender_id,
            message_text=text
        )

        user_row = get_user(
            user.id
        )

        if user_row:

            anon_code = user_row[4]

        else:

            anon_code = "0000000"

        keyboard = anonymous_message_keyboard(
            new_message_id,
            user.id,
            include_reaction=True,
            include_seen=True
        )

        reply_text = (
            f"کاربر {anon_code} "
            f"به پیام شما پاسخ داد. 🤠\n\n"
            f"پیام شما :\n"
            f"{original_text}\n\n"
            f"پیام پاسخ داده شده :\n"
            f"{text}"
        )

        try:

            await context.bot.send_message(
                chat_id=sender_id,
                text=reply_text,
                reply_markup=keyboard
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

        if row:

            anon_code = row[4]

        else:

            anon_code = "0000000"

        keyboard = anonymous_message_keyboard(
            anonymous_message_id,
            user.id,
            include_reaction=True,
            include_seen=True
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

    # =====================================================
    # SEND ANONYMOUS BUTTON
    # =====================================================

    if text == "ارسال پیام ناشناس به کاربر دلخواه":

        context.user_data.clear()

        context.user_data[
            "waiting_target"
        ] = True

        await message.reply_text(
            "آیدی عددی یا آیدی کاربر را ارسال کنید.\n"
            "مثال :\n"
            "@username\n"
            "123456789\n"
            "ربات بررسی میکند در صورت عضو بودن کاربر در ربات "
            "میتوانید به او پیام ناشناس ارسال کنید❤️‍🔥",
            reply_markup=back_keyboard()
        )

        return

    # =====================================================
    # WAITING TARGET
    # =====================================================

    if context.user_data.get(
        "waiting_target"
    ):

        target = find_user_by_input(
            text
        )

        if not target:

            await message.reply_text(
                "خطایی رخ داد ! به نظر میرسه کاربر عضو ربات نیست "
                "یا آیدی رو اشتباه وارد کردی ❌",
                reply_markup=back_keyboard()
            )

            return

        target_id = target[0]

        if target_id == user.id:

            bot = await context.bot.get_me()

            own_link = (
                f"https://t.me/{bot.username}"
                f"?start={user.id}"
            )

            await message.reply_text(
                "به خودت که نمیتونی پیام بفرستی عزیز 🥹\n\n"
                "لینک خودت:\n"
                f"{own_link}",
                reply_markup=back_keyboard()
            )

            return

        target_name = (
            target[2]
            or target[1]
            or "کاربر"
        )

        context.user_data.clear()

        context.user_data[
            "target_id"
        ] = target_id

        context.user_data[
            "sending_anonymous"
        ] = True

        await message.reply_text(
            f"شما در حال ارسال پیام ناشناس به "
            f"{target_name} هستید.\n\n"
            "پیام خود را بنویسید : 💤",
            reply_markup=cancel_keyboard()
        )

        return

    # =====================================================
    # UNKNOWN MESSAGE
    # =====================================================

    await message.reply_text(
        "دستور یافت نشد 🫪\n"
        "لطفا از پنل اصلی ربات استفاده کنید.\n"
        "الان پنل رو برات میفرستم 🤠"
    )

    await send_main_panel(
        update,
        context
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

    create_db_pool()

    init_db()

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # =====================================================
    # COMMANDS
    # =====================================================

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
            "userban",
            userban_command
        )
    )

    application.add_handler(
        CommandHandler(
            "userbot",
            userbot_command
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel_command
        )
    )

    # =====================================================
    # CALLBACKS
    # =====================================================

    application.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    # =====================================================
    # TEXT
    # =====================================================

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    # =====================================================
    # COMMAND-LIKE TEXT
    # =====================================================

    application.add_handler(
        MessageHandler(
            filters.COMMAND,
            handle_message
        )
    )

    # =====================================================
    # ERROR
    # =====================================================

    application.add_error_handler(
        error_handler
    )

    print(
        "Bot started successfully with PostgreSQL."
    )

    print(
        "PostgreSQL service: Postgre"
    )

    application.run_polling(
        drop_pending_updates=True
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    main()
