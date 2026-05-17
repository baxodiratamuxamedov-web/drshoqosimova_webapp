import os
import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from typing import Optional, List

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

# --- SOZLAMALAR ---
# Xavfsizlik uchun tokenlar Render muhitidan olinadi, agar topilmasa default qiymat ishlaydi
BOT_TOKEN = os.getenv("BOT_TOKEN", "7660014302:AAGvCgynFMB-y0Msy2_j9__4AjwJ4fGzqyY")
ADMIN_ID = int(os.getenv("ADMIN_ID", 6814831560))

WEBAPP_URL = "https://drshoqosimovawebapp.netlify.app/"
INSTAGRAM_URL = "https://www.instagram.com/dr_shoqosimova_klinika?igsh=MW1wbXhodWZ6MWo0Mg=="
TELEGRAM_CH_URL = "https://t.me/shoqosimovaZumrad"
GOOGLE_MAPS_URL = "http://maps.google.com/?q=Dr.+Shoqosimova+Klinikasi"

logging.basicConfig(level=logging.INFO)

# --- MA'LUMOTLAR BAZASI (SQLITE) ---
conn = sqlite3.connect("clinic.db", check_same_thread=False)
cursor = conn.cursor()

# Jadvallarni yaratish va tekshirish
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
    age TEXT DEFAULT 'Kiritilmadi',
    doctor TEXT,
    date TEXT,
    time TEXT,
    issue TEXT DEFAULT 'Kiritilmadi',
    reminded INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")

# Mavjud bazada age va issue ustunlari borligini tekshirish (ustunlar yo'q bo'lsa qo'shish)
cursor.execute("PRAGMA table_info(appointments)")
columns = [col[1] for col in cursor.fetchall()]
if "age" not in columns:
    cursor.execute("ALTER TABLE appointments ADD COLUMN age TEXT DEFAULT 'Kiritilmadi'")
if "issue" not in columns:
    cursor.execute("ALTER TABLE appointments ADD COLUMN issue TEXT DEFAULT 'Kiritilmadi'")
conn.commit()

cursor.execute("""
CREATE TABLE IF NOT EXISTS vacations(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor TEXT,
    date TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS doctor_schedules(
    doctor TEXT PRIMARY KEY,
    work_days TEXT,
    start_time TEXT,
    end_time TEXT
)
""")

doctors_defaults = [
    ("Dr. Shoqosimova", "1,2,3,4,5,6", "14:00", "22:00"),
    ("Dr. Maryam", "1,2,3,4,5,6", "14:00", "22:00"),
    ("Dr. Muxlisa", "1,2,3,4,5,6", "14:00", "22:00"),
    ("Dr. Ravshan", "1,2,3,4,5,6", "14:00", "22:00")
]
for doc, days, start, end in doctors_defaults:
    cursor.execute("INSERT OR IGNORE INTO doctor_schedules VALUES (?, ?, ?, ?)", (doc, days, start, end))
conn.commit()


# --- BOT VA DISPATCHER ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# --- TIMED REMINDER TASK (FONDAGI ESLATMA TIZIMI) ---
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
                text = f"🔔 <b>ESLATMA!</b>\n\n{name}, bugun {tm} da {doctor} qabulingiz bor.\nVaqtni unutmaslikni so'raymiz! 🏥"
                try:
                    await bot.send_message(user_id, text, parse_mode="HTML")
                    cursor.execute("UPDATE appointments SET reminded=1 WHERE id=?", (appt_id,))
                    conn.commit()
                except Exception as e:
                    logging.error(f"Foydalanuvchiga eslatma yuborib bo'lmadi: {e}")
        except Exception as e:
            logging.error(f"Reminder xatosi: {e}")
        
        await asyncio.sleep(60)


# --- FASTAPI LIFESPAN (KOD ISHGA TUSHGANDA VA TO'XTAGANDA) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Bot komandalari va fon topshiriqlarini ishga tushirish
    commands = [BotCommand(command="start", description="Botni ishga tushirish")]
    await bot.set_my_commands(commands)
    
    polling_task = asyncio.create_task(dp.start_polling(bot, skip_updates=True))
    reminder_task = asyncio.create_task(reminder_scheduler())
    logging.info("✅ Bot va Eslatuvchi tizim fonda muvaffaqiyatli ishga tushdi!")
    
    yield
    
    # Shutdown: Bot sessiyasini yopish va topshiriqlarni bekor qilish
    polling_task.cancel()
    reminder_task.cancel()
    await bot.session.close()
    logging.info("🛑 Tizim xavfsiz to'xtatildi.")

app = FastAPI(title="Dr. Shoqosimova Klinikasi API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- PYDANTIC MODELLARI ---
class BookingRequest(BaseModel):
    name: str
    phone: str
    age: str = "Kiritilmadi"
    doctor: str
    date: str
    time: str
    issue: str = "Kiritilmadi"
    user_id: Optional[int] = None
    lang: str = "uz"

class WebAppCancelRequest(BaseModel):
    appointment_id: int
    user_id: int


# --- TILLAR LUG'ATI VA KLAVIATURALAR ---
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
    is_admin = (lang == "admin")
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

class UserBookingState(StatesGroup):
    name = State()
    phone = State()
    age = State()
    doctor = State()
    date = State()
    time = State()
    issue = State()


# --- TELEGRAM BOT HANDLERLARI ---

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

@dp.message(F.text.in_(["📱 Onlayn Qabul", "📱 Онлайн запись"]))
async def book_option_handler(message: types.Message):
    user_id = message.from_user.id
    cursor.execute("SELECT lang FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    lang = row[0] if row else "uz"
    
    if lang == "uz":
        text = "Qabulga qanday yozilmoqchisiz?"
        b1, b2 = "🌐 Sayt orqali (Web App)", "🤖 Bot orqali"
    else:
        text = "Как вы хотите записаться на прием?"
        b1, b2 = "🌐 Через сайт (Web App)", "🤖 Через бот"
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b1, web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(text=b2, callback_data="book_via_bot")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "book_via_bot")
async def book_via_bot_start(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    cursor.execute("SELECT lang FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    lang = row[0] if row else "uz"
    await state.update_data(lang=lang)
    
    await callback.message.delete()
    text = "Ism va familiyangizni kiriting:" if lang == "uz" else "Введите ваше имя и фамилию:"
    await callback.message.answer(text, reply_markup=ReplyKeyboardRemove())
    await state.set_state(UserBookingState.name)

@dp.message(UserBookingState.name)
async def book_state_name(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data["lang"]
    await state.update_data(name=message.text)
    
    text = "Telefon raqamingizni kiriting yoki quyidagi tugmani bosing:" if lang == "uz" else "Введите номер телефона или нажмите кнопку:"
    btn_text = "📞 Telefon raqamni yuborish" if lang == "uz" else "📞 Отправить номер"
    
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=btn_text, request_contact=True)]], resize_keyboard=True)
    await message.answer(text, reply_markup=kb)
    await state.set_state(UserBookingState.phone)

@dp.message(UserBookingState.phone)
async def book_state_phone(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data["lang"]
    phone = message.contact.phone_number if message.contact else message.text
    await state.update_data(phone=phone)
    
    text = "Yoshingizni kiriting (Masalan: 25 yoki 7 oylik):" if lang == "uz" else "Введите ваш возраст (Например: 25 или 7 месяцев):"
    await message.answer(text, reply_markup=ReplyKeyboardRemove())
    await state.set_state(UserBookingState.age)

@dp.message(UserBookingState.age)
async def book_state_age(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data["lang"]
    await state.update_data(age=message.text)
    
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Dr. Shoqosimova"), KeyboardButton(text="Dr. Maryam")],
        [KeyboardButton(text="Dr. Muxlisa"), KeyboardButton(text="Dr. Ravshan")]
    ], resize_keyboard=True)
    
    text = "Shifokorni tanlang:" if lang == "uz" else "Выберите доктора:"
    await message.answer(text, reply_markup=kb)
    await state.set_state(UserBookingState.doctor)

@dp.message(UserBookingState.doctor)
async def book_state_doctor(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data["lang"]
    await state.update_data(doctor=message.text)
    
    kb = ReplyKeyboardMarkup(keyboard=[[]], resize_keyboard=True)
    for i in range(0, 5):
        day = (datetime.now() + timedelta(days=i)).strftime("%Y-%m-%d")
        kb.keyboard[0].append(KeyboardButton(text=day))
        
    text = "Sanani tanlang (Yil-Oy-Kun):" if lang == "uz" else "Выберите дату (Год-Месяц-День):"
    await message.answer(text, reply_markup=kb)
    await state.set_state(UserBookingState.date)

@dp.message(UserBookingState.date)
async def book_state_date(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data["lang"]
    doctor = data["doctor"]
    date_str = message.text
    await state.update_data(date=date_str)
    
    cursor.execute("SELECT id FROM vacations WHERE doctor=? AND date=?", (doctor, date_str))
    if cursor.fetchone():
        text = "Ushbu sanada shifokor ta'tilda. Iltimos boshqa sana kiriting:" if lang == "uz" else "В эту дату врач не работает. Введите другую дату:"
        await message.answer(text)
        return

    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        weekday = str(dt.isoweekday())
    except:
        text = "Sana xato. Format: YYYY-MM-DD"
        await message.answer(text)
        return

    cursor.execute("SELECT work_days, start_time, end_time FROM doctor_schedules WHERE doctor=?", (doctor,))
    schedule = cursor.fetchone()
    if not schedule or weekday not in schedule[0].split(","):
        text = "Bu kuni shifokor ishlamaydi. Boshqa sana tanlang:" if lang == "uz" else "В этот день врач не работает. Выберите другую дату:"
        await message.answer(text)
        return
        
    start_hour = int(schedule[1].split(":")[0])
    end_hour = int(schedule[2].split(":")[0])
    all_slots = [f"{hour}:00" for hour in range(start_hour, end_hour)]
    
    cursor.execute("SELECT time FROM appointments WHERE doctor=? AND date=?", (doctor, date_str))
    booked = [row[0] for row in cursor.fetchall()]
    available = [slot for slot in all_slots if slot not in booked]
    
    if not available:
        text = "Bu kungi barcha soatlar band. Boshqa sana tanlang:" if lang == "uz" else "Все часы заняты. Выберите другую дату:"
        await message.answer(text)
        return
        
    kb = ReplyKeyboardMarkup(keyboard=[], resize_keyboard=True)
    row = []
    for slot in available:
        row.append(KeyboardButton(text=slot))
        if len(row) == 4:
            kb.keyboard.append(row)
            row = []
    if row:
        kb.keyboard.append(row)
        
    text = "Vaqtni tanlang:" if lang == "uz" else "Выберите время:"
    await message.answer(text, reply_markup=kb)
    await state.set_state(UserBookingState.time)

@dp.message(UserBookingState.time)
async def book_state_time(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data["lang"]
    await state.update_data(time=message.text)
    
    text = "Sizni nima bezovta qilyapti? (Muammoni qisqacha yozing):" if lang == "uz" else "Что вас беспокоит? (Опишите проблему кратко):"
    await message.answer(text, reply_markup=ReplyKeyboardRemove())
    await state.set_state(UserBookingState.issue)

@dp.message(UserBookingState.issue)
async def book_state_issue(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await state.update_data(issue=message.text)
    data = await state.get_data()
    lang = data["lang"]
    
    cursor.execute("""
        INSERT INTO appointments (user_id, name, phone, age, doctor, date, time, issue)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, data["name"], data["phone"], data["age"], data["doctor"], data["date"], data["time"], data["issue"]))
    conn.commit()
    
    report = f"🎯 <b>YANGI NAVBAT (BOTDAN)!</b>\n\n👤 Bemor: {data['name']}\n📞 Telefon: {data['phone']}\n🎂 Yoshi: {data['age']}\n👨‍⚕️ Shifokor: {data['doctor']}\n📅 Sana: {data['date']}\n🕒 Vaqt: {data['time']}\n🩺 Muammo: {data['issue']}"
    try:
        await bot.send_message(chat_id=ADMIN_ID, text=report, parse_mode="HTML")
    except:
        pass
        
    await message.answer(TEXTS[lang]["success"], reply_markup=main_kb(lang))
    await state.clear()

@dp.message(F.text.in_(["📅 Mening navbatlarim", "📅 Мои записи"]))
async def my_bookings_handler(message: types.Message):
    user_id = message.from_user.id
    cursor.execute("SELECT lang FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    lang = row[0] if row else "uz"
    
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("""
        SELECT id, doctor, date, time, age FROM appointments 
        WHERE user_id=? AND date >= ? ORDER BY date ASC, time ASC
    """, (user_id, today))
    rows = cursor.fetchall()
    
    if not rows:
        msg = "Sizda faol navbatlar topilmadi 🤷‍♂️" if lang == "uz" else "У вас нет активных записей 🤷‍♂️"
        await message.answer(msg)
        return
        
    for row in rows:
        appt_id, doctor, date, time, age = row
        if lang == "uz":
            text = f"📋 <b>Navbat ma'lumoti:</b>\n\n👨‍⚕️ Shifokor: {doctor}\n📅 Sana: {date}\n🕒 Vaqt: {time}\n🎂 Yoshi: {age}"
            btn_text = "❌ Navbatni bekor qilish"
        else:
            text = f"📋 <b>Информация о записи:</b>\n\n👨‍⚕️ Доктор: {doctor}\n📅 Дата: {date}\n🕒 Время: {time}\n🎂 Возраст: {age}"
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
    row = cursor.fetchone()
    lang = row[0] if row else "uz"
    
    cursor.execute("SELECT name, doctor, date, time, age FROM appointments WHERE id=?", (appt_id,))
    info = cursor.fetchone()
    
    cursor.execute("DELETE FROM appointments WHERE id=?", (appt_id,))
    conn.commit()
    
    await callback.message.delete()
    success_msg = "✅ Navbatingiz muvaffaqiyatli bekor qilindi." if lang == "uz" else "✅ Ваша запись успешно отменена."
    await callback.answer(success_msg, show_alert=True)
    
    if info:
        name, doctor, date, time, age = info
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=f"⚠️ <b>NAVBAT BEKOR QILINDI (BOTDAN)!</b>\n\n👤 Bemor: {name}\n🎂 Yoshi: {age}\n👨‍⚕️ Shifokor: {doctor}\n📅 Sana: {date}\n🕒 Vaqt: {time}",
            parse_mode="HTML"
        )
        
        user_cancel_msg = f"❌ <b>Sizning navbatingiz bekor qilindi!</b>\n\n👨‍⚕️ Shifokor: {doctor}\n📅 Sana: {date}\n🕒 Vaqt: {time}" if lang == "uz" else f"❌ <b>Ваша запись отменена!</b>\n\n👨‍⚕️ Доктор: {doctor}\n📅 Дата: {date}\n🕒 Время: {time}"
        try:
            await bot.send_message(chat_id=user_id, text=user_cancel_msg, parse_mode="HTML")
        except:
            pass

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


# --- ADMIN KOMANDALARI ---

@dp.message(F.text == "📊 Statistika")
async def stats_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    cursor.execute("SELECT COUNT(*) FROM users")
    users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM appointments")
    apps = cursor.fetchone()[0]
    await message.answer(f"📊 STATISTIKA\n\n👥 Foydalanuvchilar: {users}\n📅 Navbatlar: {apps}")

@dp.message(F.text == "📢 Rassilka")
async def broadcast_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await message.answer(
        "Rassilka xabarini yuboring.\n(Matn, Rasm yoki Videoli xabar yuborishingiz mumkin!)", 
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
        "Masalan: 1,2,3,4,5,6 (Dushanba-Shanba):",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(AdminState.schedule_days)

@dp.message(AdminState.schedule_days)
async def edit_schedule_hours(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.update_data(days=message.text)
    await message.answer("Ish vaqti oralig'ini kiriting (Masalan: 14:00-22:00 ko'rinishida):")
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


# --- FASTAPI WEB API ENDPOINTLARI ---

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

    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
        weekday = str(dt.isoweekday())
    except ValueError:
        raise HTTPException(status_code=400, detail="Sana formati xato (Y-m-d)")

    cursor.execute("SELECT work_days, start_time, end_time FROM doctor_schedules WHERE doctor=?", (doctor,))
    schedule = cursor.fetchone()
    
    if not schedule:
        return {"available_slots": [], "message": "Shifokor grafiklari topilmadi"}
        
    work_days, start_time, end_time = schedule
    if weekday not in work_days.split(","):
        return {"available_slots": [], "message": "Bu kuni shifokorning dam olish kuni"}

    try:
        start_hour = int(start_time.split(":")[0])
        end_hour = int(end_time.split(":")[0])
    except:
        start_hour, end_hour = 14, 22

    all_slots = [f"{hour}:00" for hour in range(start_hour, end_hour)]
    
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
            raise HTTPException(status_code=400, detail="Bu vaqt allaqachon band qilingan")

        cursor.execute("""
            INSERT INTO appointments (user_id, name, phone, age, doctor, date, time, issue)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (data.user_id, data.name, data.phone, data.age, data.doctor, data.date, data.time, data.issue))
        conn.commit()

        report = f"🎯 <b>YANGI NAVBAT!</b>\n\n👤 Bemor: {data.name}\n📞 Telefon: {data.phone}\n🎂 Yoshi: {data.age}\n👨‍⚕️ Shifokor: {data.doctor}\n📅 Sana: {data.date}\n🕒 Vaqt: {data.time}\n🩺 Muammo: {data.issue}"
        try:
            await bot.send_message(chat_id=ADMIN_ID, text=report, parse_mode="HTML")
        except Exception as e:
            logging.error(f"Adminga xabar ketmadi: {e}")

        if data.user_id:
            if data.lang == "uz":
                user_msg = f"🏥 <b>Siz muvaffaqiyatli qabulga yozildingiz!</b>\n\n👨‍⚕️ Shifokor: {data.doctor}\n📅 Sana: {data.date}\n🕒 Vaqt: {data.time}\n\nKlinikamizga o'z vaqtida kelishingizni so'raymiz."
            else:
                user_msg = f"🏥 <b>Вы успешно записались на прием!</b>\n\n👨‍⚕️ Доктор: {data.doctor}\n📅 Дата: {data.date}\n🕒 Время: {data.time}\n\nПожалуйста, приходите вовремя."
            
            try:
                await bot.send_message(chat_id=data.user_id, text=user_msg, parse_mode="HTML")
            except Exception as e:
                logging.error(f"Foydalanuvchiga tasdiqlash xabari ketmadi: {e}")

        return {"success": True, "message": "Navbat muvaffaqiyatli band qilindi!"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/my-appointments")
async def get_my_appointments(user_id: int):
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("""
        SELECT id, name, phone, doctor, date, time, issue, age FROM appointments 
        WHERE user_id=? AND date >= ? ORDER BY date ASC, time ASC
    """, (user_id, today))
    rows = cursor.fetchall()
    
    appointments = []
    for row in rows:
        appointments.append({
            "id": row[0],
            "name": row[1],
            "phone": row[2],
            "doctor": row[3],
            "date": row[4],
            "time": row[5],
            "issue": row[6],
            "age": row[7]
        })
    return appointments

@app.post("/cancel-appointment")
async def cancel_appointment_endpoint(data: WebAppCancelRequest):
    cursor.execute("SELECT name, doctor, date, time, age FROM appointments WHERE id=? AND user_id=?", (data.appointment_id, data.user_id))
    info = cursor.fetchone()
    
    if not info:
        raise HTTPException(status_code=404, detail="Navbat topilmadi yoki sizga tegishli emas")
        
    cursor.execute("DELETE FROM appointments WHERE id=? AND user_id=?", (data.appointment_id, data.user_id))
    conn.commit()
    
    name, doctor, date, time, age = info
    report = f"⚠️ <b>NAVBAT BEKOR QILINDI (WEB APP'DAN)!</b>\n\n👤 Bemor: {name}\n🎂 Yoshi: {age}\n👨‍⚕️ Shifokor: {doctor}\n📅 Sana: {date}\n🕒 Vaqt: {time}"
    try:
        await bot.send_message(chat_id=ADMIN_ID, text=report, parse_mode="HTML")
    except:
        pass

    cursor.execute("SELECT lang FROM users WHERE user_id=?", (data.user_id,))
    user_lang_row = cursor.fetchone()
    lang = user_lang_row[0] if user_lang_row else "uz"

    user_cancel_msg = f"❌ <b>Sizning navbatingiz bekor qilindi (Sayt orqali)!</b>\n\n👨‍⚕️ Shifokor: {doctor}\n📅 Sana: {date}\n🕒 Vaqt: {time}" if lang == "uz" else f"❌ <b>Ваша запись отменена (через Сайт)!</b>\n\n👨‍⚕️ Доктор: {doctor}\n📅 Дата: {date}\n🕒 Время: {time}"
    try:
        await bot.send_message(chat_id=data.user_id, text=user_cancel_msg, parse_mode="HTML")
    except:
        pass
        
    return {"success": True, "message": "Navbat bekor qilindi"}
