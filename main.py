import os
import random
import string
import asyncio
import time
import html
import json
from urllib.parse import quote, urlsplit
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from threading import Thread

from flask import Flask

import psycopg2
from psycopg2 import pool

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    ReplyParameters,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ChatMember,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    ContextTypes,
    ChatMemberHandler,
    TypeHandler,
    ApplicationHandlerStop,
    filters,
)
from telegram.error import TelegramError


# =========================================================
# WEB HEALTH CHECK (Deplexo Web Service)
# =========================================================

health_app = Flask(__name__)
health_app.secret_key = os.getenv("ADMIN_PANEL_SECRET_KEY") or os.urandom(32)
health_app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=True,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)

from admin_panel import admin_panel
from mini_app import mini_app
health_app.register_blueprint(admin_panel)
health_app.register_blueprint(mini_app)


@health_app.route("/")
@health_app.route("/health")
def health_check():
    return "OK", 200


def start_health_server():
    port = int(os.environ.get("PORT", "8080"))
    health_app.run(
        host="0.0.0.0",
        port=port,
        use_reloader=False,
        threaded=True,
    )


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

ADMIN_ID = 6078875175

CHANNEL_1 = "@hidemychatRobot0"
CHANNEL_1_URL = "https://t.me/hidemychatRobot0"


DATABASE_URL = os.getenv("DATABASE_URL")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set.")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set.")

DB_POOL = None
GLOBAL_BOT = None

SUPERVISOR_COMMANDS_TEXT = """/userbot  با ارسال این دستور میتونی کاربرای ربات رو ببینی و بهشون دسترسی داشته باشی
/userban با این ارسال این دستور میتونی لیست کاربرای بن شده ربات رو ببینی
/broadcast با این دستور میتونی پیام همگانی بفرستی 
/changeusername با این دستور میتونی اسم کاربر رو اگه اسم مناسبی نداشت تغییر بدی

/ban_   با این دستور میتونی شناسه کاربری هرکس رو داشتی بعد از _ کاربر رو بن کنی
/unban_  این دستور مثل دستور بن هست و رفع بن میکنه کاربر رو
"""


# =========================================================
# DATABASE
# =========================================================

def create_db_pool():
    global DB_POOL

    if DB_POOL is None:
        # Thread-safe because the Flask admin panel and bot handlers can access
        # PostgreSQL from different threads.
        DB_POOL = psycopg2.pool.ThreadedConnectionPool(
            1,
            10,
            dsn=DATABASE_URL,
            connect_timeout=5,
            keepalives=1,
            keepalives_idle=10,
            keepalives_interval=5,
            keepalives_count=3,
        )


def db():
    """Borrow a usable connection, discarding stale connections left by network drops."""
    global DB_POOL

    if DB_POOL is None:
        create_db_pool()

    conn = DB_POOL.getconn()
    # A connection whose server-side session died may be returned by the pool.
    # Never hand an already-closed connection to a handler.
    if conn.closed:
        try:
            DB_POOL.putconn(conn, close=True)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
        conn = DB_POOL.getconn()

    if conn.closed:
        try:
            DB_POOL.putconn(conn, close=True)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
        raise psycopg2.OperationalError("PostgreSQL pool returned a closed connection")

    return conn


def release_db(conn):
    """Return only healthy, transaction-clean connections to the shared pool."""
    global DB_POOL

    if conn is None:
        return

    # The pool may already have been closed during process shutdown.
    if DB_POOL is None:
        try:
            conn.close()
        except Exception:
            pass
        return

    discard = bool(conn.closed)
    if not discard:
        try:
            # Read-only helpers often leave an implicit transaction open.
            # Roll it back before reuse; discard the connection if cleanup fails.
            if conn.get_transaction_status() != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                conn.rollback()
        except Exception:
            discard = True

    try:
        DB_POOL.putconn(conn, close=discard)
        if discard:
            print("[DB POOL] Discarded an unhealthy PostgreSQL connection.", flush=True)
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


async def get_cached_bot_username(context):
    """Return the bot username without a Telegram API round trip on each handler."""
    username = context.application.bot_data.get("bot_username") or context.bot.username
    if not username:
        bot_info = await context.bot.get_me()
        username = bot_info.username
        context.application.bot_data["bot_username"] = username
    return username


def save_abuse_report(report_type, reporter_id, reporter_name, reported_user_id,
                      reported_username, reported_name, message_id, message_text,
                      group_id=None, group_title=None):
    """Persist a user-submitted abuse report without changing existing user/message records."""
    conn = db()
    cur = None
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO abuse_reports
                (report_type, reporter_id, reporter_name, reported_user_id,
                 reported_username, reported_name, message_id, message_text,
                 group_id, group_title)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (report_type, reporter_id, reporter_name, reported_user_id,
              reported_username, reported_name, message_id, message_text,
              group_id, group_title))
        report_id = cur.fetchone()[0]
        conn.commit()
        return report_id
    except Exception:
        conn.rollback()
        raise
    finally:
        if cur is not None:
            cur.close()
        release_db(conn)


def init_db():
    conn = db()

    try:
        cur = conn.cursor()

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

        cur.execute("""
            CREATE TABLE IF NOT EXISTS blocks (
                blocker_id BIGINT NOT NULL,
                blocked_id BIGINT NOT NULL,
                unblock_code TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (blocker_id, blocked_id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS anonymous_messages (
                id BIGSERIAL PRIMARY KEY,
                sender_id BIGINT NOT NULL,
                receiver_id BIGINT NOT NULL,
                message_text TEXT NOT NULL,
                created_at TIMESTAMP,
                seen_at TIMESTAMP,
                media_type TEXT,
                file_id TEXT,
                media_caption TEXT,
                sender_message_id BIGINT,
                conversation_owner_id BIGINT,
                delivered_message_id BIGINT
            )
        """)

        cur.execute("""
            ALTER TABLE anonymous_messages
            ADD COLUMN IF NOT EXISTS delivered_message_id BIGINT
        """)

        cur.execute("""
            ALTER TABLE anonymous_messages
            ADD COLUMN IF NOT EXISTS conversation_owner_id BIGINT
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS link_views (
                owner_id BIGINT NOT NULL,
                visitor_id BIGINT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (owner_id, visitor_id)
            )
        """)

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

        # GROUPS

        cur.execute("""
            CREATE TABLE IF NOT EXISTS group_chats (
                chat_id BIGINT PRIMARY KEY,
                title TEXT,
                link_code TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Persistent state for one automatic promotional message per group every 10 hours.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS group_ad_state (
                chat_id BIGINT PRIMARY KEY,
                last_sent_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_template TEXT
            )
        """)

        # Per-template timestamps used to rotate automatic group promotions.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS group_ad_template_state (
                chat_id BIGINT NOT NULL,
                template TEXT NOT NULL,
                last_sent_at TIMESTAMP NOT NULL,
                PRIMARY KEY (chat_id, template)
            )
        """)

        # One-time marker used to stagger promotion schedules when a group is first initialized.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS group_ad_schedule_meta (
                chat_id BIGINT PRIMARY KEY,
                initialized_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Incoming human messages are sampled to detect quiet groups.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS group_ad_activity (
                id BIGSERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_group_ad_activity_chat_created
            ON group_ad_activity(chat_id, created_at)
        """)

        cur.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS channel_terms_accepted BOOLEAN NOT NULL DEFAULT FALSE
        """)

        cur.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS bot_blocked_at TIMESTAMP
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS new_user_queue (
                user_id BIGINT PRIMARY KEY,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                viewed_at TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS channel_profanity_violations (
                user_id BIGINT PRIMARY KEY,
                violation_count INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS channel_links (
                id BIGSERIAL PRIMARY KEY,
                owner_id BIGINT NOT NULL,
                channel_id BIGINT NOT NULL,
                channel_title TEXT NOT NULL,
                link_code TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(owner_id, channel_id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS pending_channel_additions (
                inviter_id BIGINT NOT NULL,
                channel_id BIGINT NOT NULL,
                channel_title TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (inviter_id, channel_id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS group_messages (
                id BIGSERIAL PRIMARY KEY,
                group_id BIGINT NOT NULL,
                sender_id BIGINT NOT NULL,
                message_text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                view_count INTEGER DEFAULT 0
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS group_message_views (
                message_id BIGINT NOT NULL,
                viewer_id BIGINT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (message_id, viewer_id)
            )
        """)

        # SAFE MIGRATIONS

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

        cur.execute("""
            ALTER TABLE anonymous_messages
            ADD COLUMN IF NOT EXISTS media_type TEXT
        """)
        cur.execute("""
            ALTER TABLE anonymous_messages
            ADD COLUMN IF NOT EXISTS file_id TEXT
        """)
        cur.execute("""
            ALTER TABLE anonymous_messages
            ADD COLUMN IF NOT EXISTS media_caption TEXT
        """)
        cur.execute("""
            ALTER TABLE anonymous_messages
            ADD COLUMN IF NOT EXISTS sender_message_id BIGINT
        """)

        cur.execute("""
            ALTER TABLE anonymous_messages
            ADD COLUMN IF NOT EXISTS delivered_message_id BIGINT
        """)

        # INDEXES

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
            CREATE INDEX IF NOT EXISTS idx_messages_receiver_created
            ON anonymous_messages(receiver_id, created_at DESC)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_sender
            ON anonymous_messages(sender_id)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_conversation_owner
            ON anonymous_messages(conversation_owner_id, created_at DESC)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_blocks_blocked
            ON blocks(blocked_id)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_channel_links_owner
            ON channel_links(owner_id)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_group_messages_group_created
            ON group_messages(group_id, created_at DESC)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_created
            ON anonymous_messages(created_at)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_reactions_message
            ON message_reactions(message_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_link_views_owner
            ON link_views(owner_id)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_group_messages_group
            ON group_messages(group_id)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_group_views_message
            ON group_message_views(message_id)
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS abuse_reports (
                id BIGSERIAL PRIMARY KEY,
                report_type TEXT NOT NULL DEFAULT 'private',
                reporter_id BIGINT NOT NULL,
                reporter_name TEXT,
                reported_user_id BIGINT NOT NULL,
                reported_username TEXT,
                reported_name TEXT,
                message_id BIGINT,
                group_id BIGINT,
                group_title TEXT,
                message_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_read BOOLEAN NOT NULL DEFAULT FALSE
            )
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_abuse_reports_unread
            ON abuse_reports(is_read, created_at DESC)
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS supervisors (
                user_id BIGINT PRIMARY KEY,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS supervisor_unban_requests (
                id BIGSERIAL PRIMARY KEY,
                supervisor_id BIGINT NOT NULL,
                target_id BIGINT NOT NULL,
                target_code TEXT NOT NULL,
                target_name TEXT,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS supervisor_broadcast_requests (
                id BIGSERIAL PRIMARY KEY,
                supervisor_id BIGINT NOT NULL,
                message_text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()

    finally:
        cur.close()
        release_db(conn)

    fill_missing_codes()
    fill_missing_group_codes()


# =========================================================
# SUPERVISORS / MODERATION HELPERS
# =========================================================

def is_supervisor(user_id):
    if not user_id or user_id == ADMIN_ID:
        return False
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM supervisors WHERE user_id = %s", (user_id,))
        return cur.fetchone() is not None
    finally:
        cur.close()
        release_db(conn)


def is_manager_or_supervisor(user_id):
    return bool(user_id and (user_id == ADMIN_ID or is_supervisor(user_id)))


def add_supervisor(user_id):
    if not user_id or user_id == ADMIN_ID:
        return False
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO supervisors (user_id)
            VALUES (%s)
            ON CONFLICT (user_id) DO NOTHING
        """, (user_id,))
        created = cur.rowcount > 0
        conn.commit()
        return created
    finally:
        cur.close()
        release_db(conn)


def remove_supervisor(user_id):
    if not user_id or user_id == ADMIN_ID:
        return False
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM supervisors WHERE user_id = %s", (user_id,))
        removed = cur.rowcount > 0
        conn.commit()
        return removed
    finally:
        cur.close()
        release_db(conn)


def get_supervisors():
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT s.user_id, u.username, u.full_name, u.display_name
            FROM supervisors s
            LEFT JOIN users u ON u.user_id = s.user_id
            ORDER BY s.added_at ASC
        """)
        return cur.fetchall()
    finally:
        cur.close()
        release_db(conn)


def find_user_by_identifier(identifier):
    value = (identifier or '').strip()
    if not value:
        return None
    conn = db()
    try:
        cur = conn.cursor()
        if value.isdigit():
            cur.execute("""
                SELECT user_id, username, full_name, display_name, ban_code
                FROM users WHERE user_id = %s
            """, (int(value),))
        else:
            username = value.lstrip('@').lower()
            cur.execute("""
                SELECT user_id, username, full_name, display_name, ban_code
                FROM users WHERE lower(username) = %s
            """, (username,))
        return cur.fetchone()
    finally:
        cur.close()
        release_db(conn)


def create_unban_request(supervisor_id, target_id, target_code, target_name, reason):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO supervisor_unban_requests
                (supervisor_id, target_id, target_code, target_name, reason)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (supervisor_id, target_id, target_code, target_name, reason))
        request_id = cur.fetchone()[0]
        conn.commit()
        return request_id
    finally:
        cur.close()
        release_db(conn)


def get_unban_request(request_id):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, supervisor_id, target_id, target_code, target_name, reason, status
            FROM supervisor_unban_requests WHERE id = %s
        """, (request_id,))
        return cur.fetchone()
    finally:
        cur.close()
        release_db(conn)


def set_unban_request_status(request_id, status):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE supervisor_unban_requests SET status = %s WHERE id = %s", (status, request_id))
        conn.commit()
    finally:
        cur.close()
        release_db(conn)


def create_broadcast_request(supervisor_id, message_text):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO supervisor_broadcast_requests (supervisor_id, message_text)
            VALUES (%s, %s) RETURNING id
        """, (supervisor_id, message_text))
        request_id = cur.fetchone()[0]
        conn.commit()
        return request_id
    finally:
        cur.close()
        release_db(conn)


def get_broadcast_request(request_id):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, supervisor_id, message_text, status
            FROM supervisor_broadcast_requests WHERE id = %s
        """, (request_id,))
        return cur.fetchone()
    finally:
        cur.close()
        release_db(conn)


def set_broadcast_request_status(request_id, status):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE supervisor_broadcast_requests SET status = %s WHERE id = %s", (status, request_id))
        conn.commit()
    finally:
        cur.close()
        release_db(conn)


def supervisor_display_name(user_id):
    row = get_user(user_id)
    if row:
        return row[5] or row[2] or (f"@{row[1]}" if row[1] else str(user_id))
    return str(user_id)


def supervisor_label(user_id):
    row = get_user(user_id)
    if row:
        return row[1] and f"@{row[1]}" or row[2] or str(user_id)
    return str(user_id)


def supervisor_panel_keyboard():
    rows = [[
        InlineKeyboardButton("افزودن ناظر ➕", callback_data="supervisor_add", style="success"),
    ]]
    supervisor_buttons = []
    for row in get_supervisors():
        uid = row[0]
        name = row[3] or row[2] or (f"@{row[1]}" if row[1] else str(uid))
        supervisor_buttons.append(
            InlineKeyboardButton(f"{name} | {uid}", callback_data=f"supervisor_select:{uid}")
        )

    # فهرست ناظران هم دو ستونه است تا پنل کوتاه‌تر و مرتب‌تر شود.
    for i in range(0, len(supervisor_buttons), 2):
        rows.append(supervisor_buttons[i:i + 2])

    rows.append([
        InlineKeyboardButton(
            "بستن و نمایش پنل اصلی",
            callback_data="supervisor_close_panel",
            style="danger"
        )
    ])
    return InlineKeyboardMarkup(rows)


def supervisor_delete_keyboard(user_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("بله ✅", callback_data=f"supervisor_delete_yes:{user_id}", style="success"),
            InlineKeyboardButton("خیر ✖️", callback_data="supervisor_delete_no", style="danger")
        ]
    ])


def manager_approval_keyboard(kind, request_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("بله ✅", callback_data=f"manager_approve:{kind}:{request_id}", style="success"),
            InlineKeyboardButton("خیر ✖️", callback_data=f"manager_reject:{kind}:{request_id}", style="danger")
        ]
    ])


def supervisor_target_ok_keyboard(callback_data="supervisor_target_ok"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("اوکی", callback_data=callback_data, style="success")]
    ])


def supervisor_back_keyboard():
    return back_keyboard()


# =========================================================
# GENERATORS
# =========================================================

def generate_code(length=8):
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choices(chars, k=length))


def generate_anon_code():
    while True:
        code = "".join(
            random.choices(string.digits, k=7)
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


def generate_group_code():
    while True:
        code = generate_code(10)

        conn = db()

        try:
            cur = conn.cursor()

            cur.execute(
                """
                SELECT 1
                FROM group_chats
                WHERE link_code = %s
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
# FILL CODES
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
                (code, user_id)
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


def fill_missing_group_codes():
    conn = db()

    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT chat_id
            FROM group_chats
            WHERE link_code IS NULL
               OR link_code = ''
        """)

        rows = cur.fetchall()

    finally:
        cur.close()
        release_db(conn)

    for (chat_id,) in rows:
        code = generate_group_code()

        conn = db()

        try:
            cur = conn.cursor()

            cur.execute(
                """
                UPDATE group_chats
                SET link_code = %s
                WHERE chat_id = %s
                """,
                (code, chat_id)
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
    """Fetch or refresh a user in one PostgreSQL round trip, preserving existing codes."""
    conn = db()
    cur = None

    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (
                user_id, username, full_name, link_code, anon_code,
                display_name, created_at, ban_code, ban_until, ban_reason
            )
            VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s, NULL, NULL)
            ON CONFLICT (user_id) DO UPDATE
            SET username = EXCLUDED.username,
                full_name = EXCLUDED.full_name,
                ban_code = COALESCE(users.ban_code, EXCLUDED.ban_code),
                bot_blocked_at = NULL
            RETURNING link_code, anon_code, (xmax = 0) AS is_new
            """,
            (
                user_id,
                username,
                full_name,
                str(user_id),
                generate_anon_code(),
                full_name or "کاربر",
                generate_ban_code(),
            )
        )
        row = cur.fetchone()
        link_code, anon_code, is_new = row

        if is_new:
            cur.execute(
                """
                INSERT INTO new_user_queue (user_id, created_at, viewed_at)
                VALUES (%s, CURRENT_TIMESTAMP, NULL)
                ON CONFLICT (user_id) DO NOTHING
                """,
                (user_id,)
            )

        conn.commit()
        return link_code, anon_code

    finally:
        if cur is not None:
            cur.close()
        release_db(conn)


def mark_user_bot_blocked(user_id):
    """Mark a user as blocked only when Telegram explicitly reports that condition."""
    if not user_id:
        return
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE users
            SET bot_blocked_at = COALESCE(bot_blocked_at, CURRENT_TIMESTAMP)
            WHERE user_id = %s
        """, (user_id,))
        conn.commit()
    finally:
        cur.close()
        release_db(conn)


def cleanup_blocked_users():
    """Remove users known to have blocked the bot for at least three days.
    Historical anonymous messages and block records are deliberately preserved.
    """
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM new_user_queue
            WHERE user_id IN (
                SELECT user_id FROM users
                WHERE bot_blocked_at IS NOT NULL
                  AND bot_blocked_at <= CURRENT_TIMESTAMP - INTERVAL '3 days'
            )
        """)
        cur.execute("""
            DELETE FROM users
            WHERE bot_blocked_at IS NOT NULL
              AND bot_blocked_at <= CURRENT_TIMESTAMP - INTERVAL '3 days'
        """)
        deleted = cur.rowcount
        conn.commit()
        return deleted
    except Exception:
        conn.rollback()
        raise
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
            SELECT display_name, full_name
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


def set_display_name(user_id, name):
    conn = db()

    try:
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE users
            SET display_name = %s
            WHERE user_id = %s
            """,
            (name, user_id)
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

    return [row[0] for row in rows]


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


def format_jalali_datetime(value):
    """Format a datetime as an Iranian/Jalali calendar date."""
    if not value:
        return "نامشخص"
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    gy, gm, gd = value.year, value.month, value.day
    g_month_days = [31, 29 if (gy % 4 == 0 and (gy % 100 != 0 or gy % 400 == 0)) else 28,
                    31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gy -= 1600
    gm -= 1
    gd -= 1
    g_day_no = 365 * gy + (gy + 3) // 4 - (gy + 99) // 100 + (gy + 399) // 400
    for month in range(gm):
        g_day_no += g_month_days[month]
    g_day_no += gd
    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053
    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365
    if j_day_no < 186:
        jm = 1 + j_day_no // 31
        jd = 1 + j_day_no % 31
    else:
        jm = 7 + (j_day_no - 186) // 30
        jd = 1 + (j_day_no - 186) % 30
    return f"{jy:04d}/{jm}/{jd} {value.hour:02d}:{value.minute:02d}"


# =========================================================
# BAN
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
    reason,
    duration_days
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

        ban_until = (
            datetime.now()
            + timedelta(days=duration_days)
        )

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

        return user_id, ban_until

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
            SELECT ban_until, ban_reason
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


def clear_expired_bans():
    """Clear expired bans in a worker thread and return the affected user IDs."""
    conn = db()
    cur = None
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT user_id
            FROM users
            WHERE ban_until IS NOT NULL
              AND ban_until <= CURRENT_TIMESTAMP
        """)
        expired = [row[0] for row in cur.fetchall()]

        if expired:
            cur.execute("""
                UPDATE users
                SET ban_until = NULL,
                    ban_reason = NULL
                WHERE ban_until IS NOT NULL
                  AND ban_until <= CURRENT_TIMESTAMP
            """)

        conn.commit()
        return expired
    except Exception:
        conn.rollback()
        raise
    finally:
        if cur is not None:
            cur.close()
        release_db(conn)


async def expire_bans_loop():
    while True:
        try:
            try:
                deleted_blocked = await asyncio.to_thread(cleanup_blocked_users)
                if deleted_blocked:
                    print(f"Removed {deleted_blocked} users who had blocked the bot for 3 days.")
            except Exception as cleanup_error:
                print("Blocked-user cleanup error:", cleanup_error)

            # Do not let a slow PostgreSQL round trip stall Telegram update handling.
            expired = await asyncio.to_thread(clear_expired_bans)

            for user_id in expired:
                try:
                    await GLOBAL_BOT.send_message(
                        chat_id=user_id,
                        text=(
                            "زمان مسدودی حساب کاربری شما تمام شد.\n"
                            "اکنون حساب کاربری شما به حالت سبز در آمده🟢\n"
                            "میتوانید از قابلیت های ربات استفاده کنید /start"
                        )
                    )
                except TelegramError as e:
                    error_text = str(e).lower()
                    if "bot was blocked by the user" in error_text or "bot is blocked by the user" in error_text:
                        try:
                            mark_user_bot_blocked(user_id)
                        except Exception as mark_error:
                            print("Could not mark blocked user:", mark_error)
                    print(f"Ban expiry notification error: {e}")

        except Exception as e:
            print(
                f"Ban expiration error: {e}"
            )

        await asyncio.sleep(30)


# =========================================================
# PRIVATE MESSAGES
# =========================================================

def save_anonymous_message(
    sender_id,
    receiver_id,
    message_text,
    media_type=None,
    file_id=None,
    media_caption=None,
    sender_message_id=None,
    conversation_owner_id=None
):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO anonymous_messages (
                sender_id, receiver_id, message_text, created_at, seen_at,
                media_type, file_id, media_caption, sender_message_id,
                conversation_owner_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (sender_id, receiver_id, message_text or "", datetime.now(), None,
             media_type, file_id, media_caption, sender_message_id, conversation_owner_id)
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
            SELECT id, sender_id, receiver_id, message_text, created_at, seen_at,
                   media_type, file_id, media_caption, sender_message_id,
                   conversation_owner_id, delivered_message_id
            FROM anonymous_messages
            WHERE id = %s
            """,
            (message_id,)
        )
        return cur.fetchone()
    finally:
        cur.close()
        release_db(conn)



def set_delivered_message_id(message_id, delivered_message_id):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE anonymous_messages SET delivered_message_id = %s WHERE id = %s",
            (delivered_message_id, message_id)
        )
        conn.commit()
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
# LINK VIEWS
# =========================================================

def register_link_view(owner_id, visitor_id):
    if owner_id == visitor_id:
        return False
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO link_views (owner_id, visitor_id) VALUES (%s, %s) ON CONFLICT (owner_id, visitor_id) DO NOTHING RETURNING owner_id",
            (owner_id, visitor_id)
        )
        inserted = cur.fetchone() is not None
        conn.commit()
        return inserted
    finally:
        cur.close()
        release_db(conn)


def get_link_view_count(owner_id):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM link_views WHERE owner_id = %s", (owner_id,))
        row = cur.fetchone()
        return row[0] if row else 0
    finally:
        cur.close()
        release_db(conn)


# =========================================================
# REACTIONS
# =========================================================

REACTIONS = [
    "😂",
    "😭",
    "❤️",
    "😍",
    "😡",
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
# BLOCK
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
            f"Membership error {channel}/{user_id}: {e}"
        )
        return False


async def is_member(
    bot,
    user_id
):
    # عضویت در هیچ کانالی اجباری نیست.
    # این تابع برای سازگاری با بررسی‌های قدیمی نگه داشته شده است.
    return True


# =========================================================
# GROUP DATABASE
# =========================================================

def save_group_chat(
    chat_id,
    title
):
    conn = db()

    try:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT link_code
            FROM group_chats
            WHERE chat_id = %s
            """,
            (chat_id,)
        )

        row = cur.fetchone()

        if row:
            link_code = row[0]

            cur.execute(
                """
                UPDATE group_chats
                SET title = %s
                WHERE chat_id = %s
                """,
                (
                    title,
                    chat_id
                )
            )

        else:
            link_code = generate_group_code()

            cur.execute(
                """
                INSERT INTO group_chats (
                    chat_id,
                    title,
                    link_code
                )
                VALUES (
                    %s, %s, %s
                )
                """,
                (
                    chat_id,
                    title,
                    link_code
                )
            )

        conn.commit()

        return link_code

    finally:
        cur.close()
        release_db(conn)


def get_group_by_link(link_code):
    conn = db()

    try:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                chat_id,
                title,
                link_code
            FROM group_chats
            WHERE lower(link_code) = %s
            """,
            (link_code.strip().lower(),)
        )

        return cur.fetchone()

    finally:
        cur.close()
        release_db(conn)


def get_all_groups():
    conn = db()

    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT
                chat_id,
                title,
                link_code
            FROM group_chats
            ORDER BY created_at ASC
        """)

        return cur.fetchall()

    finally:
        cur.close()
        release_db(conn)




# =========================================================
# ADMIN GROUP MESSAGE TOOLS
# =========================================================

def group_admin_menu_keyboard():
    # گزینه‌ها دو ستونه چیده می‌شوند؛ هر دکمه صفحه/مرحله مخصوص خودش را باز می‌کند.
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("ارسال به گروه انتخابی", callback_data="group_broadcast_selected", style="primary"),
            InlineKeyboardButton("ارسال به همه گروه‌ها", callback_data="group_broadcast_all", style="success"),
        ],
        [
            InlineKeyboardButton("افزودن گروه با لینک 🔗", callback_data="group_join_links"),
            InlineKeyboardButton("لغو عملیات ❌", callback_data="group_broadcast_cancel", style="danger"),
        ],
    ])


def group_broadcast_cancel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("لغو ارسال پیام", callback_data="group_broadcast_cancel", style="danger")]
    ])


def group_broadcast_choice_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("دکمه شیشه‌ای می‌خوام 🔗", callback_data="group_broadcast_add_button", style="primary")],
        [InlineKeyboardButton("نمی‌خوام", callback_data="group_broadcast_no_button", style="success")],
        [InlineKeyboardButton("لغو ارسال پیام", callback_data="group_broadcast_cancel", style="danger")],
    ])


def parse_group_link(value):
    value = (value or "").strip()
    if not value:
        return None, None

    if value.startswith("@"):
        return "public", value

    candidate = value
    if "://" not in candidate and candidate.startswith("t.me/"):
        candidate = "https://" + candidate

    try:
        parsed = urlsplit(candidate)
    except Exception:
        return None, None

    host = (parsed.netloc or "").lower()
    if host not in ("t.me", "www.t.me", "telegram.me", "www.telegram.me"):
        return None, None

    path = (parsed.path or "").strip("/")
    if not path:
        return None, None

    if path.startswith("+") or path.startswith("joinchat/"):
        return "private", value

    username = path.split("/", 1)[0]
    if not username or username.startswith("+"):
        return "private", value

    return "public", "@" + username


async def inspect_group_link(bot, raw_link):
    """Resolve public group links and known private invite links; bots cannot join chats by invite URL."""
    kind, value = parse_group_link(raw_link)
    if not kind:
        return {"status": "invalid"}

    chat = None

    if kind == "public":
        try:
            chat = await bot.get_chat(value)
        except TelegramError:
            return {"status": "not_found"}
    else:
        # A bot cannot resolve or join an arbitrary private invite link through the Bot API.
        # We can only match an invite link against a group the bot already knows.
        for chat_id, _title, _code in get_all_groups():
            try:
                candidate = await bot.get_chat(chat_id)
                invite_link = getattr(candidate, "invite_link", None)
                if invite_link and invite_link.rstrip("/") == raw_link.strip().rstrip("/"):
                    chat = candidate
                    break
            except TelegramError:
                continue
        if chat is None:
            return {"status": "private_unresolved"}

    if getattr(chat, "type", None) not in ("group", "supergroup"):
        return {"status": "not_group"}

    try:
        member = await bot.get_chat_member(chat_id=chat.id, user_id=bot.id)
    except TelegramError:
        return {"status": "not_member", "chat": chat}

    if member.status not in (ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER):
        return {"status": "not_member", "chat": chat}

    code = save_group_chat(chat.id, chat.title or "گروه")
    return {"status": "ok", "chat_id": chat.id, "title": chat.title or "گروه", "link_code": code}


async def group_admin_command(update, context):
    user = update.effective_user
    if not user or user.id != ADMIN_ID or not update.effective_message:
        return
    if update.effective_chat and update.effective_chat.type in ("group", "supergroup"):
        return
    context.user_data.clear()
    await update.effective_message.reply_text(
        "🎛 پنل مدیریت پیام‌های گروهی گلدن چت\n\nیکی از گزینه‌ها رو انتخاب کن:",
        reply_markup=group_admin_menu_keyboard()
    )


async def finish_group_broadcast(update, context, button_url=None):
    state = context.user_data
    source_chat_id = state.get("group_broadcast_source_chat_id")
    source_message_id = state.get("group_broadcast_source_message_id")
    mode = state.get("group_broadcast_mode")

    if not source_chat_id or not source_message_id or mode not in ("selected", "all"):
        context.user_data.clear()
        target = update.effective_message
        if target:
            await target.reply_text("درخواست ارسال پیدا نشد؛ از پنل دوباره شروع کن.")
        return

    if mode == "selected":
        selected_id = state.get("group_broadcast_target_chat_id")
        targets = [row for row in get_all_groups() if row[0] == selected_id]
        if not targets and selected_id:
            try:
                chat = await context.bot.get_chat(selected_id)
                targets = [(chat.id, chat.title or "گروه", None)]
            except TelegramError:
                targets = []
    else:
        targets = get_all_groups()

    markup = None
    if button_url:
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("باز کردن لینک 🔗", url=button_url)
        ]])

    sent = 0
    failed = 0
    not_member = 0

    for chat_id, title, _link_code in targets:
        try:
            member = await context.bot.get_chat_member(chat_id=chat_id, user_id=context.bot.id)
            if member.status not in (ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER):
                not_member += 1
                continue

            await context.bot.copy_message(
                chat_id=chat_id,
                from_chat_id=source_chat_id,
                message_id=source_message_id,
                reply_markup=markup,
            )
            sent += 1
        except TelegramError as exc:
            failed += 1
            print(f"[GROUP BROADCAST] Failed chat={chat_id}: {exc}", flush=True)
        except Exception as exc:
            failed += 1
            print(f"[GROUP BROADCAST] Unexpected chat={chat_id}: {type(exc).__name__}: {exc}", flush=True)

    context.user_data.clear()
    summary = (
        "✅ فرایند ارسال تمام شد.\n\n"
        f"ارسال موفق: {sent}\n"
        f"ناموفق: {failed}\n"
        f"ربات عضو نبود: {not_member}"
    )
    target_message = update.effective_message
    if target_message:
        await target_message.reply_text(summary, reply_markup=group_admin_menu_keyboard())
    elif update.callback_query and update.callback_query.message:
        await update.callback_query.message.reply_text(summary, reply_markup=group_admin_menu_keyboard())


async def group_admin_input_handler(update, context):
    """Capture all admin message types while a group-admin flow is waiting for input."""
    user = update.effective_user
    message = update.effective_message

    if not user or user.id != ADMIN_ID or not message:
        return
    if not update.effective_chat or update.effective_chat.type != "private":
        return

    state = context.user_data
    waiting_keys = (
        "group_broadcast_waiting_group_link",
        "group_broadcast_waiting_message",
        "group_broadcast_waiting_button_url",
        "group_join_waiting_links",
    )
    if not any(state.get(key) for key in waiting_keys):
        return

    text = (message.text or "").strip()
    if text.lower() == "/cancel" or text == "لغو ارسال پیام":
        context.user_data.clear()
        await message.reply_text(
            "❌ فرایند لغو شد.",
            reply_markup=group_admin_menu_keyboard()
        )
        raise ApplicationHandlerStop

    if state.get("group_broadcast_waiting_group_link"):
        if not text:
            await message.reply_text(
                "لطفاً لینک عمومی یا خصوصی گروه را به‌صورت متن بفرست.\n"
                "اگر لینک خصوصی قابل شناسایی نباشد، باید گروه قبلاً توسط ربات ثبت شده باشد.",
                reply_markup=group_broadcast_cancel_keyboard()
            )
            raise ApplicationHandlerStop

        result = await inspect_group_link(context.bot, text)
        if result["status"] == "ok":
            state["group_broadcast_waiting_group_link"] = False
            state["group_broadcast_target_chat_id"] = result["chat_id"]
            state["group_broadcast_waiting_message"] = True
            await message.reply_text(
                f"✅ گروه «{result['title']}» شناسایی شد و ربات عضو آن است.\n\n"
                "حالا پیام موردنظرت رو بفرست؛ متن، عکس، ویدئو، فایل و انواع پیام‌های قابل کپی تلگرام پذیرفته می‌شن.",
                reply_markup=group_broadcast_cancel_keyboard()
            )
        elif result["status"] == "not_member":
            chat = result.get("chat")
            title = getattr(chat, "title", None) or "این گروه"
            bot_username = await get_cached_bot_username(context)
            await message.reply_text(
                f"⚠️ ربات عضو «{title}» نیست و نمی‌تونه بهش پیام بفرسته.\n"
                "ربات نمی‌تونه خودش با لینک وارد گروه بشه؛ مدیر گروه باید آن را اضافه کند.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("افزودن ربات به یک گروه", url=f"https://t.me/{bot_username}?startgroup=true")],
                    [InlineKeyboardButton("لغو ارسال پیام", callback_data="group_broadcast_cancel", style="danger")]
                ])
            )
        elif result["status"] == "private_unresolved":
            await message.reply_text(
                "⚠️ از روی لینک دعوت خصوصی به‌تنهایی نمی‌شه گروه رو از طریق Bot API شناسایی کرد.\n"
                "اول ربات رو به گروه اضافه کن و داخل همان گروه دستور /linkgroup رو بزن؛ سپس دوباره لینک رو بفرست.",
                reply_markup=group_broadcast_cancel_keyboard()
            )
        elif result["status"] == "not_group":
            await message.reply_text("این لینک به گروه یا سوپرگروه اشاره نمی‌کنه. لینک گروه رو بفرست.", reply_markup=group_broadcast_cancel_keyboard())
        else:
            await message.reply_text("❌ لینک نامعتبره یا گروه پیدا نشد. لینک دیگری بفرست.", reply_markup=group_broadcast_cancel_keyboard())
        raise ApplicationHandlerStop

    if state.get("group_join_waiting_links"):
        if not text:
            await message.reply_text("لطفاً لینک‌ها رو به‌صورت متن بفرست؛ هر لینک در یک خط.", reply_markup=group_broadcast_cancel_keyboard())
            raise ApplicationHandlerStop

        links = [line.strip() for line in text.splitlines() if line.strip()]
        results = []
        needs_add = False
        for link in links[:50]:
            result = await inspect_group_link(context.bot, link)
            if result["status"] == "ok":
                results.append(f"✅ {result['title']}: ربات از قبل عضو بود و گروه ثبت شد.")
            elif result["status"] == "not_member":
                chat = result.get("chat")
                results.append(f"⚠️ {getattr(chat, 'title', None) or link}: ربات عضو نیست؛ باید مدیر گروه آن را اضافه کند.")
                needs_add = True
            elif result["status"] == "private_unresolved":
                results.append(f"🔒 {link}: لینک خصوصی با Bot API قابل شناسایی یا پیوستن خودکار نیست.")
                needs_add = True
            elif result["status"] == "not_group":
                results.append(f"⚠️ {link}: این لینک گروه نیست.")
            else:
                results.append(f"❌ {link}: لینک نامعتبر یا گروه پیدا نشد.")

        context.user_data.pop("group_join_waiting_links", None)
        report = "نتیجه بررسی لینک‌ها:\n\n" + "\n".join(results)
        if len(links) > 50:
            report += "\n\nبرای جلوگیری از محدودیت تلگرام، در هر نوبت حداکثر ۵۰ لینک بررسی شد."
        keyboard = group_admin_menu_keyboard()
        if needs_add:
            bot_username = await get_cached_bot_username(context)
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("افزودن ربات به گروه", url=f"https://t.me/{bot_username}?startgroup=true")],
                [InlineKeyboardButton("بازگشت به مدیریت گروه‌ها", callback_data="group_admin_open")]
            ])
        await message.reply_text(report[:4000], reply_markup=keyboard)
        raise ApplicationHandlerStop

    if state.get("group_broadcast_waiting_message"):
        state["group_broadcast_waiting_message"] = False
        state["group_broadcast_source_chat_id"] = message.chat_id
        state["group_broadcast_source_message_id"] = message.message_id
        state["group_broadcast_waiting_button_choice"] = True
        await message.reply_text(
            "پیام دریافت شد. دکمه شیشه‌ای داشته باشه؟",
            reply_markup=group_broadcast_choice_keyboard()
        )
        raise ApplicationHandlerStop

    if state.get("group_broadcast_waiting_button_url"):
        parsed = urlsplit(text)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            await message.reply_text(
                "لینک معتبر بفرست؛ باید با https:// یا http:// شروع بشه.",
                reply_markup=group_broadcast_cancel_keyboard()
            )
            raise ApplicationHandlerStop

        await finish_group_broadcast(update, context, button_url=text)
        raise ApplicationHandlerStop

def save_group_message(
    group_id,
    sender_id,
    message_text
):
    conn = db()

    try:
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO group_messages (
                group_id,
                sender_id,
                message_text,
                created_at,
                view_count
            )
            VALUES (
                %s, %s, %s, %s, 0
            )
            RETURNING id
            """,
            (
                group_id,
                sender_id,
                message_text,
                datetime.now()
            )
        )

        message_id = cur.fetchone()[0]

        conn.commit()

        return message_id

    finally:
        cur.close()
        release_db(conn)


def get_group_message(message_id):
    conn = db()

    try:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                id,
                group_id,
                sender_id,
                message_text,
                created_at,
                view_count
            FROM group_messages
            WHERE id = %s
            """,
            (message_id,)
        )

        return cur.fetchone()

    finally:
        cur.close()
        release_db(conn)


def add_group_view(
    message_id,
    viewer_id
):
    conn = db()

    try:
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO group_message_views (
                message_id,
                viewer_id
            )
            VALUES (
                %s, %s
            )
            ON CONFLICT (
                message_id,
                viewer_id
            )
            DO NOTHING
            RETURNING message_id
            """,
            (
                message_id,
                viewer_id
            )
        )

        inserted = cur.fetchone() is not None

        if inserted:
            cur.execute(
                """
                UPDATE group_messages
                SET view_count = view_count + 1
                WHERE id = %s
                RETURNING view_count
                """,
                (message_id,)
            )

        else:
            cur.execute(
                """
                SELECT view_count
                FROM group_messages
                WHERE id = %s
                """,
                (message_id,)
            )

        row = cur.fetchone()

        view_count = row[0] if row else 0

        conn.commit()

        return inserted, view_count

    finally:
        cur.close()
        release_db(conn)


async def is_group_member(
    bot,
    chat_id,
    user_id
):
    try:
        member = await bot.get_chat_member(
            chat_id=chat_id,
            user_id=user_id
        )

        return member.status in (
            ChatMember.MEMBER,
            ChatMember.ADMINISTRATOR,
            ChatMember.OWNER
        )

    except TelegramError as e:
        print(
            f"Group membership error: {e}"
        )
        return False


# =========================================================
# KEYBOARDS
# =========================================================

def main_keyboard():
    rows = [
        [InlineKeyboardButton("دریافت لینک ناشناس 🔗", callback_data="copy_link", style="success")],
        [
            InlineKeyboardButton("تنظیمات نام ⚙️", callback_data="name_settings", style="primary"),
            InlineKeyboardButton("تبلیغات 📢", callback_data="ads", style="primary"),
        ],
        [
            InlineKeyboardButton("کانال پشتیبانی 📣", url="https://t.me/SuppoortGoldenchat", style="primary"),
            InlineKeyboardButton("لیست مسدودی 🚫", callback_data="block_list", style="danger"),
        ],
        [InlineKeyboardButton("« راهنما❔»", callback_data="help")],
    ]
    return InlineKeyboardMarkup(rows)

def admin_main_keyboard():
    """Keep the admin's user-facing main menu identical to the regular user's menu."""
    return main_keyboard()


def back_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("بازگشت 🔙", callback_data="back_main", style="danger")]
    ])


def cancel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("لغو ارسال ", callback_data="cancel_send", style="danger")]
    ])


def join_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("عضویت در کانال رسمی", url=CHANNEL_1_URL)],
        [InlineKeyboardButton("جوین شدم ✅", callback_data="check_join", style="success")],
    ])


def link_keyboard(share_url):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("اشتراک گذاری مستقیم 📤", switch_inline_query=" ", style="success")],
        [InlineKeyboardButton("تعداد بازدید لینک 📊", callback_data="link_stats")],
        [InlineKeyboardButton("بازگشت 🔙", callback_data="back_main", style="danger")],
    ])


def name_settings_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("تغییر نام ✏️", callback_data="change_name", style="primary")],
        [InlineKeyboardButton("بازگشت 🔙", callback_data="back_main", style="danger")],
    ])


def reaction_keyboard(message_id):
    rows = []
    for start in range(0, len(REACTIONS), 4):
        rows.append([
            InlineKeyboardButton(
                reaction,
                callback_data=f"react:{message_id}:{index}"
            )
            for index, reaction in enumerate(REACTIONS[start:start + 4], start=start)
        ])
    rows.append([
        InlineKeyboardButton("بازگشت 🔙", callback_data=f"reaction_back:{message_id}", style="danger")
    ])
    return InlineKeyboardMarkup(rows)


def anonymous_message_keyboard(message_id, sender_id, include_reaction=True, include_seen=True, include_new_message=False):
    rows = []
    if include_reaction:
        rows.append([
            InlineKeyboardButton("ری اکشن :)", callback_data=f"reaction:{message_id}", style="success")
        ])
    if include_seen:
        rows.append([
            InlineKeyboardButton("مشاهده شد 👁️", callback_data=f"seen:{message_id}", style="primary")
        ])
    if include_new_message:
        rows.append([
            InlineKeyboardButton("ارسال پیام جدید 💬", callback_data=f"newmsg:{sender_id}", style="primary")
        ])
    rows.append([
        InlineKeyboardButton("پاسخ دادن 💌", callback_data=f"reply:{message_id}", style="success"),
        InlineKeyboardButton("مسدود کردن 🔴", callback_data=f"block:{sender_id}", style="danger"),
    ])
    rows.append([
        InlineKeyboardButton("گزارش تخلف 🚨", callback_data=f"report:{message_id}", style="danger")
    ])
    return InlineKeyboardMarkup(rows)


def channel_message_keyboard(message_id, sender_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("مسدود کردن 🔴", callback_data=f"block:{sender_id}", style="danger")],
        [InlineKeyboardButton("گزارش تخلف 🚨", callback_data=f"report:{message_id}", style="danger")],
    ])


def group_view_keyboard(message_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("مشاهده پیام 👁️", callback_data=f"group_view:{message_id}")],
        [InlineKeyboardButton("گزارش تخلف 🚨", callback_data=f"group_report:{message_id}", style="danger")],
    ])


def ban_cancel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("لغو عملیات ", callback_data="ban_cancel", style="danger")]
    ])


def ban_duration_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("۱ روز", callback_data="ban_duration:1"),
            InlineKeyboardButton("۳ روز", callback_data="ban_duration:3"),
        ],
        [
            InlineKeyboardButton("۵ روز", callback_data="ban_duration:5"),
            InlineKeyboardButton("۷ روز", callback_data="ban_duration:7"),
        ],
        [InlineKeyboardButton("لغو عملیات ", callback_data="ban_cancel", style="danger")],
    ])


def change_username_confirm_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("متوجه شدم ✅", callback_data="change_username_done", style="success")]
    ])


def channel_profanity_warning_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("بازگشت به پنل اصلی 🔙", callback_data="back_main", style="danger")]
    ])


def main_reply_keyboard():
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton("پیام ناشناس مستقیم به چنل 📬"),
                KeyboardButton("پیام ناشناس به کاربر دلخواه 👤")
            ],
            [
                KeyboardButton("پیام ناشناس به گروه 👥")
            ]
        ],
        resize_keyboard=True
    )


def get_channel_terms_accepted(user_id):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT channel_terms_accepted FROM users WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        return bool(row and row[0])
    finally:
        cur.close()
        release_db(conn)


def set_channel_terms_accepted(user_id):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE users SET channel_terms_accepted = TRUE WHERE user_id = %s", (user_id,))
        conn.commit()
    finally:
        cur.close()
        release_db(conn)


def save_channel_link(owner_id, channel_id, channel_title):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT link_code FROM channel_links WHERE owner_id = %s AND channel_id = %s", (owner_id, channel_id))
        row = cur.fetchone()
        if row:
            code = row[0]
            cur.execute("UPDATE channel_links SET channel_title = %s WHERE owner_id = %s AND channel_id = %s", (channel_title, owner_id, channel_id))
        else:
            while True:
                code = generate_code(10)
                cur.execute("SELECT 1 FROM channel_links WHERE link_code = %s", (code,))
                if not cur.fetchone():
                    break
            cur.execute(
                "INSERT INTO channel_links (owner_id, channel_id, channel_title, link_code) VALUES (%s, %s, %s, %s)",
                (owner_id, channel_id, channel_title, code)
            )
        conn.commit()
        return code
    finally:
        cur.close()
        release_db(conn)


def save_pending_channel_addition(inviter_id, channel_id, channel_title):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO pending_channel_additions (inviter_id, channel_id, channel_title)
            VALUES (%s, %s, %s)
            ON CONFLICT (inviter_id, channel_id)
            DO UPDATE SET channel_title = EXCLUDED.channel_title,
                          created_at = CURRENT_TIMESTAMP
        """, (inviter_id, channel_id, channel_title))
        conn.commit()
    finally:
        cur.close()
        release_db(conn)


def get_pending_channel_additions(inviter_id):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT channel_id, channel_title
            FROM pending_channel_additions
            WHERE inviter_id = %s
            ORDER BY created_at DESC
            LIMIT 20
        """, (inviter_id,))
        return cur.fetchall()
    finally:
        cur.close()
        release_db(conn)


def remove_pending_channel_addition(inviter_id, channel_id):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM pending_channel_additions
            WHERE inviter_id = %s AND channel_id = %s
        """, (inviter_id, channel_id))
        conn.commit()
    finally:
        cur.close()
        release_db(conn)


def get_channel_by_link(code):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT owner_id, channel_id, channel_title, link_code FROM channel_links WHERE lower(link_code) = %s", (code.strip().lower(),))
        return cur.fetchone()
    finally:
        cur.close()
        release_db(conn)


def get_owner_channel_links(owner_id):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT channel_id, channel_title, link_code FROM channel_links WHERE owner_id = %s ORDER BY created_at ASC", (owner_id,))
        return cur.fetchall()
    finally:
        cur.close()
        release_db(conn)


def channel_consent_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("میپذیرم ✅", callback_data="channel_terms_accept", style="success")],
        [InlineKeyboardButton("بازگشت به منوی قبلی", callback_data="channel_menu_back", style="danger")]
    ])


def channel_add_prompt_keyboard(bot_username):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("افزودن ربات به چنل", url=f"https://t.me/{bot_username}?startchannel&admin=post_messages")],
        [InlineKeyboardButton("اضافه شد ✅", callback_data="channel_added", style="success")],
        [InlineKeyboardButton("بازگشت به لیست چنل‌ها", callback_data="channel_add_new_back", style="danger")]
    ])


def channel_links_keyboard(rows):
    buttons = []
    for channel_id, title, code in rows:
        buttons.append([InlineKeyboardButton(f"📬 {title}", callback_data=f"channel_show:{code}")])
    buttons.append([InlineKeyboardButton("اضافه کردن چنل جدید ➕", callback_data="channel_add_new", style="success")])
    buttons.append([InlineKeyboardButton("بازگشت به منوی اصلی ⬅️", callback_data="back_main", style="danger")])
    return InlineKeyboardMarkup(buttons)


async def send_join_message(
    update,
    context
):
    text = (
        "درود و عرض ادب ! 👋\n"
        "خوش اومدی\n\n"
        "برای ادامه استفاده از ربات زحمت بکش "
        "توی کانال زیر جوین شو."
    )

    if update.message:
        await update.message.reply_text(
            text,
            reply_markup=join_keyboard()
        )

    elif update.callback_query:
        await update.callback_query.message.reply_text(
            text,
            reply_markup=join_keyboard()
        )


# =========================================================
# MAIN PANEL
# =========================================================

async def send_main_panel(
    update,
    context,
    show_reply_keyboard=True
):
    text = (
        "<b>درود!\n"
        "شما در پنل اصلی « گلدن چت » هستین.🤠\n\n"
        "میتونید با استفاده از پنل زیر و دکمه های کیبوردی و حتی مینی اپ از قابلیت های ربات استفاده کنید؛⚡\n"
        "ممنون از انتخاب شما 😉</b>\n\n"
        "<blockquote>دریافت مجدد منو با › /start</blockquote>"
    )

    user = update.effective_user
    panel_keyboard = admin_main_keyboard() if user and user.id == ADMIN_ID else main_keyboard()

    if update.message:
        await update.message.reply_text(
            text,
            reply_markup=panel_keyboard,
            parse_mode="HTML"
        )
        if show_reply_keyboard:
            await update.message.reply_text(
                "👇🏻",
                reply_markup=main_reply_keyboard()
            )
    else:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=panel_keyboard,
            parse_mode="HTML"
        )
        if show_reply_keyboard:
            await update.callback_query.message.reply_text(
                "👇🏻",
                reply_markup=main_reply_keyboard()
            )


# =========================================================
# GROUP LIST
# =========================================================

async def show_group_list(
    update,
    context
):
    user = update.effective_user

    buttons = []

    for chat_id, title, link_code in get_all_groups():
        try:
            if await is_group_member(
                context.bot,
                chat_id,
                user.id
            ):
                buttons.append([
                    InlineKeyboardButton(
                        title or "گروه",
                        callback_data=f"group_select:{chat_id}"
                    )
                ])
        except Exception as e:
            print(
                f"Group list error: {e}"
            )

    bot_username = await get_cached_bot_username(context)

    buttons.append([
        InlineKeyboardButton(
            "افزودن ربات به گروه",
            url=f"https://t.me/{bot_username}?startgroup=true"
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            "بازگشت 🔙",
            callback_data="back_main",
            style="danger"
        )
    ])

    keyboard = InlineKeyboardMarkup(buttons)

    text = (
        "<b>اگه توی گروهی باهم عضو بودیم اسم گروها رو این پایین میزارم 👇🏻</b>\n"
        "<b>اگه گروهی نبود روی دکمه افزودن به گروه بزن و دوباره دکمه پیام ناشناس به گروه رو بفرست تا گروهت بیاد</b>"
    )

    if update.message:
        await update.message.reply_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )


# =========================================================
# GROUP BOT ADDED
# =========================================================

async def bot_group_membership_update(
    update,
    context
):
    change = update.my_chat_member

    if not change:
        return

    chat = change.chat

    # Detect a channel where this user has just added the bot.
    # Telegram does not expose all channels owned by a user; this update is
    # the automatic discovery event available to the bot.
    if chat.type == "channel":
        status = change.new_chat_member.status
        inviter = change.from_user
        if status in (ChatMember.ADMINISTRATOR, ChatMember.OWNER) and inviter:
            try:
                inviter_member = await context.bot.get_chat_member(chat.id, inviter.id)
                if inviter_member.status in (ChatMember.ADMINISTRATOR, ChatMember.OWNER):
                    save_pending_channel_addition(inviter.id, chat.id, chat.title or "چنل")
            except TelegramError as e:
                print(f"Channel addition discovery error: {e}")
        return

    if chat.type not in (
        "group",
        "supergroup"
    ):
        return

    status = change.new_chat_member.status

    if status in (
        ChatMember.MEMBER,
        ChatMember.ADMINISTRATOR
    ):
        try:
            save_group_chat(
                chat.id,
                chat.title or "گروه"
            )

            await context.bot.send_message(
                chat_id=chat.id,
                text=(
                    "سلام من گلدن چت هستم.\n"
                    "عضو جدید گروهتون\n"
                    "از الان به بعد کارم ارسال پیام ناشناس به گروهتون 🤠\n\n"
                    "<b>برای دریافت لینک ناشناس گروه شما دستور /linkgroup ارسال کنید و برای گروه پیام ناشناس بفرستید.</b>"
                ),
                parse_mode="HTML"
            )

        except TelegramError as e:
            print(
                f"Group welcome error: {e}"
            )



# =========================================================
# AUTOMATIC GROUP PROMOTIONS
# =========================================================

QUIET_GROUP_MESSAGE_THRESHOLD = 5  # Fewer than 5 human messages in the last four hours is considered quiet.
GROUP_AD_INTERVAL_SECONDS = 10 * 60 * 60
TEHRAN_TZ = ZoneInfo("Asia/Tehran")


async def track_group_activity(update, context):
    """Record human activity in groups without changing normal message handling."""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or chat.type not in ("group", "supergroup"):
        return
    if not user or user.is_bot:
        return
    if message.text and message.text.strip().startswith("/"):
        return

    conn = None
    cur = None
    try:
        conn = db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO group_ad_activity (chat_id, created_at) VALUES (%s, CURRENT_TIMESTAMP)",
            (chat.id,)
        )
        conn.commit()
    except Exception as e:
        print(f"[GROUP ADS] Activity tracking failed for {chat.id}: {e}", flush=True)
    finally:
        if cur:
            cur.close()
        if conn:
            release_db(conn)


def group_ad_button_rows(bot_username, template, group_code):
    if template == "quiet":
        return InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "پیام ناشناس به گروه",
                url=f"https://t.me/{bot_username}?start=g_{group_code}"
            )
        ]])
    if template in ("school", "own_link"):
        return InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "دریافت لینک ناشناس من",
                url=f"https://t.me/{bot_username}?start=ad_home"
            )
        ]])
    if template == "user_target":
        return InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "ارسال پیام به کاربر دلخواه",
                url=f"https://t.me/{bot_username}?start=ad_home"
            )
        ]])
    if template in ("ex_to_user", "channel_auto", "free_ads"):
        button_text = {
            "ex_to_user": "اکست منتظره..",
            "channel_auto": "راحت تر باش😉",
            "free_ads": "تبلیغات رایگان",
        }[template]
        return InlineKeyboardMarkup([[
            InlineKeyboardButton(
                button_text,
                url=f"https://t.me/{bot_username}?start=ad_home"
            )
        ]])
    return None


def school_message_is_allowed():
    now = datetime.now(TEHRAN_TZ)
    # Python weekday: Monday=0 ... Sunday=6. Persian Saturday through Wednesday:
    # Saturday=5, Sunday=6, Monday=0, Tuesday=1, Wednesday=2.
    return now.weekday() in (5, 6, 0, 1, 2) and 8 <= now.hour < 13


async def automatic_group_ads_loop(application):
    """Send at most one automatic promotion to each group every 10 hours."""
    bot = application.bot
    while True:
        try:
            # Keep this periodic database read off the Telegram event loop.
            groups = await asyncio.to_thread(get_all_groups)
            if groups:
                conn = db()
                cur = None
                try:
                    cur = conn.cursor()

                    # Keep the legacy table populated for compatibility with earlier versions.
                    cur.execute("""
                        INSERT INTO group_ad_state (chat_id, last_sent_at)
                        SELECT chat_id, CURRENT_TIMESTAMP FROM group_chats
                        ON CONFLICT (chat_id) DO NOTHING
                    """)

                    # Migrate existing timing once. The last known template keeps its timestamp;
                    # other regular ads are made due, while quiet gets a fresh 26-hour cooldown
                    # unless the last known send was itself the quiet message.
                    cur.execute("""
                        INSERT INTO group_ad_template_state (chat_id, template, last_sent_at)
                        SELECT
                            g.chat_id,
                            t.template,
                            CASE
                                WHEN s.last_template = t.template THEN s.last_sent_at
                                WHEN t.template = 'quiet' THEN CURRENT_TIMESTAMP
                                ELSE CURRENT_TIMESTAMP - INTERVAL '10 hours'
                            END
                        FROM group_chats g
                        CROSS JOIN (VALUES
                            ('linkgroup'),
                            ('user_target'),
                            ('own_link'),
                            ('school'),
                            ('ex_to_user'),
                            ('channel_auto'),
                            ('free_ads'),
                            ('quiet')
                        ) AS t(template)
                        LEFT JOIN group_ad_state s ON s.chat_id = g.chat_id
                        ON CONFLICT (chat_id, template) DO NOTHING
                    """)

                    # Stagger overdue promotion templates when a group is first initialized.
                    # The group-wide cooldown still limits sends to one every 10 hours.
                    cur.execute("""
                        WITH new_groups AS (
                            INSERT INTO group_ad_schedule_meta (chat_id)
                            SELECT chat_id FROM group_chats
                            ON CONFLICT (chat_id) DO NOTHING
                            RETURNING chat_id
                        )
                        UPDATE group_ad_template_state AS state
                        SET last_sent_at = CASE state.template
                            WHEN 'linkgroup' THEN CURRENT_TIMESTAMP - INTERVAL '10 hours'
                            WHEN 'user_target' THEN CURRENT_TIMESTAMP - INTERVAL '9 hours'
                            WHEN 'own_link' THEN CURRENT_TIMESTAMP - INTERVAL '8 hours'
                            WHEN 'school' THEN CURRENT_TIMESTAMP - INTERVAL '7 hours'
                            WHEN 'ex_to_user' THEN CURRENT_TIMESTAMP - INTERVAL '6 hours'
                            WHEN 'channel_auto' THEN CURRENT_TIMESTAMP - INTERVAL '5 hours'
                            WHEN 'free_ads' THEN CURRENT_TIMESTAMP - INTERVAL '4 hours'
                        END
                        FROM new_groups
                        WHERE state.chat_id = new_groups.chat_id
                          AND state.template IN ('linkgroup', 'user_target', 'own_link', 'school', 'ex_to_user', 'channel_auto', 'free_ads')
                          AND state.last_sent_at <= CURRENT_TIMESTAMP - INTERVAL '10 hours'
                    """)
                    conn.commit()
                finally:
                    if cur:
                        cur.close()
                    release_db(conn)

                for chat_id, title, group_code in groups:
                    if not group_code:
                        continue

                    try:
                        member = await bot.get_chat_member(chat_id=chat_id, user_id=bot.id)
                        if member.status not in (ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER):
                            continue

                        conn = db()
                        cur = None
                        try:
                            cur = conn.cursor()

                            # Hard per-group cooldown: one automatic promotion every 10 hours.
                            cur.execute("""
                                SELECT last_sent_at > CURRENT_TIMESTAMP - INTERVAL '10 hours'
                                FROM group_ad_state
                                WHERE chat_id = %s
                            """, (chat_id,))
                            recent_group_ad = cur.fetchone()
                            if recent_group_ad and recent_group_ad[0]:
                                continue

                            cur.execute("""
                                SELECT
                                    template,
                                    last_sent_at,
                                    CASE
                                        WHEN template = 'quiet'
                                            THEN last_sent_at <= CURRENT_TIMESTAMP - INTERVAL '26 hours'
                                        ELSE last_sent_at <= CURRENT_TIMESTAMP - INTERVAL '10 hours'
                                    END AS is_due
                                FROM group_ad_template_state
                                WHERE chat_id = %s
                            """, (chat_id,))
                            states = {
                                row[0]: {"last_sent_at": row[1], "due": bool(row[2])}
                                for row in cur.fetchall()
                            }
                            cur.execute("""
                                SELECT
                                    l.last_sent_at > q.last_sent_at
                                    AND u.last_sent_at > q.last_sent_at
                                FROM group_ad_template_state q
                                JOIN group_ad_template_state l
                                  ON l.chat_id = q.chat_id AND l.template = 'linkgroup'
                                JOIN group_ad_template_state u
                                  ON u.chat_id = q.chat_id AND u.template = 'user_target'
                                WHERE q.chat_id = %s AND q.template = 'quiet'
                            """, (chat_id,))
                            gate_row = cur.fetchone()
                            required_ads_sent_since_quiet = bool(gate_row and gate_row[0])
                        finally:
                            if cur:
                                cur.close()
                            release_db(conn)

                        # Rotate through all eligible promotions by oldest last-send timestamp,
                        # so one template cannot monopolize the 10-hour schedule.
                        template = None
                        text_to_send = None
                        eligible = []

                        for candidate in ("linkgroup", "user_target", "own_link", "school", "ex_to_user", "channel_auto", "free_ads"):
                            if not states.get(candidate, {}).get("due", False):
                                continue
                            if candidate == "school" and not school_message_is_allowed():
                                continue
                            eligible.append(candidate)

                        quiet_due = states.get("quiet", {}).get("due", False)
                        if quiet_due and required_ads_sent_since_quiet:
                            conn = db()
                            cur = None
                            try:
                                cur = conn.cursor()
                                cur.execute("""
                                    SELECT COUNT(*)
                                    FROM group_ad_activity
                                    WHERE chat_id = %s
                                      AND created_at >= CURRENT_TIMESTAMP - INTERVAL '4 hours'
                                """, (chat_id,))
                                activity_count = cur.fetchone()[0]
                            finally:
                                if cur:
                                    cur.close()
                                release_db(conn)
                            if activity_count < QUIET_GROUP_MESSAGE_THRESHOLD:
                                eligible.append("quiet")

                        if eligible:
                            template = min(eligible, key=lambda candidate: states[candidate]["last_sent_at"])
                            if template == "linkgroup":
                                text_to_send = "همین حالا لینک گروه رو بگیر پیام ناشناستو بفرست 👨🏻‍💼 /linkgroup"
                            elif template == "user_target":
                                text_to_send = (
                                    "میدونستین میتونین به کاربر دلخواهتون تو ربات پیام ناشناش بدین؟ 💌\n"
                                    "فقط کافیه توی ربات عضو باشه 🤠"
                                )
                            elif template == "own_link":
                                text_to_send = (
                                    "لینک ناشناستو بگیر و از کیفیت و سرعت ربات لذت ببر👨🏻‍💼\n"
                                    "ادعام میشه بهترینم💁🏻‍♂️"
                                )
                            elif template == "school":
                                text_to_send = (
                                    "زیاد فعال نیستین\n"
                                    "آها یادم نبود مدرسه میرین 😂\n"
                                    "عیب نداره وقتی برگشتین شلوغش کنین"
                                )
                            elif template == "ex_to_user":
                                text_to_send = "به صورت ناشناس به اکست پیام بده تا متوجه نشه 👤"
                            elif template == "channel_auto":
                                text_to_send = (
                                    "با قابلیت ارسال پیام ناشناس خودکار به چنل استفاده از ربات راحت‌تر میشه 😃\n"
                                    "همین الان پیام خودکار به چنل رو فعال کن و لینکت رو به اشتراک بزار"
                                )
                            elif template == "free_ads":
                                text_to_send = "تبلیغات بدون هزینه و رایگان در ربات ⚡"
                            else:
                                text_to_send = (
                                    "چه گروه خلوتی 😩\n"
                                    "کسی حرف سکرت مکرتی\n"
                                    "ناشناسی چیزی نداره؟😭"
                                )

                        # Nothing is due/eligible for this group in this pass.
                        if template is None:
                            continue

                        # Username is cached during startup; avoid an extra Telegram API
                        # round trip for every scheduled group promotion.
                        bot_username = application.bot_data.get("bot_username") or bot.username
                        if not bot_username:
                            bot_info = await bot.get_me()
                            bot_username = bot_info.username
                        markup = group_ad_button_rows(bot_username, template, group_code)
                        await bot.send_message(
                            chat_id=chat_id,
                            text=f"<b>{text_to_send}</b>",
                            parse_mode="HTML",
                            reply_markup=markup,
                            disable_web_page_preview=True
                        )

                        # Only a successful Telegram send advances that template's own timer.
                        conn = db()
                        cur = None
                        try:
                            cur = conn.cursor()
                            cur.execute("""
                                UPDATE group_ad_template_state
                                SET last_sent_at = CURRENT_TIMESTAMP
                                WHERE chat_id = %s AND template = %s
                            """, (chat_id, template))
                            cur.execute("""
                                UPDATE group_ad_state
                                SET last_sent_at = CURRENT_TIMESTAMP, last_template = %s
                                WHERE chat_id = %s
                            """, (template, chat_id))
                            conn.commit()
                        finally:
                            if cur:
                                cur.close()
                            release_db(conn)

                        print(f"[GROUP ADS] Sent template={template} group={chat_id}", flush=True)

                        # Send at most one promotion globally per scheduler pass.
                        # The loop sleeps 60 seconds, so promotions across different
                        # groups are spread out instead of being blasted together.
                        break

                    except TelegramError as e:
                        # Failed sends never advance cooldowns; required messages will retry.
                        print(f"[GROUP ADS] Telegram send/check failed for {chat_id}: {e}", flush=True)
                    except Exception as e:
                        print(f"[GROUP ADS] Failed for {chat_id}: {type(e).__name__}: {e}", flush=True)

            # Keep the activity table bounded.
            try:
                conn = db()
                cur = None
                try:
                    cur = conn.cursor()
                    cur.execute("""
                        DELETE FROM group_ad_activity
                        WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '24 hours'
                    """)
                    conn.commit()
                finally:
                    if cur:
                        cur.close()
                    release_db(conn)
            except Exception as cleanup_error:
                print(f"[GROUP ADS] Activity cleanup failed: {cleanup_error}", flush=True)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[GROUP ADS] Scheduler loop error: {type(e).__name__}: {e}", flush=True)

        await asyncio.sleep(60)

# =========================================================
# LINK GROUP
# =========================================================

async def linkgroup_command(
    update,
    context
):
    chat = update.effective_chat

    if not chat or chat.type not in (
        "group",
        "supergroup"
    ):
        await update.message.reply_text(
            "این دستور باید داخل گروه ارسال شود."
        )
        return

    try:
        bot_member = await context.bot.get_chat_member(
            chat_id=chat.id,
            user_id=context.bot.id
        )

        if bot_member.status not in (
            ChatMember.MEMBER,
            ChatMember.ADMINISTRATOR,
            ChatMember.OWNER
        ):
            await update.message.reply_text(
                "ربات در این گروه عضو نیست."
            )
            return

    except TelegramError:
        await update.message.reply_text(
            "ربات در این گروه عضو نیست."
        )
        return

    code = save_group_chat(
        chat.id,
        chat.title or "گروه"
    )

    bot_username = await get_cached_bot_username(context)

    link = (
        f"https://t.me/{bot_username}"
        f"?start=g_{code}"
    )

    await update.message.reply_text(
        "لینک پیام ناشناش مخصوص برای گروه شما :\n"
        f"{link}"
    )


# =========================================================
# START
# =========================================================

async def start(
    update,
    context
):
    user = update.effective_user

    if not user or not update.message:
        return

    # =====================================================
    # IMPORTANT:
    # /start INSIDE GROUP DOES ABSOLUTELY NOTHING.
    # =====================================================

    chat = update.effective_chat

    if chat and chat.type in (
        "group",
        "supergroup"
    ):
        return

    if user.id != ADMIN_ID:
        ban_info = get_ban_info(user.id)

        if ban_info:
            await update.message.reply_text(
                "حساب کاربری شما مسدود شده است.🟡\n"
                f"علت : {ban_info['reason']}"
            )
            return

    if context.args:
        payload = context.args[0].strip()

        if payload == "ad_home":
            if not await is_member(context.bot, user.id):
                context.user_data["pending_link_payload"] = payload
                await send_join_message(update, context)
                return
            get_or_create_user(user.id, user.username, user.full_name)
            context.user_data.clear()
            await send_main_panel(update, context, show_reply_keyboard=True)
            return

        if payload.startswith("c_"):
            channel = get_channel_by_link(payload[2:])
            if not channel:
                await update.message.reply_text("🥀 لینک پیام ناشناس چنل نامعتبر است.")
                return
            owner_id, channel_id, channel_title, _ = channel
            if owner_id == user.id:
                await update.message.reply_text("🤠 این لینک مخصوص چنل خودته؛ نمی‌تونی برای خودت پیام بفرستی.")
                return
            get_or_create_user(user.id, user.username, user.full_name)
            context.user_data.clear()
            context.user_data["sending_channel_anonymous"] = True
            context.user_data["channel_target_owner_id"] = owner_id
            context.user_data["channel_target_id"] = channel_id
            context.user_data["channel_target_title"] = channel_title
            await update.message.reply_text(
                f"پیام شما به‌صورت ناشناس برای چنل «{channel_title}» ارسال می‌شود. 📬\n"
                "فقط متن یا ویس بفرستید؛ عکس، ویدیو و فایل پشتیبانی نمی‌شود.",
                reply_markup=cancel_keyboard()
            )
            return

        # GROUP LINK

        if payload.startswith("g_"):
            group = get_group_by_link(
                payload[2:]
            )

            if not group:
                await update.message.reply_text(
                    "🥀 لینک گروه نامعتبر است."
                )
                return

            if not await is_member(
                context.bot,
                user.id
            ):
                context.user_data["pending_link_payload"] = payload
                await send_join_message(
                    update,
                    context
                )
                return

            get_or_create_user(user.id, user.username, user.full_name)

            group_id = group[0]
            group_title = group[1] or "گروه"

            if not await is_group_member(
                context.bot,
                group_id,
                user.id
            ):
                await update.message.reply_text(
                    "به نظر میرسه شما عضو این گروه نیستید 🥀",
                    reply_markup=back_keyboard()
                )
                return

            context.user_data.clear()

            context.user_data[
                "sending_group_anonymous"
            ] = True

            context.user_data[
                "group_target_id"
            ] = group_id

            context.user_data[
                "group_target_title"
            ] = group_title

            await update.message.reply_text(
                f"شما درحال ارسال پیام ناشناس به گروه {group_title} هستید .🗨️\n"
                "پیام خود را بنویسید :",
                reply_markup=cancel_keyboard()
            )

            return

        # PRIVATE LINK

        target = get_user_by_link(
            payload
        )

        if not target:
            await update.message.reply_text(
                "🥀 لینک نامعتبر است."
            )
            return

        target_id = target[0]

        if target_id == user.id:
            bot_username = await get_cached_bot_username(context)

            own_link = (
                f"https://t.me/{bot_username}"
                f"?start={user.id}"
            )

            await update.message.reply_text(
                "به خودت که نمیتونی پیام بفرستی زیبا 🥹\n\n"
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
            context.user_data["pending_link_payload"] = payload
            await send_join_message(
                update,
                context
            )
            return

        get_or_create_user(user.id, user.username, user.full_name)
        register_link_view(target_id, user.id)

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
            "پیام خود را بنویسید 💌",
            reply_markup=cancel_keyboard()
        )

        return

    # برای کاربرانی که قبلاً در دیتابیس ثبت نشده‌اند،
    # پیام معرفی کانال رسمی فقط یک بار در اولین /start ارسال می‌شود.
    first_time_user = get_user(user.id) is None

    get_or_create_user(user.id, user.username, user.full_name)
    context.user_data.clear()

    if first_time_user:
        welcome_text = (
            "<b>چنل رسمی گلدن چت و اطلاع رسانی 🤠 📢</b>\n"
            "<b>هیچ جوین اجباری ای نیست و میتونید بدون جوین از ربات استفاده کنید 👨🏻‍💼</b>"
        )
        welcome_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "چنل رسمی گلدن چت",
                    url="https://t.me/SuppoortGoldenchat"
                )
            ]
        ])
        await update.message.reply_text(
            welcome_text,
            reply_markup=welcome_keyboard,
            parse_mode="HTML"
        )

    # پنل اصلی به‌صورت یک پیام جداگانه، زیر پیام معرفی ارسال می‌شود.
    await send_main_panel(
        update,
        context
    )


# =========================================================
# USERBOT
# =========================================================

def userbot_keyboard(
    page,
    total_pages
):
    buttons = []
    nav = []

    if page > 0:
        nav.append(
            InlineKeyboardButton(
                "قبلی",
                callback_data=f"userbot_page:{page - 1}"
            )
        )

    if page < total_pages - 1:
        nav.append(
            InlineKeyboardButton(
                "بعدی",
                callback_data=f"userbot_page:{page + 1}"
            )
        )

    if nav:
        buttons.append(nav)

    return InlineKeyboardMarkup(buttons)


def build_userbot_page(page, viewer_id=None):
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

    start_index = page * per_page
    page_users = users[
        start_index:start_index + per_page
    ]

    parts = []

    for row in page_users:
        user_id = row[0]
        username = row[1]
        full_name = row[2]
        display_name = row[4]
        ban_code = row[5]

        identifier = (
            f"@{username}"
            if username
            else str(user_id)
        )

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
            + (
                f"پیام مستقیم یه کاربر : /massage_{ban_code}\n"
                if viewer_id == ADMIN_ID else ""
            )
            + "____________________________________"
        )

    text = (
        "📋 <b>لیست کاربران ربات</b>\n\n"
        f"صفحه {page + 1} از {total_pages}\n\n"
        + "\n\n".join(parts)
    )

    return (
        text,
        userbot_keyboard(
            page,
            total_pages
        ),
        total_pages
    )


async def userbot_command(
    update,
    context
):
    user = update.effective_user

    if not user or not is_manager_or_supervisor(user.id):
        return

    if update.effective_chat.type in (
        "group",
        "supergroup"
    ):
        return

    text, keyboard, _ = build_userbot_page(0, user.id)

    await update.message.reply_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )


# =========================================================
# DIRECT MESSAGE
# =========================================================

async def send_direct_message(
    bot,
    target_id,
    target_name,
    message_text
):
    safe_name = html.escape(
        target_name or "کاربر"
    )

    safe_message = html.escape(
        message_text
    )

    text = (
        "<b>پیام از طرف مدیریت : 📢</b>\n"
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
# BAN LIST
# =========================================================

async def userban_command(
    update,
    context
):
    user = update.effective_user

    if not user or not is_manager_or_supervisor(user.id):
        return

    if update.effective_chat.type in (
        "group",
        "supergroup"
    ):
        return

    rows = get_active_banned_users()

    if not rows:
        await update.message.reply_text(
            "🟢 در حال حاضر هیچ کاربری بن نیست."
        )
        return

    parts = []

    for row in rows:
        user_id = row[0]
        username = row[1]
        ban_code = row[2]

        identifier = (
            f"@{username}"
            if username
            else str(user_id)
        )

        parts.append(
            "کاربر با آیدی : "
            f"{identifier}\n\n"
            "کد رفع بنی : "
            f"/unban_{ban_code}"
        )

    text = (
        "\n\n"
        "________________________________\n\n"
    ).join(parts)

    for i in range(0, len(text), 3900):
        await update.message.reply_text(
            text[i:i + 3900]
        )


# =========================================================
# BROADCAST
# =========================================================

async def broadcast_command(
    update,
    context
):
    user = update.effective_user

    if not user or not is_manager_or_supervisor(user.id):
        return

    if update.effective_chat.type in (
        "group",
        "supergroup"
    ):
        return

    context.user_data.clear()

    if is_supervisor(user.id):
        context.user_data["waiting_supervisor_broadcast"] = True
        await update.message.reply_text(
            "📢 متن پیام همگانی را وارد کنید :",
            reply_markup=back_keyboard()
        )
        return

    context.user_data["waiting_broadcast"] = True
    await update.message.reply_text(
        "📢 حالت ارسال پیام همگانی فعال شد.\n\n"
        "پیامی که می‌خوای برای همه کاربران ارسال بشه رو بفرست.\n"
        "برای لغو بنویس: /cancel"
    )


# =========================================================
# CHANGE USERNAME / DISPLAY NAME (ADMIN)
# =========================================================

async def changeusername_command(
    update,
    context
):
    user = update.effective_user

    if not user or not is_manager_or_supervisor(user.id):
        return

    if update.effective_chat.type in (
        "group",
        "supergroup"
    ):
        return

    context.user_data.clear()
    context.user_data["change_username_waiting_code"] = True

    await update.message.reply_text(
        "لطفا شناسه کاربری شخص را وارد کنید :",
        reply_markup=back_keyboard()
    )


# =========================================================
# SUPERVISOR COMMANDS / MANAGEMENT
# =========================================================

async def cdb_command(update, context):
    user = update.effective_user
    if not user or not is_supervisor(user.id):
        return
    if update.effective_chat.type in ("group", "supergroup"):
        return
    await update.message.reply_text(SUPERVISOR_COMMANDS_TEXT)


async def addadmin_command(update, context):
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return
    if update.effective_chat.type in ("group", "supergroup"):
        return
    context.user_data.clear()
    await update.message.reply_text(
        "به پنل افزودن ناظر خوش امدید‌\nمدیریت ناظران ربات از پنل شیشه ای",
        reply_markup=supervisor_panel_keyboard()
    )


# =========================================================
# CANCEL COMMAND
# =========================================================

async def cancel_command(
    update,
    context
):
    if update.effective_chat.type in (
        "group",
        "supergroup"
    ):
        return

    context.user_data.clear()

    await update.message.reply_text(
        "لغو شد.\nاز منوی بالا و پایین استفاده کنید.👇🏻👆🏻"
    )


# =========================================================
# HELP
# =========================================================

async def help_page(
    update,
    context
):
    text = (
        "<b>راهنمای گلدن چت 👻\n"
        "سرعت و کیفیت بالا</b>\n\n"
        "<blockquote><b>دریافت لینک : شما با دریافت لینک اختصاصی خودتون و با اشتراک گذاشتنش توی بقیه گروه ها و کانال ها و حتی بایو اکانتتون پیام های ناشناس از افراد مختلف که روشون نمیشد مستقیم بهت پیام بدن دریافت میکنی .🤠</b></blockquote>\n"
        "<blockquote><b>تنظیم نام : میتونی یک اسم برای حساب خودت انتخاب کنی که وقتی لینکت رو جایی به اشتراک میزاری بقیه روی لینکت کلیک میکنن نام نمایشی تو براشون نشون داده بشه 🙍🏻‍♂️</b></blockquote>\n"
        "<blockquote><b>تبلیغات : تبلیغات غیرفعال و به زودی فعال میشه یه صورت رفرالی و پولی</b></blockquote>\n"
        "<blockquote><b>ری اکشن : این قابلیت متفاوته وقتی کاربری بهت پیام میده و حوصله جواب دادنش رو نداری میتونس با ری اکشن جوابش رو بدی😄</b></blockquote>\n"
        "<blockquote><b>ارسال پیام ناشناس به گروه : به راحتی بدون اینکه شناخته بشی برای گروهت ناشناش پیام بفرست و لینک ناشناس گروه رو بزار تا بقیه ناشناس برای گروهت پیام بفرستن</b></blockquote>\n"
        "<blockquote><b>ارسال پیام ناشناش برای چنل :\n"
        "دیگه نیازی نیست به صورت دستی پیام هارو فور بزنی به چنل\n"
        "لینک ناشناس چنلت رو اپلود کن و مستقیم ربات اتومات برای چنل میفرسته « راستی هیچ بی احترامی نمیشه چون تشخیص فوش و بی احترامی هست و اگر به احترامی بشه پیام برای چنل ارسال نمیشه »</b></blockquote>\n"
        "<blockquote><b>در ضمن گزارش تخلف :\n"
        "هرگونه بی احترامی، پخش عکس شخصی، تهدید با عکسهای شخصی، تهدید با حرف، و باقی اذیت و آزار ها گزارش بشه بررسی میشه چه گزارش تخلف چه گزارش به پیوی ادمین 🥹❤️</b></blockquote>"
    )

    await update.callback_query.edit_message_text(
        text,
        reply_markup=back_keyboard(),
        parse_mode="HTML"
    )


# =========================================================
# ADS
# =========================================================

async def ads_page(
    update,
    context
):
    await update.callback_query.answer(
        "تبلیغات غیرفعال شده است.\nبه زودی فعال میشود\nدرحال آپدیت🫟",
        show_alert=True
    )


# =========================================================
# LINK
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

    bot_username = await get_cached_bot_username(context)

    link = (
        f"https://t.me/{bot_username}"
        f"?start={user.id}"
    )

    share_text = (
        "حوووصلم سر رفته بیاین حرف بزنیم🗣️🥀\n\n"
        "G O L D E N  C H A T"
    )
    share_url = (
        "https://t.me/share/url?url="
        + quote(link, safe="")
        + "&text="
        + quote(share_text, safe="")
    )

    await update.callback_query.edit_message_text(
        "<b>🔗 لینک اختصاصی شما :</b>\n\n"
        f'<a href="{html.escape(link, quote=True)}">{html.escape(link)}</a>\n\n'
        "لینک خود را با دیگران به اشتراک بگذارید "
        "تا بتوانند به صورت ناشناس برای شما پیام بفرستند.\n\n"
        "<b>میتونید با زدن روی اشتراک گذاری مستقیم متن آماده و لینک آماده برای بقیه ارسال کنید💌</b>",
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=link_keyboard(share_url)
    )


# =========================================================
# NAME
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
        f"نام فعلی شما:\n{current_name}\n\n"
        "این نام هنگام ارسال پیام ناشناس "
        "به فرستنده نمایش داده می‌شود.",
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
# CALLBACK HANDLER
# =========================================================

async def button_handler(
    update,
    context
):
    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    user_id = user.id
    data = query.data or ""

    # =====================================================
    # GROUP CALLBACK SAFETY
    # =====================================================
    # داخل گروه فقط مشاهده پیام و گزارش تخلف مجاز است.
    # هیچ callback مربوط به پنل خصوصی نباید در گروه اجرا شود.
    # =====================================================

    chat = query.message.chat if query.message else None

    if chat and chat.type in (
        "group",
        "supergroup"
    ):
        if not (
            data.startswith("group_view:")
            or data.startswith("group_report:")
        ):
            await query.answer()
            return


    # -----------------------------------------------------
    # ADMIN GROUP MESSAGE TOOLS
    # -----------------------------------------------------
    if data in (
        "group_admin_open",
        "group_broadcast_cancel",
        "group_broadcast_selected",
        "group_broadcast_all",
        "group_join_links",
        "group_broadcast_add_button",
        "group_broadcast_no_button",
    ):
        if user_id != ADMIN_ID:
            await query.answer("⛔️ دسترسی مجاز نیست.", show_alert=True)
            return

        if data == "group_admin_open":
            await query.answer()
            context.user_data.clear()
            await query.edit_message_text(
                "🎛 پنل مدیریت پیام‌های گروهی گلدن چت\n\nیکی از گزینه‌ها رو انتخاب کن:",
                reply_markup=group_admin_menu_keyboard()
            )
            return

        if data == "group_broadcast_cancel":
            await query.answer("فرایند لغو شد.")
            context.user_data.clear()
            await query.edit_message_text(
                "❌ فرایند لغو شد.\n\nاز پنل زیر می‌تونی دوباره شروع کنی:",
                reply_markup=group_admin_menu_keyboard()
            )
            return

        if data == "group_broadcast_selected":
            await query.answer()
            context.user_data.clear()
            context.user_data["group_broadcast_mode"] = "selected"
            context.user_data["group_broadcast_waiting_group_link"] = True
            await query.edit_message_text(
                "🔗 اول لینک گروه رو بفرست.\n"
                "ربات عضویت خودش رو بررسی می‌کنه و فقط اگر عضو گروه باشه، مرحله دریافت پیام شروع می‌شه.\n\n"
                "لینک عمومی قابل شناسایی است؛ لینک خصوصی باید با گروه ثبت‌شده تطبیق داشته باشد.",
                reply_markup=group_broadcast_cancel_keyboard()
            )
            return

        if data == "group_broadcast_all":
            await query.answer()
            context.user_data.clear()
            context.user_data["group_broadcast_mode"] = "all"
            context.user_data["group_broadcast_waiting_message"] = True
            await query.edit_message_text(
                "📨 پیام موردنظرت رو بفرست.\n"
                "متن، قالب‌بندی، لینک، عکس، ویدئو و فایل‌های قابل کپی پذیرفته می‌شن.\n\n"
                "بعدش انتخاب می‌کنی دکمه شیشه‌ای داشته باشه یا نه.",
                reply_markup=group_broadcast_cancel_keyboard()
            )
            return

        if data == "group_join_links":
            await query.answer()
            context.user_data.clear()
            context.user_data["group_join_waiting_links"] = True
            await query.edit_message_text(
                "🔗 لینک یک گروه یا فهرستی از لینک‌ها رو بفرست؛ هر لینک در یک خط.\n\n"
                "نکته: تلگرام اجازه نمی‌ده ربات با لینک دعوت خودش وارد گروه بشه. این بخش لینک‌ها رو بررسی می‌کنه و گروه‌هایی رو که ربات از قبل عضو آن‌هاست ثبت می‌کنه؛ برای بقیه باید مدیر ربات رو اضافه کنه.",
                reply_markup=group_broadcast_cancel_keyboard()
            )
            return

        if data == "group_broadcast_add_button":
            await query.answer()
            if not context.user_data.get("group_broadcast_waiting_button_choice"):
                await query.message.reply_text("درخواست فعالی وجود نداره؛ از پنل دوباره شروع کن.")
                return
            context.user_data["group_broadcast_waiting_button_choice"] = False
            context.user_data["group_broadcast_waiting_button_url"] = True
            await query.edit_message_text(
                "لینک مقصد دکمه شیشه‌ای رو بفرست (با https:// یا http:// شروع بشه).",
                reply_markup=group_broadcast_cancel_keyboard()
            )
            return

        if data == "group_broadcast_no_button":
            await query.answer("پیام بدون دکمه ارسال می‌شود.")
            if not context.user_data.get("group_broadcast_waiting_button_choice"):
                await query.message.reply_text("درخواست فعالی وجود نداره؛ از پنل دوباره شروع کن.")
                return
            context.user_data["group_broadcast_waiting_button_choice"] = False
            await finish_group_broadcast(update, context)
            return

    # -----------------------------------------------------
    # CHANNEL FEATURE CONSENT / SETUP
    # -----------------------------------------------------
    if data == "channel_add_new_back":
        await query.answer()
        context.user_data.clear()
        rows = get_owner_channel_links(user_id)
        bot_username = await get_cached_bot_username(context)
        parts = ["<b>چنل‌های متصل شما و لینک اختصاصی پیام ناشناس:</b>"]
        if rows:
            for _, title, code in rows:
                parts.append(f"\n<b>نام چنل :</b> {html.escape(title)}\n<b>لینک اختصاصی پیام ناشناس چنل :</b> https://t.me/{bot_username}?start=c_{code}")
        else:
            parts.append("\nهنوز چنلی اضافه نکردی؛ برای شروع روی «اضافه کردن چنل جدید ➕» بزن.")
        await query.edit_message_text("\n".join(parts), parse_mode="HTML", reply_markup=channel_links_keyboard(rows), disable_web_page_preview=True)
        return

    if data == "channel_menu_back":
        await query.answer()
        context.user_data.clear()
        await send_main_panel(update, context, show_reply_keyboard=True)
        return

    if data == "channel_terms_accept":
        await query.answer("موافقت شما ثبت شد ✅")
        set_channel_terms_accepted(user_id)
        bot_username = await get_cached_bot_username(context)
        context.user_data.clear()
        await query.edit_message_text(
            "<b>برای دریافت لینک ناشناس چنل، ابتدا ربات را با دکمه شیشه‌ای زیر به چنل اضافه و ادمین کن 🤠</b>\n\n"
            "بعد از ادمین کردن، روی «اضافه شد ✅» بزن و سپس آیدی عمومی چنل مثل @YourChannel را ارسال کن.",
            parse_mode="HTML",
            reply_markup=channel_add_prompt_keyboard(bot_username)
        )
        return

    if data == "channel_add_new":
        await query.answer()
        context.user_data.clear()
        bot_username = await get_cached_bot_username(context)
        await query.edit_message_text(
            "<b>برای دریافت لینک ناشناس چنل، ابتدا ربات را با دکمه شیشه‌ای زیر به چنل اضافه و ادمین کن 🤠</b>\n\n"
            "بعد از ادمین کردن، روی «اضافه شد ✅» بزن.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("افزودن ربات به چنل", url=f"https://t.me/{bot_username}?startchannel&admin=post_messages")],
                [InlineKeyboardButton("اضافه شد ✅", callback_data="channel_added", style="success")],
                [InlineKeyboardButton("بازگشت به منوی قبلی", callback_data="channel_add_new_back", style="danger")]
            ])
        )
        return

    if data == "channel_added":
        await query.answer()
        context.user_data.clear()
        candidates = get_pending_channel_additions(user_id)
        connected = []
        for candidate_id, candidate_title in candidates:
            try:
                bot_member = await context.bot.get_chat_member(candidate_id, context.bot.id)
                owner_member = await context.bot.get_chat_member(candidate_id, user_id)
                if bot_member.status not in (ChatMember.ADMINISTRATOR, ChatMember.OWNER):
                    continue
                if owner_member.status not in (ChatMember.ADMINISTRATOR, ChatMember.OWNER):
                    continue
                if hasattr(bot_member, "can_post_messages") and bot_member.can_post_messages is False:
                    continue
                save_channel_link(user_id, candidate_id, candidate_title)
                remove_pending_channel_addition(user_id, candidate_id)
                connected.append(candidate_title)
            except TelegramError:
                continue

        if connected:
            bot_username = await get_cached_bot_username(context)
            rows = get_owner_channel_links(user_id)
            parts = ["<b>چنل‌های متصل شما و لینک اختصاصی پیام ناشناس:</b>"]
            for _, title, code in rows:
                parts.append(f"\n<b>نام چنل :</b> {html.escape(title)}\n<b>لینک اختصاصی پیام ناشناس چنل :</b> https://t.me/{bot_username}?start=c_{code}")
            await query.edit_message_text("\n".join(parts), parse_mode="HTML", reply_markup=channel_links_keyboard(rows), disable_web_page_preview=True)
            return

        context.user_data["waiting_channel_identifier"] = True
        await query.edit_message_text(
            "<b>هنوز ربات از رویداد افزودن چنل نتونسته چنل شما رو شناسایی کنه.</b>\n"
            "اگر همین الان ربات رو ادمین کردی، دوباره امتحان کن. اگر باز هم شناسایی نشد، آیدی عمومی چنل مثل @YourChannel یا شناسه عددی چنل خصوصی رو بفرست.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("بازگشت به لیست چنل‌ها", callback_data="channel_add_new_back", style="danger")]
            ])
        )
        return

    if data.startswith("channel_show:"):
        await query.answer()
        code = data.split(":", 1)[1]
        bot_username = await get_cached_bot_username(context)
        row = get_channel_by_link(code)
        if not row or row[0] != user_id:
            await query.message.reply_text(" چنل پیدا نشد.")
            return
        await query.message.reply_text(
            f"<b>نام چنل :</b> {html.escape(row[2])}\n"
            f"<b>لینک اختصاصی پیام ناشناس چنل :</b> https://t.me/{bot_username}?start=c_{row[3]}",
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("اضافه کردن چنل جدید ➕", callback_data="channel_add_new", style="success")],
                [InlineKeyboardButton("بازگشت به منوی اصلی ⬅️", callback_data="back_main", style="danger")]
            ])
        )
        return

    # -----------------------------------------------------
    # JOIN
    # -----------------------------------------------------

    if data == "check_join":
        if not await is_member(
            context.bot,
            user_id
        ):
            await query.answer(
                "هنوز توی کانال عضو نشدی🤠💔",
                show_alert=True
            )
            return

        await query.answer(
            "عضویت شما تأیید شد ✅"
        )

        # فقط بعد از تأیید کامل عضویت، کاربر وارد users می‌شود.
        # پیام جوین اجباری نیز مستقیماً با پنل اصلی جایگزین می‌شود.
        context.user_data.clear()
        get_or_create_user(
            user_id,
            user.username,
            user.full_name
        )

        await send_main_panel(
            update,
            context,
            show_reply_keyboard=True
        )

        return

    # -----------------------------------------------------
    # CHANGE USERNAME DONE
    # -----------------------------------------------------

    if data == "change_username_done":
        await query.answer("انجام شد ✅")
        context.user_data.clear()

        text = (
            "<b>درود!\n"
            "شما در پنل اصلی « گلدن چت » هستین.🤠\n\n"
            "میتونید با استفاده از پنل زیر و دکمه های کیبوردی و حتی مینی اپ از قابلیت های ربات استفاده کنید؛⚡\n"
            "ممنون از انتخاب شما 😉</b>\n\n"
            "<blockquote>دریافت مجدد منو با › /start</blockquote>"
        )

        await query.message.edit_text(
            text,
            reply_markup=main_keyboard(),
            parse_mode="HTML"
        )
        return

    # -----------------------------------------------------
    # SUPERVISOR MANAGEMENT
    # -----------------------------------------------------

    if data == "supervisor_add":
        if user_id != ADMIN_ID:
            await query.answer("دسترسی ندارید ", show_alert=True); return
        context.user_data.clear()
        context.user_data["supervisor_add_waiting_identifier"] = True
        await query.answer()
        await query.edit_message_text("آیدی تلگرام شخص یا شناسه کاربری را وارد کنید :", reply_markup=back_keyboard())
        return

    if data.startswith("supervisor_select:"):
        if user_id != ADMIN_ID:
            await query.answer("دسترسی ندارید ", show_alert=True); return
        try: target_id = int(data.split(":", 1)[1])
        except (ValueError, IndexError):
            await query.answer("شناسه نامعتبر است ", show_alert=True); return
        if target_id == ADMIN_ID or not is_supervisor(target_id):
            await query.answer("ناظر پیدا نشد ", show_alert=True); return
        name = html.escape(supervisor_display_name(target_id))
        await query.answer()
        await query.edit_message_text(
            "آیا قصد حذف ادمین را دارید؟\nبله ✅  خیر ✖️",
            reply_markup=supervisor_delete_keyboard(target_id)
        )
        return

    if data.startswith("supervisor_delete_yes:"):
        if user_id != ADMIN_ID:
            await query.answer("دسترسی ندارید ", show_alert=True); return
        try: target_id = int(data.split(":", 1)[1])
        except (ValueError, IndexError):
            await query.answer("شناسه نامعتبر است ", show_alert=True); return
        context.user_data.clear()
        context.user_data["supervisor_remove_waiting_reason"] = True
        context.user_data["supervisor_remove_target_id"] = target_id
        await query.answer()
        await query.edit_message_text("علت حذف را وارد کنید:", reply_markup=back_keyboard())
        return

    if data == "supervisor_delete_no":
        if user_id != ADMIN_ID:
            await query.answer("دسترسی ندارید ", show_alert=True); return
        context.user_data.clear()
        await query.answer()
        await query.edit_message_text(
            "به پنل افزودن ناظر خوش امدید‌\nمدیریت ناظران ربات از پنل شیشه ای",
            reply_markup=supervisor_panel_keyboard()
        )
        return

    if data.startswith("manager_approve:") or data.startswith("manager_reject:"):
        if user_id != ADMIN_ID:
            await query.answer("دسترسی ندارید ", show_alert=True); return
        parts = data.split(":")
        if len(parts) != 3:
            await query.answer("درخواست نامعتبر است ", show_alert=True); return
        action, kind, request_id = parts[0], parts[1], parts[2]
        try: request_id = int(request_id)
        except ValueError:
            await query.answer("درخواست نامعتبر است ", show_alert=True); return
        approved = action == "manager_approve"
        if kind == "unban":
            req = get_unban_request(request_id)
            if not req or req[6] != "pending":
                await query.answer("این درخواست قبلاً بررسی شده است.", show_alert=True); return
            if approved:
                target_id = unban_user_by_code(req[3])
                if target_id:
                    set_unban_request_status(request_id, "approved")
                    await query.answer("رفع بن تأیید شد ✅")
                    await query.message.edit_text("🟢 درخواست رفع بن با موفقیت تأیید شد.")
                    try:
                        await context.bot.send_message(chat_id=req[1], text=f"درخواست رفع بن کاربر {req[4] or 'کاربر'} توسط مدیر تأیید شد.✅")
                    except TelegramError: pass
                    try:
                        await context.bot.send_message(chat_id=target_id, text="مسدودی حساب کاربری شما توسط مدیر رفع شد.\nاکنون حساب کاربری شما به حالت سبز در آمده 🟢\nمیتوانید از قابلیت های ربات استفاده کنید /start")
                    except TelegramError: pass
                else:
                    set_unban_request_status(request_id, "rejected")
                    await query.answer("کاربر دیگر بن نیست.", show_alert=True)
                return
            set_unban_request_status(request_id, "rejected")
            await query.answer("درخواست رد شد ")
            await query.message.edit_text(
                "<b>درود!\nشما در پنل اصلی « گلدن چت » هستین.🤠\n\nمیتونید با استفاده از پنل زیر و دکمه های کیبوردی و حتی مینی اپ از قابلیت های ربات استفاده کنید؛⚡\nممنون از انتخاب شما 😉</b>\n\n<blockquote>دریافت مجدد منو با › /start</blockquote>",
                reply_markup=main_keyboard(), parse_mode="HTML"
            )
            try:
                await context.bot.send_message(chat_id=req[1], text=f"درخواست رفع بن کاربر ( {req[4] or 'کاربر'} ) توسط مدیر تایید نشد🛑")
            except TelegramError: pass
            return
        if kind == "broadcast":
            req = get_broadcast_request(request_id)
            if not req or req[3] != "pending":
                await query.answer("این درخواست قبلاً بررسی شده است.", show_alert=True); return
            if approved:
                set_broadcast_request_status(request_id, "approved")
                await query.answer("پیام همگانی تأیید شد ✅")
                await query.message.edit_text("📢 درخواست پیام همگانی تأیید شد؛ ارسال آغاز شد...")
                success = failed = 0
                for target_id in get_all_user_ids():
                    try:
                        await context.bot.send_message(chat_id=target_id, text=req[2])
                        success += 1
                    except TelegramError:
                        failed += 1
                    await asyncio.sleep(0.03)
                await query.message.edit_text(f"✅ پیام همگانی ارسال شد.\n\nموفق: {success}\nناموفق: {failed}\nکل کاربران: {success + failed}")
                try:
                    await context.bot.send_message(chat_id=req[1], text=f"پیام همگانی شما توسط مدیر تأیید و ارسال شد.✅\nموفق: {success}\nناموفق: {failed}")
                except TelegramError: pass
                return
            set_broadcast_request_status(request_id, "rejected")
            await query.answer("درخواست رد شد ")
            await query.message.edit_text(
                "<b>درود!\nشما در پنل اصلی « گلدن چت » هستین.🤠\n\nمیتونید با استفاده از پنل زیر و دکمه های کیبوردی و حتی مینی اپ از قابلیت های ربات استفاده کنید؛⚡\nممنون از انتخاب شما 😉</b>\n\n<blockquote>دریافت مجدد منو با › /start</blockquote>",
                reply_markup=main_keyboard(), parse_mode="HTML"
            )
            try:
                await context.bot.send_message(chat_id=req[1], text="درخواست ارسال پیام همگانی شما توسط مدیر تایید نشد🛑")
            except TelegramError: pass
            return

    if data == "supervisor_target_ok":
        await query.answer("انجام شد ✅")
        context.user_data.clear()
        await query.message.edit_text(
            "<b>درود!\nشما در پنل اصلی « گلدن چت » هستین.🤠\n\n"
            "میتونید با استفاده از پنل زیر و دکمه های کیبوردی و حتی مینی اپ از قابلیت های ربات استفاده کنید؛⚡\n"
            "ممنون از انتخاب شما 😉</b>\n\n"
            "<blockquote>دریافت مجدد منو با › /start</blockquote>",
            reply_markup=main_keyboard(), parse_mode="HTML"
        )
        return

    # -----------------------------------------------------
    # CLOSE SUPERVISOR PANEL -> MAIN PANEL
    # -----------------------------------------------------

    if data == "supervisor_close_panel":
        if user_id != ADMIN_ID:
            await query.answer("دسترسی ندارید ", show_alert=True)
            return

        await query.answer("پنل بسته شد ✅")
        context.user_data.clear()

        text = (
            "<b>درود!\n"
            "شما در پنل اصلی « گلدن چت » هستین.🤠\n\n"
            "میتونید با استفاده از پنل زیر و دکمه های کیبوردی و حتی مینی اپ از قابلیت های ربات استفاده کنید؛⚡\n"
            "ممنون از انتخاب شما 😉</b>\n\n"
            "<blockquote>دریافت مجدد منو با › /start</blockquote>"
        )

        await query.message.edit_text(
            text,
            reply_markup=main_keyboard(),
            parse_mode="HTML"
        )
        return

    # -----------------------------------------------------
    # BACK
    # -----------------------------------------------------

    if data == "back_main":
        await query.answer()
        context.user_data.clear()

        text = (
            "<b>درود!\n"
            "شما در پنل اصلی « گلدن چت » هستین.🤠\n\n"
            "میتونید با استفاده از پنل زیر و دکمه های کیبوردی و حتی مینی اپ از قابلیت های ربات استفاده کنید؛⚡\n"
            "ممنون از انتخاب شما 😉</b>\n\n"
            "<blockquote>دریافت مجدد منو با › /start</blockquote>"
        )

        # فقط همان پیام فعلی ویرایش می‌شود؛ پیام جدید و 👇🏻 ارسال نمی‌شود.
        await query.message.edit_text(
            text,
            reply_markup=main_keyboard(),
            parse_mode="HTML"
        )
        return

    # -----------------------------------------------------
    # CANCEL SEND
    # -----------------------------------------------------

    if data == "cancel_send":
        await query.answer(
            "لغو شد "
        )

        context.user_data.clear()

        await query.message.reply_text(
            "لغو شد.\nاز منوی بالا و پایین استفاده کنید.👇🏻👆🏻"
        )

        await send_main_panel(
            update,
            context,
            show_reply_keyboard=False
        )

        return

    # -----------------------------------------------------
    # GROUP LIST BACK
    # -----------------------------------------------------

    if data == "group_list_back":
        await query.answer()

        context.user_data.clear()

        await show_group_list(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # GROUP SELECT
    # -----------------------------------------------------

    if data.startswith("group_select:"):
        try:
            group_id = int(
                data.split(":", 1)[1]
            )
        except (ValueError, IndexError):
            await query.answer(
                "گروه نامعتبر است ",
                show_alert=True
            )
            return

        group = None

        for row in get_all_groups():
            if row[0] == group_id:
                group = row
                break

        if not group:
            await query.answer(
                "گروه پیدا نشد ",
                show_alert=True
            )
            return

        if not await is_group_member(
            context.bot,
            group_id,
            user_id
        ):
            await query.answer(
                "شما عضو این گروه نیستید ",
                show_alert=True
            )
            return

        await query.answer()

        context.user_data.clear()

        context.user_data[
            "sending_group_anonymous"
        ] = True

        context.user_data[
            "group_target_id"
        ] = group_id

        context.user_data[
            "group_target_title"
        ] = group[1] or "گروه"

        await query.edit_message_text(
            f"اوکی گروه {group[1] or 'گروه'} انتخاب شد حالا پیامت رو بنویس تا توی گروه ارسال کنم :",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "بازگشت 🔙",
                        callback_data="group_list_back",
                        style="danger"
                    )
                ]
            ])
        )

        return

    # -----------------------------------------------------
    # GROUP VIEW
    # -----------------------------------------------------

    if data.startswith("group_view:"):
        try:
            message_id = int(
                data.split(":", 1)[1]
            )
        except (ValueError, IndexError):
            await query.answer(
                "پیام نامعتبر است ",
                show_alert=True
            )
            return

        group_message = get_group_message(
            message_id
        )

        if not group_message:
            await query.answer(
                "این پیام دیگر موجود نیست ",
                show_alert=True
            )
            return

        group_id = group_message[1]
        message_text = group_message[3]

        if not await is_group_member(
            context.bot,
            group_id,
            user_id
        ):
            safe_name = html.escape(
                user.full_name or "کاربر"
            )

            text = (
                f'<b>کاربر '
                f'<a href="tg://user?id={user_id}">'
                f'{safe_name}'
                f'</a> جهت مشاهده پیام عضو ربات شوید سپس مجدد روی «مشاهده پیام بزنید» . 👇🏻</b>\n'
                f'<b><a href="https://t.me/HideMyChatRobot?start">'
                f'https://t.me/HideMyChatRobot?start'
                f'</a></b>'
            )

            await query.message.reply_text(
                text,
                parse_mode="HTML"
            )

            await query.answer()

            return

        inserted, view_count = add_group_view(
            message_id,
            user_id
        )

        await query.answer(
            message_text,
            show_alert=True
        )

        try:
            await query.message.edit_text(
                "<b>گروه شما یک پیام ناشناش جدید دارد 🤠</b>\n\n"
                f"<b>این پیام توسط {view_count} نفر مشاهده شد‌.</b>",
                reply_markup=group_view_keyboard(
                    message_id
                ),
                parse_mode="HTML"
            )
        except TelegramError as e:
            print(
                f"Group view edit error: {e}"
            )

        return

    # -----------------------------------------------------
    # GROUP REPORT
    # -----------------------------------------------------

    if data.startswith("group_report:"):
        try:
            message_id = int(
                data.split(":", 1)[1]
            )
        except (ValueError, IndexError):
            await query.answer(
                "گزارش نامعتبر است ",
                show_alert=True
            )
            return

        group_message = get_group_message(
            message_id
        )

        if not group_message:
            await query.answer(
                "این پیام دیگر موجود نیست ",
                show_alert=True
            )
            return

        group_id = group_message[1]
        sender_id = group_message[2]
        original_text = group_message[3]

        group = None

        for row in get_all_groups():
            if row[0] == group_id:
                group = row
                break

        group_title = (
            group[1]
            if group and group[1]
            else "گروه"
        )

        reporter_name = (
            user.full_name
            or "کاربر"
        )

        reported = get_user(
            sender_id
        )

        if reported:
            username = reported[1]
            full_name = reported[2]
            ban_code = reported[6]
        else:
            username = None
            full_name = "کاربر"
            ban_code = get_ban_code(
                sender_id
            )

        username_text = (
            f"@{username}"
            if username
            else "ندارد"
        )

        ban_code = (
            ban_code
            or get_ban_code(sender_id)
        )

        safe_group_title = html.escape(
            group_title
        )

        safe_reporter_name = html.escape(
            reporter_name
        )

        safe_full_name = html.escape(
            full_name or "ندارد"
        )

        safe_original_text = html.escape(
            original_text
        )

        try:
            save_abuse_report(
                "group", user_id, reporter_name, sender_id, username,
                full_name or "کاربر", message_id, original_text, group_id, group_title
            )
        except Exception as report_db_error:
            print(f"Could not save group abuse report: {report_db_error}")
            await query.answer("ثبت گزارش در دیتابیس با خطا مواجه شد ", show_alert=True)
            return

        report_text = (
            "<b>🚨 گزارش تخلف پیام ناشناس گروه</b>\n\n"
            f"<b>نام گروه :</b> {safe_group_title}\n"
            f"<b>آیدی گروه :</b> {group_id}\n\n"
            f"<b>گزارش‌دهنده :</b> {safe_reporter_name}\n"
            f"<b>آیدی گزارش‌دهنده :</b> {user_id}\n\n"
            "<b>پیام گزارش‌شده :</b>\n"
            f"{safe_original_text}\n\n"
            f"<b>آیدی فرستنده ناشناس :</b> {sender_id}\n"
            f"<b>آیدی تلگرام :</b> {username_text}\n"
            f"<b>نام حساب :</b> {safe_full_name}\n\n"
            f"<b>کد بن کاربر :</b> /ban_{ban_code}\n"
            f"<b>کد رفع بن :</b> /unban_{ban_code}"
        )

        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=report_text,
                parse_mode="HTML"
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
                f"Group report error: {e}"
            )

            await query.answer(
                "ارسال گزارش با خطا مواجه شد ",
                show_alert=True
            )

        return

    # -----------------------------------------------------
    # USERBOT PAGE
    # -----------------------------------------------------

    if data.startswith("userbot_page:"):
        if not is_manager_or_supervisor(user_id):
            await query.answer(
                "دسترسی ندارید ",
                show_alert=True
            )
            return

        try:
            page = int(
                data.split(":", 1)[1]
            )
        except (ValueError, IndexError):
            await query.answer(
                "صفحه نامعتبر است ",
                show_alert=True
            )
            return

        text, keyboard, _ = build_userbot_page(
            page, user_id
        )

        await query.answer()

        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        return

    # -----------------------------------------------------
    # MAIN BUTTONS
    # -----------------------------------------------------

    if data == "link_stats":
        await query.answer()
        count = get_link_view_count(user_id)
        await query.message.edit_text(
            f"تعداد کاربرانی که روی لینک شما کلیک کردند : {count}",
            reply_markup=back_keyboard()
        )
        return

    if data == "copy_link":
        await query.answer()

        await show_link(
            update,
            context
        )

        return

    if data == "name_settings":
        await query.answer()

        await name_settings(
            update,
            context
        )

        return

    if data == "change_name":
        await query.answer()

        await change_name(
            update,
            context
        )

        return

    if data == "ads":
        await query.answer(
            "تبلیغات غیرفعال شده است.\nبه زودی فعال میشود\nدرحال آپدیت🫟",
            show_alert=True
        )
        return

    if data == "block_list":
        await query.answer()

        await block_list_page(
            update,
            context
        )

        return

    if data == "help":
        await query.answer()

        await help_page(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # REACTION OPEN
    # -----------------------------------------------------

    if data.startswith("reaction:"):
        try:
            message_id = int(
                data.split(":", 1)[1]
            )
        except (ValueError, IndexError):
            await query.answer(
                "پیام نامعتبر است ",
                show_alert=True
            )
            return

        msg = get_anonymous_message(
            message_id
        )

        if not msg:
            await query.answer(
                "این پیام دیگر موجود نیست ",
                show_alert=True
            )
            return

        sender_id = msg[1]
        receiver_id = msg[2]

        if receiver_id != user_id:
            await query.answer(
                "این پیام متعلق به شما نیست ",
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

        if has_reaction(
            message_id,
            user_id
        ):
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

        return

    # -----------------------------------------------------
    # REACTION BACK
    # -----------------------------------------------------

    if data.startswith("reaction_back:"):
        try:
            message_id = int(
                data.split(":", 1)[1]
            )
        except (ValueError, IndexError):
            await query.answer(
                "پیام نامعتبر است ",
                show_alert=True
            )
            return

        msg = get_anonymous_message(
            message_id
        )

        if not msg:
            await query.answer(
                "پیام پیدا نشد ",
                show_alert=True
            )
            return

        sender_id = msg[1]
        receiver_id = msg[2]

        if receiver_id != user_id:
            await query.answer(
                "این پیام متعلق به شما نیست ",
                show_alert=True
            )
            return

        await query.answer()

        await query.edit_message_reply_markup(
            reply_markup=anonymous_message_keyboard(
                message_id,
                sender_id,
                True,
                True
            )
        )

        return

    # -----------------------------------------------------
    # REACTION SELECT
    # -----------------------------------------------------

    if data.startswith("react:"):
        pieces = data.split(":")

        if len(pieces) != 3:
            await query.answer(
                "ری‌اکشن نامعتبر است ",
                show_alert=True
            )
            return

        try:
            message_id = int(pieces[1])
            index = int(pieces[2])
        except ValueError:
            await query.answer(
                "ری‌اکشن نامعتبر است ",
                show_alert=True
            )
            return

        if index < 0 or index >= len(REACTIONS):
            await query.answer(
                "ری‌اکشن نامعتبر است ",
                show_alert=True
            )
            return

        reaction = REACTIONS[index]

        msg = get_anonymous_message(
            message_id
        )

        if not msg:
            await query.answer(
                "این پیام دیگر موجود نیست ",
                show_alert=True
            )
            return

        sender_id = msg[1]
        receiver_id = msg[2]
        original_text = msg[3]
        media_type = msg[6]
        media_file_id = msg[7]
        media_caption = msg[8]

        if receiver_id != user_id:
            await query.answer(
                "این پیام متعلق به شما نیست ",
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

        await query.edit_message_reply_markup(
            reply_markup=anonymous_message_keyboard(
                message_id,
                sender_id,
                include_reaction=False,
                include_seen=False
            )
        )

        await query.answer(
            "ری اکشن با موفقیت ارسال شد ⚡",
            show_alert=True
        )

        try:
            safe_text = html.escape(
                original_text
            )

            safe_reaction = html.escape(
                reaction
            )

            notification = (
                "<b>"
                "کاربر به پیام "
                f"« {safe_text} » "
                f"واکنشی نشان داد : {safe_reaction}"
                "</b>"
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

    # -----------------------------------------------------
    # SEEN
    # -----------------------------------------------------

    if data.startswith("seen:"):
        try:
            message_id = int(
                data.split(":", 1)[1]
            )
        except (ValueError, IndexError):
            await query.answer(
                "پیام نامعتبر است ",
                show_alert=True
            )
            return

        msg = get_anonymous_message(
            message_id
        )

        if not msg:
            await query.answer(
                "این پیام دیگر موجود نیست ",
                show_alert=True
            )
            return

        sender_id = msg[1]
        receiver_id = msg[2]

        if receiver_id != user_id:
            await query.answer(
                "این پیام متعلق به شما نیست ",
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
            except TelegramError:
                pass

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

    # -----------------------------------------------------
    # SEND A NEW MESSAGE TO THE PERSON WHO REPLIED
    # -----------------------------------------------------

    if data.startswith("newmsg:"):
        try:
            target_id = int(data.split(":", 1)[1])
        except (ValueError, IndexError):
            await query.answer("کاربر نامعتبر است.", show_alert=True)
            return

        if target_id == user_id or is_blocked(user_id, target_id) or is_blocked(target_id, user_id):
            await query.answer("امکان ارسال پیام به این کاربر وجود ندارد.", show_alert=True)
            return

        await query.answer()
        context.user_data.clear()
        context.user_data["sending_anonymous"] = True
        context.user_data["target_id"] = target_id
        await query.message.reply_text(
            "پیام جدید خود را برای همین کاربر بنویسید یا ارسال کنید: 📨",
            reply_markup=cancel_keyboard()
        )
        return

    # -----------------------------------------------------
    # REPLY
    # -----------------------------------------------------

    if data.startswith("reply:"):
        try:
            message_id = int(
                data.split(":", 1)[1]
            )
        except (ValueError, IndexError):
            await query.answer(
                "پیام نامعتبر است ",
                show_alert=True
            )
            return

        msg = get_anonymous_message(
            message_id
        )

        if not msg:
            await query.answer(
                "این پیام دیگر موجود نیست ",
                show_alert=True
            )
            return

        sender_id = msg[1]
        receiver_id = msg[2]

        if receiver_id != user_id:
            await query.answer(
                "این پیام متعلق به شما نیست ",
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
            "replying"
        ] = True

        context.user_data[
            "reply_message_id"
        ] = message_id

        context.user_data[
            "reply_sender_id"
        ] = sender_id

        await query.message.reply_text(
            "پاسخ خود را بنویسید: 📨",
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
                "کاربر نامعتبر است ",
                show_alert=True
            )
            return

        if blocked_id == user_id:
            await query.answer(
                "نمی‌توانی خودت را بلاک کنی ",
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

    # -----------------------------------------------------
    # REPORT
    # -----------------------------------------------------

    if data.startswith("report:"):
        try:
            message_id = int(
                data.split(":", 1)[1]
            )
        except (ValueError, IndexError):
            await query.answer(
                "گزارش نامعتبر است ",
                show_alert=True
            )
            return

        msg = get_anonymous_message(
            message_id
        )

        if not msg:
            await query.answer(
                "این پیام دیگر موجود نیست ",
                show_alert=True
            )
            return

        sender_id = msg[1]
        receiver_id = msg[2]
        original_text = msg[3]

        if receiver_id != user_id:
            await query.answer(
                "این پیام متعلق به شما نیست ",
                show_alert=True
            )
            return

        reported = get_user(
            sender_id
        )

        if reported:
            username = reported[1]
            full_name = reported[2]
            ban_code = reported[6]
        else:
            username = None
            full_name = "کاربر"
            ban_code = get_ban_code(
                sender_id
            )

        username_text = (
            f"@{username}"
            if username
            else "ندارد"
        )

        ban_code = (
            ban_code
            or get_ban_code(sender_id)
        )

        try:
            save_abuse_report(
                "private", user_id, user.full_name or "کاربر", sender_id,
                username, full_name or "کاربر", message_id, original_text
            )
        except Exception as report_db_error:
            print(f"Could not save private abuse report: {report_db_error}")
            await query.answer("ثبت گزارش در دیتابیس با خطا مواجه شد ", show_alert=True)
            return

        report_text = (
            "🚨 گزارش تخلف برای کاربر و پیام زیر ثبت شد .👇🏻\n\n"
            f"آیدی کاربر : {username_text}\n"
            f"آیدی عددی کاربر : {sender_id}\n"
            f"نام حساب کاربری تلگرام : {full_name or 'ندارد'}\n\n"
            f"پیام گزارش شده :\n"
            f"{original_text}\n\n"
            f"کد بن کاربر : /ban_{ban_code}\n"
            f"کد رفع بن : /unban_{ban_code}"
        )

        try:
            # گزارش برای مدیر اصلی
            recipients = {ADMIN_ID}

            # گزارش برای تمام ناظرهای فعال
            for supervisor in get_supervisors():
                supervisor_id = supervisor[0]
                if supervisor_id:
                    recipients.add(supervisor_id)

            sent_to_any = False

            for recipient_id in recipients:
                try:
                    await context.bot.send_message(
                        chat_id=recipient_id,
                        text=report_text
                    )

                    # اگر پیام رسانه‌ای بوده، خود رسانه هم برای مدیر/ناظر ارسال شود.
                    if media_type and media_type != "text" and media_file_id:
                        admin_media_caption = html.escape(
                            media_caption or original_text or ""
                        )

                        if media_type == "photo":
                            await context.bot.send_photo(
                                chat_id=recipient_id,
                                photo=media_file_id,
                                caption=admin_media_caption or None,
                                parse_mode="HTML"
                            )
                        elif media_type == "video":
                            await context.bot.send_video(
                                chat_id=recipient_id,
                                video=media_file_id,
                                caption=admin_media_caption or None,
                                parse_mode="HTML"
                            )
                        elif media_type == "voice":
                            await context.bot.send_voice(
                                chat_id=recipient_id,
                                voice=media_file_id,
                                caption=admin_media_caption or None,
                                parse_mode="HTML"
                            )
                        elif media_type == "audio":
                            await context.bot.send_audio(
                                chat_id=recipient_id,
                                audio=media_file_id,
                                caption=admin_media_caption or None,
                                parse_mode="HTML"
                            )
                        elif media_type == "document":
                            await context.bot.send_document(
                                chat_id=recipient_id,
                                document=media_file_id,
                                caption=admin_media_caption or None,
                                parse_mode="HTML"
                            )

                    sent_to_any = True

                except TelegramError as recipient_error:
                    # خراب بودن چت یک ناظر نباید مانع ارسال گزارش به بقیه شود.
                    print(
                        f"Report delivery error for {recipient_id}: {recipient_error}"
                    )

            if sent_to_any:
                await query.answer(
                    "گزارش تخلف با موفقیت ثبت شد 🚨",
                    show_alert=True
                )

                await query.message.reply_text(
                    "🚨 گزارش تخلف شما با موفقیت ثبت شد.\n"
                    "گزارش برای مدیریت و ناظران ارسال شد."
                )
            else:
                await query.answer(
                    "ارسال گزارش با خطا مواجه شد ",
                    show_alert=True
                )

        except Exception as e:
            print(
                f"Report error: {e}"
            )

            await query.answer(
                "ارسال گزارش با خطا مواجه شد ",
                show_alert=True
            )

        return


# =========================================================
# ANONYMOUS MEDIA
# =========================================================

def get_message_payload(message):
    if message.text is not None:
        return "text", None, message.text
    if message.photo:
        return "photo", message.photo[-1].file_id, message.caption or ""
    if message.video:
        return "video", message.video.file_id, message.caption or ""
    if message.voice:
        return "voice", message.voice.file_id, message.caption or ""
    if message.audio:
        return "audio", message.audio.file_id, message.caption or ""
    if message.document:
        return "document", message.document.file_id, message.caption or ""
    return None, None, ""


async def send_anonymous_media(bot, chat_id, media_type, file_id, caption, reply_markup=None, reply_to_message_id=None):
    rp = ReplyParameters(message_id=reply_to_message_id) if reply_to_message_id else None
    if media_type == "photo":
        return await bot.send_photo(chat_id=chat_id, photo=file_id, caption=caption or None, reply_markup=reply_markup, reply_parameters=rp)
    if media_type == "video":
        return await bot.send_video(chat_id=chat_id, video=file_id, caption=caption or None, reply_markup=reply_markup, reply_parameters=rp)
    if media_type == "voice":
        return await bot.send_voice(chat_id=chat_id, voice=file_id, caption=caption or None, reply_markup=reply_markup, reply_parameters=rp)
    if media_type == "audio":
        return await bot.send_audio(chat_id=chat_id, audio=file_id, caption=caption or None, reply_markup=reply_markup, reply_parameters=rp)
    if media_type == "document":
        return await bot.send_document(chat_id=chat_id, document=file_id, caption=caption or None, reply_markup=reply_markup, reply_parameters=rp)
    return await bot.send_message(chat_id=chat_id, text=caption or "", reply_markup=reply_markup, reply_parameters=rp)


async def media_handler(update, context):
    user = update.effective_user
    message = update.message
    if not user or not message or message.chat.type in ("group", "supergroup"):
        return
    media_type, file_id, caption = get_message_payload(message)
    if not media_type or media_type == "text":
        return
    if user.id != ADMIN_ID and get_ban_info(user.id):
        return
    if not await is_member(context.bot, user.id):
        await send_join_message(update, context)
        return

    if context.user_data.get("sending_channel_anonymous"):
        if media_type != "voice":
            await message.reply_text(" برای پیام ناشناس چنل فقط متن و ویس قابل ارسال است.")
            return
        owner_id = context.user_data.get("channel_target_owner_id")
        channel_id = context.user_data.get("channel_target_id")
        if not owner_id or not channel_id:
            context.user_data.clear()
            await message.reply_text(" اطلاعات چنل پیدا نشد.", reply_markup=back_keyboard())
            return
        row = get_user(user.id)
        anon_code = row[4] if row else "0000000"
        message_id = save_anonymous_message(user.id, owner_id, "[پیام صوتی]", "voice", file_id, caption, message.message_id, owner_id)
        keyboard = channel_message_keyboard(message_id, user.id)
        try:
            await context.bot.send_message(chat_id=channel_id, text=f"<b>پیام ناشناس از طرف کاربر {anon_code}</b>", parse_mode="HTML")
            await context.bot.send_voice(chat_id=channel_id, voice=file_id, caption=caption or None)
            await context.bot.send_message(
                chat_id=owner_id,
                text=f"<b>پیام ناشناسی از طرف کاربر {anon_code} برای چنل شما ارسال شد.</b>\n\n<b>پیام : پیام صوتی</b>\n\n<b>گزارش تخلف و بلاک 👇🏻</b>",
                parse_mode="HTML",
                reply_markup=keyboard
            )
            await context.bot.send_voice(chat_id=owner_id, voice=file_id)
            await message.reply_text("✅ ویس ناشناس با موفقیت به چنل ارسال شد.", reply_markup=back_keyboard())
        except TelegramError as e:
            print(f"Anonymous channel voice send error: {e}")
            await message.reply_text(" ارسال ویس به چنل ناموفق بود. دسترسی ادمین ربات را بررسی کنید.")
        context.user_data.clear()
        return

    if context.user_data.get("replying"):
        original_message_id = context.user_data.get("reply_message_id")
        sender_id = context.user_data.get("reply_sender_id")
        original = get_anonymous_message(original_message_id) if original_message_id else None
        if not original or original[1] != sender_id or original[2] != user.id or is_blocked(user.id, sender_id):
            context.user_data.clear()
            await message.reply_text(" اطلاعات پیام پیدا نشد.")
            return
        new_id = save_anonymous_message(user.id, sender_id, caption, media_type, file_id, caption, message.message_id, original[10] if original[10] else original[2])
        keyboard = anonymous_message_keyboard(
            new_id, user.id, True, True, include_new_message=True
        )
        try:
            row = get_user(user.id)
            anon_code = row[4] if row else "0000000"
            conversation_owner_id = original[10] or original[2]
            display = (
                f"کاربر {html.escape(get_display_name(user.id))}"
                if user.id == conversation_owner_id
                else f"کاربر {anon_code}"
            )

            # ابتدا اعلان پاسخ را روی پیام اصلی کاربر ریپلای می‌کنیم.
            # خود پاسخ بعد از آن، به‌صورت پیام جداگانه ارسال می‌شود.
            if original[9]:
                await context.bot.send_message(
                    chat_id=sender_id,
                    text=f"<b>{display} به پیام شما پاسخ داد. 🤠</b>",
                    parse_mode="HTML",
                    reply_parameters=ReplyParameters(
                        message_id=original[9],
                        allow_sending_without_reply=True
                    )
                )
            delivered = await send_anonymous_media(
                context.bot, sender_id, media_type, file_id, caption, keyboard
            )

            try:
                set_delivered_message_id(new_id, delivered.message_id)
            except Exception as e:
                print(f"Reply delivered id save error: {e}")

            await message.reply_text("✅ پاسخ شما با موفقیت ارسال شد.", reply_markup=back_keyboard())
        except TelegramError as e:
            print(f"Reply media Telegram error: {e}")
            await message.reply_text(" ارسال پاسخ با خطا مواجه شد.")
        context.user_data.clear()
        return

    if context.user_data.get("sending_anonymous"):
        target_id = context.user_data.get("target_id")
        if not target_id or target_id == user.id or is_blocked(target_id, user.id):
            context.user_data.clear()
            await message.reply_text(" ارسال پیام انجام نشد.", reply_markup=back_keyboard())
            return

        target_ban_info = get_ban_info(target_id)
        if target_ban_info:
            context.user_data.clear()
            target_user = get_user(target_id)
            target_name = (target_user[5] if target_user and target_user[5] else target_user[2] if target_user and target_user[2] else "کاربر")
            await message.reply_text(
                f"<b>حساب کاربری ({html.escape(target_name)}) مسدود شده است🟡</b>\n"
                "شما نمیتوانید به این مقصد پیامی ارسال کنید🙈\n\n"
                "« گلدن چت »", reply_markup=back_keyboard(), parse_mode="HTML")
            return
        mid = save_anonymous_message(user.id, target_id, caption, media_type, file_id, caption, message.message_id, target_id)
        keyboard = anonymous_message_keyboard(mid, user.id, True, True)
        row = get_user(user.id)
        anon_code = row[4] if row else "0000000"
        try:
            header = await context.bot.send_message(
                chat_id=target_id,
                text=f"<b>کاربر {anon_code} برای شما پیام ناشناسی ارسال کرد : 👇🏻</b>",
                parse_mode="HTML"
            )
            delivered = await send_anonymous_media(
                context.bot, target_id, media_type, file_id, caption, keyboard,
                reply_to_message_id=header.message_id
            )
            set_delivered_message_id(mid, delivered.message_id)
            await message.reply_text("✅ پیام ناشناس با موفقیت ارسال شد.", reply_markup=back_keyboard())
        except TelegramError:
            await message.reply_text(" خطا در ارسال پیام.")
        context.user_data.clear()
        return

    await message.reply_text(" این نوع فایل در این بخش قابل ارسال نیست.")


# =========================================================
# HANDLE MESSAGE
# =========================================================

async def handle_message(
    update,
    context
):
    user = update.effective_user
    message = update.message

    if not user or not message:
        return

    # =====================================================
    # GROUP SAFETY
    # =====================================================
    # هیچ پیام متنی عادی داخل گروه توسط این handler پردازش نمی‌شود.
    # =====================================================

    if message.chat.type in (
        "group",
        "supergroup"
    ):
        return

    if not message.text:
        return

    text = message.text

    if not text.strip():
        return

    # =====================================================
    # SUPERVISOR-ONLY FLOWS
    # =====================================================

    if user.id == ADMIN_ID and context.user_data.get("supervisor_remove_waiting_reason"):
        if text.strip() == "بازگشت 🔙" or text.lower() == "/cancel":
            context.user_data.clear()
            await send_main_panel(update, context, show_reply_keyboard=False)
            return
        target_id = context.user_data.get("supervisor_remove_target_id")
        reason = text.strip()
        if not target_id or not is_supervisor(target_id):
            context.user_data.clear()
            await message.reply_text(" ناظر پیدا نشد.", reply_markup=back_keyboard())
            return
        remove_supervisor(target_id)
        context.user_data.clear()
        await message.reply_text("ناظر با موفقیت حذف شد.✅", reply_markup=back_keyboard())
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"شما توسط مدیر ربات از ادمینی خارج شدید.😄\nعلت مدیر : {html.escape(reason)}",
                reply_markup=supervisor_target_ok_keyboard()
            )
        except TelegramError:
            pass
        try:
            await context.bot.set_my_commands(
                [
                    __import__('telegram').BotCommand("start", "شروع ربات"),
                    __import__('telegram').BotCommand("cancel", "لغو عملیات"),
                ],
                scope=__import__('telegram').BotCommandScopeChat(target_id)
            )
        except Exception:
            pass
        return

    if user.id == ADMIN_ID and context.user_data.get("supervisor_add_waiting_identifier"):
        if text.strip() == "بازگشت 🔙" or text.lower() == "/cancel":
            context.user_data.clear()
            await send_main_panel(update, context, show_reply_keyboard=False)
            return
        target = find_user_by_identifier(text.strip())
        if not target:
            await message.reply_text(" کاربر پیدا نشد. باید آیدی عددی یا username کاربری باشد که ربات قبلاً او را شناخته است.", reply_markup=back_keyboard())
            return
        target_id = target[0]
        if target_id == ADMIN_ID:
            await message.reply_text(" مدیر اصلی نمی‌تواند ناظر شود.", reply_markup=back_keyboard())
            return
        if is_supervisor(target_id):
            await message.reply_text(" این کاربر از قبل ناظر است.", reply_markup=back_keyboard())
            return
        add_supervisor(target_id)
        context.user_data.clear()
        target_name = target[3] or target[2] or (f"@{target[1]}" if target[1] else "کاربر")
        await message.reply_text(f"کاربر {html.escape(target_name)} با موفقیت ناظر شد.✅", parse_mode="HTML", reply_markup=supervisor_panel_keyboard())
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="شما توسط مدیر ربات به عنوان ناظر انتخاب شدید.🎊\nدریافت کامند ها جهت استفاده از ربات /cdb را ارسال کنید.",
                reply_markup=supervisor_target_ok_keyboard()
            )
            from telegram import BotCommand, BotCommandScopeChat
            await context.bot.set_my_commands(
                [
                    BotCommand("cdb", "دریافت کامند های ناظر"),
                    BotCommand("userbot", "مشاهده کاربران ربات"),
                    BotCommand("userban", "لیست کاربران بن شده"),
                    BotCommand("broadcast", "ارسال پیام همگانی"),
                    BotCommand("changeusername", "تغییر نام کاربر"),
                    BotCommand("ban_", "بن کردن کاربر با شناسه"),
                    BotCommand("unban_", "درخواست رفع بن کاربر"),
                ],
                scope=BotCommandScopeChat(target_id)
            )
        except TelegramError:
            pass
        return

    if is_supervisor(user.id):
        # supervisor change display name
        if context.user_data.get("change_username_waiting_code"):
            if text.strip() == "بازگشت 🔙" or text.lower() == "/cancel":
                context.user_data.clear()
                await send_main_panel(update, context, show_reply_keyboard=False)
                return
            target = find_user_by_identifier(text.strip())
            if not target:
                # Also accept the user's ban code, as the command description refers to the user identifier.
                conn = db()
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT user_id, full_name, display_name, username, ban_code FROM users WHERE lower(ban_code) = %s", (text.strip().lower(),))
                    by_code = cur.fetchone()
                finally:
                    cur.close(); release_db(conn)
                if by_code:
                    target = (by_code[0], by_code[3], by_code[1], by_code[2], by_code[4])
            if not target:
                await message.reply_text(" شناسه کاربری پیدا نشد.\nلطفا شناسه صحیح کاربر را وارد کنید :", reply_markup=back_keyboard())
                return
            target_id = target[0]
            if target_id == ADMIN_ID or is_supervisor(target_id):
                await message.reply_text(" نمی‌توانی نام نمایشی مدیر یا ناظر را از این بخش تغییر بدهی.", reply_markup=back_keyboard())
                return
            context.user_data.clear()
            context.user_data["change_username_waiting_name"] = True
            context.user_data["change_username_target_id"] = target_id
            context.user_data["change_username_code"] = target[4] if len(target) > 4 else ""
            await message.reply_text("لطفا نام نمایشی جدید کاربر را انتخاب کنید :", reply_markup=back_keyboard())
            return

        if context.user_data.get("change_username_waiting_name"):
            if text.strip() == "بازگشت 🔙" or text.lower() == "/cancel":
                context.user_data.clear(); await send_main_panel(update, context, show_reply_keyboard=False); return
            new_name = text.strip()
            if not new_name:
                await message.reply_text(" نام نمایشی نمی‌تواند خالی باشد.", reply_markup=back_keyboard()); return
            if len(new_name) > 50:
                await message.reply_text(" نام خیلی طولانی است.\nحداکثر ۵۰ کاراکتر وارد کنید.", reply_markup=back_keyboard()); return
            context.user_data["change_username_waiting_name"] = False
            context.user_data["change_username_waiting_reason"] = True
            context.user_data["change_username_new_name"] = new_name
            await message.reply_text("علت تغییر نام :", reply_markup=back_keyboard())
            return

        if context.user_data.get("change_username_waiting_reason"):
            if text.strip() == "بازگشت 🔙" or text.lower() == "/cancel":
                context.user_data.clear(); await send_main_panel(update, context, show_reply_keyboard=False); return
            reason = text.strip()
            if not reason:
                await message.reply_text(" علت تغییر نام نمی‌تواند خالی باشد.", reply_markup=back_keyboard()); return
            if len(reason) > 1000:
                await message.reply_text(" علت تغییر نام خیلی طولانی است.\nحداکثر ۱۰۰۰ کاراکتر وارد کنید.", reply_markup=back_keyboard()); return
            target_id = context.user_data.get("change_username_target_id")
            new_name = context.user_data.get("change_username_new_name")
            if not target_id or not new_name:
                context.user_data.clear(); await message.reply_text(" اطلاعات تغییر نام پیدا نشد.", reply_markup=back_keyboard()); return
            old_name = get_display_name(target_id)
            set_display_name(target_id, new_name)
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=f"نام نمایشی شما توسط ادمین به {html.escape(new_name)} تغییر یافت✅\nعلت : {html.escape(reason)}",
                    reply_markup=change_username_confirm_keyboard(),
                    parse_mode="HTML"
                )
            except TelegramError:
                pass
            context.user_data.clear()
            await message.reply_text(
                f"✅ نام نمایشی کاربر با موفقیت تغییر کرد.\n\nنام قبلی : {html.escape(old_name)}\nنام جدید : {html.escape(new_name)}\nعلت : {html.escape(reason)}",
                parse_mode="HTML", reply_markup=back_keyboard()
            )
            return

        # supervisor broadcast request
        if context.user_data.get("waiting_supervisor_broadcast"):
            if text.strip() == "بازگشت 🔙" or text.lower() == "/cancel":
                context.user_data.clear()
                await send_main_panel(update, context, show_reply_keyboard=False)
                return
            request_id = create_broadcast_request(user.id, text.strip())
            context.user_data.clear()
            label = html.escape(supervisor_label(user.id))
            request_text = (
                "<b>درخواست پیام همگانی</b>\n\n"
                f"ناظر {label} درخواست ارسال پیام همگانی زیر را دارد:\n\n"
                f"{html.escape(text.strip())}\n\n"
                "<b>آیا میپذیرید ؟</b>"
            )
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=request_text,
                parse_mode="HTML",
                reply_markup=manager_approval_keyboard("broadcast", request_id)
            )
            await message.reply_text("درخواست پیام همگانی برای مدیر ارسال شد.✅", reply_markup=back_keyboard())
            return

        # supervisor unban reason
        if context.user_data.get("waiting_supervisor_unban_reason"):
            if text.strip() == "بازگشت 🔙" or text.lower() == "/cancel":
                context.user_data.clear()
                await send_main_panel(update, context, show_reply_keyboard=False)
                return
            reason = text.strip()
            if not reason:
                await message.reply_text(" علت رفع بن نمی‌تواند خالی باشد.", reply_markup=back_keyboard())
                return
            target_id = context.user_data.get("supervisor_unban_target_id")
            target_code = context.user_data.get("supervisor_unban_code")
            target_name = context.user_data.get("supervisor_unban_name") or "کاربر"
            request_id = create_unban_request(user.id, target_id, target_code, target_name, reason)
            context.user_data.clear()
            req_text = (
                f"ناظر ( {html.escape(supervisor_label(user.id))} ) درخواست رفع بن کاربر "
                f"( {html.escape(target_name)} ) را ارسال کرد.\n\n"
                "آیا میپذیرید ؟\n\n"
                "بله ✅  خیر ✖️"
            )
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=req_text,
                reply_markup=manager_approval_keyboard("unban", request_id)
            )
            await message.reply_text("درخواست رفع بن برای مدیر ارسال شد.✅", reply_markup=back_keyboard())
            return

        # supervisor ban reason uses the existing duration callback
        if context.user_data.get("waiting_ban_reason"):
            if text.strip() == "بازگشت 🔙" or text.lower() == "/cancel":
                context.user_data.clear()
                await send_main_panel(update, context, show_reply_keyboard=False)
                return
            reason = text.strip()
            if len(reason) > 1000:
                await message.reply_text(" علت بن خیلی طولانی است.\nحداکثر ۱۰۰۰ کاراکتر وارد کنید.")
                return
            context.user_data["ban_reason"] = reason
            context.user_data["waiting_ban_reason"] = False
            context.user_data["waiting_ban_duration"] = True
            await message.reply_text("تعداد زمانی که کاربر در حالت بنی قرار بگیرد را وارد کنید", reply_markup=ban_duration_keyboard())
            return

        # supervisor dynamic ban/unban commands
        if text.lower().startswith("/ban_"):
            code = text[5:].strip().lower()
            conn = db()
            try:
                cur = conn.cursor()
                cur.execute("SELECT user_id FROM users WHERE lower(ban_code) = %s", (code,))
                row = cur.fetchone()
            finally:
                cur.close(); release_db(conn)
            if not row:
                await message.reply_text(" کد بن پیدا نشد.")
                return
            target_id = row[0]
            if target_id == ADMIN_ID or is_supervisor(target_id):
                await message.reply_text(" این کاربر قابل بن شدن توسط ناظر نیست.")
                return
            context.user_data.clear()
            context.user_data["waiting_ban_reason"] = True
            context.user_data["ban_code"] = code
            context.user_data["ban_target_id"] = target_id
            await message.reply_text("علت بنی کاربر را وارد کنید  :", reply_markup=ban_cancel_keyboard())
            return

        if text.lower().startswith("/unban_"):
            code = text[7:].strip().lower()
            conn = db()
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT user_id, full_name, display_name, username, ban_code
                    FROM users WHERE lower(ban_code) = %s
                """, (code,))
                row = cur.fetchone()
            finally:
                cur.close(); release_db(conn)
            if not row:
                await message.reply_text(" کد رفع بن پیدا نشد.")
                return
            target_id, full_name, display_name, username, ban_code = row
            if not get_ban_info(target_id):
                await message.reply_text(" این کاربر در حال حاضر بن نیست.")
                return
            target_name = display_name or full_name or (f"@{username}" if username else "کاربر")
            context.user_data.clear()
            context.user_data["waiting_supervisor_unban_reason"] = True
            context.user_data["supervisor_unban_target_id"] = target_id
            context.user_data["supervisor_unban_code"] = ban_code or code
            context.user_data["supervisor_unban_name"] = target_name
            await message.reply_text("علت رفع بن کردن کاربر رو وارد کن :", reply_markup=back_keyboard())
            return

    # =====================================================
    # ADMIN
    # =====================================================

    if user.id == ADMIN_ID:

        # CHANGE DISPLAY NAME - STEP 1: USER CODE

        if context.user_data.get(
            "change_username_waiting_code"
        ):
            if text.strip() == "بازگشت 🔙":
                context.user_data.clear()
                await send_main_panel(
                    update,
                    context,
                    show_reply_keyboard=False
                )
                return

            code = text.strip().lower()

            conn = db()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT user_id, full_name, display_name
                    FROM users
                    WHERE lower(ban_code) = %s
                    """,
                    (code,)
                )
                target = cur.fetchone()
            finally:
                cur.close()
                release_db(conn)

            if not target:
                await message.reply_text(
                    " شناسه کاربری پیدا نشد.\n\n"
                    "لطفا شناسه صحیح کاربر را وارد کنید :",
                    reply_markup=back_keyboard()
                )
                return

            if target[0] == ADMIN_ID:
                await message.reply_text(
                    " نمی‌توانی نام نمایشی خود ادمین را از این بخش تغییر بدهی.",
                    reply_markup=back_keyboard()
                )
                return

            context.user_data.clear()
            context.user_data["change_username_waiting_name"] = True
            context.user_data["change_username_target_id"] = target[0]
            context.user_data["change_username_code"] = code

            await message.reply_text(
                "لطفا نام نمایشی جدید کاربر را انتخاب کنید :",
                reply_markup=back_keyboard()
            )
            return

        # CHANGE DISPLAY NAME - STEP 2: NEW NAME

        if context.user_data.get(
            "change_username_waiting_name"
        ):
            if text.strip() == "بازگشت 🔙":
                context.user_data.clear()
                await send_main_panel(
                    update,
                    context,
                    show_reply_keyboard=False
                )
                return

            new_name = text.strip()

            if not new_name:
                await message.reply_text(
                    " نام نمایشی نمی‌تواند خالی باشد.\n\n"
                    "لطفا نام نمایشی جدید را وارد کنید :",
                    reply_markup=back_keyboard()
                )
                return

            if len(new_name) > 50:
                await message.reply_text(
                    " نام خیلی طولانی است.\n"
                    "حداکثر ۵۰ کاراکتر وارد کنید.",
                    reply_markup=back_keyboard()
                )
                return

            context.user_data["change_username_waiting_name"] = False
            context.user_data["change_username_waiting_reason"] = True
            context.user_data["change_username_new_name"] = new_name

            await message.reply_text(
                "علت تغییر نام :",
                reply_markup=back_keyboard()
            )
            return

        # CHANGE DISPLAY NAME - STEP 3: REASON + APPLY

        if context.user_data.get(
            "change_username_waiting_reason"
        ):
            if text.strip() == "بازگشت 🔙":
                context.user_data.clear()
                await send_main_panel(
                    update,
                    context,
                    show_reply_keyboard=False
                )
                return

            reason = text.strip()

            if not reason:
                await message.reply_text(
                    " علت تغییر نام نمی‌تواند خالی باشد.\n\n"
                    "لطفا علت تغییر نام را وارد کنید :",
                    reply_markup=back_keyboard()
                )
                return

            if len(reason) > 1000:
                await message.reply_text(
                    " علت تغییر نام خیلی طولانی است.\n"
                    "حداکثر ۱۰۰۰ کاراکتر وارد کنید.",
                    reply_markup=back_keyboard()
                )
                return

            target_id = context.user_data.get(
                "change_username_target_id"
            )
            new_name = context.user_data.get(
                "change_username_new_name"
            )

            if not target_id or not new_name:
                context.user_data.clear()
                await message.reply_text(
                    " اطلاعات تغییر نام پیدا نشد.",
                    reply_markup=back_keyboard()
                )
                return

            old_name = get_display_name(target_id)
            set_display_name(target_id, new_name)

            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=(
                        f"نام نمایشی شما توسط ادمین به {html.escape(new_name)} تغییر یافت✅\n"
                        f"علت : {html.escape(reason)}"
                    ),
                    reply_markup=change_username_confirm_keyboard(),
                    parse_mode="HTML"
                )
            except TelegramError:
                pass

            context.user_data.clear()

            await message.reply_text(
                "✅ نام نمایشی کاربر با موفقیت تغییر کرد.\n\n"
                f"نام قبلی : {html.escape(old_name)}\n"
                f"نام جدید : {html.escape(new_name)}\n"
                f"علت : {html.escape(reason)}",
                parse_mode="HTML"
            )
            return

        # DIRECT MESSAGE

        if context.user_data.get(
            "waiting_direct_message"
        ):
            if text.lower() == "/cancel":
                context.user_data.clear()

                await message.reply_text(
                    " ارسال پیام مستقیم لغو شد."
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
                    " اطلاعات کاربر پیدا نشد."
                )
                return

            try:
                await send_direct_message(
                    context.bot,
                    target_id,
                    target_name,
                    text
                )

                context.user_data.clear()

                await message.reply_text(
                    "✅ پیام مستقیم با موفقیت برای کاربر ارسال شد."
                )

            except TelegramError:
                context.user_data.clear()

                await message.reply_text(
                    " ارسال پیام مستقیم انجام نشد.\n"
                    "ممکن است کاربر ربات را بلاک کرده باشد."
                )

            return

        # MASSAGE

        if text.lower().startswith(
            "/massage_"
        ):
            code = text[
                len("/massage_"):
            ].strip().lower()

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
                    (code,)
                )

                target = cur.fetchone()

            finally:
                cur.close()
                release_db(conn)

            if not target:
                await message.reply_text(
                    " کد کاربر پیدا نشد."
                )
                return

            target_id = target[0]

            if target_id == ADMIN_ID:
                await message.reply_text(
                    " نمی‌توانی برای خودت پیام مستقیم ارسال کنی."
                )
                return

            target_name = (
                target[2]
                or target[3]
                or (
                    f"@{target[1]}"
                    if target[1]
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

        # BAN REASON

        if context.user_data.get(
            "waiting_ban_reason"
        ):
            if text.lower() == "/cancel":
                context.user_data.clear()

                await message.reply_text(
                    " عملیات بن لغو شد."
                )

                return

            reason = text.strip()

            if len(reason) > 1000:
                await message.reply_text(
                    " علت بن خیلی طولانی است.\n"
                    "حداکثر ۱۰۰۰ کاراکتر وارد کنید."
                )
                return

            context.user_data[
                "ban_reason"
            ] = reason

            context.user_data[
                "waiting_ban_reason"
            ] = False

            context.user_data[
                "waiting_ban_duration"
            ] = True

            await message.reply_text(
                "تعداد زمانی که کاربر در حالت بنی قرار بگیرد را وارد کنید",
                reply_markup=ban_duration_keyboard()
            )

            return

        # BAN COMMAND

        if text.lower().startswith("/ban_"):
            code = text[5:].strip()

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
                    " کد بن پیدا نشد."
                )
                return

            target_user_id = row[0]

            if target_user_id == ADMIN_ID:
                await message.reply_text(
                    " نمی‌توانی خودت را بن کنی."
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
                "علت بنی کاربر را وارد کنید  :",
                reply_markup=ban_cancel_keyboard()
            )

            return

        # UNBAN COMMAND

        if text.lower().startswith("/unban_"):
            code = text[7:].strip()

            target_id = unban_user_by_code(
                code
            )

            if not target_id:
                await message.reply_text(
                    " کد رفع بن پیدا نشد."
                )
                return

            await message.reply_text(
                "🟢 بن کاربر با موفقیت رفع شد.\n\n"
                f"آیدی عددی کاربر : {target_id}"
            )

            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=(
                        "مسدودی حساب کاربری شما توسط ادمین رفع شد.\n"
                        "اکنون حساب کاربری شما به حالت سبز در آمده 🟢\n"
                        "میتوانید از قابلیت های ربات استفاده کنید /start"
                    )
                )
            except TelegramError:
                pass

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

    get_or_create_user(
        user.id,
        user.username,
        user.full_name
    )

    if context.user_data.get("waiting_channel_identifier"):
        if text.strip() == "بازگشت 🔙" or text.lower() == "/cancel":
            context.user_data.clear()
            await send_main_panel(update, context, show_reply_keyboard=True)
            return
        identifier = text.strip()
        try:
            channel_chat = await context.bot.get_chat(identifier)
            member = await context.bot.get_chat_member(channel_chat.id, context.bot.id)
            if member.status not in (ChatMember.ADMINISTRATOR, ChatMember.OWNER):
                await message.reply_text(
                    " ربات هنوز ادمین چنل نیست. ابتدا ربات را ادمین کنید و دوباره «اضافه شد ✅» را بزنید.",
                    reply_markup=back_keyboard()
                )
                return
            if hasattr(member, "can_post_messages") and member.can_post_messages is False:
                await message.reply_text(" دسترسی ارسال پست برای ربات فعال نیست.", reply_markup=back_keyboard())
                return
            save_channel_link(user.id, channel_chat.id, channel_chat.title or identifier)
            bot_username = await get_cached_bot_username(context)
            rows = get_owner_channel_links(user.id)
            parts = ["<b>چنل‌های متصل شما و لینک اختصاصی پیام ناشناس:</b>"]
            for _, title, code in rows:
                parts.append(f"\n<b>نام چنل :</b> {html.escape(title)}\n<b>لینک اختصاصی پیام ناشناس چنل :</b> https://t.me/{bot_username}?start=c_{code}")
            context.user_data.clear()
            await message.reply_text("\n".join(parts), parse_mode="HTML", reply_markup=channel_links_keyboard(rows), disable_web_page_preview=True)
        except TelegramError as e:
            print(f"Channel setup error: {e}")
            await message.reply_text(
                " چنل پیدا نشد یا ربات دسترسی بررسی آن را ندارد. آیدی عمومی چنل مثل @YourChannel را بفرستید و مطمئن شوید ربات ادمین با دسترسی ارسال پست است.",
                reply_markup=back_keyboard()
            )
        return

    # =====================================================
    # BACK
    # =====================================================

    if text.strip() == "بازگشت 🔙":
        context.user_data.clear()

        await send_main_panel(
            update,
            context,
            show_reply_keyboard=False
        )

        return

    # =====================================================
    # BROADCAST
    # =====================================================

    if context.user_data.get(
        "waiting_broadcast"
    ):
        if text.lower() == "/cancel":
            context.user_data.clear()

            await message.reply_text(
                "لغو شد.\nاز منوی بالا و پایین استفاده کنید.👇🏻👆🏻"
            )

            return

        users = get_all_user_ids()

        status = await message.reply_text(
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

        await status.edit_text(
            "✅ ارسال پیام همگانی تمام شد.\n\n"
            f"موفق: {success}\n"
            f"ناموفق: {failed}\n"
            f"کل کاربران: {len(users)}"
        )

        return

    # =====================================================
    # UNBLOCK
    # =====================================================

    if text.lower().startswith(
        "/unblock_"
    ):
        code = text[
            len("/unblock_"):
        ].strip()

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
                " کد رفع مسدودی پیدا نشد."
            )

        return

    # =====================================================
    # CHANGE NAME
    # =====================================================

    if context.user_data.get(
        "changing_name"
    ):
        new_name = text.strip()

        if not new_name:
            await message.reply_text(
                " نام نمی‌تواند خالی باشد."
            )
            return

        if len(new_name) > 50:
            await message.reply_text(
                " نام خیلی طولانی است.\n"
                "حداکثر ۵۰ کاراکتر وارد کنید."
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

        if not original_message_id or not sender_id:
            context.user_data.clear()

            await message.reply_text(
                " اطلاعات پیام پیدا نشد."
            )

            return

        original = get_anonymous_message(
            original_message_id
        )

        if not original:
            context.user_data.clear()

            await message.reply_text(
                " پیام اصلی پیدا نشد."
            )

            return

        if (
            original[1] != sender_id
            or original[2] != user.id
        ):
            context.user_data.clear()

            await message.reply_text(
                " خطا در اطلاعات پیام."
            )

            return

        if is_blocked(
            user.id,
            sender_id
        ):
            context.user_data.clear()

            await message.reply_text(
                " این کاربر را بلاک کرده‌اید."
            )

            return

        new_id = save_anonymous_message(
            user.id,
            sender_id,
            text,
            "text",
            None,
            text,
            message.message_id,
            original[10] if original[10] else original[2]
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
            new_id,
            user.id,
            True,
            True,
            include_new_message=True
        )

        safe_original = html.escape(
            original[3]
        )

        safe_text = html.escape(
            text
        )

        reply_text = (
            f"کاربر {anon_code} "
            "به پیام شما پاسخ داد. 🤠\n\n"
            f"پیام شما :\n{safe_original}\n\n"
            f"پیام پاسخ داده شده :\n{safe_text}"
        )

        try:
            conversation_owner_id = original[10] or original[2]
            display = (
                f"کاربر {html.escape(get_display_name(user.id))}"
                if user.id == conversation_owner_id
                else f"کاربر {anon_code}"
            )

            # اعلان پاسخ روی پیام اصلی کاربر ریپلای می‌شود.
            # متن پاسخ در پیام جداگانه و بدون Reply ارسال خواهد شد.
            if original[9]:
                await context.bot.send_message(
                    chat_id=sender_id,
                    text=f"<b>{display} به پیام شما پاسخ داد. 🤠</b>",
                    parse_mode="HTML",
                    reply_parameters=ReplyParameters(
                        message_id=original[9],
                        allow_sending_without_reply=True
                    )
                )
            delivered = await context.bot.send_message(
                chat_id=sender_id,
                text=html.escape(text),
                reply_markup=keyboard,
                parse_mode="HTML"
            )

            try:
                set_delivered_message_id(new_id, delivered.message_id)
            except Exception as e:
                print(f"Reply delivered id save error: {e}")

            await message.reply_text(
                "✅ پاسخ شما با موفقیت ارسال شد.",
                reply_markup=back_keyboard()
            )

        except TelegramError as e:
            print(f"Reply send Telegram error: {e}")
            await message.reply_text(
                " ارسال پاسخ با خطا مواجه شد."
            )

        context.user_data.clear()

        return

    # =====================================================
    # SEND ANONYMOUS MESSAGE TO CHANNEL LINK
    # =====================================================
    if context.user_data.get("sending_channel_anonymous"):
        owner_id = context.user_data.get("channel_target_owner_id")
        channel_id = context.user_data.get("channel_target_id")
        if not owner_id or not channel_id:
            context.user_data.clear()
            await message.reply_text(" اطلاعات چنل پیدا نشد.", reply_markup=back_keyboard())
            return

        row = get_user(user.id)
        anon_code = row[4] if row else "0000000"
        message_id = save_anonymous_message(
            user.id, owner_id, text, "text", None, text, message.message_id, owner_id
        )
        keyboard = channel_message_keyboard(message_id, user.id)

        try:
            # Send the anonymous message directly, without AI moderation or a review status.
            await context.bot.send_message(
                chat_id=channel_id,
                text=f"<b>پیام ناشناس از طرف کاربر {anon_code}</b>\n\n{html.escape(text)}",
                parse_mode="HTML"
            )
            await context.bot.send_message(
                chat_id=owner_id,
                text=(
                    f"<b>پیام ناشناسی از طرف کاربر {anon_code} برای چنل شما ارسال شد.</b>\n\n"
                    f"<b>پیام :</b>\n{html.escape(text)}\n\n"
                    "<b>گزارش تخلف و بلاک 👇🏻</b>"
                ),
                parse_mode="HTML",
                reply_markup=keyboard
            )
            await message.reply_text(
                "✅ پیام ناشناس با موفقیت به چنل ارسال شد.",
                reply_markup=back_keyboard()
            )
        except TelegramError as e:
            print(f"Anonymous channel text send error: {e}")
            await message.reply_text(
                " ارسال به چنل ناموفق بود. بررسی کنید ربات هنوز ادمین چنل و دارای دسترسی ارسال پست باشد.",
                reply_markup=back_keyboard()
            )
        context.user_data.clear()
        return

    # =====================================================
    # SEND TO GROUP
    # =====================================================

    if context.user_data.get(
        "sending_group_anonymous"
    ):
        group_id = context.user_data.get(
            "group_target_id"
        )

        if not group_id:
            context.user_data.clear()

            await message.reply_text(
                " مقصد گروه پیدا نشد.",
                reply_markup=back_keyboard()
            )

            return

        if not await is_group_member(
            context.bot,
            group_id,
            user.id
        ):
            context.user_data.clear()

            await message.reply_text(
                " شما دیگر عضو این گروه نیستید.",
                reply_markup=back_keyboard()
            )

            return

        try:
            bot_member = await context.bot.get_chat_member(
                chat_id=group_id,
                user_id=context.bot.id
            )

            if bot_member.status not in (
                ChatMember.MEMBER,
                ChatMember.ADMINISTRATOR,
                ChatMember.OWNER
            ):
                raise TelegramError(
                    "Bot is not member"
                )

        except TelegramError:
            context.user_data.clear()

            await message.reply_text(
                " ربات دیگر در این گروه عضو نیست.",
                reply_markup=back_keyboard()
            )

            return

        group_message_id = save_group_message(
            group_id,
            user.id,
            text
        )

        try:
            await context.bot.send_message(
                chat_id=group_id,
                text=(
                    "<b>گروه شما یک پیام ناشناش جدید دارد 🤠</b>\n\n"
                    "<b>این پیام توسط 0 نفر مشاهده شد‌.</b>"
                ),
                reply_markup=group_view_keyboard(
                    group_message_id
                ),
                parse_mode="HTML"
            )

            await message.reply_text(
                "✅ پیام ناشناس با موفقیت در گروه ارسال شد.",
                reply_markup=back_keyboard()
            )

        except TelegramError:
            await message.reply_text(
                " خطا در ارسال پیام به گروه."
            )

        context.user_data.clear()

        return

    # =====================================================
    # SEND TO USER
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
                " مقصد پیام پیدا نشد.",
                reply_markup=back_keyboard()
            )

            return

        if target_id == user.id:
            context.user_data.clear()

            await message.reply_text(
                " نمی‌توانی به خودت پیام بفرستی.",
                reply_markup=back_keyboard()
            )

            return

        target_ban_info = get_ban_info(target_id)
        if target_ban_info:
            context.user_data.clear()
            target_user = get_user(target_id)
            target_name = (target_user[5] if target_user and target_user[5] else target_user[2] if target_user and target_user[2] else "کاربر")
            await message.reply_text(
                f"<b>حساب کاربری ({html.escape(target_name)}) مسدود شده است🟡</b>\n"
                "شما نمیتوانید به این مقصد پیامی ارسال کنید🙈\n\n"
                "« گلدن چت »", reply_markup=back_keyboard(), parse_mode="HTML")
            return

        if is_blocked(
            target_id,
            user.id
        ):
            context.user_data.clear()

            await message.reply_text(
                " شما توسط این کاربر بلاک شده‌اید.",
                reply_markup=back_keyboard()
            )

            return

        message_id = save_anonymous_message(
            user.id,
            target_id,
            text,
            "text",
            None,
            text,
            message.message_id,
            target_id
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
            message_id,
            user.id,
            True,
            True
        )

        try:
            header = await context.bot.send_message(
                chat_id=target_id,
                text=f"<b>کاربر {anon_code} برای شما پیام ناشناسی ارسال کرد : 👇🏻</b>",
                parse_mode="HTML"
            )

            delivered = await context.bot.send_message(
                chat_id=target_id,
                text=html.escape(text),
                reply_markup=keyboard,
                parse_mode="HTML",
                reply_parameters=ReplyParameters(
                    message_id=header.message_id,
                    allow_sending_without_reply=True
                )
            )
            set_delivered_message_id(message_id, delivered.message_id)

            await message.reply_text(
                "✅ پیام ناشناس با موفقیت ارسال شد.",
                reply_markup=back_keyboard()
            )

        except TelegramError:
            await message.reply_text(
                " خطا در ارسال پیام."
            )

        context.user_data.clear()

        return

    # =====================================================
    # CHANNEL ANONYMOUS BUTTON
    # =====================================================
    if text.strip() == "پیام ناشناس مستقیم به چنل 📬":
        context.user_data.clear()
        if get_channel_terms_accepted(user.id):
            rows = get_owner_channel_links(user.id)
            if rows:
                bot_username = await get_cached_bot_username(context)
                parts = ["<b>چنل‌های متصل شما و لینک اختصاصی پیام ناشناس:</b>"]
                for _, title, code in rows:
                    parts.append(f"\n<b>نام چنل :</b> {html.escape(title)}\n<b>لینک اختصاصی پیام ناشناس چنل :</b> https://t.me/{bot_username}?start=c_{code}")
                await message.reply_text("\n".join(parts), parse_mode="HTML", reply_markup=channel_links_keyboard(rows), disable_web_page_preview=True)
            else:
                bot_username = await get_cached_bot_username(context)
                context.user_data["waiting_channel_identifier"] = True
                await message.reply_text(
                    "<b>برای دریافت لینک ناشناس چنل، ابتدا ربات را با دکمه زیر به چنل اضافه و ادمین کنید 🤠</b>\n\n"
                    "بعد از ادمین کردن، روی «اضافه شد ✅» بزنید؛ سپس آیدی عمومی چنل مثل @YourChannel را ارسال کنید.",
                    parse_mode="HTML",
                    reply_markup=channel_add_prompt_keyboard(bot_username)
                )
        else:
            terms = (
                "<b>اول با دقت متن زیر را بخوانید و سپس روی میپذیریم کلیک کنید :</b>\n\n"
                "<blockquote>استفاده از این قابلیت یعنی هر کاربری هر پیامی را بتواند برای چنل شما ارسال کند.\n"
                "این ربات هیچگونه فیلتری روی پیام ها ندارد و تنها میتوانید گزارش دهید.\n"
                "شما با این قابلیت اجازه میدهید هر کاربری هر پیامی برای چنل شما ارسال کند.\n\n"
                "راهنمایی :\n"
                "این قابلیت یک لینک جداگانه از لینک پیام ناشناسی که ربات برات میفرسته ارسال میکنه با انتشار اون لینک توی چنلت ممبر های چنلت برای چنلت پیام ارسال میکنن و نیازی نیست پیام رو فوروارد کنی توی چنلت\n\n"
                "توجه !\n"
                "کاربرها فقط میتونن برای ارسال پیام به چنل فقط از متن و ویس استفاده کنن\n"
                "یعنی نه عکس و ویدیو نه هیچ چیز دیگه\n"
                "فقط متن و ویس\n"
                "ربات حتما باید توی چنل عضو باشه!!!</blockquote>\n\n"
                "<b>اگه میپذیری روی دکمه شیشه ای زیر کلیک کن 👇🏻</b>"
            )
            await message.reply_text(terms, parse_mode="HTML", reply_markup=channel_consent_keyboard())
        return

    # =====================================================
    # USER TARGET BUTTON
    # =====================================================

    if text.strip() == "پیام ناشناس به کاربر دلخواه 👤" or text.strip() == "ارسال پیام ناشناس به کاربر دلخواه 👤":
        context.user_data.clear()

        context.user_data[
            "waiting_target"
        ] = True

        await message.reply_text(
            "آیدی عددی یا آیدی کاربر را ارسال کنید.\n"
            "مثال : \n"
            "@username \n"
            "123456789\n"
            "ربات بررسی میکند در صورت عضو بودن کاربر در ربات میتوانید به او پیام ناشناس ارسال کنید❤️‍🔥",
            reply_markup=back_keyboard()
        )

        return

    # =====================================================
    # GROUP BUTTON
    # =====================================================

    if text == "پیام ناشناس به گروه 👥" or text == "ارسال پیام ناشناس به گروه 👥":
        await show_group_list(
            update,
            context
        )

        return

    # =====================================================
    # WAITING TARGET
    # =====================================================

    if context.user_data.get("waiting_target"):
        if text.strip() == "بازگشت 🔙" or text.strip().lower() == "/cancel":
            context.user_data.clear()
            await send_main_panel(update, context, show_reply_keyboard=True)
            return

        target = find_user_by_input(text.strip())

        if not target:
            await message.reply_text(
                "خطایی رخ داد ! به نظر میرسه کاربر عضو ربات نیست یا آیدی رو اشتباه وارد کردی ",
                reply_markup=back_keyboard()
            )

            return

        target_id = target[0]

        if target_id == user.id:
            bot_username = await get_cached_bot_username(context)

            own_link = (
                f"https://t.me/{bot_username}"
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
    # UNKNOWN
    # =====================================================

    await message.reply_text(
        "دستور یافت نشد 🫪\n"
        "لطفا از پنل اصلی ربات استفاده کنید.\n"
        "الان پنل رو برات میفرستم 🤠"
    )

    await send_main_panel(
        update,
        context,
        show_reply_keyboard=False
    )


# =========================================================
# BAN CALLBACK
# =========================================================

async def ban_callback(
    update,
    context
):
    query = update.callback_query
    user = update.effective_user

    if not is_manager_or_supervisor(user.id):
        await query.answer(
            "دسترسی ندارید ",
            show_alert=True
        )
        return

    if query.message and query.message.chat.type in (
        "group",
        "supergroup"
    ):
        await query.answer()
        return

    data = query.data or ""

    # CANCEL

    if data == "ban_cancel":
        context.user_data.clear()

        await query.answer(
            "عملیات بن لغو شد "
        )

        try:
            await query.edit_message_reply_markup(
                reply_markup=None
            )
        except TelegramError:
            pass

        await query.message.reply_text(
            " عملیات بن لغو شد."
        )

        return

    # DURATION

    if data.startswith(
        "ban_duration:"
    ):
        try:
            duration = int(
                data.split(":", 1)[1]
            )
        except (ValueError, IndexError):
            await query.answer(
                "مدت نامعتبر است ",
                show_alert=True
            )
            return

        if duration not in (
            1,
            3,
            5,
            7
        ):
            await query.answer(
                "مدت نامعتبر است ",
                show_alert=True
            )
            return

        ban_code = context.user_data.get(
            "ban_code"
        )

        target_id = context.user_data.get(
            "ban_target_id"
        )

        reason = context.user_data.get(
            "ban_reason"
        )

        if not ban_code or not target_id or not reason:
            context.user_data.clear()

            await query.answer(
                "اطلاعات بن پیدا نشد ",
                show_alert=True
            )

            return

        result = ban_user_by_code(
            ban_code,
            reason,
            duration
        )

        if not result:
            context.user_data.clear()

            await query.answer(
                "کد بن پیدا نشد ",
                show_alert=True
            )

            return

        banned_id, ban_until = result

        context.user_data.clear()

        await query.answer(
            "کاربر با موفقیت بن شد ✅"
        )

        try:
            await query.edit_message_reply_markup(
                reply_markup=None
            )
        except TelegramError:
            pass

        await query.message.reply_text(
            f"کاربر با موفقیت به مدت {duration} روز بن شد."
        )

        try:
            await context.bot.send_message(
                chat_id=banned_id,
                text=(
                    f"⛔ حساب کاربری شما به مدت {duration} روز مسدود شد.\n"
                    f"شناسه کاربری : {ban_code}\n"
                    f"علت : {reason}\n"
                    f"تاریخ رفع بن : {format_jalali_datetime(ban_until)}\n\n"
                    "چنانچه مطمئنید که حساب کاربری شما تخلفی نداشته و مقصر نبوده‌اید، به ادمین پیام دهید و شناسه کاربری خود + مدارک را ارسال کنید : @TMTAHAV"
                )
            )
        except TelegramError:
            pass


async def callback_router(
    update,
    context
):
    data = update.callback_query.data or ""

    if (
        data == "ban_cancel"
        or data.startswith("ban_duration:")
    ):
        await ban_callback(
            update,
            context
        )
        return

    await button_handler(
        update,
        context
    )


# =========================================================
# INLINE SHARING
# =========================================================

async def inline_share_handler(update, context):
    query = update.inline_query
    user = update.effective_user
    if not query or not user:
        return

    # Reuse the username fetched during startup instead of making a Telegram
    # API request for every inline query.
    cached_username = context.application.bot_data.get("bot_username") or context.bot.username
    if not cached_username:
        bot_username = await get_cached_bot_username(context)
        cached_username = bot_username
    bot_username = f"@{cached_username}"

    # Keep the existing personal share card available, and always show
    # a second result that sends only the bot username.
    get_or_create_user(user.id, user.username, user.full_name)
    own_link = f"https://t.me/{bot_username}?start={user.id}"
    results = [
        InlineQueryResultArticle(
            id="golden-chat-share",
            title="حوووصلم سر رفته بیاین حرف بزنیم🗣️🥀",
            description="G O L D E N  C H A T",
            input_message_content=InputTextMessageContent(
                f'<a href="{html.escape(own_link, quote=True)}"><b>حوووصلم سر رفته بیاین حرف بزنیم🗣️🥀</b></a>\n\n'
                f'<a href="{html.escape(own_link, quote=True)}">{html.escape(own_link)}</a>\n\n'
                f'<b>G O L D E N  C H A T</b>',
                parse_mode="HTML",
                disable_web_page_preview=True
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("حرف بزنیممم", url=own_link, style="primary")]
            ])
        ),
        InlineQueryResultArticle(
            id="golden-chat-bot-username",
            title="ارسال آیدی ربات",
            description="برای ارسال آیدی ربات کلیک کنید",
            input_message_content=InputTextMessageContent(bot_username)
        )
    ]
    await query.answer(results, cache_time=0, is_personal=True)


# =========================================================
# UPDATE TRACE / ERROR
# =========================================================

async def update_trace_handler(update, context):
    """Log update arrival and retain a monotonic start time for slow-update diagnostics."""
    try:
        context.application.bot_data.setdefault("_perf_update_started", {})[update.update_id] = time.monotonic()
        user = update.effective_user
        chat = update.effective_chat
        message = update.effective_message
        if update.callback_query:
            kind = "callback_query"
        elif update.inline_query:
            kind = "inline_query"
        elif message and message.text and message.text.startswith("/"):
            kind = "command"
        elif message:
            kind = "message"
        else:
            kind = "other"
        print(
            "[UPDATE RECEIVED] "
            f"id={update.update_id} kind={kind} "
            f"user_id={user.id if user else 'none'} "
            f"chat_type={chat.type if chat else 'none'}",
            flush=True,
        )
    except Exception as trace_error:
        print(f"[UPDATE TRACE ERROR] {type(trace_error).__name__}: {trace_error}", flush=True)


async def update_completion_handler(update, context):
    """Log only slow updates; never log message text or personal content."""
    started = context.application.bot_data.get("_perf_update_started", {}).pop(update.update_id, None)
    if started is None:
        return
    elapsed_ms = (time.monotonic() - started) * 1000
    if elapsed_ms >= 500:
        print(
            f"[SLOW UPDATE] id={update.update_id} elapsed_ms={elapsed_ms:.0f}",
            flush=True,
        )


async def error_handler(
    update,
    context
):
    error_text = str(context.error or "").lower()
    user = update.effective_user if update else None
    # Telegram sends no update when a person presses Stop/blocks the bot.
    # We can only mark the account when an outgoing API call reports this explicitly.
    if user and (
        "bot was blocked by the user" in error_text
        or "bot is blocked by the user" in error_text
    ):
        try:
            mark_user_bot_blocked(user.id)
        except Exception as mark_error:
            print("Could not mark blocked user:", mark_error)
    print("BOT ERROR:", repr(context.error), flush=True)


# =========================================================
# POST INIT / SHUTDOWN
# =========================================================

async def post_init(
    application
):
    global GLOBAL_BOT

    print("[BOOT] post_init entered; checking Telegram connection.", flush=True)
    try:
        bot_info = await application.bot.get_me()
        application.bot_data["bot_username"] = bot_info.username
        webhook_info = await application.bot.get_webhook_info()
        print(
            f"[BOOT] Telegram authentication OK: username=@{bot_info.username}, bot_id={bot_info.id}.",
            flush=True,
        )
        print(
            "[BOOT] Webhook status: "
            f"configured={bool(webhook_info.url)}, "
            f"pending_updates={webhook_info.pending_update_count}.",
            flush=True,
        )
    except Exception as startup_check_error:
        print(
            f"[BOOT CHECK FAILED] {type(startup_check_error).__name__}: {startup_check_error}",
            flush=True,
        )

    GLOBAL_BOT = application.bot

    application.bot_data[
        "ban_expiration_task"
    ] = asyncio.create_task(
        expire_bans_loop()
    )

    application.bot_data["automatic_group_ads_task"] = asyncio.create_task(
        automatic_group_ads_loop(application)
    )

    try:
        from telegram import BotCommand, BotCommandScopeChat

        # منوی پیش فرض برای کاربران عادی فقط کامندهای عمومی ربات است.
        # کامندهای مدیریتی/نظارتی فقط با scope اختصاصی برای مدیر یا ناظر نمایش داده می‌شوند.
        await application.bot.set_my_commands([
            BotCommand("start", "شروع ربات"),
            BotCommand("cancel", "لغو عملیات"),
        ])

        # منوی اختصاصی مدیر اصلی
        await application.bot.set_my_commands([
            BotCommand("start", "شروع ربات"),
            BotCommand("cancel", "لغو عملیات"),
            BotCommand("linkgroup", "مدیریت گروه"),
            BotCommand("broadcast", "پیام همگانی"),
            BotCommand("userban", "لیست بن شده ها"),
            BotCommand("userbot", "لیست کاربران"),
            BotCommand("changeusername", "تغییر نام کاربر"),
            BotCommand("addadmin", "مدیریت ناظران"),
            BotCommand("groupadmin", "مدیریت پیام‌های گروهی"),
        ], scope=BotCommandScopeChat(ADMIN_ID))

        # منوی اختصاصی هر ناظر
        for row in get_supervisors():
            await application.bot.set_my_commands([
                BotCommand("cdb", "دریافت کامند های ناظر"),
                BotCommand("userbot", "مشاهده کاربران ربات"),
                BotCommand("userban", "لیست کاربران بن شده"),
                BotCommand("broadcast", "ارسال پیام همگانی"),
                BotCommand("changeusername", "تغییر نام کاربر"),
                BotCommand("ban_", "بن کردن کاربر با شناسه"),
                BotCommand("unban_", "درخواست رفع بن کاربر"),
            ], scope=BotCommandScopeChat(row[0]))
    except Exception as e:
        print("Command scope setup error:", e)


async def post_shutdown(
    application
):
    global DB_POOL
    global GLOBAL_BOT

    task = application.bot_data.get(
        "ban_expiration_task"
    )

    ads_task = application.bot_data.get("automatic_group_ads_task")
    if ads_task:
        ads_task.cancel()
        try:
            await ads_task
        except asyncio.CancelledError:
            pass

    if task:
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

    GLOBAL_BOT = None

    if DB_POOL is not None:
        DB_POOL.closeall()
        DB_POOL = None


# =========================================================
# MAIN
# =========================================================

def main():
    print("[BOOT] main.py entered.", flush=True)

    # Expose HTTP health endpoints for Deplexo's web-service readiness check.
    Thread(target=start_health_server, daemon=True).start()
    print("[BOOT] Health server thread started.", flush=True)

    print("[BOOT] Creating PostgreSQL connection pool.", flush=True)
    create_db_pool()

    print("[BOOT] Initializing database schema (existing data is preserved).", flush=True)
    init_db()
    print("[BOOT] Database initialization completed.", flush=True)

    # Tune Telegram HTTP connection pools so bursts of sends/edits do not
    # queue behind a tiny default pool. Keep update processing sequential:
    # many Golden Chat flows rely on context.user_data and must stay ordered.
    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .connection_pool_size(32)
        .pool_timeout(10)
        .connect_timeout(10)
        .read_timeout(20)
        .write_timeout(20)
        .get_updates_connection_pool_size(4)
        .get_updates_pool_timeout(10)
        .get_updates_connect_timeout(10)
        .get_updates_read_timeout(30)
        .get_updates_write_timeout(10)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # COMMANDS

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "linkgroup",
            linkgroup_command
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
            "changeusername",
            changeusername_command
        )
    )

    application.add_handler(
        CommandHandler(
            "cdb",
            cdb_command
        )
    )

    application.add_handler(
        CommandHandler(
            "addadmin",
            addadmin_command
        )
    )

    application.add_handler(
        CommandHandler(
            "groupadmin",
            group_admin_command
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel_command
        )
    )

    # Capture arbitrary message types for the admin group-broadcast flow before normal handlers.
    application.add_handler(
        MessageHandler(filters.ALL, group_admin_input_handler),
        group=-3,
    )

    # Track group activity before other message handlers (does not consume the update).
    application.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS,
            track_group_activity
        ),
        group=-2,
    )

    # BOT ADDED TO GROUP

    application.add_handler(
        ChatMemberHandler(
            bot_group_membership_update,
            ChatMemberHandler.MY_CHAT_MEMBER
        )
    )

    # Inline mode must be enabled for this bot in BotFather.
    application.add_handler(
        InlineQueryHandler(
            inline_share_handler
        )
    )

    # CALLBACKS

    application.add_handler(
        CallbackQueryHandler(
            callback_router
        )
    )

    # ANONYMOUS MEDIA

    application.add_handler(
        MessageHandler(
            (filters.PHOTO | filters.VIDEO | filters.VOICE | filters.AUDIO | filters.Document.ALL),
            media_handler
        )
    )

    # TEXT

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    # COMMAND-LIKE TEXT

    application.add_handler(
        MessageHandler(
            filters.COMMAND,
            handle_message
        )
    )

    # This handler runs first and logs incoming update metadata without message text.
    application.add_handler(
        TypeHandler(Update, update_trace_handler),
        group=-1,
    )

    # Runs after normal handlers and reports only updates taking >= 500 ms.
    # This is intentionally lightweight and does not change update concurrency.
    application.add_handler(
        TypeHandler(Update, update_completion_handler),
        group=99,
    )

    application.add_error_handler(
        error_handler
    )

    print("[BOOT] Handlers registered; starting Telegram polling now.", flush=True)
    print("[BOOT] PostgreSQL service: Postgre.", flush=True)

    try:
        application.run_polling(
            drop_pending_updates=False,
            bootstrap_retries=-1,
        )
    except Exception as polling_error:
        print(
            f"[POLLING FATAL] {type(polling_error).__name__}: {polling_error}",
            flush=True,
        )
        raise
    finally:
        print("[BOOT] Telegram polling loop exited.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as fatal_error:
        print(
            f"[FATAL STARTUP ERROR] {type(fatal_error).__name__}: {fatal_error}",
            flush=True,
        )
        raise

# Redeploy trigger: verified channel-review animation and moderation flow.
