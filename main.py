import asyncio
import logging
import json
import sqlite3
import requests
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, WebAppInfo,
    InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, ReplyKeyboardRemove
)
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

# ===================== SOZLAMALAR =====================
BOT_TOKEN = "7660014302:AAGvCgynFMB-y0Msy2_j9__4AjwJ4fGzqyY"
ADMIN_ID = 6814831560

WEBAPP_URL = "https://drshoqosimovawebapp.netlify.app/"
INSTAGRAM_URL = "https://www.instagram.com/dr_shoqosimova_klinika?igsh=MW1wbXhodWZ6MWo0Mg=="
TELEGRAM_CH_URL = "https://t.me/shoqosimovaZumrad"
GOOGLE_MAPS_URL = "http://maps.google.com/?q=Dr.+Shoqosimova+Klinikasi"

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Dr. Shoqosimova Klinikasi API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ===================== DATABASE =====================
conn = sqlite3.connect("clinic.db", check_same_thread=False)
cursor = conn.cursor()

# Foydalanuvchilar jadvali
cursor.execute("""
CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY,
    lang TEXT DEFAULT 'uz'
)
""")

# Qabullar jadvali
cursor.execute("""
CREATE TABLE IF NOT EXISTS appointments(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    name TEXT,
    phone TEXT,
    doctor TEXT,
    date TEXT,
    time TEXT,
    issue TEXT,
    reminded INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")

# Ta'tillar jadvali
cursor.execute("""
CREATE TABLE IF NOT EXISTS vacations(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor TEXT,
    date TEXT
)
""")

# Shifokorlar grafik jadvali (YANGI)
cursor.execute("""
CREATE TABLE IF NOT EXISTS doctor_schedules(
    doctor TEXT PRIMARY KEY,
    work_days TEXT, -- Masalan: "1,2,3,4,5,6" (Dush-Shan)
    start_time TEXT, -- "14:00"
    end_time TEXT -- "22:00"
)
""")

# Standart shifokorlar grafiklarini bazaga kiritish (agar mavjud bo'lmasa)
doctors_defaults = [
    ("Dr. Shoqosimova", "1,2,3,4,5,6", "14:00", "22:00"),
    ("Dr. Maryam", "1,2,3,4,5,6", "14:00", "22:00"),
    ("Dr. Muxlisa", "1,2,3,4,5,6", "14:00", "22:00"),
    ("Dr. Ravshan", "1,2,3,4,5,6", "14:00", "22:00")
]
for doc, days, start, end in doctors_defaults:
    cursor.execute("INSERT OR IGNORE INTO doctor_schedules VALUES (?, ?, ?, ?)", (doc, days, start, end))
conn.commit()

# ===================== Pydantic Models =====================
class BookingRequest(BaseModel):
    name: str
    phone: str
    doctor: str
    date: str
    time: str
    issue: str = "Kiritilmadi"
    user_id: int = None
    lang: str = "uz"

# ===================== TEXTS =====================
TEXTS = {
    "uz": {
        "welcome": "🏥 Dr. Shoqosimova klinikasiga xush kelibsiz!",
        "book": "📱 Onlayn Qabul",
        "my_bookings": "📅 Mening navbatlarim",
        "services": "👨‍⚕️ Xizmatlar",
        "contact": "📞 Aloqa",
        "social": "🌐 Ijtimoiy tarmoqlar",
        "change": "🇺🇿/🇷🇺 Tilni o'zgartirish",
        "success": "✅ Navbatingiz muvaffaqiyatli band qilindi!"
    },
    "ru": {
        "welcome": "🏥 Добро пожаловать в клинику Dr. Shoqosimova!",
        "book": "📱 Онлайн запись",
        "my_bookings": "📅 Мои записи",
        "services": "👨‍⚕️ Услуги",
        "contact": "📞 Контакты",
        "social": "🌐 Соц сети",
        "change": "🇺🇿/🇷🇺 Изменить язык",
        "success": "✅ Ваша запись успешно оформлена!"
    }
}

def main_kb(lang="uz"):
    is_admin = lang == "admin"
    actual_lang = "uz" if is_admin else lang
    
    kb = [
        [KeyboardButton(text=TEXTS[actual_lang]["book"], web_app=WebAppInfo(url=WEBAPP_URL))],
        [KeyboardButton(text=TEXTS[actual_lang]["my_bookings"])],
        [KeyboardButton(text=TEXTS[actual_lang]["services"]), KeyboardButton(text=TEXTS[actual_lang]["contact"])],
        [KeyboardButton(text=TEXTS[actual_lang]["social"]), KeyboardButton(text=TEXTS[actual_lang]["change"])]
    ]
    
    if is_admin:
        kb.append([KeyboardButton(text="📊 Statistika"), KeyboardButton(text="⚙️ Grafikni o'zgartirish")])
        kb.append([KeyboardButton(text="📢 Rassilka")])
    
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

lang_kb = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang_uz"),
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru")
    ]
])

class AdminState(StatesGroup):
    broadcast_media = State()
    schedule_doc = State()
    schedule_days = State()
    schedule_hours = State()

# ===================== BOT HANDLERS =====================
@dp.message(CommandStart())
async def start_handler(message: types.Message):
    user_id = message.from_user.id
    cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (user_id,))
    conn.commit()

    if user_id == ADMIN_ID:
        await message.answer("👑 Admin paneli", reply_markup=main_kb("admin"))
    else:
        await message.answer("Tilni tanlang / Выберите язык:", reply_markup=lang_kb)

@dp.callback_query(F.data.startswith("lang_"))
async def lang_callback(callback: types.CallbackQuery):
    lang = callback.data.split("_")[1]
    cursor.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, callback.from_user.id))
    conn.commit()
    await callback.message.delete()
    await callback.message.answer(TEXTS[lang]["welcome"], reply_markup=main_kb(lang))

# --- MENING NAVBATLARIM (YANGI) ---
@dp.message(F.text.in_(["📅 Mening navbatlarim", "📅 Мои записи"]))
async def my_bookings_handler(message: types.Message):
    user_id = message.from_user.id
    cursor.execute("SELECT lang FROM users WHERE user_id=?", (user_id,))
    lang = cursor.fetchone()[0] or "uz"
    
    # Kelgusi yoki bugungi qabullarni olish
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("""
        SELECT id, doctor, date, time FROM appointments 
        WHERE user_id=? AND date >= ? ORDER BY date ASC, time ASC
    """, (user_id, today))
    rows = cursor.fetchall()
    
    if not rows:
        msg = "Sizda faol navbatlar topilmadi 🤷‍♂️" if lang == "uz" else "У вас нет активных записей 🤷‍♂️"
        await message.answer(msg)
        return
        
    for row in rows:
        appt_id, doctor, date, time = row
        if lang == "uz":
            text = f"📋 <b>Navbat ma'lumoti:</b>\n\n👨‍⚕️ Shifokor: {doctor}\n📅 Sana: {date}\n🕒 Vaqt: {time}"
            btn_text = "❌ Navbatni bekor qilish"
        else:
            text = f"📋 <b>Информация о записи:</b>\n\n👨‍⚕️ Доктор: {doctor}\n📅 Дата: {date}\n🕒 Время: {time}"
            btn_text = "❌ Отменить запись"
            
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=btn_text, callback_data=f"cancel_{appt_id}")]
        ])
        await message.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_booking_callback(callback: types.CallbackQuery):
    appt_id = callback.data.split("_")[1]
    user_id = callback.from_user.id
    cursor.execute("SELECT lang FROM users WHERE user_id=?", (user_id,))
    lang = cursor.fetchone()[0] or "uz"
    
    cursor.execute("SELECT name, doctor, date, time FROM appointments WHERE id=?", (appt_id,))
    info = cursor.fetchone()
    
    cursor.execute("DELETE FROM appointments WHERE id=?", (appt_id,))
    conn.commit()
    
    await callback.message.delete()
    success_msg = "✅ Navbatingiz muvaffaqiyatli bekor qilindi." if lang == "uz" else "✅ Ваша запись успешно отменена."
    await callback.answer(success_msg, show_alert=True)
    
    # Adminga ogohlantirish yuborish
    if info:
        name, doctor, date, time = info
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=f"⚠️ <b>NAVBAT BEKOR QILINDI!</b>\n\n👤 Bemor: {name}\n👨‍⚕️ Shifokor: {doctor}\n📅 Sana: {date}\n🕒 Vaqt: {time}",
            parse_mode="HTML"
        )

@dp.message(F.text.in_(["👨‍⚕️ Xizmatlar", "👨‍⚕️ Услуги"]))
async def services_handler(message: types.Message):
    await message.answer("""
👨‍⚕️ Bizning shifokorlar va xizmatlar:

1. Dr. Shoqosimova — Pediatr, Terapevt, Zuluk muolajasi
2. Dr. Maryam — Zuluk terapiyasi, Masaj
3. Dr. Muxlisa — Zuluk va Hijoma mutaxassisi
4. Dr. Ravshan — Zuluk terapiyasi (Erkaklar uchun)
""")

@dp.message(F.text.in_(["📞 Aloqa", "📞 Контакты"]))
async def contact_handler(message: types.Message):
    await message.answer(f"""
📞 Telefon: +998959508878
🕒 Ish vaqti: 14:00 - 22:00
❌ Yakshanba — dam olish kuni

📍 Bizning manzilimizni xaritadan ko'rish: {GOOGLE_MAPS_URL}
""")

@dp.message(F.text.in_(["🌐 Ijtimoiy tarmoqlar", "🌐 Соц сети"]))
async def social_handler(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📸 Instagram", url=INSTAGRAM_URL),
            InlineKeyboardButton(text="📢 Telegram Kanal", url=TELEGRAM_CH_URL)
        ],
        [
            InlineKeyboardButton(text="📍 Bizning manzil (Google Maps)", url=GOOGLE_MAPS_URL)
        ]
    ])
    await message.answer("Klinikamizning rasmiy sahifalari va xaritadagi manzili:", reply_markup=kb)

@dp.message(F.text.in_(["🇺🇿/🇷🇺 Tilni o'zgartirish", "🇺🇿/🇷🇺 Изменить язык"]))
async def change_lang(message: types.Message):
    await message.answer("Tilni tanlang / Выберите язык:", reply_markup=lang_kb)

# ===================== BOT ADMIN CONTROLS =====================
@dp.message(F.text == "📊 Statistika")
async def stats_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    cursor.execute("SELECT COUNT(*) FROM users")
    users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM appointments")
    apps = cursor.fetchone()[0]
    await message.answer(f"📊 STATISTIKA\n\n👥 Foydalanuvchilar: {users}\n📅 Navbatlar: {apps}")

# --- CHIROYLI MEDIA RASSILKA (YANGI) ---
@dp.message(F.text == "📢 Rassilka")
async def broadcast_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await message.answer(
        "Rassilka xabarini yuboring.\n(Matn, Rasm yoki Videoli xabar yuborishingiz mumkin! Tegishli tugmalar saqlanib qoladi)", 
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(AdminState.broadcast_media)

@dp.message(AdminState.broadcast_media)
async def broadcast_media_send(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    success = 0
    
    await message.answer("Rassilka boshlandi, iltimos kuting...")
    
    for user in users:
        try:
            # Xabar turiga qarab barchaga mos ravishda tarqatish
            if message.photo:
                await bot.send_photo(user[0], photo=message.photo[-1].file_id, caption=message.caption)
            elif message.video:
                await bot.send_video(user[0], video=message.video.file_id, caption=message.caption)
            else:
                await bot.send_message(user[0], message.text)
            success += 1
            await asyncio.sleep(0.05)
        except:
            pass
            
    await message.answer(f"✅ Rassilka yakunlandi! {success} ta foydalanuvchiga muvaffaqiyatli yetkazildi.", reply_markup=main_kb("admin"))
    await state.clear()

# --- SHIFOKORLAR GRAFIKINI O'ZGARTIRISH (YANGI) ---
@dp.message(F.text == "⚙️ Grafikni o'zgartirish")
async def edit_schedule_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Dr. Shoqosimova"), KeyboardButton(text="Dr. Maryam")],
        [KeyboardButton(text="Dr. Muxlisa"), KeyboardButton(text="Dr. Ravshan")]
    ], resize_keyboard=True)
    await message.answer("Grafigini o'zgartirmoqchi bo'lgan shifokorni tanlang:", reply_markup=kb)
    await state.set_state(AdminState.schedule_doc)

@dp.message(AdminState.schedule_doc)
async def edit_schedule_days(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.update_data(doctor=message.text)
    await message.answer(
        "Shifokorning ish kunlarini raqamlar bilan dushanbadan shanbagacha kiriting.\n"
        "Masalan, Dushanbadan Jumabacha bo'lsa: 1,2,3,4,5 yozing. Har kuni bo'lsa: 1,2,3,4,5,6 kiriting:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(AdminState.schedule_days)

@dp.message(AdminState.schedule_days)
async def edit_schedule_hours(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.update_data(days=message.text)
    await message.answer("Ish vaqti oralig'ini kiriting (Masalan: 14:00-20:00 yoki 09:00-18:00 ko'rinishida):")
    await state.set_state(AdminState.schedule_hours)

@dp.message(AdminState.schedule_hours)
async def edit_schedule_save(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    try:
        times = message.text.split("-")
        start_t = times[0].strip()
        end_t = times[1].strip()
        
        data = await state.get_data()
        cursor.execute("""
            UPDATE doctor_schedules 
            SET work_days=?, start_time=?, end_time=? 
            WHERE doctor=?
        """, (data['days'], start_t, end_t, data['doctor']))
        conn.commit()
        
        await message.answer(f"✅ {data['doctor']} grafiklari muvaffaqiyatli yangilandi va Web App-ga ulandi!", reply_markup=main_kb("admin"))
    except:
        await message.answer("Xatolik! Vaqtni to'g'ri formatda kiriting (Masalan: 14:00-22:00)", reply_markup=main_kb("admin"))
    await state.clear()

# ===================== AUTOMATED REMINDER =====================
async def reminder_scheduler():
    while True:
        try:
            now = datetime.now()
            target = now + timedelta(hours=1)
            target_date = target.strftime("%Y-%m-%d")
            target_time = target.strftime("%H:00")

            cursor.execute("""
                SELECT id, user_id, name, doctor, time 
                FROM appointments 
                WHERE date=? AND time=? AND reminded=0
            """, (target_date, target_time))
            
            rows = cursor.fetchall()
            for row in rows:
                appt_id, user_id, name, doctor, tm = row
                text = f"🔔 ESLATMA!\n\n{name}, bugun {tm} da {doctor} qabuli bor.\nVaqtni unutmaslikni so'raymiz! 🏥"
                try:
                    await bot.send_message(user_id, text)
                    cursor.execute("UPDATE appointments SET reminded=1 WHERE id=?", (appt_id,))
                    conn.commit()
                except:
                    pass
        except Exception as e:
            logging.error(f"Reminder xatosi: {e}")
        
        await asyncio.sleep(60)

# ===================== FASTAPI ENDPOINTS =====================
@app.get("/")
async def root():
    return {"status": "ok", "message": "API va Bot muvaffaqiyatli ishlamoqda ✅"}

@app.get("/doctors")
async def get_doctors():
    return [
        {"name": "Dr. Shoqosimova", "specialty": "Pediatr, Terapevt, Zuluk muolajasi"},
        {"name": "Dr. Maryam", "specialty": "Zuluk terapiyasi, Masaj"},
        {"name": "Dr. Muxlisa", "specialty": "Zuluk va Hijoma mutaxassisi"},
        {"name": "Dr. Ravshan", "specialty": "Zuluk terapiyasi (Erkaklar uchun)"}
    ]

# --- SHIFOKOR GRAFIGIGA MOSLASHGAN API (YANGI O'ZGARISH) ---
@app.get("/available-slots")
async def get_available_slots(doctor: str, date: str):
    # 1. Ta'til kunini tekshirish
    cursor.execute("SELECT id FROM vacations WHERE doctor=? AND date=?", (doctor, date))
    if cursor.fetchone():
        return {"available_slots": [], "message": "Bu kuni shifokor ta'tilda"}

    # 2. Haftalik grafikni tekshirish
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
        weekday = str(dt.isoweekday()) # 1=Dush, 7=Yaksh
    except ValueError:
        raise HTTPException(status_code=400, detail="Sana formati xato (Y-m-d)")

    cursor.execute("SELECT work_days, start_time, end_time FROM doctor_schedules WHERE doctor=?", (doctor,))
    schedule = cursor.fetchone()
    
    if not schedule:
        return {"available_slots": [], "message": "Shifokor grafiklari topilmadi"}
        
    work_days, start_time, end_time = schedule
    if weekday not in work_days.split(","):
        return {"available_slots": [], "message": "Bu kuni shifokorning dam olish kuni"}

    # 3. Grafik soatlariga qarab slotlarni yaratish
    try:
        start_hour = int(start_time.split(":")[0])
        end_hour = int(end_time.split(":")[0])
    except:
        start_hour, end_hour = 14, 22 # muammo bo'lsa standart qiymat

    all_slots = [f"{hour}:00" for hour in range(start_hour, end_hour)]
    
    # Band qilingan soatlarni olib tashlash
    cursor.execute("SELECT time FROM appointments WHERE doctor=? AND date=?", (doctor, date))
    booked = [row[0] for row in cursor.fetchall()]
    available = [slot for slot in all_slots if slot not in booked]

    return {"doctor": doctor, "date": date, "available_slots": available}

@app.post("/book")
async def book_appointment(data: BookingRequest):
    try:
        cursor.execute("SELECT id FROM appointments WHERE doctor=? AND date=? AND time=?", 
                       (data.doctor, data.date, data.time))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Bu vaqt band")

        cursor.execute("""
            INSERT INTO appointments (user_id, name, phone, doctor, date, time, issue)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (data.user_id, data.name, data.phone, data.doctor, data.date, data.time, data.issue))
        conn.commit()

        report = f"🎯 <b>YANGI NAVBAT!</b>\n\n👤 Bemor: {data.name}\n📞 Telefon: {data.phone}\n👨‍⚕️ Shifokor: {data.doctor}\n📅 Sana: {data.date}\n🕒 Vaqt: {data.time}\n🩺 Muammo: {data.issue}"
        try:
            await bot.send_message(chat_id=ADMIN_ID, text=report, parse_mode="HTML")
        except:
            pass

        return {"success": True, "message": "Navbat muvaffaqiyatli band qilindi!"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ===================== LIFECYCLE TIZIMI =====================
@app.on_event("startup")
async def on_startup():
    commands = [BotCommand(command="start", description="Botni ishga tushirish")]
    await bot.set_my_commands(commands)
    
    asyncio.create_task(dp.start_polling(bot, skip_updates=True))
    asyncio.create_task(reminder_scheduler())
    print("✅ Bot va Eslatuvchi tizim fonda ishga tushdi!")

@app.on_event("shutdown")
async def on_shutdown():
    await bot.session.close()
