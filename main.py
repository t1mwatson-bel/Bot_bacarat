import oss
import requests
import json
import time
from datetime import datetime
import pytz

# =====================================================================
# ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ (берутся с хостинга)
# =====================================================================
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')

# Проверка что переменные заданы
if not BOT_TOKEN or not CHAT_ID:
    print("❌ Ошибка: BOT_TOKEN или CHAT_ID не заданы в переменных окружения!")
    exit(1)

MOSCOW_TZ = pytz.timezone('Europe/Moscow')

def send_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Ошибка отправки в Telegram: {e}")
        return False

# =====================================================================
# URL ДЛЯ ЗАПРОСОВ
# =====================================================================
URL = "https://1xlite-84484.pro/service-api/LiveFeed/Get1x2_VZip?sports=1&count=40&gr=415&mode=4&country=190&partner=7&getEmpty=true&virtualSports=true&noFilterBlockEvent=true"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru,en;q=0.9",
    "Content-Type": "application/json",
    "Referer": "https://1xlite-84484.pro/ru/live/football",
    "Cookie": "platform_type=desktop; auid=uaJbk2qDTUEWPz+AAzc0Ag==; lng=ru; cookies_agree_type=3; tzo=3; is12h=0; referral_values=%7B%22type%22%3A%22reflinkid%22%2C%22val%22%3A%22s_50970m_355c_%22%2C%22additional%22%3A%7B%22name_tag%22%3A%22tag%22%7D%7D; reflinkid=s_50970m_355c_; fatman_uuid=45f69ff0-ecb1-67d4-3ff2-3a45baafc739; che_g=777dc1b9-efbf-4728-947a-4a2992ef6da5; SESSION=240c24b0d757110703d84a2c059a9fc4; sh.session.id=684214c4-f09e-42da-9c1a-ea61b9aca91b; _ym_uid=1786989905737338437; _ym_d=1786989905; _ym_isad=2; _ga=GA1.1.547872848.1786989906; _ga_7JGWL9SV66=GS2.1.s1786989906$o1$g0$t1786989906$j60$l0$h408279378; _ym_visorc=b; window_width=1365"
}

def fetch_data():
    try:
        response = requests.get(URL, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("Value"):
                print(f"✅ Данные получены. Найдено объектов: {len(data['Value'])}")
                return data
            else:
                print("⚠️ API вернул пустой ответ.")
                return None
        print(f"❌ Ошибка HTTP: {response.status_code}")
        return None
    except Exception as e:
        print(f"❌ Ошибка запроса: {e}")
        return None

# =====================================================================
# ПАРСИНГ МАТЧЕЙ
# =====================================================================
def parse_matches(data):
    matches = []
    for item in data.get("Value", []):
        home = item.get("O1")
        away = item.get("O2")
        league = item.get("L", "Неизвестно")
        
        # Счет
        score_home = None
        score_away = None
        sc = item.get("SC", {})
        if sc:
            fs = sc.get("FS", {})
            if fs:
                score_home = fs.get("S1")
                score_away = fs.get("S2")

        # Коэффициенты
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
                "item": item  # сохраняем для статистики
            })
    return matches

# =====================================================================
# ПАРСИНГ СТАТИСТИКИ
# =====================================================================
def parse_statistics(item):
    stats_data = {
        "minute": None,
        "possession_home": None,
        "possession_away": None,
        "shots_home": None,
        "shots_away": None,
        "corners_home": None,
        "corners_away": None
    }
    
    sc = item.get("SC", {})
    
    # Время матча
    ts = sc.get("TS", 0)
    if ts and ts > 0:
        stats_data["minute"] = ts // 60
    
    # Статистика
    for stat in sc.get("ST", []):
        if stat.get("Key") == 0:
            for s in stat.get("Value", []):
                sid = s.get("ID")
                if sid == 29:  # Владение
                    stats_data["possession_home"] = s.get("S1")
                    stats_data["possession_away"] = s.get("S2")
                elif sid == 59:  # Удары в створ
                    stats_data["shots_home"] = s.get("S1")
                    stats_data["shots_away"] = s.get("S2")
                elif sid == 70:  # Угловые
                    stats_data["corners_home"] = s.get("S1")
                    stats_data["corners_away"] = s.get("S2")
    
    return stats_data

# =====================================================================
# ФИЛЬТРЫ
# =====================================================================
def should_send_signal(old_coeff, current_coeff, score_home, score_away, stats):
    # 1. Счет 0:0
    if score_home != 0 or score_away != 0:
        return False
    
    # 2. Не позднее 85-й минуты
    if stats.get("minute") and stats["minute"] > 85:
        return False
    
    # 3. Пороги
    DROP_THRESHOLD = 0.5
    MIN_COEFF = 1.5
    MIN_DROP_PERCENT = 15
    
    if old_coeff < MIN_COEFF:
        return False
    
    drop = old_coeff - current_coeff
    if drop < DROP_THRESHOLD:
        return False
    
    drop_percent = (drop / old_coeff) * 100
    if drop_percent < MIN_DROP_PERCENT:
        return False
    
    return True

# =====================================================================
# ОСНОВНОЙ ЦИКЛ
# =====================================================================
def main():
    print("📊 БОТ-МОНИТОРИНГ ПРОСАДОК (1XBET)")
    print("=" * 60)
    print(f"🤖 Бот запущен")
    print(f"📨 Отправка в чат: {CHAT_ID}")
    print("=" * 60)
    print("🔧 ФИЛЬТРЫ:")
    print("   ✅ Счет 0:0 (только без голов)")
    print("   ✅ Не позднее 85-й минуты")
    print("   ✅ Порог просадки: 0.5")
    print("   ✅ Мин. коэффициент: 1.5")
    print("   ✅ Мин. процент просадки: 15%")
    print("   ✅ Защита от дублей: 60 сек")
    print("=" * 60)

    last_data = {}
    last_signal_time = {}

    while True:
        try:
            print(f"\n🕐 {datetime.now(MOSCOW_TZ).strftime('%H:%M:%S')} - ПРОВЕРКА")

            data = fetch_data()
            if not data:
                time.sleep(30)
                continue

            matches = parse_matches(data)
            print(f"📊 Найдено матчей: {len(matches)}")

            for match in matches:
                mid = match["id"]
                
                score_h = match.get("score_home")
                score_a = match.get("score_away")
                
                stats = parse_statistics(match.get("item", {}))
                
                if score_h is None or score_a is None:
                    continue

                if mid not in last_data:
                    last_data[mid] = {
                        "p1": match["p1"],
                        "p2": match["p2"],
                        "home": match["home"],
                        "away": match["away"],
                        "league": match["league"]
                    }
                    continue

                old = last_data[mid]
                
                # Проверяем П1 (просадка на хозяев)
                if should_send_signal(old["p1"], match["p1"], score_h, score_a, stats):
                    signal_key = f"{mid}_p1"
                    if signal_key not in last_signal_time or (time.time() - last_signal_time[signal_key]) > 60:
                        
                        msg = f"📉 <b>ПРОСАДКА КОЭФФИЦИЕНТА</b>\n"
                        msg += f"🏆 {match['league']}\n"
                        msg += f"⚽ {match['home']} vs {match['away']}\n"
                        msg += f"📊 <b>ПРОСАДКА НА ХОЗЯЕВ</b>\n"
                        msg += f"💰 {old['p1']:.2f} → {match['p1']:.2f} (⬇️ {old['p1'] - match['p1']:.2f})\n"
                        msg += f"📊 Просадка: {((old['p1'] - match['p1']) / old['p1'] * 100):.1f}%\n"
                        msg += f"🎯 Счет: {score_h}:{score_a} (0:0 ✅)\n"
                        
                        if stats.get("minute"):
                            msg += f"⏱️ Минута: {stats['minute']}'\n"
                        
                        if stats.get("possession_home") is not None and stats.get("possession_away") is not None:
                            msg += f"📊 Владение: {stats['possession_home']}% vs {stats['possession_away']}%\n"
                        if stats.get("shots_home") is not None and stats.get("shots_away") is not None:
                            msg += f"🎯 Удары в створ: {stats['shots_home']} vs {stats['shots_away']}\n"
                        if stats.get("corners_home") is not None and stats.get("corners_away") is not None:
                            msg += f"🚩 Угловые: {stats['corners_home']} vs {stats['corners_away']}\n"
                        
                        msg += f"\n🔥 <b>СТАВКА:</b> ИТБ хозяев ({match['home']})"
                        
                        if send_telegram(msg):
                            last_signal_time[signal_key] = time.time()
                            print(f"📤 Сигнал: {match['home']} — П1 (0:0)")

                # Проверяем П2 (просадка на гостей)
                if should_send_signal(old["p2"], match["p2"], score_h, score_a, stats):
                    signal_key = f"{mid}_p2"
                    if signal_key not in last_signal_time or (time.time() - last_signal_time[signal_key]) > 60:
                        
                        msg = f"📉 <b>ПРОСАДКА КОЭФФИЦИЕНТА</b>\n"
                        msg += f"🏆 {match['league']}\n"
                        msg += f"⚽ {match['home']} vs {match['away']}\n"
                        msg += f"📊 <b>ПРОСАДКА НА ГОСТЕЙ</b>\n"
                        msg += f"💰 {old['p2']:.2f} → {match['p2']:.2f} (⬇️ {old['p2'] - match['p2']:.2f})\n"
                        msg += f"📊 Просадка: {((old['p2'] - match['p2']) / old['p2'] * 100):.1f}%\n"
                        msg += f"🎯 Счет: {score_h}:{score_a} (0:0 ✅)\n"
                        
                        if stats.get("minute"):
                            msg += f"⏱️ Минута: {stats['minute']}'\n"
                        
                        if stats.get("possession_home") is not None and stats.get("possession_away") is not None:
                            msg += f"📊 Владение: {stats['possession_home']}% vs {stats['possession_away']}%\n"
                        if stats.get("shots_home") is not None and stats.get("shots_away") is not None:
                            msg += f"🎯 Удары в створ: {stats['shots_home']} vs {stats['shots_away']}\n"
                        if stats.get("corners_home") is not None and stats.get("corners_away") is not None:
                            msg += f"🚩 Угловые: {stats['corners_home']} vs {stats['corners_away']}\n"
                        
                        msg += f"\n🔥 <b>СТАВКА:</b> ИТБ гостей ({match['away']})"
                        
                        if send_telegram(msg):
                            last_signal_time[signal_key] = time.time()
                            print(f"📤 Сигнал: {match['away']} — П2 (0:0)")

                last_data[mid]["p1"] = match["p1"]
                last_data[mid]["p2"] = match["p2"]

            time.sleep(30)

        except Exception as e:
            print(f"❌ Ошибка в основном цикле: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()