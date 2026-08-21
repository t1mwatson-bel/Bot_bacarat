import os
import sys
import requests
import json
import re
import time
from datetime import datetime, timedelta
import pytz

# =====================================================================
# ПРИНУДИТЕЛЬНЫЙ ВЫВОД ЛОГОВ
# =====================================================================
sys.stdout.flush()
print("=" * 60, flush=True)
print("🃏 ПАРСЕР 21 КЛАССИК - V3 API", flush=True)
print("=" * 60, flush=True)

# =====================================================================
# ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
# =====================================================================
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID_21')
if not CHAT_ID:
    CHAT_ID = os.getenv('CHAT_ID')

MOSCOW_TZ = pytz.timezone('Europe/Moscow')
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

SUITS_NAMES = {0: "♠", 1: "♣", 2: "♦", 3: "♥"}
RANKS = {2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "10", 11: "J", 12: "Q", 13: "K", 14: "A"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://1xlite-84484.pro/ru/live/twentyone/2092323-21-classics",
    "Cookie": "platform_type=desktop; SESSION=34219176f69eace1b636911e2de9a15e; lng=ru; cookies_agree_type=3; tzo=3; is12h=0; auid=uaJbk2qIgo2M+6ofAxNqAg==; _ym_isad=2; mdd=1; _ga_7JGWL9SV66=GS2.1.s1787337341$o4$g1$t1787337359$j42$l0$h1608459194; window_width=150; referral_values=%7B%22type%22%3A%22reflinkid%22%2C%22val%22%3A%22s_50970m_355c_%22%2C%22additional%22%3A%7B%22name_tag%22%3A%22tag%22%7D%7D; fatman_uuid=45f69ff0-ecb1-67d4-3ff2-3a45baafc739; che_g=777dc1b9-efbf-4728-947a-4a2992ef6da5; sh.session.id=684214c4-f09e-42da-9c1a-ea61b9aca91b; _ym_uid=1786989905737338437; _ym_d=1786989905; _ga=GA1.1.547872848.1786989906"
}

print("✅ Настройки загружены", flush=True)

# =====================================================================
# ФУНКЦИИ
# =====================================================================
def get_game_number():
    now = datetime.now(MOSCOW_TZ)
    start = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if now < start:
        start = start - timedelta(days=1)
    diff_minutes = (now - start).total_seconds() / 60
    game_number = int(diff_minutes / 2) % 720 + 1
    return game_number

def get_active_game_id():
    try:
        url = "https://1xlite-84484.pro/service-api/main-live-feed/v3/games1x2?cfView=3&count=40&fcountry=1&gr=415&grMode=4&lng=ru&ref=7&selectedMs=1.146.2092323,2.146.2092323,10.146.2092323"
        print(f"🔍 Запрос к API V3...", flush=True)
        response = requests.get(url, headers=HEADERS, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if isinstance(data, list):
                games = data
            elif isinstance(data, dict) and "Value" in data:
                games = data.get("Value", [])
            else:
                print(f"⚠️ Неизвестный формат ответа", flush=True)
                return None
            
            print(f"📊 Найдено игр в ответе: {len(games)}", flush=True)
            
            for game in games:
                if game.get("liga", {}).get("id") == 2092323:
                    game_id = game.get("id")
                    if game_id:
                        print(f"✅ Найден ID игры (21 Классик): {game_id}", flush=True)
                        return str(game_id)
            
            print("⚠️ Игра 21 Классик не найдена", flush=True)
        else:
            print(f"⚠️ Статус API: {response.status_code}", flush=True)
    except Exception as e:
        print(f"❌ Ошибка: {e}", flush=True)
    
    return None

def get_game_data(game_id):
    try:
        url = "https://1xlite-84484.pro/service-api/main-live-feed/v3/games1x2?cfView=3&count=40&fcountry=1&gr=415&grMode=4&lng=ru&ref=7&selectedMs=1.146.2092323,2.146.2092323,10.146.2092323"
        response = requests.get(url, headers=HEADERS, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if isinstance(data, list):
                games = data
            elif isinstance(data, dict) and "Value" in data:
                games = data.get("Value", [])
            else:
                return None
            
            for game in games:
                if str(game.get("id")) == str(game_id):
                    return game
            
            return None
        else:
            print(f"⚠️ Статус API: {response.status_code}", flush=True)
            return None
    except Exception as e:
        print(f"❌ Ошибка: {e}", flush=True)
        return None

def parse_cards_from_json(cards_json):
    if not cards_json or cards_json == "[]":
        return []
    try:
        cards_data = json.loads(cards_json)
        cards = []
        for card in cards_data:
            cs = card.get("CS", 0)
            cv = card.get("CV", 0)
            suit = SUITS_NAMES.get(cs, "?")
            rank = RANKS.get(cv, str(cv))
            cards.append({"CS": cs, "CV": cv, "suit": suit, "rank": rank})
        return cards
    except Exception as e:
        print(f"❌ Ошибка парсинга карт: {e}", flush=True)
        return []

def calculate_score(cards):
    if not cards:
        return 0
    
    score = 0
    aces = 0
    
    for c in cards:
        cv = c.get("CV", 0)
        if cv == 14:
            aces += 1
            score += 11
        elif cv == 13:
            score += 4
        elif cv == 12:
            score += 3
        elif cv == 11:
            score += 2
        elif 6 <= cv <= 10:
            score += cv
    
    while score > 21 and aces > 0:
        score -= 10
        aces -= 1
    
    return score

def is_game_finished(state, player_cards, dealer_cards, p_score, d_score):
    if state in ["4", "5"]:
        return True
    
    if p_score == 21 or d_score == 21:
        return True
    
    if p_score > 21 or d_score > 21:
        return True
    
    if dealer_cards and len(dealer_cards) >= 2 and d_score >= 17:
        return True
    
    return False

def format_cards_hand(cards):
    if not cards:
        return ""
    result = []
    for c in cards:
        result.append(f"{c['rank']}{c['suit']}")
    return "".join(result)

def build_message(game_num, player_cards, dealer_cards, p_score, d_score, state):
    p_hand = format_cards_hand(player_cards)
    d_hand = format_cards_hand(dealer_cards)
    total = p_score + d_score if dealer_cards else p_score
    
    if is_game_finished(state, player_cards, dealer_cards, p_score, d_score):
        if p_score > 21:
            return f"#N{game_num}. {p_score}({p_hand}) - ✅{d_score}({d_hand}) #T{total}"
        if d_score > 21:
            return f"#N{game_num}. ✅{p_score}({p_hand}) - {d_score}({d_hand}) #T{total}"
        if p_score == 21:
            return f"#N{game_num}. ✅{p_score}({p_hand}) - {d_score}({d_hand}) #T{total}"
        if d_score == 21:
            return f"#N{game_num}. {p_score}({p_hand}) - ✅{d_score}({d_hand}) #T{total}"
        if p_score > d_score:
            return f"#N{game_num}. ✅{p_score}({p_hand}) - {d_score}({d_hand}) #T{total}"
        if d_score > p_score:
            return f"#N{game_num}. {p_score}({p_hand}) - ✅{d_score}({d_hand}) #T{total}"
        return f"#N{game_num}. {p_score}({p_hand}) - 🔰{d_score}({d_hand}) #T{total}"
    
    if not dealer_cards:
        arrow = "◀️"
    else:
        arrow = "▶️"
    
    return f"#N{game_num}. {p_score}({p_hand}) {arrow} {d_score}({d_hand}) #T{total}"

def send_message(text):
    try:
        r = requests.post(API + "/sendMessage", json={"chat_id": CHAT_ID, "text": text})
        if r.status_code == 200:
            return r.json()["result"]["message_id"]
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}", flush=True)
    return None

def edit_message(message_id, text):
    try:
        url = f"{API}/editMessageText"
        payload = {"chat_id": CHAT_ID, "message_id": message_id, "text": text}
        r = requests.post(url, json=payload)
        return r.status_code == 200
    except Exception as e:
        print(f"❌ Ошибка редактирования: {e}", flush=True)
        return False

def wait_for_start():
    while True:
        now = datetime.now(MOSCOW_TZ)
        if now.second == 58 and now.minute % 2 == 1:
            return time.time()
        time.sleep(0.1)

# =====================================================================
# ОСНОВНОЙ ЦИКЛ
# =====================================================================
def main():
    print("🔄 ПАРСЕР ЗАПУЩЕН, ОЖИДАНИЕ СТАРТА...", flush=True)
    processed_games = set()
    
    while True:
        try:
            start_time = wait_for_start()
            print(f"🕐 Старт в {datetime.fromtimestamp(start_time).strftime('%H:%M:%S')}", flush=True)
            
            time.sleep(2)
            
            game_id = None
            print("🔍 Поиск игры...", flush=True)
            for _ in range(10):
                any_id = get_active_game_id()
                if any_id:
                    if any_id not in processed_games:
                        game_id = any_id
                        processed_games.add(game_id)
                        print(f"✅ Найдена игра: {game_id}", flush=True)
                        break
                    else:
                        print(f"⏭️ Игра {any_id} уже обработана", flush=True)
                time.sleep(0.5)
            
            if not game_id:
                print("❌ Игра не найдена, перезапуск...", flush=True)
                continue
            
            game_started = False
            last_message_id = None
            game_number = 0
            game_finished = False
            
            while not game_finished:
                try:
                    game_data = get_game_data(game_id)
                    if not game_data:
                        time.sleep(0.3)
                        continue
                    
                    scores = game_data.get("scores", {})
                    statistic = scores.get("statistic", {}).get("main", {})
                    
                    player_cards_json = statistic.get("P1", "[]")
                    dealer_cards_json = statistic.get("P2", "[]")
                    state = statistic.get("STATE", "0")
                    
                    player_cards = parse_cards_from_json(player_cards_json)
                    dealer_cards = parse_cards_from_json(dealer_cards_json)
                    
                    if player_cards:
                        if not game_started:
                            game_started = True
                            game_number = get_game_number()
                        
                        p_score = calculate_score(player_cards)
                        d_score = calculate_score(dealer_cards) if dealer_cards else 0
                        
                        msg = build_message(game_number, player_cards, dealer_cards, p_score, d_score, state)
                        
                        if last_message_id:
                            edit_message(last_message_id, msg)
                        else:
                            last_message_id = send_message(msg)
                        
                        print(f"🔄 {msg}", flush=True)
                        
                        if is_game_finished(state, player_cards, dealer_cards, p_score, d_score):
                            game_finished = True
                            print(f"🏁 Игра завершена", flush=True)
                    
                    time.sleep(0.3)
                    
                except Exception as e:
                    print(f"❌ Сбой: {e}", flush=True)
                    time.sleep(3)
                    break
            
            print("⏰ Игра завершена, ожидание следующей...", flush=True)
            
        except Exception as e:
            print(f"❌ Критическая ошибка: {e}", flush=True)
            time.sleep(5)

if __name__ == "__main__":
    main()