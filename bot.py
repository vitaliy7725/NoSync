import telebot
from telebot import types
import random
import string
import json
import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

# ================= НАСТРОЙКИ =================
BOT_TOKEN = '8660429035:AAEgkmB_oXzrZYz_JxI46sugIOEQJcAMrBs' 
ADMIN_ID = 8378052126
# ============================================

bot = telebot.TeleBot(BOT_TOKEN)
db_lock = threading.Lock()

def get_db():
    conn = sqlite3.connect('nosync_users.db', check_same_thread=False)
    return conn

# Инициализация БД
with db_lock:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users
                      (tg_id TEXT PRIMARY KEY, username TEXT, tracks TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS auth_codes
                      (code TEXT PRIMARY KEY, tg_id TEXT, name TEXT)''')
    conn.commit()
    conn.close()

# --- HTTP СЕРВЕР ---
class ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True
    allow_reuse_port = True

class AuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # 1. Проверка кода для входа
        if self.path.startswith('/check_auth'):
            query = parse_qs(urlparse(self.path).query)
            code = query.get('code', [None])[0]
            
            if code:
                with db_lock:
                    conn = get_db()
                    cursor = conn.cursor()
                    cursor.execute("SELECT tg_id, name FROM auth_codes WHERE code = ?", (code,))
                    row = cursor.fetchone()
                    conn.close()
                
                if row:
                    response = json.dumps({"status": "success", "id": row[0], "name": row[1]})
                else:
                    response = json.dumps({"status": "not_found"})
            else:
                response = json.dumps({"status": "error"})
                
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(response.encode())

        # 2. Получение данных друга по ID
        elif self.path.startswith('/get_user'):
            query = parse_qs(urlparse(self.path).query)
            friend_id = query.get('id', [None])[0]
            
            if friend_id:
                with db_lock:
                    conn = get_db()
                    cursor = conn.cursor()
                    cursor.execute("SELECT username, tracks FROM users WHERE tg_id = ?", (friend_id,))
                    row = cursor.fetchone()
                    conn.close()
                
                if row:
                    tracks = json.loads(row[1]) if row[1] else []
                    response = json.dumps({"status": "success", "name": row[0], "tracks": tracks})
                else:
                    response = json.dumps({"status": "not_found"})
            else:
                response = json.dumps({"status": "error"})
                
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(response.encode())

        # 3. Получение прямой ссылки на аудиофайл
        elif self.path.startswith('/get_audio'):
            query = parse_qs(urlparse(self.path).query)
            file_id = query.get('file_id', [None])[0]
            
            if file_id:
                try:
                    file_info = bot.get_file(file_id)
                    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
                    response = json.dumps({"status": "success", "url": file_url})
                except Exception as e:
                    response = json.dumps({"status": "error", "message": str(e)})
            else:
                response = json.dumps({"status": "error"})
                
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(response.encode())
        else:
            self.send_response(404)
            self.end_headers()

def run_server():
    port = int(os.environ.get('PORT', 5000))
    server = ReusableHTTPServer(('0.0.0.0', port), AuthHandler)
    print(f"Веб-сервер для авторизации и друзей запущен на порту {port}...")
    server.serve_forever()

# --- ПРЕМИУМ КЛЮЧИ ---
KEYS_FILE = 'premium_keys.json'
if os.path.exists(KEYS_FILE):
    with open(KEYS_FILE, 'r') as f:
        valid_keys = json.load(f)
else:
    valid_keys = {}

pending_checks = {}

def generate_key():
    part1 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    part2 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"NOSYNC-{part1}-{part2}"

def save_keys():
    with open(KEYS_FILE, 'w') as f:
        json.dump(valid_keys, f)

# --- КОМАНДЫ БОТА ---
@bot.message_handler(commands=['start'])
def start(message):
    tg_id = str(message.from_user.id)
    username = message.from_user.first_name or "Пользователь"
    
    with db_lock:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO users (tg_id, username, tracks) VALUES (?, ?, ?)", (tg_id, username, '[]'))
            conn.commit()
        conn.close()
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_login = types.KeyboardButton('🔑 Войти в приложение')
    btn_pay = types.KeyboardButton('💳 Я оплатил (400₽)')
    btn_help = types.KeyboardButton('❓ Как это работает?')
    markup.add(btn_login, btn_pay, btn_help)
    
    bot.send_message(
        message.chat.id,
        f"Привет, {username}! Это бот для входа в **NoSync**.\n\n"
        "👇 Нажмите «Войти в приложение», чтобы авторизоваться.",
        parse_mode='Markdown',
        reply_markup=markup
    )

@bot.message_handler(func=lambda message: message.text == '🔑 Войти в приложение')
def ask_auth_code(message):
    bot.send_message(message.chat.id, "Введите код, который показан у вас в приложении NoSync на экране входа:")
    bot.register_next_step_handler(message, process_auth_code)

def process_auth_code(message):
    code = message.text.strip().upper()
    user_id = str(message.from_user.id)
    username = message.from_user.first_name or "Пользователь"
    
    try:
        with db_lock:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO auth_codes (code, tg_id, name) VALUES (?, ?, ?)", (code, user_id, username))
            conn.commit()
            conn.close()
            
        bot.send_message(
            message.chat.id,
            f"✅ Успешно! Код **{code}** привязан к вашему аккаунту.\n\n"
            f"Ваш Telegram ID: `{user_id}`\n\n"
            "Вернитесь в приложение и нажмите «Проверить».",
            parse_mode='Markdown'
        )
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

@bot.message_handler(content_types=['audio'])
def handle_audio(message):
    tg_id = str(message.from_user.id)
    file_id = message.audio.file_id
    title = message.audio.title or "Без названия"
    artist = message.audio.performer or "Неизвестен"
    duration = message.audio.duration or 0

    with db_lock:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT tracks FROM users WHERE tg_id = ?", (tg_id,))
        row = cursor.fetchone()
        
        if row:
            tracks = json.loads(row[0]) if row[0] else []
            tracks.append({
                "name": title,
                "artist": artist,
                "duration": duration,
                "file_id": file_id
            })
            cursor.execute("UPDATE users SET tracks = ? WHERE tg_id = ?", (json.dumps(tracks, ensure_ascii=False), tg_id))
            conn.commit()
        conn.close()

@bot.message_handler(commands=['clear_tracks'])
def clear_user_tracks(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        target_id = message.text.split()[1]
        with db_lock:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET tracks = '[]' WHERE tg_id = ?", (target_id,))
            conn.commit()
            conn.close()
        bot.send_message(ADMIN_ID, f"✅ Все треки пользователя {target_id} удалены.")
    except Exception:
        bot.send_message(ADMIN_ID, "Ошибка. Используйте: `/clear_tracks ID_пользователя`", parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '💳 Я оплатил (400₽)')
def ask_for_receipt(message):
    bot.send_message(message.chat.id, "Отправьте ваш чек (фото или PDF) одним сообщением.")
    bot.register_next_step_handler(message, process_receipt)

def process_receipt(message):
    if message.content_type in ['photo', 'document']:
        user_id = message.from_user.id
        username = message.from_user.username or "Без_юзернейма"
        pending_checks[user_id] = {"username": username, "chat_id": message.chat.id}
        
        markup = types.InlineKeyboardMarkup()
        btn_approve = types.InlineKeyboardButton("✅ Подтвердить оплату", callback_data=f"approve_{user_id}")
        btn_reject = types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{user_id}")
        markup.add(btn_approve, btn_reject)

        bot.send_message(ADMIN_ID, f"🔔 **Новый чек на проверку!**\nОт: @{username} (ID: {user_id})", parse_mode='Markdown', reply_markup=markup)
        bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
        bot.send_message(message.chat.id, "✅ Чек отправлен на проверку!")
    else:
        bot.send_message(message.chat.id, "⚠️ Отправьте фото или PDF-файл.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_') or call.data.startswith('reject_'))
def handle_admin_action(call):
    if call.from_user.id != ADMIN_ID: return
    action, user_id_str = call.data.split('_')
    user_id = int(user_id_str)

    if action == 'approve':
        new_key = generate_key()
        valid_keys[new_key] = {"used": False}
        save_keys()
        if user_id in pending_checks:
            bot.send_message(user_id, f"🎉 **Оплата подтверждена!**\n\nВаш ключ активации:\n`{new_key}`\n\nСкопируйте его в приложении.", parse_mode='Markdown')
            del pending_checks[user_id]
        bot.edit_message_text(f"✅ Ключ `{new_key}` выдан.", chat_id=ADMIN_ID, message_id=call.message.message_id, parse_mode='Markdown')
    else:
        if user_id in pending_checks:
            bot.send_message(user_id, "❌ Чек отклонен.")
            del pending_checks[user_id]
        bot.edit_message_text(f"❌ Чек отклонен.", chat_id=ADMIN_ID, message_id=call.message.message_id)

if __name__ == '__main__':
    threading.Thread(target=run_server, daemon=True).start()
    print("Бот NoSync запущен на сервере и работает 24/7...")
    bot.infinity_polling()