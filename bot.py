import logging
import os
import json
from datetime import time as dtime
from typing import Dict, Any
import pytz

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("خطأ: التوكن مش موجود في متغير البيئة TELEGRAM_BOT_TOKEN")

CAIRO_TZ = pytz.timezone('Africa/Cairo')

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

DATA_FILE = "data.json"
CHANNELS: Dict[int, Dict[str, Any]] = {}
USER_STATE: Dict[int, Dict[str, Any]] = {}

WEEKDAYS_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


def format_time_12h(hour: int, minute: int) -> str:
    """تحويل الوقت إلى نظام 12 ساعة مع صباحاً/مساءً"""
    period = "صباحاً" if hour < 12 else "مساءً"
    hour_12 = hour if hour == 0 else (hour if hour <= 12 else hour - 12)
    if hour == 0:
        hour_12 = 12
    return f"{hour_12}:{minute:02d} {period}"


def parse_time_12h(hour_12: int, period: str) -> int:
    """تحويل الوقت من 12 ساعة إلى 24 ساعة"""
    if period == "AM":
        return 0 if hour_12 == 12 else hour_12
    else:
        return 12 if hour_12 == 12 else hour_12 + 12


def load_data():
    global CHANNELS
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        CHANNELS = {}
        return
    except Exception as e:
        logging.error("فشل قراءة data.json: %s", e)
        CHANNELS = {}
        return

    CHANNELS = {}
    for cid_str, info in raw.items():
        cid = int(cid_str)
        jobs = []
        for job in info.get("jobs", []):
            h, m = map(int, job["time"].split(":"))
            jobs.append(
                {
                    "id": job["id"],
                    "text": job["text"],
                    "photo": job.get("photo"),
                    "time": dtime(h, m),
                    "days": tuple(job["days"]),
                    "user_id": job["user_id"],
                    "paused": job.get("paused", False),
                }
            )
        CHANNELS[cid] = {"title": info.get("title", "قناة"), "jobs": jobs}


def save_data():
    try:
        out = {}
        for cid, info in CHANNELS.items():
            jobs = []
            for job in info["jobs"]:
                jobs.append(
                    {
                        "id": job["id"],
                        "text": job["text"],
                        "photo": job.get("photo"),
                        "time": job["time"].strftime("%H:%M"),
                        "days": list(job["days"]),
                        "user_id": job["user_id"],
                        "paused": job.get("paused", False),
                    }
                )
            out[str(cid)] = {"title": info["title"], "jobs": jobs}
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error("فشل الحفظ: %s", e)


load_data()


def get_main_menu(user_id: int) -> InlineKeyboardMarkup:
    keyboard = []
    for cid, data in CHANNELS.items():
        title = data["title"]
        keyboard.append([InlineKeyboardButton(title, callback_data=f"select_{cid}")])
    return InlineKeyboardMarkup(keyboard)


def get_channel_menu(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("إضافة رسالة", callback_data=f"addmsg_{chat_id}")],
            [InlineKeyboardButton("عرض الرسائل", callback_data=f"list_{chat_id}")],
            [InlineKeyboardButton("رجوع", callback_data="back")],
        ]
    )


async def send_job_callback(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data or {}
    chat_id = job_data.get("chat_id")
    text = job_data.get("text")
    photo = job_data.get("photo")
    
    if chat_id:
        try:
            if photo:
                await context.bot.send_photo(chat_id=chat_id, photo=photo, caption=text)
            elif text:
                await context.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logging.error("فشل إرسال الرسالة للـchat %s : %s", chat_id, e)


def schedule_job(application: Application, chat_id: int, job: dict):
    name = f"{chat_id}_{job['id']}"
    for j in application.job_queue.get_jobs_by_name(name):
        j.schedule_removal()

    if job.get("paused", False):
        logging.info("Job %s is paused, not scheduling", name)
        return

    days_tuple = tuple(job["days"])
    application.job_queue.run_daily(
        send_job_callback, 
        time=job["time"], 
        days=days_tuple, 
        name=name, 
        data={"chat_id": chat_id, "text": job["text"], "photo": job.get("photo")},
        tzinfo=CAIRO_TZ
    )
    logging.info("Scheduled job %s for chat %s at %s (Cairo time) on days %s", job["id"], chat_id, job["time"], days_tuple)


def unschedule_job(application: Application, chat_id: int, job_id: int):
    name = f"{chat_id}_{job_id}"
    removed = 0
    for j in application.job_queue.get_jobs_by_name(name):
        j.schedule_removal()
        removed += 1
    logging.info("Removed %d scheduled jobs named %s", removed, name)


async def check_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    """التحقق من أن المستخدم أدمن في القناة"""
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception as e:
        logging.warning("فشل جلب صلاحيات العضو: %s", e)
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = get_main_menu(user_id)
    text = "مرحبا! أنا بوت الجدولة 🤖\nاضفني في قناة → ثم ابعت /start\n\n⏰ التوقيت: القاهرة (Africa/Cairo)"
    if not keyboard.inline_keyboard:
        text += "\n\nلا توجد قنوات متفعلة بعد."
    if update.message:
        await update.message.reply_text(text, reply_markup=keyboard)
    else:
        await update.effective_chat.send_message(text, reply_markup=keyboard)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "شرح سريع:\n"
        "- ضيف البوت في القناة كـ admin.\n"
        "- افتح شات البوت الخاص وابعت /start\n"
        "- هتلاقي اسم القناة اضغط عليه عشان تضيف رسالة مجدولة.\n\n"
        "المميزات:\n"
        "✅ جدولة رسائل نصية\n"
        "✅ إرسال صور مع نصوص\n"
        "✅ اختيار أيام محددة أو كل الأيام\n"
        "✅ تعديل الرسائل\n"
        "✅ إيقاف مؤقت للرسائل\n"
        "✅ نظام 12 ساعة (صباحاً/مساءً)\n"
        "⏰ التوقيت: القاهرة (Africa/Cairo)\n\n"
        "الرسائل هترسل تلقائي كل أسبوع في الأيام والوقت اللي تختارهم."
    )
    await update.message.reply_text(text)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "back":
        await query.edit_message_text("اختر قناة:", reply_markup=get_main_menu(user_id))
        return

    if data.startswith("select_"):
        chat_id = int(data.split("_", 1)[1])
        title = CHANNELS.get(chat_id, {}).get("title", "قناة")
        await query.edit_message_text(f"التحكم في: {title}", reply_markup=get_channel_menu(chat_id))
        return

    if data.startswith("addmsg_"):
        chat_id = int(data.split("_", 1)[1])
        
        if not await check_admin(context, chat_id, user_id):
            await query.edit_message_text("لازم تكون أدمن في القناة عشان تضيف رسائل مجدولة.")
            return

        USER_STATE[user_id] = {"step": "wait_text", "chat_id": chat_id, "edit_mode": False}
        await query.edit_message_text(
            "اكتب نص الرسالة اللي عايز تتبعت.\n\n"
            "أو ابعت صورة مع نص لنشر صورة مع نص في نفس الرسالة."
        )
        return

    if data.startswith("list_"):
        chat_id = int(data.split("_", 1)[1])
        jobs = CHANNELS.get(chat_id, {}).get("jobs", [])
        if not jobs:
            await query.edit_message_text("لا توجد رسائل.", reply_markup=get_channel_menu(chat_id))
            return
        keyboard = []
        for job in jobs:
            days = "كل الأسبوع" if len(job["days"]) == 7 else "، ".join(WEEKDAYS_AR[d] for d in job["days"])
            text = job["text"][:20] + "..." if len(job["text"]) > 20 else job["text"]
            status = "⏸️" if job.get("paused") else "✅"
            photo_icon = "📷" if job.get("photo") else ""
            time_12h = format_time_12h(job['time'].hour, job['time'].minute)
            keyboard.append([InlineKeyboardButton(
                f"{status} {photo_icon} {text} — {time_12h} — {days}", 
                callback_data=f"job_{chat_id}_{job['id']}"
            )])
        keyboard.append([InlineKeyboardButton("رجوع", callback_data=f"select_{chat_id}")])
        await query.edit_message_text("الرسائل:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("job_"):
        parts = data.split("_")
        chat_id, job_id = int(parts[1]), int(parts[2])
        job = next((j for j in CHANNELS[chat_id]["jobs"] if j["id"] == job_id), None)
        if not job:
            await query.edit_message_text("الرسالة غير موجودة.")
            return
        days = "كل الأسبوع" if len(job["days"]) == 7 else "، ".join(WEEKDAYS_AR[d] for d in job["days"])
        time_12h = format_time_12h(job['time'].hour, job['time'].minute)
        status = "متوقفة مؤقتاً ⏸️" if job.get("paused") else "نشطة ✅"
        photo_status = "\n📷 تحتوي على صورة" if job.get("photo") else ""
        msg = f"الرسالة:\n{job['text']}\n\nالوقت: {time_12h} (توقيت القاهرة)\nالأيام: {days}\nالحالة: {status}{photo_status}"
        
        keyboard = [
            [InlineKeyboardButton("إرسال الآن", callback_data=f"sendnow_{chat_id}_{job_id}")],
        ]
        
        if job.get("paused"):
            keyboard.append([InlineKeyboardButton("▶️ استئناف", callback_data=f"resume_{chat_id}_{job_id}")])
        else:
            keyboard.append([InlineKeyboardButton("⏸️ إيقاف مؤقت", callback_data=f"pause_{chat_id}_{job_id}")])
        
        keyboard.extend([
            [InlineKeyboardButton("✏️ تعديل", callback_data=f"edit_{chat_id}_{job_id}")],
            [InlineKeyboardButton("🗑️ حذف", callback_data=f"delete_{chat_id}_{job_id}")],
            [InlineKeyboardButton("رجوع", callback_data=f"list_{chat_id}")],
        ])
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("pause_"):
        _, chat_id_s, job_id_s = data.split("_")
        chat_id, job_id = int(chat_id_s), int(job_id_s)
        
        if not await check_admin(context, chat_id, user_id):
            await query.answer("لازم تكون أدمن في القناة", show_alert=True)
            return
        
        job = next((j for j in CHANNELS[chat_id]["jobs"] if j["id"] == job_id), None)
        if job:
            job["paused"] = True
            unschedule_job(context.application, chat_id, job_id)
            save_data()
            await query.answer("تم إيقاف الرسالة مؤقتاً ⏸️")
            await query.edit_message_reply_markup(reply_markup=None)
            await button_handler(update, context)
        return

    if data.startswith("resume_"):
        _, chat_id_s, job_id_s = data.split("_")
        chat_id, job_id = int(chat_id_s), int(job_id_s)
        
        if not await check_admin(context, chat_id, user_id):
            await query.answer("لازم تكون أدمن في القناة", show_alert=True)
            return
        
        job = next((j for j in CHANNELS[chat_id]["jobs"] if j["id"] == job_id), None)
        if job:
            job["paused"] = False
            schedule_job(context.application, chat_id, job)
            save_data()
            await query.answer("تم استئناف الرسالة ▶️")
            await query.edit_message_reply_markup(reply_markup=None)
            await button_handler(update, context)
        return

    if data.startswith("edit_"):
        _, chat_id_s, job_id_s = data.split("_")
        chat_id, job_id = int(chat_id_s), int(job_id_s)
        
        if not await check_admin(context, chat_id, user_id):
            await query.answer("لازم تكون أدمن في القناة", show_alert=True)
            return
        
        job = next((j for j in CHANNELS[chat_id]["jobs"] if j["id"] == job_id), None)
        if not job:
            await query.edit_message_text("الرسالة غير موجودة.")
            return
        
        keyboard = [
            [InlineKeyboardButton("تعديل النص", callback_data=f"edit_text_{chat_id}_{job_id}")],
            [InlineKeyboardButton("تعديل الوقت", callback_data=f"edit_time_{chat_id}_{job_id}")],
            [InlineKeyboardButton("تعديل الأيام", callback_data=f"edit_days_{chat_id}_{job_id}")],
            [InlineKeyboardButton("رجوع", callback_data=f"job_{chat_id}_{job_id}")],
        ]
        await query.edit_message_text("ماذا تريد تعديله؟", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("edit_text_"):
        _, _, chat_id_s, job_id_s = data.split("_")
        chat_id, job_id = int(chat_id_s), int(job_id_s)
        USER_STATE[user_id] = {
            "step": "wait_text", 
            "chat_id": chat_id, 
            "edit_mode": True, 
            "edit_job_id": job_id
        }
        await query.edit_message_text("اكتب النص الجديد للرسالة:")
        return

    if data.startswith("edit_time_"):
        _, _, chat_id_s, job_id_s = data.split("_")
        chat_id, job_id = int(chat_id_s), int(job_id_s)
        USER_STATE[user_id] = {
            "step": "wait_period", 
            "chat_id": chat_id, 
            "edit_mode": True, 
            "edit_job_id": job_id
        }
        keyboard = [
            [InlineKeyboardButton("صباحاً (AM)", callback_data=f"period_AM_{chat_id}")],
            [InlineKeyboardButton("مساءً (PM)", callback_data=f"period_PM_{chat_id}")],
            [InlineKeyboardButton("إلغاء", callback_data=f"job_{chat_id}_{job_id}")],
        ]
        await query.edit_message_text("اختر الفترة:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("edit_days_"):
        _, _, chat_id_s, job_id_s = data.split("_")
        chat_id, job_id = int(chat_id_s), int(job_id_s)
        job = next((j for j in CHANNELS[chat_id]["jobs"] if j["id"] == job_id), None)
        if not job:
            await query.edit_message_text("الرسالة غير موجودة.")
            return
        
        USER_STATE[user_id] = {
            "step": "wait_days", 
            "chat_id": chat_id, 
            "edit_mode": True, 
            "edit_job_id": job_id,
            "days": set(job["days"])
        }
        
        kb = []
        days_set = set(job["days"])
        for idx, day in enumerate(WEEKDAYS_AR):
            label = day + (" ✅" if idx in days_set else "")
            kb.append([InlineKeyboardButton(label, callback_data=f"toggleday_{idx}_{chat_id}")])
        
        all_selected = len(days_set) == 7
        kb.append([InlineKeyboardButton(
            "الكل ✅" if all_selected else "الكل", 
            callback_data=f"toggleall_{chat_id}"
        )])
        kb.append([InlineKeyboardButton("تأكيد وحفظ", callback_data=f"confirm_edit_{chat_id}_{job_id}")])
        kb.append([InlineKeyboardButton("إلغاء", callback_data=f"job_{chat_id}_{job_id}")])
        
        await query.edit_message_text(
            f"الأيام المحددة: {', '.join(WEEKDAYS_AR[d] for d in sorted(days_set)) if days_set else 'لا يوجد'}\nاضغط لتعديل:", 
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    if data.startswith("confirm_edit_"):
        _, _, chat_id_s, job_id_s = data.split("_")
        chat_id, job_id = int(chat_id_s), int(job_id_s)
        state = USER_STATE.get(user_id)
        
        if not state or not state.get("edit_mode"):
            await query.edit_message_text("مافيش عملية تعديل جارية.")
            return
        
        job = next((j for j in CHANNELS[chat_id]["jobs"] if j["id"] == job_id), None)
        if not job:
            await query.edit_message_text("الرسالة غير موجودة.")
            return
        
        days = sorted(list(state.get("days", [])))
        if not days:
            await query.answer("لازم تختار يوم واحد على الأقل", show_alert=True)
            return
        
        unschedule_job(context.application, chat_id, job_id)
        job["days"] = tuple(days)
        save_data()
        
        if not job.get("paused", False):
            schedule_job(context.application, chat_id, job)
        
        USER_STATE.pop(user_id, None)
        await query.edit_message_text("تم تحديث الأيام بنجاح! ✅", reply_markup=get_channel_menu(chat_id))
        return

    if data.startswith("sendnow_"):
        _, chat_id_s, job_id_s = data.split("_")
        chat_id, job_id = int(chat_id_s), int(job_id_s)
        
        if not await check_admin(context, chat_id, user_id):
            await query.answer("لازم تكون أدمن في القناة", show_alert=True)
            return
        
        job = next((j for j in CHANNELS[chat_id]["jobs"] if j["id"] == job_id), None)
        if not job:
            await query.edit_message_text("الرسالة غير موجودة.")
            return
        
        if job.get("photo"):
            await context.bot.send_photo(chat_id=chat_id, photo=job["photo"], caption=job["text"])
        else:
            await context.bot.send_message(chat_id=chat_id, text=job["text"])
        
        await query.edit_message_text("تم الإرسال فورًا! ✅")
        return

    if data.startswith("delete_"):
        _, chat_id_s, job_id_s = data.split("_")
        chat_id, job_id = int(chat_id_s), int(job_id_s)
        
        if not await check_admin(context, chat_id, user_id):
            await query.answer("لازم تكون أدمن في القناة", show_alert=True)
            return
        
        keyboard = [
            [InlineKeyboardButton("نعم", callback_data=f"confirm_delete_{chat_id}_{job_id}")],
            [InlineKeyboardButton("لا", callback_data=f"job_{chat_id}_{job_id}")],
        ]
        await query.edit_message_text("تأكيد الحذف؟", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("confirm_delete_"):
        _, _, chat_id_s, job_id_s = data.split("_")
        chat_id, job_id = int(chat_id_s), int(job_id_s)
        job = next((j for j in CHANNELS[chat_id]["jobs"] if j["id"] == job_id), None)
        if job:
            unschedule_job(context.application, chat_id, job_id)
            CHANNELS[chat_id]["jobs"].remove(job)
            save_data()
            await query.edit_message_text("تم الحذف! 🗑️", reply_markup=get_channel_menu(chat_id))
        else:
            await query.edit_message_text("الرسالة مش موجودة.")
        return

    if data.startswith("period_"):
        parts = data.split("_")
        period = parts[1]
        chat_id = int(parts[2])
        USER_STATE[user_id].update({"period": period, "step": "wait_hour"})
        
        hours = []
        for i in range(1, 13):
            hours.append(InlineKeyboardButton(f"{i}", callback_data=f"hour_{i}_{chat_id}"))
        
        keyboard = [hours[i:i+4] for i in range(0, 12, 4)]
        keyboard.append([InlineKeyboardButton("رجوع", callback_data=f"addmsg_{chat_id}")])
        await query.edit_message_text(f"اختر الساعة ({period}):", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("hour_"):
        parts = data.split("_")
        hour_12 = int(parts[1])
        chat_id = int(parts[2])
        USER_STATE[user_id].update({"hour_12": hour_12, "step": "wait_minute"})
        
        minutes_kb = []
        for i in range(0, 60, 5):
            minutes_kb.append(InlineKeyboardButton(f"{i:02d}", callback_data=f"minute_{i}_{chat_id}"))
        
        keyboard = [minutes_kb[i:i+6] for i in range(0, len(minutes_kb), 6)]
        keyboard.append([InlineKeyboardButton("رجوع", callback_data=f"addmsg_{chat_id}")])
        await query.edit_message_text("اختر الدقيقة:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("minute_"):
        parts = data.split("_")
        minute = int(parts[1])
        chat_id = int(parts[2])
        USER_STATE[user_id].update({"minute": minute, "step": "wait_days"})
        
        kb = []
        for idx, day in enumerate(WEEKDAYS_AR):
            kb.append([InlineKeyboardButton(day, callback_data=f"toggleday_{idx}_{chat_id}")])
        
        kb.append([InlineKeyboardButton("الكل", callback_data=f"toggleall_{chat_id}")])
        kb.append([InlineKeyboardButton("تأكيد وحفظ", callback_data=f"confirm_add_{chat_id}")])
        kb.append([InlineKeyboardButton("إلغاء", callback_data=f"addmsg_{chat_id}")])
        
        USER_STATE[user_id].setdefault("days", set())
        await query.edit_message_text("اضغط على الأيام اللي عايز تتكرر فيها الرسالة (اضغط للتحديد/إلغاء):", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("toggleday_"):
        _, day_idx_s, chat_id_s = data.split("_")
        day_idx, chat_id = int(day_idx_s), int(chat_id_s)
        days_set = USER_STATE[user_id].setdefault("days", set())
        if day_idx in days_set:
            days_set.remove(day_idx)
        else:
            days_set.add(day_idx)
        USER_STATE[user_id]["days"] = days_set
        
        kb = []
        for idx, day in enumerate(WEEKDAYS_AR):
            label = day + (" ✅" if idx in days_set else "")
            kb.append([InlineKeyboardButton(label, callback_data=f"toggleday_{idx}_{chat_id}")])
        
        all_selected = len(days_set) == 7
        kb.append([InlineKeyboardButton(
            "الكل ✅" if all_selected else "الكل", 
            callback_data=f"toggleall_{chat_id}"
        )])
        kb.append([InlineKeyboardButton("تأكيد وحفظ", callback_data=f"confirm_add_{chat_id}")])
        kb.append([InlineKeyboardButton("إلغاء", callback_data=f"addmsg_{chat_id}")])
        
        await query.edit_message_text(
            f"الأيام المحددة: {', '.join(WEEKDAYS_AR[d] for d in sorted(days_set)) if days_set else 'لا يوجد'}\nاضغط لتعديل:", 
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    if data.startswith("toggleall_"):
        chat_id = int(data.split("_")[1])
        days_set = USER_STATE[user_id].setdefault("days", set())
        
        if len(days_set) == 7:
            days_set.clear()
        else:
            days_set = set(range(7))
        
        USER_STATE[user_id]["days"] = days_set
        
        kb = []
        for idx, day in enumerate(WEEKDAYS_AR):
            label = day + (" ✅" if idx in days_set else "")
            kb.append([InlineKeyboardButton(label, callback_data=f"toggleday_{idx}_{chat_id}")])
        
        all_selected = len(days_set) == 7
        kb.append([InlineKeyboardButton(
            "الكل ✅" if all_selected else "الكل", 
            callback_data=f"toggleall_{chat_id}"
        )])
        kb.append([InlineKeyboardButton("تأكيد وحفظ", callback_data=f"confirm_add_{chat_id}")])
        kb.append([InlineKeyboardButton("إلغاء", callback_data=f"addmsg_{chat_id}")])
        
        await query.edit_message_text(
            f"الأيام المحددة: {', '.join(WEEKDAYS_AR[d] for d in sorted(days_set)) if days_set else 'لا يوجد'}\nاضغط لتعديل:", 
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    if data.startswith("confirm_add_"):
        chat_id = int(data.replace("confirm_add_", ""))
        state = USER_STATE.get(user_id)
        if not state or state.get("step") not in ("wait_days", "wait_minute"):
            await query.edit_message_text("مافيش عملية إضافة جارية. ابدأ من جديد.")
            return
        
        text = state.get("text")
        photo = state.get("photo")
        period = state.get("period")
        hour_12 = state.get("hour_12")
        minute = state.get("minute")
        days = sorted(list(state.get("days", [])))
        
        if (not text and not photo) or hour_12 is None or minute is None or not days or not period:
            await query.edit_message_text("لازم تكمل كل الخطوات: نص، ساعة، دقيقة، وأيام.")
            return
        
        hour_24 = parse_time_12h(hour_12, period)
        
        if state.get("edit_mode"):
            job_id = state.get("edit_job_id")
            job = next((j for j in CHANNELS[chat_id]["jobs"] if j["id"] == job_id), None)
            if job:
                unschedule_job(context.application, chat_id, job_id)
                job["text"] = text
                job["photo"] = photo
                job["time"] = dtime(hour_24, minute)
                job["days"] = tuple(days)
                save_data()
                
                if not job.get("paused", False):
                    schedule_job(context.application, chat_id, job)
                
                USER_STATE.pop(user_id, None)
                await query.edit_message_text("تم تحديث الرسالة بنجاح! ✅", reply_markup=get_channel_menu(chat_id))
            else:
                await query.edit_message_text("الرسالة غير موجودة.")
        else:
            existing = CHANNELS.setdefault(chat_id, {"title": f"قناة_{chat_id}", "jobs": []})["jobs"]
            new_id = max((j["id"] for j in existing), default=0) + 1
            job_obj = {
                "id": new_id, 
                "text": text, 
                "photo": photo,
                "time": dtime(hour_24, minute), 
                "days": tuple(days), 
                "user_id": user_id,
                "paused": False
            }
            CHANNELS[chat_id]["jobs"].append(job_obj)
            save_data()
            schedule_job(context.application, chat_id, job_obj)
            
            USER_STATE.pop(user_id, None)
            await query.edit_message_text("تم إضافة الرسالة وجدولتها! ✅ هتتكرر كل أسبوع في الأيام اللي اخترتها.", reply_markup=get_channel_menu(chat_id))
        return

    logging.info("Unknown callback data: %s", data)
    await query.edit_message_text("حدث شيء غير متوقع. ارجع وحاول تاني.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    
    user_id = update.effective_user.id
    if user_id not in USER_STATE or USER_STATE[user_id].get("step") != "wait_text":
        return
    
    text = ""
    photo = None
    
    if update.message.photo:
        photo = update.message.photo[-1].file_id
        text = update.message.caption or ""
    elif update.message.text:
        text = update.message.text.strip()
    
    if not text and not photo:
        await update.message.reply_text("الرجاء إرسال نص أو صورة مع نص.")
        return
    
    chat_id = USER_STATE[user_id]["chat_id"]
    edit_mode = USER_STATE[user_id].get("edit_mode", False)
    
    if edit_mode:
        job_id = USER_STATE[user_id].get("edit_job_id")
        job = next((j for j in CHANNELS[chat_id]["jobs"] if j["id"] == job_id), None)
        if job:
            unschedule_job(context.application, chat_id, job_id)
            job["text"] = text
            job["photo"] = photo
            save_data()
            
            if not job.get("paused", False):
                schedule_job(context.application, chat_id, job)
            
            USER_STATE.pop(user_id, None)
            await update.message.reply_text("تم تحديث النص بنجاح! ✅", reply_markup=get_channel_menu(chat_id))
        else:
            await update.message.reply_text("الرسالة غير موجودة.")
    else:
        USER_STATE[user_id].update({"step": "wait_period", "text": text, "photo": photo})
        
        keyboard = [
            [InlineKeyboardButton("صباحاً (AM)", callback_data=f"period_AM_{chat_id}")],
            [InlineKeyboardButton("مساءً (PM)", callback_data=f"period_PM_{chat_id}")],
            [InlineKeyboardButton("رجوع", callback_data=f"addmsg_{chat_id}")],
        ]
        await update.message.reply_text("اختر الفترة:", reply_markup=InlineKeyboardMarkup(keyboard))


async def new_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            chat = update.message.chat
            chat_id = chat.id
            title = chat.title or chat.username or "قناة"
            if chat_id not in CHANNELS:
                CHANNELS[chat_id] = {"title": title, "jobs": []}
                save_data()
            await update.message.reply_text(f"تم التفعيل في {title}!\nافتح الشات الخاص وابعت /start")
            logging.info("Bot added to chat %s (%s)", chat_id, title)


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_message))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_chat_member))

    for cid, info in CHANNELS.items():
        for job in info.get("jobs", []):
            try:
                schedule_job(app, cid, job)
            except Exception as e:
                logging.error("فشل جدولة job %s in chat %s: %s", job.get("id"), cid, e)

    logging.info("البوت شغال! يبدأ polling... (توقيت القاهرة)")
    app.run_polling()


if __name__ == "__main__":
    main()
