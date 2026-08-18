import os
import sys
import time
import requests
import json
from datetime import datetime, timedelta
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

# =====================================================================
# ОТПРАВКА И РЕДАКТИРОВАНИЕ В TELEGRAM
# =====================================================================
def send_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return response.json().get("result", {}).get("message_id")
        return None
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}", flush=True)
        return None

def edit_telegram(message_id, text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
        payload = {
            "chat_id": CHAT_ID,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Ошибка редактирования: {e}", flush=True)
        return False

# =====================================================================
# API 1XBET
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

# =====================================================================
# ЧЕРНЫЙ СПИСОК ЛИГ (ШУМ И КИБЕРСПОРТ)
# =====================================================================
BLACKLIST_LEAGUES = [
    # ===== КОРОТКИЙ ФУТБОЛ =====
    "Short Football", "ShortFootball", "Short Football D1",
    "Short Football 4x4", "Short Football 5x5", "Short Football 3x3", "Short Football 2x2",
    "4x4", "5x5", "Division 4x4", "Division 5x5",
    
    # ===== LFL / 5x5 =====
    "BudnesLiga LFL 5x5", "BundesLiga LFL 5x5",
    "BudnesLiga", "BundesLiga", "LFL",
    
    # ===== MLS+ =====
    "MLS+",
    
    # ===== СТУДЕНЧЕСКИЕ =====
    "Student League", "Student League 2",
    
    # ===== SUBSOCCER (НОВЫЙ!) =====
    "Subsoccer",
    "sub",  # блокирует все (sub) в названиях
    
    # ===== ЛЮБИТЕЛЬСКИЕ =====
    "люб",
    
    # ===== КИБЕРСПОРТ =====
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
    
    # ===== ТОВАРИЩЕСКИЕ =====
    "Club Friendlies", "Товарищеские"
]

# =====================================================================
# ЗАПРОС ДАННЫХ
# =====================================================================
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

# =====================================================================
# ПАРСИНГ МАТЧЕЙ
# =====================================================================
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

    ts = sc.get("TS", 0)
    if ts and ts > 0:
        stats_data["minute"] = ts // 60

    for stat in sc.get("ST", []):
        if stat.get("Key") == 0:
            for s in stat.get("Value", []):
                sid = s.get("ID")
                if sid == 29:
                    stats_data["possession_home"] = s.get("S1")
                    stats_data["possession_away"] = s.get("S2")
                elif sid == 59:
                    stats_data["shots_home"] = s.get("S1")
                    stats_data["shots_away"] = s.get("S2")
                elif sid == 70:
                    stats_data["corners_home"] = s.get("S1")
                    stats_data["corners_away"] = s.get("S2")

    return stats_data

# =====================================================================
# ФИЛЬТРЫ
# =====================================================================
def should_send_signal(old_coeff, current_coeff, score_home, score_away, stats):
    if score_home is not None and score_away is not None:
        if score_home > 4 or score_away > 4:
            return False

    if stats.get("minute") and stats["minute"] > 85:
        return False

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
# ИСТОРИЯ ДЛЯ ПРОВЕРКИ РЕЗУЛЬТАТОВ
# =====================================================================
history_file = "history.json"

def load_history():
    if os.path.exists(history_file):
        with open(history_file, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except:
                return []
    return []

def save_history(history):
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

def add_to_history(signal_data):
    history = load_history()
    history.append(signal_data)
    save_history(history)

def check_match_result(match_id):
    try:
        response = requests.get(URL, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            for item in data.get("Value", []):
                if str(item.get("I")) == str(match_id):
                    sc = item.get("SC", {})
                    fs = sc.get("FS", {})
                    if fs:
                        return {
                            "home": fs.get("S1", 0),
                            "away": fs.get("S2", 0),
                            "status": "finished"
                        }
                    else:
                        return {"status": "not_finished"}
            return {"status": "not_found"}
    except Exception as e:
        print(f"❌ Ошибка проверки результата: {e}", flush=True)
    return {"status": "error"}

def edit_result_report(entry):
    """Редактирует исходное сообщение, дописывая результат (голы ПОСЛЕ СИГНАЛА)"""
    result = entry.get("result")
    if not result:
        return

    # Счет на момент сигнала
    try:
        score_h_signal, score_a_signal = map(int, entry['score'].split(':'))
    except:
        score_h_signal, score_a_signal = 0, 0

    # Финальный счет
    score_h_final = result.get("home", 0)
    score_a_final = result.get("away", 0)

    # Считаем голы ПОСЛЕ СИГНАЛА
    home_goals_after = score_h_final - score_h_signal
    away_goals_after = score_a_final - score_a_signal

    # Формируем обновленный текст
    msg = f"📉 <b>ПРОСАДКА КОЭФФИЦИЕНТА</b>\n"
    msg += f"🏆 {entry['league']}\n"
    msg += f"⚽ {entry['home']} vs {entry['away']}\n"
    msg += f"📊 <b>{entry['bet']}</b>\n"
    msg += f"💰 {entry['old_coeff']:.2f} → {entry['new_coeff']:.2f} (⬇️ {entry['drop']:.2f})\n"
    msg += f"📊 Просадка: {entry['drop_percent']}%\n"
    msg += f"🎯 Счет на момент сигнала: {entry['score']}\n"
    if entry.get('minute'):
        msg += f"⏱️ Минута: {entry['minute']}'\n"
    if entry.get('possession'):
        msg += f"📊 Владение: {entry['possession']}\n"
    if entry.get('shots'):
        msg += f"🎯 Удары в створ: {entry['shots']}\n"
    if entry.get('corners'):
        msg += f"🚩 Угловые: {entry['corners']}\n"
    msg += f"\n🔥 <b>СТАВКА:</b> {entry['bet']}\n"

    # ДОПИСЫВАЕМ РЕЗУЛЬТАТ
    msg += f"\n📊 <b>ИТОГОВЫЙ СЧЕТ:</b> {score_h_final}:{score_a_final}\n"
    
    if "хозяев" in entry['bet']:
        if home_goals_after > 0:
            msg += f"✅ <b>РЕЗУЛЬТАТ: ЗАШЛО!</b> 🎉 (голов после сигнала: {home_goals_after})\n"
        else:
            msg += f"❌ <b>РЕЗУЛЬТАТ: НЕ ЗАШЛО</b> (голов после сигнала: 0)\n"
    elif "гостей" in entry['bet']:
        if away_goals_after > 0:
            msg += f"✅ <b>РЕЗУЛЬТАТ: ЗАШЛО!</b> 🎉 (голов после сигнала: {away_goals_after})\n"
        else:
            msg += f"❌ <b>РЕЗУЛЬТАТ: НЕ ЗАШЛО</b> (голов после сигнала: 0)\n"
    else:
        msg += f"⚠️ Неизвестный тип ставки\n"

    # Редактируем сообщение
    edit_telegram(entry["message_id"], msg)

# =====================================================================
# ПРОВЕРКА РЕЗУЛЬТАТОВ (каждые 5 минут)
# =====================================================================
def check_results():
    history = load_history()
    updated = False

    for entry in history:
        if entry.get("result") is not None:
            continue

        result = check_match_result(entry["match_id"])
        if result and result.get("status") == "finished":
            entry["result"] = result
            updated = True
            edit_result_report(entry)
        elif result and result.get("status") == "not_found":
            signal_time = datetime.fromisoformat(entry["signal_time"])
            if datetime.now() > signal_time + timedelta(minutes=10):
                entry["result"] = {"status": "not_found"}
                updated = True
                edit_result_report(entry)

    if updated:
        save_history(history)

# =====================================================================
# ОСНОВНОЙ ЦИКЛ
# =====================================================================
def main():
    print("✅ БОТ ГОТОВ К РАБОТЕ (ЧЕРНЫЙ СПИСОК + РЕДАКТИРОВАНИЕ + ПРОВЕРКА ГОЛОВ ПОСЛЕ СИГНАЛА)", flush=True)
    send_telegram("🚀 Бот запущен! Результаты дописываются в исходные сообщения. Проверяются голы ПОСЛЕ СИГНАЛА.")

    last_data = {}
    last_signal_time = {}

    while True:
        try:
            print(f"\n🕐 {datetime.now(MOSCOW_TZ).strftime('%H:%M:%S')} - ПРОВЕРКА", flush=True)

            data = fetch_data()
            if not data:
                time.sleep(30)
                continue

            matches = parse_matches(data)
            print(f"📊 Найдено матчей: {len(matches)}", flush=True)

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

                # ===== ПРОСАДКА НА ХОЗЯЕВ =====
                if should_send_signal(old["p1"], match["p1"], score_h, score_a, stats):
                    signal_key = f"{mid}_p1"
                    if signal_key not in last_signal_time or (time.time() - last_signal_time[signal_key]) > 60:
                        msg = f"📉 <b>ПРОСАДКА КОЭФФИЦИЕНТА</b>\n"
                        msg += f"🏆 {match['league']}\n"
                        msg += f"⚽ {match['home']} vs {match['away']}\n"
                        msg += f"📊 <b>ПРОСАДКА НА ХОЗЯЕВ</b>\n"
                        msg += f"💰 {old['p1']:.2f} → {match['p1']:.2f} (⬇️ {old['p1'] - match['p1']:.2f})\n"
                        msg += f"📊 Просадка: {((old['p1'] - match['p1']) / old['p1'] * 100):.1f}%\n"
                        msg += f"🎯 Текущий счет: {score_h}:{score_a}\n"
                        if stats.get("minute"):
                            msg += f"⏱️ Минута: {stats['minute']}'\n"
                        if stats.get("possession_home") is not None and stats.get("possession_away") is not None:
                            msg += f"📊 Владение: {stats['possession_home']}% vs {stats['possession_away']}%\n"
                        if stats.get("shots_home") is not None and stats.get("shots_away") is not None:
                            msg += f"🎯 Удары в створ: {stats['shots_home']} vs {stats['shots_away']}\n"
                        if stats.get("corners_home") is not None and stats.get("corners_away") is not None:
                            msg += f"🚩 Угловые: {stats['corners_home']} vs {stats['corners_away']}\n"
                        msg += f"\n🔥 <b>СТАВКА:</b> ИТБ хозяев ({match['home']})"

                        message_id = send_telegram(msg)
                        if message_id:
                            last_signal_time[signal_key] = time.time()
                            print(f"📤 Сигнал: {match['home']} — П1 (счет {score_h}:{score_a})", flush=True)

                            add_to_history({
                                "match_id": mid,
                                "league": match['league'],
                                "home": match['home'],
                                "away": match['away'],
                                "bet": f"ИТБ хозяев ({match['home']})",
                                "old_coeff": old['p1'],
                                "new_coeff": match['p1'],
                                "drop": old['p1'] - match['p1'],
                                "drop_percent": round(((old['p1'] - match['p1']) / old['p1'] * 100), 1),
                                "score": f"{score_h}:{score_a}",
                                "minute": stats.get("minute"),
                                "possession": f"{stats.get('possession_home')}% vs {stats.get('possession_away')}%" if stats.get('possession_home') else None,
                                "shots": f"{stats.get('shots_home')} vs {stats.get('shots_away')}" if stats.get('shots_home') else None,
                                "corners": f"{stats.get('corners_home')} vs {stats.get('corners_away')}" if stats.get('corners_home') else None,
                                "message_id": message_id,
                                "signal_time": datetime.now().isoformat(),
                                "result": None
                            })

                # ===== ПРОСАДКА НА ГОСТЕЙ =====
                if should_send_signal(old["p2"], match["p2"], score_h, score_a, stats):
                    signal_key = f"{mid}_p2"
                    if signal_key not in last_signal_time or (time.time() - last_signal_time[signal_key]) > 60:
                        msg = f"📉 <b>ПРОСАДКА КОЭФФИЦИЕНТА</b>\n"
                        msg += f"🏆 {match['league']}\n"
                        msg += f"⚽ {match['home']} vs {match['away']}\n"
                        msg += f"📊 <b>ПРОСАДКА НА ГОСТЕЙ</b>\n"
                        msg += f"💰 {old['p2']:.2f} → {match['p2']:.2f} (⬇️ {old['p2'] - match['p2']:.2f})\n"
                        msg += f"📊 Просадка: {((old['p2'] - match['p2']) / old['p2'] * 100):.1f}%\n"
                        msg += f"🎯 Текущий счет: {score_h}:{score_a}\n"
                        if stats.get("minute"):
                            msg += f"⏱️ Минута: {stats['minute']}'\n"
                        if stats.get("possession_home") is not None and stats.get("possession_away") is not None:
                            msg += f"📊 Владение: {stats['possession_home']}% vs {stats['possession_away']}%\n"
                        if stats.get("shots_home") is not None and stats.get("shots_away") is not None:
                            msg += f"🎯 Удары в створ: {stats['shots_home']} vs {stats['shots_away']}\n"
                        if stats.get("corners_home") is not None and stats.get("corners_away") is not None:
                            msg += f"🚩 Угловые: {stats['corners_home']} vs {stats['corners_away']}\n"
                        msg += f"\n🔥 <b>СТАВКА:</b> ИТБ гостей ({match['away']})"

                        message_id = send_telegram(msg)
                        if message_id:
                            last_signal_time[signal_key] = time.time()
                            print(f"📤 Сигнал: {match['away']} — П2 (счет {score_h}:{score_a})", flush=True)

                            add_to_history({
                                "match_id": mid,
                                "league": match['league'],
                                "home": match['home'],
                                "away": match['away'],
                                "bet": f"ИТБ гостей ({match['away']})",
                                "old_coeff": old['p2'],
                                "new_coeff": match['p2'],
                                "drop": old['p2'] - match['p2'],
                                "drop_percent": round(((old['p2'] - match['p2']) / old['p2'] * 100), 1),
                                "score": f"{score_h}:{score_a}",
                                "minute": stats.get("minute"),
                                "possession": f"{stats.get('possession_home')}% vs {stats.get('possession_away')}%" if stats.get('possession_home') else None,
                                "shots": f"{stats.get('shots_home')} vs {stats.get('shots_away')}" if stats.get('shots_home') else None,
                                "corners": f"{stats.get('corners_home')} vs {stats.get('corners_away')}" if stats.get('corners_home') else None,
                                "message_id": message_id,
                                "signal_time": datetime.now().isoformat(),
                                "result": None
                            })

                last_data[mid]["p1"] = match["p1"]
                last_data[mid]["p2"] = match["p2"]

            # Проверка результатов каждые 5 минут
            if int(time.time()) % 300 < 30:
                check_results()
                print("📊 Проверка результатов выполнена", flush=True)

            time.sleep(30)

        except Exception as e:
            print(f"❌ Ошибка в основном цикле: {e}", flush=True)
            time.sleep(30)

if __name__ == "__main__":
    main()