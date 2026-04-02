import os
import wave
import sqlite3
import threading
import asyncio 
import speech_recognition as sr
import re
import logging
from flask import Flask, request
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, FSInputFile, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta

# FPDF2 import
try:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
except ImportError:
    from fpdf2 import FPDF
    from fpdf.enums import XPos, YPos

# Loglarni sozlash (Xatoliklarni terminalda aniq ko'rish uchun)
logging.basicConfig(level=logging.INFO)

# --- SOZLAMALAR ---
API_TOKEN = '6083562451:AAGRCJLa9crAyc15MyeDLf7XDAXSVz1ruK0'
ADMIN_ID = 1891092592 
USD_RATE = 12900  
EUR_RATE = 14000

app = Flask(__name__)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- DATABASE ---
def get_db():
    return sqlite3.connect('smart_wallet.db', check_same_thread=False)

def init_db():
    with get_db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users 
                      (chat_id INTEGER PRIMARY KEY, name TEXT, age INTEGER, phone TEXT, balance REAL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS history 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, 
                       type TEXT, amount REAL, date TIMESTAMP, 
                       FOREIGN KEY(chat_id) REFERENCES users(chat_id))''')
init_db()

# --- LUG'AT VA YORDAMCHI FUNKSIYALAR ---
soz_raqam = {
    "nol": 0, "bir": 1, "ikki": 2, "uch": 3, "to'rt": 4, "besh": 5, "olti": 6, "yetti": 7, "sakkiz": 8, "to'qqiz": 9,
    "o'n": 10, "yigirma": 20, "o'ttiz": 30, "qirq": 40, "ellik": 50, "oltmish": 60, "yetmish": 70, "sakson": 80, "to'qson": 90,
    "yuz": 100, "ming": 1000, "million": 1000000, "miliyon": 1000000
}

def is_valid_phone(phone):
    pattern = r'^(\+998|998|)\d{9}$'
    return bool(re.match(pattern, str(phone).replace(" ", "")))

def text_to_int(text):
    text = text.lower().replace("'", "").replace("-", " ").replace("`", "")
    words = text.split()
    total = 0
    current_segment = 0
    
    for w in words:
        val = 0
        if w.isdigit():
            val = int(w)
        elif w in soz_raqam:
            val = soz_raqam[w]
        else:
            continue
            
        if val == 1000 or val == 1000000:
            if current_segment == 0: current_segment = 1
            total += current_segment * val
            current_segment = 0
        else:
            current_segment += val
            
    return total + current_segment

def convert_to_som(text):
    text = text.lower().replace("'", "").replace("`", "").strip()
    multiplier = 1
    if any(x in text for x in ["$", "dollar", "usd"]): multiplier = USD_RATE
    elif any(x in text for x in ["euro", "eur", "evro"]): multiplier = EUR_RATE
    
    if any(x in text for x in ["ming", "million", "miliyon", "yuz", "o'n", "yigirma"]):
        return text_to_int(text) * multiplier
    
    try:
        numbers = re.findall(r"\d+\.?\d*", text.replace(" ", ""))
        if numbers:
            return float(numbers[0]) * multiplier
    except:
        pass
    return 0

# --- KLAVIATURALAR ---
def main_kb(user_id):
    kb = [[KeyboardButton(text="📊 Statistika"), KeyboardButton(text="📄 PDF Hisobot")]]
    if user_id == ADMIN_ID:
        kb.append([KeyboardButton(text="👥 Foydalanuvchilar boshqaruvi")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def stats_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📅 Bugun"), KeyboardButton(text="📅 Shu hafta")],
        [KeyboardButton(text="📅 Shu oy"), KeyboardButton(text="📅 Shu yil")],
        [KeyboardButton(text="🔙 Orqaga")]
    ], resize_keyboard=True)

# --- PDF GENERATOR FUNKSIYASI ---
def generate_pdf(uid, history, user, period_name):
    pdf = FPDF()
    pdf.add_page()
    
    pdf.set_fill_color(33, 150, 243) 
    pdf.rect(0, 0, 210, 40, 'F')
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", 'B', 20)
    pdf.cell(0, 20, text=f"MOLIYAVIY HISOBOT: {period_name}", align='C', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", 'B', 12)
    pdf.ln(15)
    pdf.cell(0, 10, text=f"Foydalanuvchi: {user[0]}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 10, text=f"Sana: {datetime.now().strftime('%Y-%m-%d %H:%M')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(5)

    pdf.set_fill_color(200, 200, 200)
    pdf.set_font("Helvetica", 'B', 11)
    pdf.cell(45, 12, text="Sana", border=1, fill=True)
    pdf.cell(35, 12, text="Turi", border=1, fill=True)
    pdf.cell(55, 12, text="Miqdor (so'm)", border=1, fill=True, align='C', new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("Helvetica", size=10)
    for idx, h in enumerate(history):
        pdf.set_fill_color(245, 245, 245) if idx % 2 == 0 else pdf.set_fill_color(255, 255, 255)
        pdf.cell(45, 10, text=str(h[2])[:16], border=1, fill=True)
        pdf.set_text_color(0, 128, 0) if h[0] == 'kirim' else pdf.set_text_color(200, 0, 0)
        pdf.cell(35, 10, text=h[0].upper(), border=1, fill=True)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(55, 10, text=f"{h[1]:,.0f}", border=1, fill=True, align='R', new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(10)
    pdf.set_font("Helvetica", 'B', 14)
    pdf.set_fill_color(33, 150, 243); pdf.set_text_color(255, 255, 255)
    pdf.cell(80, 15, text="YAKUNIY BALANS:", border=1, fill=True, align='R')
    pdf.cell(55, 15, text=f"{user[1]:,.0f} so'm", border=1, fill=True, align='C')

    path = f"report_{uid}_{period_name}.pdf"
    pdf.output(path)
    return path

# --- REGISTRATSIYA ---
class Reg(StatesGroup):
    name, age, phone, balance = State(), State(), State(), State()

@dp.message(Command("start"))
async def start(m: types.Message, state: FSMContext):
    with get_db() as conn:
        user = conn.execute("SELECT name FROM users WHERE chat_id=?", (m.from_user.id,)).fetchone()
    if user:
        await m.answer(f"Xush kelibsiz, {user[0]}!", reply_markup=main_kb(m.from_user.id))
    else:
        await m.answer("Ismingizni kiriting:")
        await state.set_state(Reg.name)

@dp.message(Reg.name)
async def reg_n(m: types.Message, state: FSMContext):
    await state.update_data(n=m.text); await m.answer("Yoshingiz:"); await state.set_state(Reg.age)

@dp.message(Reg.age)
async def reg_a(m: types.Message, state: FSMContext):
    await state.update_data(a=m.text); await m.answer("Raqamingizni yuboring:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]], resize_keyboard=True))
    await state.set_state(Reg.phone)

@dp.message(Reg.phone, F.contact | F.text)
async def reg_p(m: types.Message, state: FSMContext):
    p = m.contact.phone_number if m.contact else m.text
    if not is_valid_phone(p): return await m.answer("Xato raqam!")
    await state.update_data(p=p); await m.answer("Boshlang'ich balans:", reply_markup=ReplyKeyboardRemove()); await state.set_state(Reg.balance)

@dp.message(Reg.balance)
async def reg_f(m: types.Message, state: FSMContext):
    val = convert_to_som(m.text)
    if val == 0:
        try: val = float(m.text.replace(" ", ""))
        except: val = 0
    d = await state.get_data()
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO users VALUES (?,?,?,?,?)", (m.from_user.id, d['n'], d['a'], d['p'], val))
    await m.answer("Tayyor!", reply_markup=main_kb(m.from_user.id)); await state.clear()

# --- STATISTIKA ---
@dp.message(F.text == "📊 Statistika")
async def stats_menu(m: types.Message):
    await m.answer("Davrni tanlang:", reply_markup=stats_kb())

@dp.message(F.text == "🔙 Orqaga")
async def back_main(m: types.Message):
    await m.answer("Asosiy menyu", reply_markup=main_kb(m.from_user.id))

@dp.message(F.text.in_(["📅 Bugun", "📅 Shu hafta", "📅 Shu oy", "📅 Shu yil"]))
async def show_stats(m: types.Message):
    uid = m.from_user.id
    period_name = m.text
    days = {"📅 Bugun": 1, "📅 Shu hafta": 7, "📅 Shu oy": 30, "📅 Shu yil": 365}[period_name]
    limit = datetime.now() - timedelta(days=days)
    
    with get_db() as conn:
        kirim = conn.execute("SELECT SUM(amount) FROM history WHERE chat_id=? AND type='kirim' AND date > ?", (uid, limit)).fetchone()[0] or 0
        chiqim = conn.execute("SELECT SUM(amount) FROM history WHERE chat_id=? AND type='chiqim' AND date > ?", (uid, limit)).fetchone()[0] or 0
        user = conn.execute("SELECT name, balance FROM users WHERE chat_id=?", (uid,)).fetchone()
        history = conn.execute("SELECT type, amount, date FROM history WHERE chat_id=? AND date > ? ORDER BY date DESC", (uid, limit)).fetchall()

    if not user: return
    msg = (f"📈 **{period_name} uchun tahlil:**\n━━━━━━━━━━━━━━\n✅ Kirim: +{kirim:,.0f} so'm\n❌ Chiqim: -{chiqim:,.0f} so'm\n━━━━━━━━━━━━━━\n💳 **Balans: {user[1]:,.0f} so'm**")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📥 PDF variantni yuklash", callback_data=f"pdf_{days}")]])
    await m.answer(msg, reply_markup=kb)

@dp.callback_query(F.data.startswith("pdf_"))
async def send_period_pdf(call: types.CallbackQuery):
    days = int(call.data.split("_")[1])
    uid = call.from_user.id
    limit = datetime.now() - timedelta(days=days)
    period_label = {1: "Bugun", 7: "Hafta", 30: "Oy", 365: "Yil"}[days]
    with get_db() as conn:
        user = conn.execute("SELECT name, balance FROM users WHERE chat_id=?", (uid,)).fetchone()
        history = conn.execute("SELECT type, amount, date FROM history WHERE chat_id=? AND date > ? ORDER BY date DESC", (uid, limit)).fetchall()
    path = generate_pdf(uid, history, user, period_label)
    await call.message.answer_document(FSInputFile(path), caption=f"{period_label} hisoboti")
    if os.path.exists(path): os.remove(path)
    await call.answer()

@dp.message(F.text == "📄 PDF Hisobot")
async def full_pdf_report(m: types.Message):
    uid = m.from_user.id
    with get_db() as conn:
        user = conn.execute("SELECT name, balance FROM users WHERE chat_id=?", (uid,)).fetchone()
        history = conn.execute("SELECT type, amount, date FROM history WHERE chat_id=? ORDER BY date DESC", (uid,)).fetchall()
    path = generate_pdf(uid, history, user, "UMUMIY")
    await m.answer_document(FSInputFile(path), caption="Sizning barcha amallaringiz hisoboti."); 
    if os.path.exists(path): os.remove(path)

# --- ADMIN PANEL ---
@dp.message(F.text == "👥 Foydalanuvchilar boshqaruvi")
async def admin_users(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    with get_db() as conn:
        users = conn.execute("SELECT chat_id, name FROM users").fetchall()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"👤 {u[1]}", callback_data=f"view_{u[0]}")] for u in users])
    await m.answer("Foydalanuvchini tanlang:", reply_markup=kb)

@dp.callback_query(F.data.startswith("view_"))
async def view_user_history(call: types.CallbackQuery):
    target_id = int(call.data.split("_")[1])
    with get_db() as conn:
        u = conn.execute("SELECT name, balance FROM users WHERE chat_id=?", (target_id,)).fetchone()
        h = conn.execute("SELECT type, amount, date FROM history WHERE chat_id=? ORDER BY date DESC LIMIT 5", (target_id,)).fetchall()
    res = f"👤 {u[0]} | 💰 {u[1]:,.0f} so'm\n\nOxirgi 5 amal:\n"
    for i in h: res += f"{'🟢' if i[0]=='kirim' else '🔴'} {i[1]:,.0f} | {str(i[2])[5:16]}\n"
    await call.message.answer(res); await call.answer()

# --- FLASK (ESP32 INTEGRATSIYA) ---
@app.route('/upload', methods=['POST'])
def upload():
    uid = request.args.get('uid')
    status = request.args.get('status')
    if not uid: return "UID missing", 400
    
    # PermissionError oldini olish uchun har bir so'rovga unikal fayl nomi
    temp_voice = f"v_{uid}_{datetime.now().strftime('%H%M%S')}.wav"
    
    try:
        with wave.open(temp_voice, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(request.data)
        
        r = sr.Recognizer()
        with sr.AudioFile(temp_voice) as source:
            audio = r.record(source)
        
        # Google recognition (Fayl ushbu blokdan keyin yopiladi)
        text = r.recognize_google(audio, language='uz-UZ')
        amt = convert_to_som(text)
        
        if amt > 0:
            with get_db() as conn:
                u = conn.execute("SELECT name, balance FROM users WHERE chat_id=?", (uid,)).fetchone()
                if not u: return "User not found", 404
                new_bal = u[1] + amt if status == 'kirim' else u[1] - amt
                conn.execute("UPDATE users SET balance=? WHERE chat_id=?", (new_bal, uid))
                conn.execute("INSERT INTO history (chat_id, type, amount, date) VALUES (?,?,?,?)", 
                             (uid, status, amt, datetime.now()))
                conn.commit()
                
                # Asinxron xabar yuborish (Asyncio Loop xavfsizligi bilan)
                asyncio.run_coroutine_threadsafe(
                    bot.send_message(uid, f"🎙 {text}\n{'✅' if status=='kirim' else '❌'} {amt:,.0f} so'm\n💰 Balans: {new_bal:,.0f} so'm"),
                    loop
                )
                return f"{u[0]}|{amt:,.0f}|{new_bal:,.0f}", 200
        return "Summa aniqlanmadi", 400
    except Exception as e:
        logging.error(f"Flask Error: {e}")
        return str(e), 500
    finally:
        # Windowsda faylni o'chirishdan oldin uning yopilganiga amin bo'lish
        if os.path.exists(temp_voice):
            try:
                os.remove(temp_voice)
            except Exception as e:
                logging.warning(f"File remove error: {e}")

def start_flask():
    app.run(host='0.0.0.0', port=5000, threaded=True)

async def main():
    # Telegram bot pollingni boshlash
    await dp.start_polling(bot, skip_updates=True)

if __name__ == '__main__':
    # Global loopni yaratish
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Flaskni alohida threadda boshlash
    threading.Thread(target=start_flask, daemon=True).start()
    
    # Asosiy bot pollingni loop ichida yuritish
    try:
        loop.run_until_complete(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Dastur to'xtatildi")
