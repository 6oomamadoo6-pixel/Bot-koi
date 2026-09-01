import os
import sqlite3
import random
import string
from datetime import datetime

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

DB_NAME = "bot.db"


# =========================================================
# DATABASE
# =========================================================

def db():
    return sqlite3.connect(DB_NAME)


def init_db():
    conn = db()
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
            unblock_code TEXT UNIQUE,
            PRIMARY KEY (blocker_id, blocked_id)
        )
    """)

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

    conn.commit()
    conn.close()

    fill_missing_unblock_codes()


# =========================================================
# CODE GENERATORS
# =========================================================

def generate_code(length=10):
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=length))


def generate_anon_code():
    conn = db()
    cur = conn.cursor()

    while True:
        code = "".join(
            random.choices(string.digits, k=7)
        )

        cur.execute(
            "SELECT 1 FROM users WHERE anon_code = ?",
            (code,)
        )

        if cur.fetchone() is None:
            conn.close()
            return code


def generate_unblock_code():
    conn = db()
    cur = conn.cursor()

    while True:
        code = generate_code(10)

        cur.execute(
            "SELECT 1 FROM blocks WHERE unblock_code = ?",
            (code,)
        )

        if cur.fetchone() is None:
            conn.close()
            return code


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
    """, (user_id,))

    row = cur.fetchone()

    if row:
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
    """, (link_code,))

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
    """, (user_id,))

    row = cur.fetchone()

    conn.close()

    if not row:
        return "کاربر"

    return row[0] or row[1] or "کاربر"


def set_display_name(user_id, name):
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
# BLOCK FUNCTIONS
# =========================================================

def is_blocked(blocker_id, blocked_id):
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


def block_user(blocker_id, blocked_id):
    if blocker_id == blocked_id:
        return None

    conn = db()
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
        INSERT INTO blocks (
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


def unblock_by_code(user_id, code):
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
    """, (user_id,))

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

    except TelegramError as exc:
        print(
            f"Membership error: "
            f"{channel} / {user_id}: {exc}"
        )
        return False


async def is_member(bot, user_id):
    first = await check_channel_member(
        bot,
        CHANNEL_1,
        user_id
    )

    if not first:
        return False

    second = await check_channel_member(
        bot,
        CHANNEL_2,
        user_id
    )

    return second


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


def name_keyboard():
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
# START
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

    # -----------------------------------------------------
    # LINK START
    # -----------------------------------------------------

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
        full_name = target[1]
        display_name = target[2]

        # -------------------------------------------------
        # SELF LINK
        # -------------------------------------------------

        if target_id == user.id:
            bot = await context.bot.get_me()

            own_link = (
                f"https://t.me/"
                f"{bot.username}"
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
        # FORCE JOIN
        # -------------------------------------------------

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

        context.user_data["target_id"] = target_id

        target_name = (
            display_name
            or full_name
            or "کاربر"
        )

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
        f"https://t.me/"
        f"{bot.username}"
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

    current = get_display_name(
        user.id
    )

    text = (
        "⚙️ تنظیمات نام\n\n"
        f"نام فعلی شما:\n"
        f"{current}\n\n"
        "می‌توانید نامی را انتخاب کنید که "
        "هنگام باز شدن لینک به فرستنده نمایش داده شود."
    )

    await update.callback_query.edit_message_text(
        text,
        reply_markup=name_keyboard()
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
    user_id = update.effective_user.id

    rows = get_block_list(
        user_id
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

        if index < len(rows) - 1:
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
# BUTTON HANDLER
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    user = query.from_user
    data = query.data or ""

    await query.answer()

    # -----------------------------------------------------
    # CHECK JOIN
    # -----------------------------------------------------

    if data == "check_join":
        if await is_member(
            context.bot,
            user.id
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
            user.id
        ):
            await send_join_message(
                update,
                context
            )
        else:
            await send_main_panel(
                update,
                context
            )

        return

    # -----------------------------------------------------
    # CANCEL SEND
    # -----------------------------------------------------

    if data == "cancel_send":
        context.user_data.clear()

        await query.edit_message_text(
            "❌ ارسال پیام ناشناس لغو شد.",
            reply_markup=back_keyboard()
        )

        return

    # -----------------------------------------------------
    # COPY LINK
    # -----------------------------------------------------

    if data == "copy_link":
        await show_link(
            update,
            context
        )
        return

    # -----------------------------------------------------
    # NAME SETTINGS
    # -----------------------------------------------------

    if data == "name_settings":
        await name_settings(
            update,
            context
        )
        return

    # -----------------------------------------------------
    # CHANGE NAME
    # -----------------------------------------------------

    if data == "change_name":
        context.user_data.clear()
        context.user_data["awaiting_name"] = True

        await query.edit_message_text(
            "✏️ نام جدید خودت را ارسال کن:\n\n"
            "این نام به فرستنده لینک ناشناس "
            "نمایش داده می‌شود.",
            reply_markup=back_keyboard()
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

    if data.startswith("reply_"):
        try:
            target_id = int(
                data.split("_", 1)[1]
            )
        except (ValueError, IndexError):
            await query.answer(
                "دکمه نامعتبر است.",
                show_alert=True
            )
            return

        if target_id == user.id:
            await query.answer(
                "این کاربر نامعتبر است.",
                show_alert=True
            )
            return

        context.user_data.clear()
        context.user_data["reply_to"] = target_id

        await query.message.reply_text(
            "💬 پاسخ خود را بنویسید:",
            reply_markup=cancel_keyboard()
        )

        return

    # -----------------------------------------------------
    # BLOCK
    # -----------------------------------------------------

    if data.startswith("block_"):
        try:
            blocked_id = int(
                data.split("_", 1)[1]
            )
        except (ValueError, IndexError):
            await query.answer(
                "دکمه نامعتبر است.",
                show_alert=True
            )
            return

        if blocked_id == user.id:
            await query.answer(
                "نمی‌توانی خودت را بلاک کنی.",
                show_alert=True
            )
            return

        block_user(
            user.id,
            blocked_id
        )

        await query.edit_message_text(
            "🔴 کاربر با موفقیت بلاک شد.",
            reply_markup=back_keyboard()
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

    text = message.text or ""
    stripped = text.strip()

    # -----------------------------------------------------
    # UNBLOCK
    # -----------------------------------------------------

    if (
        stripped.startswith("unblock_")
        and stripped.endswith("/")
    ):
        if not await is_member(
            context.bot,
            user.id
        ):
            await send_join_message(
                update,
                context
            )
            return

        code = stripped[
            len("unblock_"):-1
        ].strip()

        if code and unblock_by_code(
            user.id,
            code
        ):
            await message.reply_text(
                "🟢 کاربر با موفقیت "
                "از لیست مسدودی خارج شد.",
                reply_markup=back_keyboard()
            )
        else:
            await message.reply_text(
                "❌ کد رفع مسدودی نامعتبر است "
                "یا قبلاً استفاده شده.",
                reply_markup=back_keyboard()
            )

        return

    # -----------------------------------------------------
    # MEMBERSHIP
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

    # -----------------------------------------------------
    # NAME
    # -----------------------------------------------------

    if context.user_data.get(
        "awaiting_name"
    ):
        name = stripped

        if not name:
            await message.reply_text(
                "❌ نام نمی‌تواند خالی باشد.\n"
                "دوباره نام را ارسال کن."
            )
            return

        if len(name) > 40:
            await message.reply_text(
                "❌ نام خیلی طولانی است. "
                "حداکثر ۴۰ کاراکتر."
            )
            return

        set_display_name(
            user.id,
            name
        )

        context.user_data.clear()

        await message.reply_text(
            f"✅ نام شما با موفقیت تغییر کرد.\n\n"
            f"نام جدید: {name}",
            reply_markup=back_keyboard()
        )

        return

    # -----------------------------------------------------
    # ANONYMOUS MESSAGE
    # -----------------------------------------------------

    if "target_id" in context.user_data:
        target_id = context.user_data[
            "target_id"
        ]

        if target_id == user.id:
            context.user_data.clear()

            await message.reply_text(
                "به خودت که نمیتونی پیام بفرستی عزیز 🥹",
                reply_markup=back_keyboard()
            )

            return

        if is_blocked(
            target_id,
            user.id
        ):
            context.user_data.clear()

            await message.reply_text(
                "❌ شما توسط این کاربر "
                "بلاک شده‌اید.",
                reply_markup=back_keyboard()
            )

            return

        conn = db()
        cur = conn.cursor()

        cur.execute(
            "SELECT anon_code FROM users WHERE user_id = ?",
            (user.id,)
        )

        row = cur.fetchone()

        conn.close()

        anon_code = (
            row[0]
            if row
            else "0000000"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "پاسخ",
                    callback_data=f"reply_{user.id}"
                ),
                InlineKeyboardButton(
                    "بلاک",
                    callback_data=f"block_{user.id}"
                )
            ]
        ])

        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    f"👤 کاربر {anon_code} "
                    "برای شما پیام ناشناسی ارسال کرد:\n\n"
                    f"{text}"
                ),
                reply_markup=keyboard
            )

            await message.reply_text(
                "✅ پیام ناشناس با موفقیت ارسال شد.",
                reply_markup=back_keyboard()
            )

        except TelegramError as exc:
            print(
                f"Anonymous message error: {exc}"
            )

            await message.reply_text(
                "❌ خطا در ارسال پیام. "
                "ممکن است کاربر ربات را بلاک کرده باشد.",
                reply_markup=back_keyboard()
            )

        context.user_data.clear()

        return

    # -----------------------------------------------------
    # REPLY
    # -----------------------------------------------------

    if "reply_to" in context.user_data:
        target_id = context.user_data[
            "reply_to"
        ]

        if target_id == user.id:
            context.user_data.clear()

            await message.reply_text(
                "❌ پاسخ نامعتبر است.",
                reply_markup=back_keyboard()
            )

            return

        if is_blocked(
            target_id,
            user.id
        ):
            context.user_data.clear()

            await message.reply_text(
                "❌ شما توسط این کاربر "
                "بلاک شده‌اید.",
                reply_markup=back_keyboard()
            )

            return

        conn = db()
        cur = conn.cursor()

        cur.execute(
            "SELECT anon_code FROM users WHERE user_id = ?",
            (user.id,)
        )

        row = cur.fetchone()

        conn.close()

        anon_code = (
            row[0]
            if row
            else "0000000"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "پاسخ",
                    callback_data=f"reply_{user.id}"
                ),
                InlineKeyboardButton(
                    "بلاک",
                    callback_data=f"block_{user.id}"
                )
            ]
        ])

        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    f"💬 پاسخ ناشناس از کاربر "
                    f"{anon_code}:\n\n{text}"
                ),
                reply_markup=keyboard
            )

            await message.reply_text(
                "✅ پاسخ ناشناس ارسال شد.",
                reply_markup=back_keyboard()
            )

        except TelegramError as exc:
            print(
                f"Reply error: {exc}"
            )

            await message.reply_text(
                "❌ خطا در ارسال پاسخ.",
                reply_markup=back_keyboard()
            )

        context.user_data.clear()

        return

    # -----------------------------------------------------
    # DEFAULT
    # -----------------------------------------------------

    await send_main_panel(
        update,
        context
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):
    print(
        f"Unhandled error: "
        f"{context.error!r}"
    )


# =========================================================
# MAIN
# =========================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is not set. "
            "Add BOT_TOKEN in Railway Variables."
        )

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

    app.add_error_handler(
        error_handler
    )

    print(
        "ربات روشن شد و در حال اتصال به Telegram است..."
    )

    app.run_polling(
        drop_pending_updates=True
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
