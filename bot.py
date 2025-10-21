import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from dotenv import load_dotenv
from zoneinfo import ZoneInfo

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ---------------------------
# Конфигурация и константы
# ---------------------------

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_TZ = os.getenv("BOT_TZ", "Europe/Moscow")
DATABASE_PATH = os.getenv("DATABASE_PATH", "todo.db")

TZ = ZoneInfo(BOT_TZ)

# Этапы диалога для /add
ADD_TEXT, ADD_DEADLINE, ADD_PRIORITY = range(3)

# Этапы диалога для /edit
EDIT_CHOOSE, EDIT_TEXT, EDIT_DEADLINE, EDIT_PRIORITY = range(4)

# Быстрые варианты сроков
QUICK_DEADLINES = ["Сегодня", "Завтра", "Через 3 дня", "Без срока"]

# Приоритеты
PRIORITY_LABELS = {
    3: "🔴 Высокий",
    2: "🟡 Средний",
    1: "🔵 Низкий",
}
PRIORITY_FROM_LABEL = {
    "🔴 Высокий": 3,
    "🟡 Средний": 2,
    "🔵 Низкий": 1,
}
PRIORITY_ORDER = [3, 2, 1]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("task-bot")


# ---------------------------
# Утилиты даты/времени
# ---------------------------

def now_tz() -> datetime:
    return datetime.now(TZ)


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(ZoneInfo("UTC"))


def from_utc_str(iso_str: Optional[str]) -> Optional[datetime]:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(TZ)
    except Exception:
        return None


def to_utc_str(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return to_utc(dt).isoformat()


def human_datetime(dt: Optional[datetime]) -> str:
    if dt is None:
        return "Без срока"
    return dt.strftime("%d.%m.%Y %H:%M")


def parse_user_deadline(value: str) -> Optional[datetime]:
    """
    Парсит ввод пользователя:
    - Сегодня/Завтра/Через 3 дня/Без срока
    - DD.MM.YYYY
    - DD.MM.YYYY HH:MM
    - YYYY-MM-DD
    - YYYY-MM-DD HH:MM
    Если указана только дата — дедлайн принимается как 23:59 локального времени.
    Возвращает datetime в локальной TZ или None (без срока).
    """
    v = (value or "").strip()
    if not v:
        return None

    v_low = v.lower()
    if v_low == "без срока":
        return None
    if v_low == "сегодня":
        d = now_tz().date()
        return datetime(d.year, d.month, d.day, 23, 59, tzinfo=TZ)
    if v_low == "завтра":
        d = now_tz().date() + timedelta(days=1)
        return datetime(d.year, d.month, d.day, 23, 59, tzinfo=TZ)
    if v_low in ("через 3 дня", "через три дня"):
        d = now_tz().date() + timedelta(days=3)
        return datetime(d.year, d.month, d.day, 23, 59, tzinfo=TZ)

    # Попробуем форматы с временем
    fmts = [
        "%d.%m.%Y %H:%M",
        "%Y-%m-%d %H:%M",
        "%d.%m.%Y",
        "%Y-%m-%d",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(v, fmt)
            if "%H:%M" not in fmt:
                dt = dt.replace(hour=23, minute=59)
            return dt.replace(tzinfo=TZ)
        except ValueError:
            continue

    return None


# ---------------------------
# Слой доступа к данным (SQLite)
# ---------------------------

class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.ensure_schema()

    def ensure_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 2,
                due_at_utc TEXT NULL,
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS archive_tasks (
                id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                priority INTEGER NOT NULL,
                due_at_utc TEXT NULL,
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL,
                done_at_utc TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL UNIQUE,
                chat_id INTEGER NOT NULL,
                notify_at_utc TEXT NOT NULL,
                sent INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
            )
            """
        )
        self.conn.commit()

    # -------- Tasks ---------
    def create_task(
        self,
        chat_id: int,
        user_id: int,
        text: str,
        priority: int,
        due_at_local: Optional[datetime],
    ) -> int:
        now_utc = to_utc_str(now_tz())
        due_utc = to_utc_str(due_at_local)
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO tasks (chat_id, user_id, text, priority, due_at_utc, created_at_utc, updated_at_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (chat_id, user_id, text, priority, due_utc, now_utc, now_utc),
        )
        task_id = cur.lastrowid
        self.conn.commit()
        return task_id

    def get_task(self, chat_id: int, task_id: int) -> Optional[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM tasks WHERE chat_id = ? AND id = ?",
            (chat_id, task_id),
        )
        row = cur.fetchone()
        return row

    def update_task_text(self, chat_id: int, task_id: int, text: str) -> bool:
        cur = self.conn.cursor()
        cur.execute(
            """
            UPDATE tasks
            SET text = ?, updated_at_utc = ?
            WHERE chat_id = ? AND id = ?
            """,
            (text, to_utc_str(now_tz()), chat_id, task_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def update_task_priority(self, chat_id: int, task_id: int, priority: int) -> bool:
        cur = self.conn.cursor()
        cur.execute(
            """
            UPDATE tasks
            SET priority = ?, updated_at_utc = ?
            WHERE chat_id = ? AND id = ?
            """,
            (priority, to_utc_str(now_tz()), chat_id, task_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def update_task_due(self, chat_id: int, task_id: int, due_at_local: Optional[datetime]) -> bool:
        cur = self.conn.cursor()
        cur.execute(
            """
            UPDATE tasks
            SET due_at_utc = ?, updated_at_utc = ?
            WHERE chat_id = ? AND id = ?
            """,
            (to_utc_str(due_at_local), to_utc_str(now_tz()), chat_id, task_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def delete_task(self, chat_id: int, task_id: int) -> bool:
        cur = self.conn.cursor()
        cur.execute(
            "DELETE FROM tasks WHERE chat_id = ? AND id = ?",
            (chat_id, task_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def archive_task(self, chat_id: int, task_id: int) -> Optional[sqlite3.Row]:
        task = self.get_task(chat_id, task_id)
        if not task:
            return None
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO archive_tasks
                (id, chat_id, user_id, text, priority, due_at_utc, created_at_utc, updated_at_utc, done_at_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task["id"],
                task["chat_id"],
                task["user_id"],
                task["text"],
                task["priority"],
                task["due_at_utc"],
                task["created_at_utc"],
                task["updated_at_utc"],
                to_utc_str(now_tz()),
            ),
        )
        cur.execute("DELETE FROM tasks WHERE id = ? AND chat_id = ?", (task_id, chat_id))
        self.conn.commit()
        return task

    def list_tasks_sorted(self, chat_id: int) -> List[sqlite3.Row]:
        # NULLS LAST для due (имитация через CASE)
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT *
            FROM tasks
            WHERE chat_id = ?
            ORDER BY priority DESC,
                     CASE WHEN due_at_utc IS NULL THEN 1 ELSE 0 END ASC,
                     due_at_utc ASC
            """,
            (chat_id,),
        )
        return cur.fetchall()

    # -------- Reminders ---------
    def upsert_reminder(self, chat_id: int, task_id: int, notify_at_local: Optional[datetime]) -> None:
        cur = self.conn.cursor()
        if notify_at_local is None:
            # Удаляем напоминание, если было
            cur.execute("DELETE FROM reminders WHERE task_id = ?", (task_id,))
            self.conn.commit()
            return
        cur.execute(
            """
            INSERT INTO reminders (task_id, chat_id, notify_at_utc, sent)
            VALUES (?, ?, ?, 0)
            ON CONFLICT(task_id) DO UPDATE SET
                chat_id = excluded.chat_id,
                notify_at_utc = excluded.notify_at_utc,
                sent = 0
            """,
            (task_id, chat_id, to_utc_str(notify_at_local)),
        )
        self.conn.commit()

    def due_reminders(self, now_local: datetime) -> List[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT * FROM reminders
            WHERE sent = 0 AND notify_at_utc <= ?
            """,
            (to_utc_str(now_local),),
        )
        return cur.fetchall()

    def mark_reminder_sent(self, reminder_id: int) -> None:
        cur = self.conn.cursor()
        cur.execute("UPDATE reminders SET sent = 1 WHERE id = ?", (reminder_id,))
        self.conn.commit()


# ---------------------------
# Вспомогательные функции форматирования
# ---------------------------

def format_task_summary(task_row: sqlite3.Row) -> str:
    due = from_utc_str(task_row["due_at_utc"])
    pr = int(task_row["priority"]) if task_row["priority"] is not None else 2
    parts = [
        f"📝 <b>Текст задачи</b>: {escape_html(task_row['text'])}",
        f"⏰ <b>Срок</b>: {escape_html(human_datetime(due))}",
        f"🎯 <b>Приоритет</b>: {PRIORITY_LABELS.get(pr, '🟡 Средний')}",
        f"ID: <code>#{task_row['id']}</code>",
    ]
    return "\n".join(parts)


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def compute_notify_time(due_local: Optional[datetime]) -> Optional[datetime]:
    if due_local is None:
        return None
    return due_local - timedelta(minutes=1)


# ---------------------------
# Хэндлеры команд
# ---------------------------

DB = Database(DATABASE_PATH)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Я бот-ассистент для задач.\n\n"
        "Доступные команды:\n"
        "/add — добавить задачу\n"
        "/edit <id> — редактировать задачу\n"
        "/done <id> — отметить как выполненную\n"
        "/delete <id> — удалить задачу\n"
        "/list — показать список задач",
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


# ----- /add -----
async def add_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["add_task"] = {}
    await update.message.reply_text("Шаг 1/3. Введите текст задачи: 📝")
    return ADD_TEXT


async def add_got_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Пустой текст. Введите текст задачи:")
        return ADD_TEXT
    context.user_data["add_task"]["text"] = text
    # Предложить быстрые кнопки срока
    keyboard = [[d] for d in QUICK_DEADLINES]
    await update.message.reply_text(
        "Шаг 2/3. Укажите срок выполнения: ⏰\n"
        "Можно выбрать кнопку или ввести дату вручную (напр. 21.10.2025 18:00)",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
    )
    return ADD_DEADLINE


async def add_got_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.message.text or "").strip()
    due_local = parse_user_deadline(value)
    if value.lower() != "без срока" and due_local is None:
        await update.message.reply_text(
            "Не удалось распознать дату. Примеры: 2025-10-21 18:00, 21.10.2025, Сегодня, Завтра, Через 3 дня, Без срока.\n"
            "Попробуйте снова:",
        )
        return ADD_DEADLINE
    context.user_data["add_task"]["due"] = due_local

    # Кнопки приоритета
    keyboard = [["🔴 Высокий"], ["🟡 Средний"], ["🔵 Низкий"]]
    await update.message.reply_text(
        "Шаг 3/3. Выберите приоритет: 🎯",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
    )
    return ADD_PRIORITY


async def add_got_priority(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    label = (update.message.text or "").strip()
    if label not in PRIORITY_FROM_LABEL:
        await update.message.reply_text(
            "Неверный приоритет. Выберите из кнопок: 🔴 Высокий / 🟡 Средний / 🔵 Низкий",
        )
        return ADD_PRIORITY

    pr = PRIORITY_FROM_LABEL[label]
    draft = context.user_data.get("add_task", {})
    text = draft.get("text")
    due_local = draft.get("due")

    # Сохраняем в базу
    user = update.effective_user
    chat = update.effective_chat
    task_id = DB.create_task(chat.id, user.id, text, pr, due_local)

    # Напоминание (за 1 минуту до дедлайна)
    notify_local = compute_notify_time(due_local)
    DB.upsert_reminder(chat.id, task_id, notify_local)

    task_row = DB.get_task(chat.id, task_id)
    await update.message.reply_html(
        "✅ Задача создана!\n\n" + format_task_summary(task_row),
        reply_markup=ReplyKeyboardRemove(),
    )

    # очистка
    context.user_data.pop("add_task", None)
    return ConversationHandler.END


async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("add_task", None)
    await update.message.reply_text("Создание задачи отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ----- /edit -----

def _parse_task_id_from_args(args: List[str]) -> Optional[int]:
    if not args:
        return None
    try:
        tid = int(args[0].lstrip("#"))
        return tid
    except Exception:
        return None


async def edit_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    args = context.args or []
    chat = update.effective_chat
    task_id = _parse_task_id_from_args(args)
    if not task_id:
        await update.message.reply_text("Укажите ID: /edit <id>")
        return ConversationHandler.END

    task = DB.get_task(chat.id, task_id)
    if not task:
        await update.message.reply_text("Задача не найдена.")
        return ConversationHandler.END

    context.user_data["edit_task_id"] = task_id
    await update.message.reply_html(
        "Редактирование задачи:\n\n" + format_task_summary(task)
    )

    keyboard = [["Текст"], ["Срок"], ["Приоритет"], ["Готово"]]
    await update.message.reply_text(
        "Что хотите изменить?",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )
    return EDIT_CHOOSE


async def edit_choose(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = (update.message.text or "").strip().lower()
    if choice == "готово":
        task_id = context.user_data.get("edit_task_id")
        chat = update.effective_chat
        if task_id:
            task = DB.get_task(chat.id, int(task_id))
            if task:
                await update.message.reply_html(
                    "✅ Изменения сохранены!\n\n" + format_task_summary(task),
                    reply_markup=ReplyKeyboardRemove(),
                )
        context.user_data.pop("edit_task_id", None)
        return ConversationHandler.END

    if choice == "текст":
        await update.message.reply_text("Введите новый текст задачи: 📝")
        return EDIT_TEXT

    if choice == "срок":
        keyboard = [[d] for d in QUICK_DEADLINES]
        await update.message.reply_text(
            "Укажите новый срок выполнения: ⏰",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
        )
        return EDIT_DEADLINE

    if choice == "приоритет":
        keyboard = [["🔴 Высокий"], ["🟡 Средний"], ["🔵 Низкий"]]
        await update.message.reply_text(
            "Выберите новый приоритет: 🎯",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
        )
        return EDIT_PRIORITY

    await update.message.reply_text("Не понял выбор. Нажмите кнопку.")
    return EDIT_CHOOSE


async def edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Пустой текст. Введите новый текст:")
        return EDIT_TEXT
    task_id = int(context.user_data.get("edit_task_id"))
    chat = update.effective_chat
    DB.update_task_text(chat.id, task_id, text)
    await update.message.reply_text("✅ Текст обновлён.")

    # Возврат к меню выбора
    keyboard = [["Текст"], ["Срок"], ["Приоритет"], ["Готово"]]
    await update.message.reply_text(
        "Что ещё изменить?",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )
    return EDIT_CHOOSE


async def edit_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.message.text or "").strip()
    due_local = parse_user_deadline(value)
    if value.lower() != "без срока" and due_local is None:
        await update.message.reply_text(
            "Не удалось распознать дату. Примеры: 2025-10-21 18:00, 21.10.2025, Сегодня, Завтра, Через 3 дня, Без срока.\n"
            "Попробуйте снова:",
        )
        return EDIT_DEADLINE

    task_id = int(context.user_data.get("edit_task_id"))
    chat = update.effective_chat
    DB.update_task_due(chat.id, task_id, due_local)
    DB.upsert_reminder(chat.id, task_id, compute_notify_time(due_local))
    await update.message.reply_text("✅ Срок обновлён.")

    keyboard = [["Текст"], ["Срок"], ["Приоритет"], ["Готово"]]
    await update.message.reply_text(
        "Что ещё изменить?",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )
    return EDIT_CHOOSE


async def edit_priority(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    label = (update.message.text or "").strip()
    if label not in PRIORITY_FROM_LABEL:
        await update.message.reply_text("Выберите один из вариантов.")
        return EDIT_PRIORITY

    priority = PRIORITY_FROM_LABEL[label]
    task_id = int(context.user_data.get("edit_task_id"))
    chat = update.effective_chat
    DB.update_task_priority(chat.id, task_id, priority)
    await update.message.reply_text("✅ Приоритет обновлён.")

    keyboard = [["Текст"], ["Срок"], ["Приоритет"], ["Готово"]]
    await update.message.reply_text(
        "Что ещё изменить?",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )
    return EDIT_CHOOSE


async def edit_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("edit_task_id", None)
    await update.message.reply_text("Редактирование отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ----- /done -----
async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    chat = update.effective_chat
    task_id = _parse_task_id_from_args(args)
    if not task_id:
        await update.message.reply_text("Укажите ID: /done <id>")
        return

    existing = DB.get_task(chat.id, task_id)
    if not existing:
        await update.message.reply_text("Задача не найдена.")
        return

    archived = DB.archive_task(chat.id, task_id)
    if archived:
        await update.message.reply_text(
            f"Отлично! Задача '{archived['text']}' выполнена! 🎉"
        )
    else:
        await update.message.reply_text("Не удалось архивировать задачу.")


# ----- /delete -----
async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    chat = update.effective_chat
    task_id = _parse_task_id_from_args(args)
    if not task_id:
        await update.message.reply_text("Укажите ID: /delete <id>")
        return

    task = DB.get_task(chat.id, task_id)
    if not task:
        await update.message.reply_text("Задача не найдена.")
        return

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Да", callback_data=f"del:{task_id}:yes"),
            InlineKeyboardButton("Нет", callback_data=f"del:{task_id}:no"),
        ]
    ])
    await update.message.reply_text(
        f"Вы уверены, что хотите удалить задачу '{task['text']}'?",
        reply_markup=kb,
    )


async def delete_confirm_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = (query.data or "")
    if not data.startswith("del:"):
        return

    _, task_id_str, decision = data.split(":", 2)
    try:
        task_id = int(task_id_str)
    except Exception:
        await query.edit_message_text("Некорректный запрос.")
        return

    chat = update.effective_chat
    task = DB.get_task(chat.id, task_id)
    if not task:
        await query.edit_message_text("Задача не найдена.")
        return

    if decision == "yes":
        if DB.delete_task(chat.id, task_id):
            await query.edit_message_text("Задача удалена.")
        else:
            await query.edit_message_text("Не удалось удалить задачу.")
    else:
        await query.edit_message_text("Удаление отменено.")


# ----- /list -----
async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    rows = DB.list_tasks_sorted(chat.id)
    if not rows:
        await update.message.reply_text("Список задач пуст. Добавьте с помощью /add")
        return

    groups: Dict[int, List[sqlite3.Row]] = {3: [], 2: [], 1: []}
    for r in rows:
        groups[int(r["priority"])].append(r)

    lines: List[str] = ["Ваши задачи:"]
    for pr in PRIORITY_ORDER:
        items = groups.get(pr, [])
        if not items:
            continue
        lines.append("")
        lines.append(f"{PRIORITY_LABELS[pr]}:")
        for r in items:
            due = from_utc_str(r["due_at_utc"])  # локальное время
            lines.append(
                f"• [#{r['id']}] {r['text']} — ⏰ {human_datetime(due)}"
            )

    await update.message.reply_text("\n".join(lines))


# ---------------------------
# Воркер напоминаний
# ---------------------------
async def reminders_worker(_: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        due_list = DB.due_reminders(now_tz())
        for rem in due_list:
            try:
                task = DB.get_task(rem["chat_id"], rem["task_id"])  # может быть уже удалена
                chat_id = rem["chat_id"]
                if task:
                    due = from_utc_str(task["due_at_utc"]) or now_tz()
                    text = task["text"]
                    msg = f"Напоминание: через минуту у вас запланировано '{text}'."
                else:
                    msg = "Напоминание по задаче."
                # Инициируем отправку через глобальное приложение
                await app.bot.send_message(chat_id=chat_id, text=msg)
                DB.mark_reminder_sent(rem["id"])
            except Exception as e:
                logger.exception("Ошибка при отправке напоминания: %s", e)
    except Exception as e:
        logger.exception("Ошибка воркера напоминаний: %s", e)


# ---------------------------
# Инициализация приложения
# ---------------------------

def build_application() -> Application:
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    # /add conversation
    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_entry)],
        states={
            ADD_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_text)],
            ADD_DEADLINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_deadline)],
            ADD_PRIORITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_got_priority)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
        name="add_task_conv",
        persistent=False,
    )

    # /edit conversation
    edit_conv = ConversationHandler(
        entry_points=[CommandHandler("edit", edit_entry)],
        states={
            EDIT_CHOOSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_choose)],
            EDIT_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_text)],
            EDIT_DEADLINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_deadline)],
            EDIT_PRIORITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_priority)],
        },
        fallbacks=[CommandHandler("cancel", edit_cancel)],
        name="edit_task_conv",
        persistent=False,
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(add_conv)
    application.add_handler(edit_conv)
    application.add_handler(CommandHandler("done", done_cmd))
    application.add_handler(CommandHandler("delete", delete_cmd))
    application.add_handler(CommandHandler("list", list_cmd))
    application.add_handler(CallbackQueryHandler(delete_confirm_cb))

    # Воркер напоминаний
    application.job_queue.run_repeating(lambda c: reminders_worker(c), interval=30, first=10)

    return application


app: Application = build_application()


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN в окружении")
    logger.info("Бот запускается…")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
