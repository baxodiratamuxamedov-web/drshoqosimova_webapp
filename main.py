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

# ===================== S0ZLAMALAR =====================
BOT_TOKEN = "7660014302:AAGvCgynFMB-y0Msy2_j9__4AjwJ4fGzqyY"
ADMIN_ID = 6814831560
WEBAPP_URL = "https://your-vercel-site.vercel.app"  # Web App (Vercel) URL manzilingiz

logging.basicConfig(level=logging.INFO)

# FastAPI obyekti
app = FastAPI(title="Dr. Shoqosimova Klinikasi API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Aiogram Bot obyekti
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ===================== DATABASE =====================
conn = sqlite3.connect("clinic.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY,
    lang TEXT DEFAULT 'uz'
)
""")

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

cursor.execute("""
CREATE TABLE IF NOT EXISTS vacations(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor TEXT,
    date TEXT
)
""")
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
        "services": "👨‍⚕️ Xizmatlar",
        "contact": "📞 Aloqa",
        "social": "🌐 Ijtimoiy tarmoqlar",
        "change": "🇺🇿/🇷🇺 Tilni o'zgartirish",
        "success": "✅ Navbatingiz muvaffaqiyatli band qilindi!"
    },
    "ru": {
        "welcome": "🏥 Добро пожаловать в клинику Dr. Shoqosimova!",
        "book": "📱 Онлайн запись",
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
        [KeyboardButton(text=TEXTS[actual_lang]["services"]), KeyboardButton(text=TEXTS[actual_lang]["contact"])],
        [KeyboardButton(text=TEXTS[actual_lang]["social"])],
        [KeyboardButton(text=TEXTS[actual_lang]["change"])]
    ]
    
    if is_admin:
        kb.append([KeyboardButton(text="📊 Statistika")])
        kb.append([KeyboardButton(text="📢 Rassilka")])
    
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

lang_kb = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang_uz"),
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru")
    ]
])

class AdminState(StatesGroup):
    broadcast = State()

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

@dp.message(F.text.in_(["👨‍⚕️ Xizmatlar", "👨‍⚕️ Услуги"]))
async def services_handler(message: types.Message):
    await message.answer("""
👨‍⚕️ Bizning shifokorlar:

1. Dr. Shoqosimova — Pediatr, Terapevt, Zuluk
2. Dr. Maryam — Zuluk terapiyasi, Masaj
3. Dr. Muxlisa — Zuluk va Hijoma
4. Dr. Ravshan — Zuluk terapiyasi (Erkaklar)
""")

@dp.message(F.text.in_(["📞 Aloqa", "📞 Контакты"]))
async def contact_handler(message: types.Message):
    await message.answer("""
📞 Telefon: +998959508878
🕒 Ish vaqti: 14:00 - 22:00
❌ Yakshanba — dam olish kuni
""")

@dp.message(F.text.in_(["🌐 Ijtimoiy tarmoqlar", "🌐 Соц сети"]))
async def social_handler(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Instagram", url="https://instagram.com")]
    ])
    await message.answer("Bizning sahifalar:", reply_markup=kb)

@dp.message(F.text.in_(["🇺🇿/🇷🇺 Tilni o'zgartirish", "🇺🇿/🇷🇺 Изменить язык"]))
async def change_lang(message: types.Message):
    await message.answer("Tilni tanlang / Выберите язык:", reply_markup=lang_kb)

# ===================== BOT ADMIN CONTROLS =====================
@dp.message(F.text == "📊 Statistika")
async def stats_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    cursor.execute("SELECT COUNT(*) FROM users")
    users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM appointments")
    apps = cursor.fetchone()[0]
    await message.answer(f"📊 STATISTIKA\n\n👥 Foydalanuvchilar: {users}\n📅 Navbatlar: {apps}")

@dp.message(F.text == "📢 Rassilka")
async def broadcast_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Xabar matnini yuboring:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdminState.broadcast)

@dp.message(AdminState.broadcast)
async def broadcast_send(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    success = 0
    for user in users:
        try:
            await bot.send_message(user[0], message.text)
            success += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await message.answer(f"✅ Xabar yuborildi: {success} ta foydalanuvchiga", reply_markup=main_kb("admin"))
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

@app.get("/available-slots")
async def get_available_slots(doctor: str, date: str):
    cursor.execute("SELECT id FROM vacations WHERE doctor=? AND date=?", (doctor, date))
    if cursor.fetchone():
        return {"available_slots": [], "message": "Bu kuni shifokor ta'tilda"}

    all_slots = ["14:00", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00", "21:00"]
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
    
    # Bot va Eslatmalarni fonda alohida xavfsiz vazifa sifatida yurgizish
    asyncio.create_task(dp.start_polling(bot, skip_updates=True))
    asyncio.create_task(reminder_scheduler())
    print("✅ Bot va Eslatuvchi tizim fonda ishga tushdi!")

@app.on_event("shutdown")
async def on_shutdown():
    await bot.session.close()
