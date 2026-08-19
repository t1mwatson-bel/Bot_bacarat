import os
import sys
import time
import requests
from datetime import datetime
import pytz

# =====================================================================
# ПРИНУДИТЕЛЬНЫЙ ВЫВОД ЛОГОВ
# =====================================================================
sys.stdout.flush()
print("=" * 60, flush=True)
print("📊 БОТ-МОНИТОРИНГ ПРОСАДОК (1XBET) - ЗАПУСК", flush=True)
print("=" * 60, flush=True)

# =====================================================================
# ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
# =====================================================================
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')

print(f"✅ BOT_TOKEN: {BOT_TOKEN[:5] if BOT_TOKEN else 'НЕ НАЙДЕН'}...", flush=True)
print(f"✅ CHAT_ID: {CHAT_ID if CHAT_ID else 'НЕ НАЙДЕН'}", flush=True)

if not BOT_TOKEN or not CHAT_ID:
    print("❌ КРИТИЧЕСКАЯ ОШИБКА: переменные не заданы!", flush=True)
    exit(1)

MOSCOW_TZ = pytz.timezone('Europe/Moscow')

def send_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}", flush=True)
        return False

URL = "https://1xlite-84484.pro/service-api/LiveFeed/Get1x2_VZip?sports=1&count=40&gr=415&mode=4&country=190&partner=7&getEmpty=true&virtualSports=true&noFilterBlockEvent=true"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru,en;q=0.9",
    "Content-Type": "application/json",
    "Referer": "https://1xlite-84484.pro/ru/live/football",
    "Cookie": "platform_type=desktop; auid=uaJbk2qDTUEWPz+AAzc0Ag==; lng=ru; cookies_agree_type=3; tzo=3; is12h=0; referral_values=%7B%22type%22%3A%22reflinkid%22%2C%22val%22%3A%22s_50970m_355c_%22%2C%22additional%22%3A%7B%22name_tag%22%3A%22tag%22%7D%7D; reflinkid=s_50970m_355c_; fatman_uuid=45f69ff0-ecb1-67d4-3ff2-3a45baafc739; che_g=777dc1b9-efbf-4728-947a-4a2992ef6da5; SESSION=240c24b0d757110703d84a2c059a9fc4; sh.session.id=684214c4-f09e-42da-9c1a-ea61b9aca91b; _ym_uid=1786989905737338437; _ym_d=1786989905; _ym_isad=2; _ga=GA1.1.547872848.1786989906; _ga_7JGWL9SV66=GS2.1.s1786989906$o1$g0$t1786989906$j60$l0$h408279378; _ym_visorc=b; window_width=1365"
}

# =====================================================================
# ЧЕРНЫЙ СПИСОК (КИБЕРСПОРТ + ШУМ)
# =====================================================================
BLACKLIST_LEAGUES = [
    "Short Football", "ShortFootball", "Short Football D1",
    "Short Football 4x4", "Short Football 5x5", "Short Football 3x3", "Short Football 2x2",
    "4x4", "5x5", "Division 4x4", "Division 5x5",
    "BudnesLiga LFL 5x5", "BundesLiga LFL 5x5",
    "BudnesLiga", "BundesLiga", "LFL",
    "MLS+",
    "Student League", "Student League 2",
    "Subsoccer", "sub",
    "люб",
    "FIFA", "PES", "Кибер", "Esports", "Cyber", "eSports",
    "Mortal Kombat", "Tekken", "Counter Strike", "Dota",
    "World of tanks", "Rocket League", "StreetFighter", "Call of Duty",
    "Dead Or Alive", "WWE", "King of Fighters", "Overwatch", "Looney Tunes",
    "Hellish Quart", "Need for Speed", "Fatal Fury", "Roller Champions",
    "Guilty Gear", "GigaBash", "Angry Birds", "SEGA", "StarCraft", "Injustice",
    "Flatout", "LaserLeague", "CrossOut", "Pixel Cup", "Killer Instinct",
    "Table Football", "Blade and Soul", "Assault Squad", "Cut The Rope",
    "Subway Surfers", "Sonic", "Crash", "Sekiro", "TABS", "Rumble Stars",
    "Robot Champions", "Boxing Champs", "Mega Baseball", "Raid Shadow Legends",
    "Power of Power", "Mutant League", "World of Warcraft", "Cuphead",
    "Club Friendlies", "Товарищеские"
]

def fetch_data():
    try:
        response = requests.get(URL, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("Value"):
                print(f"✅ Данные получены. Найдено объектов: {len(data['Value'])}", flush=True)
                return data
            else:
                print("⚠️ API вернул пустой ответ.", flush=True)
                return None
        print(f"❌ Ошибка HTTP: {response.status_code}", flush=True)
        return None
    except Exception as e:
        print(f"❌ Ошибка запроса: {e}", flush=True)
        return None

def parse_matches(data):
    matches = []
    for item in data.get("Value", []):
        home = item.get("O1")
        away = item.get("O2")
        league = item.get("L", "Неизвестно")

        league_lower = league.lower()
        if any(bad_league.lower() in league_lower for bad_league in BLACKLIST_LEAGUES):
            print(f"⏭️ Пропущена лига (черный список): {league}", flush=True)
            continue

        score_home = None
        score_away = None
        sc = item.get("SC", {})
        if sc:
            fs = sc.get("FS", {})
            if fs:
                score_home = fs.get("S1")
                score_away = fs.get("S2")

        coeffs = {}
        for e in item.get("E", []):
            t = e.get("T")
            c = e.get("C")
            if t in [1, 2, 3]:
                coeffs[t] = c

        if home and away and coeffs.get(1) and coeffs.get(2):
            matches.append({
                "id": item.get("I"),
                "home": home,
                "away": away,
                "league": league,
                "score_home": score_home,
                "score_away": score_away,
                "p1": coeffs.get(1),
                "p2": coeffs.get(2),
                "draw": coeffs.get(3),
                "item": item
            })
    return matches

def parse_statistics(item):
    stats