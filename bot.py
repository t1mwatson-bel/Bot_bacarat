import os
import sys
import time
import requests
from datetime import datetime
import pytz

# ФОРСИРУЕМ ВЫВОД В ЛОГИ
sys.stdout.flush()
print("=" * 50)
print("🚀 БОТ НАЧАЛ ЗАГРУЗКУ", datetime.now(), flush=True)
sys.stdout.flush()

# ПРОВЕРКА ПЕРЕМЕННЫХ
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')

print(f"BOT_TOKEN: {BOT_TOKEN[:5] if BOT_TOKEN else 'НЕ НАЙДЕН'}...", flush=True)
print(f"CHAT_ID: {CHAT_ID if CHAT_ID else 'НЕ НАЙДЕН'}", flush=True)
sys.stdout.flush()

if not BOT_TOKEN or not CHAT_ID:
    print("❌ КРИТИЧЕСКАЯ ОШИБКА: переменные не заданы!", flush=True)
    exit(1)

# ТЕСТОВОЕ СООБЩЕНИЕ
def send_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
        response = requests.post(url, json=payload, timeout=10)
        print(f"Telegram ответ: {response.status_code}", flush=True)
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Ошибка Telegram: {e}", flush=True)
        return False

# ОТПРАВЛЯЕМ ТЕСТ
send_telegram("🚀 БОТ ЗАПУЩЕН НА BOTHOST! ЛОГИ РАБОТАЮТ!")

# ОСНОВНОЙ ЦИКЛ (упрощенный для диагностики)
print("✅ БОТ ГОТОВ К РАБОТЕ", flush=True)
sys.stdout.flush()

while True:
    print(f"🔄 {datetime.now().strftime('%H:%M:%S')} - БОТ ЖИВ!", flush=True)
    time.sleep(30)