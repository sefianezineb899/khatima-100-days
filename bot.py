import os
import sqlite3
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

TOKEN = os.environ["BOT_TOKEN"]
DB_PATH = os.getenv("DB_PATH", "khatima.db")
TZ = ZoneInfo("Africa/Algiers")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# مراحل اليوم:
# review_start -> review_audio -> review_selfcheck
# recite_start -> recite_audio -> recite_selfcheck -> day_complete

def now():
    return datetime.now(TZ)

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS students (
                user_id INTEGER PRIMARY KEY,
                day INTEGER NOT NULL DEFAULT 1,
                stage TEXT NOT NULL DEFAULT 'review_start',
                deadline TEXT,
                reminder_sent TEXT NOT NULL DEFAULT '',
                review_file_id TEXT,
                recite_file_id TEXT,
                updated_at TEXT
            )
        """)

def get_student(user_id):
    with db() as con:
        row = con.execute("SELECT * FROM students WHERE user_id=?", (user_id,)).fetchone()
        if row is None:
            con.execute(
                "INSERT INTO students(user_id, day, stage, updated_at) VALUES(?,1,'review_start',?)",
                (user_id, now().isoformat())
            )
            row = con.execute("SELECT * FROM students WHERE user_id=?", (user_id,)).fetchone()
        return dict(row)

def update_student(user_id, **fields):
    if not fields:
        return
    fields["updated_at"] = now().isoformat()
    columns = ", ".join(f"{key}=?" for key in fields)
    values = list(fields.values()) + [user_id]
    with db() as con:
        con.execute(f"UPDATE students SET {columns} WHERE user_id=?", values)

def keyboard(*rows):
    return ReplyKeyboardMarkup(
        [[KeyboardButton(text) for text in row] for row in rows],
        resize_keyboard=True
    )

def page_range(start, count):
    end = start + count - 1
    return f"الصفحات {start}–{end}"

def daily_text(day):
    new_start = (day - 1) * 6 + 1
    total = day * 6
    return (
        f"🌿 اليوم {day} من 100\n\n"
        f"📖 مراجعة اليوم: 6 صفحات جديدة ({page_range(new_start, 6)}).\n"
        f"📚 السرد المتراكم: {total} صفحة من بداية المصحف "
        f"({page_range(1, total)}).\n\n"
        "ابدئي بالمراجعة، ثم اضغطي «أنهيت المراجعة»."
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    s = get_student(user_id)
    await update.message.reply_text(
        "أهلاً بكِ في رفيق الخاتمة 🌸\n"
        "تحدّي سرد القرآن في 100 يوم.\n\n"
        "كل يوم: 6 صفحات مراجعة جديدة، ثم سرد متراكم يبدأ من أول المصحف.\n"
        "لديكِ 24 ساعة لإكمال مرحلتي اليوم. إذا انتهت المهلة دون إكمالهما تعودين إلى اليوم الأول.\n\n"
        + daily_text(s["day"]),
        reply_markup=keyboard(["📖 واجب اليوم", "📊 تقدمي"])
    )
    if not s["deadline"]:
        set_new_deadline(user_id)

async def show_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = get_student(update.effective_user.id)
    stage = s["stage"]
    if stage == "review_start":
        await update.message.reply_text(
            daily_text(s["day"]),
            reply_markup=keyboard(["أنهيت المراجعة", "📊 تقدمي"])
        )
    elif stage in ("review_audio", "review_selfcheck"):
        await update.message.reply_text(
            "أكملي مراجعة الصفحات الست، ثم أرسلي تسجيلك الصوتي هنا. "
            "سأعيد إرسال التسجيل إليك لتستمعي إليه وتراجعيه بنفسك."
        )
    elif stage == "recite_start":
        await update.message.reply_text(
            f"📚 الآن السرد المتراكم لليوم {s['day']}:\n"
            f"{page_range(1, s['day'] * 6)} — المجموع {s['day'] * 6} صفحة.\n\n"
            "عندما تنتهين من السرد اضغطي «أنهيت السرد».",
            reply_markup=keyboard(["أبدأ السرد", "📊 تقدمي"])
        )
    elif stage in ("recite_audio", "recite_selfcheck"):
        await update.message.reply_text(
            "أرسلي تسجيل السرد المتراكم، وسأعيده إليك لتستمعي إليه وتراجعيه بنفسك."
        )
    else:
        await update.message.reply_text(
            "🌟 أتممتِ اليوم بنجاح! أحسنتِ.\n" + daily_text(min(s["day"], 100)),
            reply_markup=keyboard(["📖 واجب اليوم", "📊 تقدمي"])
        )

def set_new_deadline(user_id):
    update_student(
        user_id,
        deadline=(now() + timedelta(hours=24)).isoformat(),
        reminder_sent=""
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text or ""
    s = get_student(user_id)

    if text == "📊 تقدمي":
        remaining = max(0, 100 - s["day"])
        await update.message.reply_text(
            f"🌸 أنتِ في اليوم {s['day']} من 100.\n"
            f"المتبقي بعد هذا اليوم: {remaining} يوماً.\n"
            f"مرحلتك الحالية: {stage_ar(s['stage'])}"
        )
        return

    if text == "📖 واجب اليوم":
        await show_task(update, context)
        return

    if text == "أنهيت المراجعة" and s["stage"] == "review_start":
        update_student(user_id, stage="review_audio")
        await update.message.reply_text(
            f"بارك الله فيكِ! 🌷 أرسلي الآن تسجيل مراجعة الصفحات الست "
            f"({page_range((s['day']-1)*6+1, 6)})."
        )
        return

    if text == "تم التصحيح" and s["stage"] == "review_selfcheck":
        update_student(user_id, stage="recite_start")
        await update.message.reply_text(
            f"أحسنتِ! انتهت مراجعة اليوم. 🌸\n\n"
            f"حان وقت السرد المتراكم: {s['day']*6} صفحة "
            f"({page_range(1, s['day']*6)}).",
            reply_markup=keyboard(["أبدأ السرد", "📊 تقدمي"])
        )
        return

    if text == "أبدأ السرد" and s["stage"] == "recite_start":
        update_student(user_id, stage="recite_audio")
        await update.message.reply_text(
            f"رائع! أرسلي الآن تسجيل السرد المتراكم لعدد {s['day']*6} صفحة. "
            "سأعيده إليك لتستمعي إليه وتراجعيه بنفسك."
        )
        return

    if text == "تم التصحيح" and s["stage"] == "recite_selfcheck":
        if s["day"] >= 100:
            update_student(user_id, stage="day_complete", deadline=None)
            await update.message.reply_text(
                "🏆 ما شاء الله! أتممتِ تحدّي المئة يوم وسرد القرآن الكريم كاملاً.\n"
                "نسأل الله أن يجعله راسخاً في صدركِ."
            )
            return
        next_day = s["day"] + 1
        update_student(
            user_id, day=next_day, stage="review_start",
            review_file_id=None, recite_file_id=None
        )
        set_new_deadline(user_id)
        await update.message.reply_text(
            f"🌟 تقبّل الله منكِ! أتممتِ اليوم {next_day-1}.\n"
            "بدأت مهلة الـ24 ساعة الجديدة.\n\n" + daily_text(next_day),
            reply_markup=keyboard(["أنهيت المراجعة", "📖 واجب اليوم", "📊 تقدمي"])
        )
        return

    await update.message.reply_text(
        "اختاري أحد الأزرار الظاهرة أسفل المحادثة لإكمال واجبك."
    )

def stage_ar(stage):
    names = {
        "review_start": "المراجعة اليومية",
        "review_audio": "إرسال تسجيل المراجعة",
        "review_selfcheck": "الاستماع والتصحيح الذاتي للمراجعة",
        "recite_start": "السرد المتراكم",
        "recite_audio": "إرسال تسجيل السرد",
        "recite_selfcheck": "الاستماع والتصحيح الذاتي للسرد",
        "day_complete": "إتمام التحدّي"
    }
    return names.get(stage, stage)

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    s = get_student(user_id)
    message = update.message

    file_id = None
    if message.voice:
        file_id = message.voice.file_id
    elif message.audio:
        file_id = message.audio.file_id

    if not file_id:
        return

    if s["stage"] == "review_audio":
        update_student(user_id, stage="review_selfcheck", review_file_id=file_id)
        await context.bot.send_voice(
            chat_id=user_id, voice=file_id,
            caption="هذا تسجيل مراجعتك. استمعي إليه وصححي أخطاءك بنفسك، ثم اضغطي «تم التصحيح»."
        )
        await message.reply_text(
            "🎧 أعدتُ إليكِ تسجيل المراجعة. بعد الاستماع والتصحيح الذاتي اضغطي:",
            reply_markup=keyboard(["تم التصحيح"])
        )
    elif s["stage"] == "recite_audio":
        update_student(user_id, stage="recite_selfcheck", recite_file_id=file_id)
        if message.audio:
            await context.bot.send_audio(
                chat_id=user_id, audio=file_id,
                caption="هذا تسجيل سردك. استمعي إليه وراجعيه بنفسك."
            )
        else:
            await context.bot.send_voice(
                chat_id=user_id, voice=file_id,
                caption="هذا تسجيل سردك. استمعي إليه وراجعيه بنفسك."
            )
        await message.reply_text(
            "🎧 أعدتُ إليكِ تسجيل السرد. بعد الاستماع والتصحيح الذاتي اضغطي «تم التصحيح».",
            reply_markup=keyboard(["تم التصحيح"])
        )
    else:
        await message.reply_text(
            "لا يوجد تسجيل مطلوب في هذه المرحلة. اضغطي «واجب اليوم» لمعرفة خطوتك الحالية."
        )

async def reminders(context: ContextTypes.DEFAULT_TYPE):
    with db() as con:
        rows = con.execute(
            "SELECT user_id, day, stage, deadline, reminder_sent FROM students WHERE deadline IS NOT NULL"
        ).fetchall()

    for row in rows:
        user_id = row["user_id"]
        deadline = datetime.fromisoformat(row["deadline"])
        seconds_left = (deadline - now()).total_seconds()

        if seconds_left <= 0:
            update_student(
                user_id, day=1, stage="review_start",
                deadline=(now() + timedelta(hours=24)).isoformat(),
                reminder_sent="", review_file_id=None, recite_file_id=None
            )
            try:
                await context.bot.send_message(
                    user_id,
                    "⏰ انتهت مهلة الـ24 ساعة قبل إكمال واجب اليوم.\n"
                    "نبدأ من جديد بعزيمة أقوى. عدتِ إلى اليوم الأول.\n\n" + daily_text(1),
                    reply_markup=keyboard(["أنهيت المراجعة", "📖 واجب اليوم"])
                )
            except Exception:
                log.exception("Could not notify user %s", user_id)
            continue

        elapsed = 24 * 3600 - seconds_left
        due = []
        if elapsed >= 6 * 3600:
            due.append(("6", "🌷 تذكير لطيف: خذي وقتك، لكن لا تنسي واجب اليوم. خطوة صغيرة تقرّبك من هدفك."))
        if elapsed >= 12 * 3600:
            due.append(("12", "💪 مرّ نصف الوقت! أنتِ قادرة بإذن الله، أكملي واجبك اليوم."))
        if elapsed >= 18 * 3600:
            due.append(("18", "⏳ بقيت ساعات قليلة من المهلة. لا تؤجلي وردك أكثر."))
        if elapsed >= 22 * 3600:
            due.append(("22", "🚨 تذكير أخير: بقيت ساعتان تقريباً على انتهاء المهلة. أكملي واجبك حتى لا تعودي لليوم الأول."))

        sent = set(filter(None, row["reminder_sent"].split(",")))
        for key, msg in due:
            if key not in sent:
                try:
                    await context.bot.send_message(user_id, msg)
                    sent.add(key)
                    update_student(user_id, reminder_sent=",".join(sorted(sent)))
                except Exception:
                    log.exception("Could not send reminder to %s", user_id)

async def post_init(app: Application):
    init_db()
    app.job_queue.run_repeating(reminders, interval=60, first=10)

def main():
    init_db()
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))
    app.run_polling()

if __name__ == "__main__":
    main()
