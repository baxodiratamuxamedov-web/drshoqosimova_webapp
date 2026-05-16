from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
import requests

app = FastAPI(title="Dr. Shoqosimova Klinikasi API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===================== CONFIG =====================
BOT_TOKEN = "7660014302:AAGvCgynFMB-y0Msy2_j9__4AjwJ4fGzqyY"
ADMIN_ID = 6814831560

# ===================== DATABASE =====================
conn = sqlite3.connect("clinic.db", check_same_thread=False)
cursor = conn.cursor()

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

# ===================== MODELS =====================
class BookingRequest(BaseModel):
    name: str
    phone: str
    doctor: str
    date: str
    time: str
    issue: str = "Kiritilmadi"
    user_id: int = None
    lang: str = "uz"

# ===================== ENDPOINTS =====================
@app.get("/")
async def root():
    return {"status": "ok", "message": "API ishlamoqda ✅"}

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
    # Ta'til tekshirish
    cursor.execute("SELECT id FROM vacations WHERE doctor=? AND date=?", (doctor, date))
    if cursor.fetchone():
        return {"available_slots": [], "message": "Bu kuni shifokor ta'tilda"}

    all_slots = ["14:00", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00", "21:00"]

    cursor.execute("SELECT time FROM appointments WHERE doctor=? AND date=?", (doctor, date))
    booked = [row[0] for row in cursor.fetchall()]

    available = [slot for slot in all_slots if slot not in booked]

    return {
        "doctor": doctor,
        "date": date,
        "available_slots": available
    }

@app.post("/book")
async def book_appointment(data: BookingRequest):
    try:
        # Tekshirish
        cursor.execute("SELECT id FROM appointments WHERE doctor=? AND date=? AND time=?", 
                      (data.doctor, data.date, data.time))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Bu vaqt band")

        # Saqlash
        cursor.execute("""
            INSERT INTO appointments (user_id, name, phone, doctor, date, time, issue)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (data.user_id, data.name, data.phone, data.doctor, data.date, data.time, data.issue))
        conn.commit()

        # Admin ga xabar
        report = f"""
🎯 YANGI NAVBAT!

👤 Bemor: {data.name}
📞 Telefon: {data.phone}
👨‍⚕️ Shifokor: {data.doctor}
📅 Sana: {data.date}
🕒 Vaqt: {data.time}
🩺 Muammo: {data.issue}
"""
        try:
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                         json={"chat_id": ADMIN_ID, "text": report, "parse_mode": "HTML"})
        except:
            pass

        return {"success": True, "message": "Navbat muvaffaqiyatli band qilindi!"}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

print("✅ Server ishga tushdi!")