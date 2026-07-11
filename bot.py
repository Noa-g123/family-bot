import os
import json
import asyncio
import logging
import random
from datetime import datetime, date, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN", "")
IL_TZ = pytz.timezone("Asia/Jerusalem")

# ======= שעות מפתח =======
EVENING_SEND_HOUR   = 18   # 18:30 — שליחת משימות מחר לבחירה
EVENING_SEND_MIN    = 30
MORNING_TASKS_HOUR  = 7    # 07:00 — שליחת משימות היום עם כפתורי ביצוע
MORNING_TASKS_MIN   = 0

# אחרי כמה דקות מהתזכורת שואלים "בוצע?"
REMINDER_FOLLOWUP_MIN = 60   # שעה אחרי תזכורת
ESCALATE_HOURS        = 2    # אחרי 2 שעות ללא ביצוע → התראה לרונן + נועה

PARENTS = ["רונן", "נועה"]   # מי מקבל התראה על משימה שלא בוצעה

# ======= משפחה =======
FAMILY_NAMES = ["רונן", "נועה", "יובל", "יהלי"]

DATA_FILE = "data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"chat_ids": {}, "tasks": {}, "group_chat_id": None, "pending_checks": []}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ======= משימות קבועות =======
FIXED_TASKS = {
    "sun_tue_thu": {          # ראשון=6 שלישי=1 חמישי=3
        "הוצאת דיימונד צהריים": "יהלי",
        "הוצאת דיימונד ערב":    "יובל",
    },
    "mon_wed_fri": {          # שני=0 רביעי=2 שישי=4
        "הוצאת דיימונד צהריים": "יובל",
        "הוצאת דיימונד ערב":    "יהלי",
    },
    "monday":  {"קניות אונליין":     "נועה"},
    "friday":  {"קניית בשר בבוקר":  "רונן"},
}

DAILY_TASKS_BASE = [
    "הוצאת דיימונד בוקר",
    "הכנת כריכים לבי״ס",
    "קניית לחמניות",
    "הכנת ארוחת צהריים מראש והפשרת בשר",
    "הורדת בגדים מהחבל והפרדה לחדרים",
    "כיבוס מכונת בגדים (ראשונה)",
    "תליית מכונת בגדים (ראשונה)",
    "כיבוס מכונת בגדים (שנייה)",
    "תליית מכונת בגדים (שנייה)",
    "הוצאת מדיח + הכנסת כלים בוקר + הפעלה אם מלא",
    "הוצאת כלים ממדיח צהריים",
    "הכנסת כלים למדיח אחה״צ + הפעלה אם מלא",
    "הוצאת כלים ממדיח ערב",
    "הכנסת כלים למדיח 22:00",
    "סידור החלל מציוד (בוקר)",
    "סידור החלל מציוד (ערב)",
]

FRIDAY_EXTRA = [
    "שאיבת אבק מזנון",
    "שאיבת שטיח וספה",
    "שטיפת רצפה",
    "סידור ממד",
    "סידור חדר אישי ושטיפה",
]

PERSONAL_DAILY = "קיפול כביסה אישית בחדר"

CELEBRATE_MSGS = [
    "כל הכבוד, ענק!", "מדהים לגמרי!", "אתה/את שוווה!",
    "אלוף/ה אמיתי/ת!", "עבודה מעולה!", "פנטסטי בטירוף!",
    "ברווו ברווו!", "נהדר, תותח/ית!", "מספר אחת!",
    "המשפחה גאה בך!", "בום! בוצע!", "יאללה כוכב!",
]

# דמויות ריקוד לכל בן משפחה — אנימציית ASCII + אמוג'י
FAMILY_DANCERS = {
    "רונן": {
        "name": "פומבה",
        "frames": [
            "  🐗\n /|🍑|\\ \n  | |\n  \" \"",
            "  🐗\n \\|🍑|/ \n  | |\n  \" \"",
            "  🐗\n /|🍑|\\ \n /  \\\n",
            "  🐗\n \\|🍑|/ \n  /\\\n",
        ],
        "emoji": "🐗",
        "color": "🟠",
    },
    "נועה": {
        "name": "סמור",
        "frames": [
            "  🦡\n /|🍑|\\ \n  | |\n  \" \"",
            "  🦡\n \\|🍑|/ \n  | |\n  \" \"",
            "  🦡\n /|🍑|\\ \n /  \\\n",
            "  🦡\n \\|🍑|/ \n  /\\\n",
        ],
        "emoji": "🦡",
        "color": "⚪",
    },
    "יובל": {
        "name": "קפיברה",
        "frames": [
            "  🐾\n /|🍑|\\ \n  | |\n  \" \"",
            "  🐾\n \\|🍑|/ \n  | |\n  \" \"",
            "  🐾\n /|🍑|\\ \n /  \\\n",
            "  🐾\n \\|🍑|/ \n  /\\\n",
        ],
        "emoji": "🦫",
        "color": "🟤",
    },
    "יהלי": {
        "name": "דב רקדן",
        "frames": [
            "  🐻\n /|🍑|\\ \n  | |\n  \" \"",
            "  🐻\n \\|🍑|/ \n  | |\n  \" \"",
            "  🐻\n /|🍑|\\ \n /  \\\n",
            "  🐻\n \\|🍑|/ \n  /\\\n",
        ],
        "emoji": "🐻",
        "color": "🟫",
    },
}

DANCE_LINES = [
    "💃 זזזזזזז! תקדוד/י!",
    "🕺 מטורף! הכי טוב/ה!",
    "🎵 הגוף לא משקר!",
    "🍑 שייקי שייקי!",
    "🎶 ריקוד הניצחון!",
]

def get_celebration(name: str = None) -> str:
    msg  = random.choice(CELEBRATE_MSGS)
    dance = random.choice(DANCE_LINES)
    if name and name in FAMILY_DANCERS:
        d = FAMILY_DANCERS[name]
        emoji = d["emoji"]
        char  = d["name"]
        return (
            f"{emoji}{emoji}{emoji}\n"
            f"*{char} רוקד/ת לכבודך!*\n\n"
            f"{emoji} 🍑💨  ← שייק שייק!\n\n"
            f"🎉 {msg}\n"
            f"{dance}"
        )
    return f"🎉 {msg}\n{dance}"

# ======= בניית משימות ליום =======

def get_day_tasks(target_date: date):
    weekday = target_date.weekday()  # 0=שני … 6=ראשון
    is_friday = (weekday == 4)

    fixed_today = {}
    if weekday in [6, 1, 3]:
        fixed_today.update(FIXED_TASKS["sun_tue_thu"])
    elif weekday in [0, 2, 4]:
        fixed_today.update(FIXED_TASKS["mon_wed_fri"])
    if weekday == 0:
        fixed_today.update(FIXED_TASKS["monday"])
    if is_friday:
        fixed_today.update(FIXED_TASKS["friday"])

    base = list(DAILY_TASKS_BASE)
    if is_friday:
        base += FRIDAY_EXTRA

    tasks = []
    for task_name in base:
        tasks.append({
            "name":        task_name,
            "assigned":    fixed_today.get(task_name),   # None = צריך בחירה
            "done":        False,
            "done_by":     None,
            "done_time":   None,
            "reminder_sent": False,   # האם נשלחה תזכורת ביצוע
            "followup_sent": False,   # האם נשלח followup
        })

    # משימות קבועות שאינן בבסיס (קניות/בשר וכו')
    for task_name, person in fixed_today.items():
        if not any(t["name"] == task_name for t in tasks):
            tasks.append({
                "name": task_name, "assigned": person,
                "done": False, "done_by": None, "done_time": None,
                "reminder_sent": False, "followup_sent": False,
            })

    return tasks

def get_date_key(d: date = None):
    if d is None:
        d = datetime.now(IL_TZ).date()
    return d.strftime("%Y-%m-%d")

def find_name_by_chat(data, chat_id):
    for name, cid in data.get("chat_ids", {}).items():
        if cid == chat_id:
            return name
    return None

# ======= כפתורי ביצוע למשימה =======

def build_complete_keyboard(key, my_tasks, name):
    keyboard = []
    for t in my_tasks:
        if not t["done"]:
            safe = t["name"][:28].replace("_","‑")  # em-dash to avoid split issues
            keyboard.append([InlineKeyboardButton(
                f"✅ בוצע: {t['name'][:28]}",
                callback_data=f"cmp|{key}|{name}|{t['name'][:28]}"
            )])
    return keyboard

# ======= /start =======

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    chat_id   = update.effective_chat.id
    chat_type = update.effective_chat.type

    if chat_type in ["group", "supergroup"]:
        data["group_chat_id"] = chat_id
        save_data(data)
        await update.message.reply_text(
            "✅ *הקבוצה המשפחתית נרשמה!*\n\n"
            "עכשיו כל אחד מהמשפחה שולח /start לבוט בפרטי ובוחר את שמו.",
            parse_mode="Markdown"
        )
        return

    keyboard = [[InlineKeyboardButton(n, callback_data=f"reg|{n}")] for n in FAMILY_NAMES]
    await update.message.reply_text("שלום! 👋 מי את/ה?",
                                     reply_markup=InlineKeyboardMarkup(keyboard))

async def register_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, name = query.data.split("|", 1)
    data = load_data()
    data.setdefault("chat_ids", {})[name] = query.message.chat_id
    save_data(data)
    await query.edit_message_text(
        f"✅ *שלום {name}! נרשמת בהצלחה* 🏠\n\n"
        f"כל ערב ב-18:30 תקבל/י הודעה לבחירת משימות מחר.\n"
        f"כל בוקר ב-06:30 — סיכום המשימות שלך להיום עם כפתורי ביצוע.\n\n"
        f"פקודות: /today  |  /status",
        parse_mode="Markdown"
    )

# ======= /today =======

async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data  = load_data()
    key   = get_date_key()
    tasks = data.get("tasks", {}).get(key)
    if not tasks:
        await update.message.reply_text("אין עדיין משימות להיום. הן יופיעו הערב 🌙")
        return

    name = find_name_by_chat(data, update.effective_chat.id)
    if name:
        my_tasks = [t for t in tasks if t.get("assigned") == name]
        text = f"📋 *המשימות שלך היום, {name}:*\n\n"
        for t in my_tasks:
            text += ("✅ " if t["done"] else "⬜ ") + t["name"] + "\n"
        text += f"\n🧹 *כל יום:* {PERSONAL_DAILY}"
        keyboard = build_complete_keyboard(key, my_tasks, name)
        await update.message.reply_text(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)
    else:
        text = "📋 *כל משימות היום:*\n\n"
        for t in tasks:
            text += ("✅ " if t["done"] else "⬜ ") + t["name"] + \
                    f" — _{t.get('assigned') or 'לא שובץ'}_\n"
        await update.message.reply_text(text, parse_mode="Markdown")

# ======= /status =======

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data  = load_data()
    key   = get_date_key()
    today = datetime.now(IL_TZ).date()
    tasks = data.get("tasks", {}).get(key)
    if not tasks:
        await update.message.reply_text("אין עדיין משימות להיום.")
        return

    done    = [t for t in tasks if t["done"]]
    pending = [t for t in tasks if not t["done"]]
    text = f"📊 *סטטוס — {today.strftime('%d/%m/%Y')}*\n\n"
    text += f"✅ בוצע: {len(done)}/{len(tasks)}\n\n"
    for nm in FAMILY_NAMES:
        my_all  = [t for t in tasks if t.get("assigned") == nm]
        my_done = [t for t in my_all  if t["done"]]
        text += f"👤 *{nm}*: {len(my_done)}/{len(my_all)}\n"
    if pending:
        text += "\n⏳ *עוד לא בוצע:*\n"
        for t in pending[:10]:
            text += f"• {t['name']} ({t.get('assigned') or 'פתוח'})\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# ======= שליחת משימות ערב (18:30) — בחירה =======

async def send_evening_tasks(app):
    """18:30: שולח משימות מחר לבחירה"""
    data     = load_data()
    tomorrow = datetime.now(IL_TZ).date() + timedelta(days=1)
    key      = get_date_key(tomorrow)

    tasks = get_day_tasks(tomorrow)
    data.setdefault("tasks", {})[key] = tasks
    save_data(data)

    day_names = ["שני","שלישי","רביעי","חמישי","שישי","שבת","ראשון"]
    day_name  = day_names[tomorrow.weekday()]

    group_id = data.get("group_chat_id")
    if group_id:
        fixed = [t for t in tasks if t.get("assigned")]
        flex  = [t for t in tasks if not t.get("assigned")]
        text  = f"🏠 *משימות בית — {day_name} {tomorrow.strftime('%d/%m')}*\n\n"
        if fixed:
            text += "📌 *קבועות:*\n"
            for t in fixed:
                text += f"• {t['name']} → {t['assigned']}\n"
        if flex:
            text += f"\n✏️ *{len(flex)} משימות פתוחות* — כל אחד בוחר בפרטי!\n"
        text += f"\n🧹 כל אחד: {PERSONAL_DAILY}"
        await app.bot.send_message(group_id, text, parse_mode="Markdown")

    chat_ids  = data.get("chat_ids", {})
    flex_tasks = [t for t in tasks if not t.get("assigned")]

    for name, cid in chat_ids.items():
        if not cid:
            continue
        my_fixed = [t for t in tasks if t.get("assigned") == name]
        text = f"👋 *שלום {name}!*\n\n"
        text += f"📅 *משימות מחר — {day_name} {tomorrow.strftime('%d/%m')}*\n\n"
        if my_fixed:
            text += "📌 *הקבועות שלך:*\n"
            for t in my_fixed:
                text += f"• {t['name']}\n"

        if flex_tasks:
            text += f"\n✏️ *בחר/י מהמשימות הפתוחות:*\n_(לחץ/י על משימה כדי לקחת אותה)_\n"
            keyboard = []
            for i, t in enumerate(flex_tasks):
                keyboard.append([InlineKeyboardButton(
                    f"⬜ {t['name']}",
                    callback_data=f"take|{key}|{i}|{name}"
                )])
            keyboard.append([InlineKeyboardButton(
                "✅ סיימתי לבחור",
                callback_data=f"done_choosing|{key}|{name}"
            )])
            await app.bot.send_message(cid, text, parse_mode="Markdown",
                                        reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await app.bot.send_message(cid, text, parse_mode="Markdown")

# ======= שליחת משימות בוקר (06:30) — ביצוע =======

async def send_morning_tasks(app):
    """06:30: שולח לכל אחד את המשימות שלו היום עם כפתורי סימון ביצוע"""
    data     = load_data()
    today    = datetime.now(IL_TZ).date()
    key      = get_date_key(today)
    tasks    = data.get("tasks", {}).get(key)
    if not tasks:
        # יום ראשון ולא נבחרו משימות — בנה אוטומטי
        tasks = get_day_tasks(today)
        data.setdefault("tasks", {})[key] = tasks
        save_data(data)

    day_names = ["שני","שלישי","רביעי","חמישי","שישי","שבת","ראשון"]
    day_name  = day_names[today.weekday()]
    chat_ids  = data.get("chat_ids", {})

    for name, cid in chat_ids.items():
        if not cid:
            continue
        my_tasks = [t for t in tasks if t.get("assigned") == name]
        if not my_tasks:
            continue

        text = f"☀️ *בוקר טוב {name}!*\n"
        text += f"📋 *המשימות שלך היום — {day_name} {today.strftime('%d/%m')}:*\n\n"
        for t in my_tasks:
            text += f"⬜ {t['name']}\n"
        text += f"\n🧹 *ואל תשכח/י:* {PERSONAL_DAILY}\n\n"
        text += "_סמן/י ביצוע עם הכפתורים למטה:_"

        keyboard = build_complete_keyboard(key, my_tasks, name)
        await app.bot.send_message(cid, text, parse_mode="Markdown",
                                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)

    # תזמן בדיקות followup לשעה מאוחר יותר
    await schedule_followup_checks(app, key, tasks, data)

# ======= לוגיקת תזכורות חכמות =======

async def schedule_followup_checks(app, key, tasks, data):
    """קובע בדיקות לאחר שעה ולאחר שעתיים לכל משימה לא מבוצעת"""
    now = datetime.now(IL_TZ)
    checks = data.setdefault("pending_checks", [])

    for t in tasks:
        if not t.get("assigned") or t["done"]:
            continue
        task_name = t["name"]
        # בדיקה ראשונה אחרי שעה
        check_time_1 = (now + timedelta(hours=1)).isoformat()
        # בדיקה שנייה + אסקלציה אחרי שעתיים
        check_time_2 = (now + timedelta(hours=ESCALATE_HOURS)).isoformat()

        checks.append({"key": key, "task": task_name, "check_at": check_time_1, "type": "followup"})
        checks.append({"key": key, "task": task_name, "check_at": check_time_2, "type": "escalate"})

    save_data(data)

async def run_pending_checks(app):
    """רץ כל 15 דקות — בודק followups ואסקלציות"""
    data = load_data()
    now  = datetime.now(IL_TZ)
    checks = data.get("pending_checks", [])
    remaining = []

    for check in checks:
        check_at = datetime.fromisoformat(check["check_at"])
        if check_at.tzinfo is None:
            check_at = IL_TZ.localize(check_at)

        if now < check_at:
            remaining.append(check)
            continue

        key   = check["key"]
        tname = check["task"]
        ctype = check["type"]
        tasks = data.get("tasks", {}).get(key, [])
        task  = next((t for t in tasks if t["name"] == tname), None)

        if not task or task["done"]:
            continue  # כבר בוצע, דלג

        assigned = task.get("assigned")
        cid = data.get("chat_ids", {}).get(assigned)

        if ctype == "followup" and cid and not task.get("followup_sent"):
            # שאל "האם בוצע?"
            text = (
                f"⏰ *{assigned}*, האם כבר ביצעת:\n"
                f"*{tname}*?\n\n"
                f"לחץ/י לאישור ביצוע 👇"
            )
            keyboard = [[
                InlineKeyboardButton("✅ כן, בוצע!", callback_data=f"cmp|{key}|{assigned}|{tname[:28]}"),
                InlineKeyboardButton("🔜 עוד לא", callback_data=f"snooze|{key}|{assigned}|{tname[:28]}"),
            ]]
            try:
                await app.bot.send_message(cid, text, parse_mode="Markdown",
                                            reply_markup=InlineKeyboardMarkup(keyboard))
                task["followup_sent"] = True
                save_data(data)
            except Exception as e:
                logger.error(f"followup send error: {e}")

        elif ctype == "escalate":
            # עדיין לא בוצע — התראה לרונן + נועה
            group_id   = data.get("group_chat_id")
            chat_ids   = data.get("chat_ids", {})
            alert_text = (
                f"🚨 *התראה: משימה לא בוצעה!*\n\n"
                f"👤 *{assigned}* לא סימן/ה ביצוע:\n"
                f"📌 *{tname}*\n\n"
                f"רונן ונועה — בבקשה בדקו מה קורה 🙏"
            )
            # שלח לקבוצה
            if group_id:
                try:
                    await app.bot.send_message(group_id, alert_text, parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"group alert error: {e}")
            # שלח גם בפרטי לרונן ונועה
            for parent in PARENTS:
                pcid = chat_ids.get(parent)
                if pcid:
                    try:
                        await app.bot.send_message(pcid, alert_text, parse_mode="Markdown")
                    except Exception as e:
                        logger.error(f"parent alert error: {e}")

    data["pending_checks"] = remaining
    save_data(data)

# ======= אנימציית ריקוד =======

DANCE_FRAMES = {
    "רונן": [   # פומבה
        "```\n    🐗\n   (🍑)\n  / | \\\n    |\n   / \\\n```",
        "```\n      🐗\n     (🍑)\n   \\  |  /\n      |\n    \\   /\n```",
        "```\n  🎵 🐗\n   \\(🍑)/\n    /|\\\n    | |\n   _| |_\n```",
        "```\n  🐗 🎶\n  (🍑)\\\n   /|\n  / |\n /  |\n```",
    ],
    "נועה": [   # סמור
        "```\n    🦡\n   (🍑)\n  / | \\\n    |\n   / \\\n```",
        "```\n      🦡\n     (🍑)\n   \\  |  /\n      |\n    \\   /\n```",
        "```\n  🎵 🦡\n   \\(🍑)/\n    /|\\\n    | |\n   _| |_\n```",
        "```\n  🦡 🎶\n  (🍑)\\\n   /|\n  / |\n /  |\n```",
    ],
    "יובל": [   # קפיברה
        "```\n    🦫\n   (🍑)\n  / | \\\n    |\n   / \\\n```",
        "```\n      🦫\n     (🍑)\n   \\  |  /\n      |\n    \\   /\n```",
        "```\n  🎵 🦫\n   \\(🍑)/\n    /|\\\n    | |\n   _| |_\n```",
        "```\n  🦫 🎶\n  (🍑)\\\n   /|\n  / |\n /  |\n```",
    ],
    "יהלי": [   # דב רקדן
        "```\n    🐻\n   (🍑)\n  / | \\\n    |\n   / \\\n```",
        "```\n      🐻\n     (🍑)\n   \\  |  /\n      |\n    \\   /\n```",
        "```\n  🎵 🐻\n   \\(🍑)/\n    /|\\\n    | |\n   _| |_\n```",
        "```\n  🐻 🎶\n  (🍑)\\\n   /|\n  / |\n /  |\n```",
    ],
}

DANCE_CAPTIONS = {
    "רונן":  ["פומבה מרים את התחת! 🐗💨", "פומבה בריקוד הניצחון! 🎺", "שלב שלב! אחד שניים! 🐗🕺"],
    "נועה":  ["סמור מטלטל! 🦡💃",          "סמור הכי מגניב! 🎵",        "שייק שייק סמורית! 🦡✨"],
    "יובל":  ["קפיברה רוקד! 🦫🕺",          "הקפיברה לא עוצר! 🎶",       "תחת קפיברה בתנועה! 🦫💥"],
    "יהלי":  ["הדב רקדן יצא לרקוד! 🐻💃",  "הדב לא מפסיק לנענע! 🎵",   "ריקוד הדב האגדי! 🐻🏆"],
}

def build_dance_animation(name: str, task_name: str) -> str:
    frames = DANCE_FRAMES.get(name, [])
    captions = DANCE_CAPTIONS.get(name, ["כל הכבוד!"])
    d = FAMILY_DANCERS.get(name, {})
    char_name = d.get("name", name)
    emoji = d.get("emoji", "🎉")

    frame = random.choice(frames) if frames else emoji
    caption = random.choice(captions)

    lines = [
        f"✅ *{name} ביצע/ה:*",
        f"_{task_name}_\n",
        frame,
        f"\n*{caption}*",
        f"〰️〰️〰️〰️〰️",
        f"{emoji} _{char_name} שמח/ה בשבילך!_ {emoji}",
    ]
    return "\n".join(lines)


# ======= callback handler =======

async def task_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cb   = query.data
    data = load_data()

    # --- רישום ---
    if cb.startswith("reg|"):
        _, name = cb.split("|", 1)
        data.setdefault("chat_ids", {})[name] = query.message.chat_id
        save_data(data)
        await query.edit_message_text(
            f"✅ *שלום {name}! נרשמת בהצלחה* 🏠\n\n"
            f"כל ערב ב-18:30 — בחירת משימות מחר.\n"
            f"כל בוקר ב-06:30 — משימות היום עם כפתורי ביצוע.\n\n"
            f"פקודות: /today  |  /status",
            parse_mode="Markdown"
        )
        return

    # --- בחירת משימה ערב ---
    if cb.startswith("take|"):
        _, key, idx_str, name = cb.split("|", 3)
        idx        = int(idx_str)
        tasks      = data.get("tasks", {}).get(key, [])
        flex_tasks = [t for t in tasks if not t.get("assigned")]

        if idx < len(flex_tasks):
            chosen = flex_tasks[idx]
            for t in tasks:
                if t["name"] == chosen["name"] and not t.get("assigned"):
                    t["assigned"] = name
                    break
            save_data(data)

        flex_now  = [t for t in tasks if not t.get("assigned")]
        my_taken  = [t for t in tasks if t.get("assigned") == name]
        taken_txt = "\n".join(f"• {t['name']}" for t in my_taken)
        text = f"✅ *לקחת: {chosen['name']}*\n\n*המשימות שלך עד כה:*\n{taken_txt}\n\n"

        keyboard = []
        if flex_now:
            text += "✏️ *משימות פתוחות נוספות:*"
            for i, t in enumerate(flex_now):
                keyboard.append([InlineKeyboardButton(
                    f"⬜ {t['name']}",
                    callback_data=f"take|{key}|{i}|{name}"
                )])
        keyboard.append([InlineKeyboardButton("✅ סיימתי לבחור",
                                               callback_data=f"done_choosing|{key}|{name}")])
        await query.edit_message_text(text, parse_mode="Markdown",
                                       reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # --- סיום בחירה ---
    if cb.startswith("done_choosing|"):
        _, key, name = cb.split("|", 2)
        tasks    = data.get("tasks", {}).get(key, [])
        my_tasks = [t for t in tasks if t.get("assigned") == name]
        text = f"🎯 *המשימות שלך, {name}:*\n\n"
        for t in my_tasks:
            text += ("✅ " if t["done"] else "⬜ ") + t["name"] + "\n"
        text += f"\n🧹 *ואל תשכח/י:* {PERSONAL_DAILY}\n\n"
        text += "_מחר ב-06:30 תקבל/י תזכורת עם כפתורי ביצוע_ ☀️"
        keyboard = build_complete_keyboard(key, my_tasks, name)
        await query.edit_message_text(text, parse_mode="Markdown",
                                       reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)
        return

    # --- סימון ביצוע ---
    if cb.startswith("cmp|"):
        _, key, name, task_partial = cb.split("|", 3)
        tasks = data.get("tasks", {}).get(key, [])
        completed_name = None
        for t in tasks:
            if (t["name"][:28] == task_partial or task_partial in t["name"]) \
               and t.get("assigned") == name and not t["done"]:
                t["done"]      = True
                t["done_by"]   = name
                t["done_time"] = datetime.now(IL_TZ).isoformat()
                completed_name = t["name"]
                break
        save_data(data)

        celebration = get_celebration(name)
        await query.answer("🎉 " + random.choice(CELEBRATE_MSGS), show_alert=True)

        my_tasks  = [t for t in tasks if t.get("assigned") == name]
        done_cnt  = sum(1 for t in my_tasks if t["done"])
        text = f"🎯 *המשימות שלך, {name}:*\n\n"
        for t in my_tasks:
            text += ("✅ " if t["done"] else "⬜ ") + t["name"] + "\n"
        text += f"\n\n{celebration}\n\n*{done_cnt}/{len(my_tasks)} בוצעו!*"
        if done_cnt == len(my_tasks):
            d = FAMILY_DANCERS.get(name, {})
            emoji = d.get("emoji", "🏆")
            text += f"\n\n{emoji}🏆{emoji}\n*סיימת הכל! אלוף/ה אמיתי/ת!*\n{emoji}🏆{emoji}"

        keyboard = build_complete_keyboard(key, my_tasks, name)
        await query.edit_message_text(text, parse_mode="Markdown",
                                       reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)

        # שלח הודעת ריקוד נפרדת וחגיגית!
        dance_text = build_dance_animation(name, completed_name or task_partial)
        await query.message.reply_text(dance_text, parse_mode="Markdown")
        return

    # --- דחיית followup (עוד לא) ---
    if cb.startswith("snooze|"):
        _, key, name, task_partial = cb.split("|", 3)
        await query.edit_message_text(
            f"⏳ אוקי {name}, אזכיר לך שוב בעוד שעה!\n*{task_partial}*",
            parse_mode="Markdown"
        )
        # הוסף בדיקה נוספת בעוד שעה
        data = load_data()
        new_check_time = (datetime.now(IL_TZ) + timedelta(hours=1)).isoformat()
        data.setdefault("pending_checks", []).append({
            "key": key, "task": task_partial,
            "check_at": new_check_time, "type": "followup"
        })
        save_data(data)
        return

# ======= main =======

# ======= פקודת בדיקה =======

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/test — מריץ את כל הזרימות ידנית לבדיקה"""
    args = context.args  # /test evening | morning | check | dance
    cmd  = args[0].lower() if args else "all"

    await update.message.reply_text(f"🧪 מריץ בדיקה: *{cmd}*...", parse_mode="Markdown")

    app = context.application

    if cmd in ("evening", "all"):
        await update.message.reply_text("📤 שולח משימות ערב (בחירה למחר)...")
        await send_evening_tasks(app)
        await update.message.reply_text("✅ הודעות ערב נשלחו!")

    if cmd in ("morning", "all"):
        await update.message.reply_text("☀️ שולח משימות בוקר (היום)...")
        await send_morning_tasks(app)
        await update.message.reply_text("✅ הודעות בוקר נשלחו!")

    if cmd in ("check", "all"):
        await update.message.reply_text("🔍 מריץ בדיקת followup/אסקלציה...")
        await run_pending_checks(app)
        await update.message.reply_text("✅ בדיקת checks הסתיימה!")

    if cmd == "dance":
        # בדיקת אנימציות ריקוד לכל בני המשפחה
        await update.message.reply_text("💃 בדיקת ריקודים לכל המשפחה:")
        for name in FAMILY_NAMES:
            dance = build_dance_animation(name, "משימת בדיקה")
            await update.message.reply_text(dance, parse_mode="Markdown")

    if cmd == "all":
        await update.message.reply_text(
            "✅ *כל הבדיקות הסתיימו!*\n\n"
            "בדוק:\n"
            "• הגיעו הודעות לכולם בפרטי?\n"
            "• הגיעה הודעה לקבוצה?\n"
            "• כפתורי הבחירה והביצוע עובדים?\n\n"
            "פקודות בדיקה נוספות:\n"
            "`/test evening` — רק הודעות ערב\n"
            "`/test morning` — רק הודעות בוקר\n"
            "`/test check`   — רק בדיקת followups\n"
            "`/test dance`   — רק ריקודי הדמויות",
            parse_mode="Markdown"
        )


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("today",  today_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("test",   test_command))
    app.add_handler(CallbackQueryHandler(register_callback, pattern=r"^reg\|"))
    app.add_handler(CallbackQueryHandler(task_callback,
        pattern=r"^(take\||done_choosing\||cmp\||snooze\|)"))

    scheduler = AsyncIOScheduler(timezone=IL_TZ)

    # 18:30 — בחירת משימות מחר
    scheduler.add_job(
        lambda: asyncio.create_task(send_evening_tasks(app)),
        "cron", hour=EVENING_SEND_HOUR, minute=EVENING_SEND_MIN
    )
    # 06:30 — שליחת משימות היום + כפתורי ביצוע
    scheduler.add_job(
        lambda: asyncio.create_task(send_morning_tasks(app)),
        "cron", hour=MORNING_TASKS_HOUR, minute=MORNING_TASKS_MIN
    )
    # כל 15 דקות — בדיקת followups ואסקלציות
    scheduler.add_job(
        lambda: asyncio.create_task(run_pending_checks(app)),
        "interval", minutes=15
    )

    async def on_startup(app):
        scheduler.start()
        logger.info("🤖 הבוט המשפחתי רץ!")

    app.post_init = on_startup
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
