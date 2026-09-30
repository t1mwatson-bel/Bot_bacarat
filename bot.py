import os
import sys
import re
import json
import time
import requests
import pytz

from datetime import datetime, time as dtime, timedelta


# =====================================================================
# ENV
# =====================================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    BOT_TOKEN = os.getenv("BOT_TOKEN_PROGNOZ")

CHANNEL_PROGNOZ = os.getenv("CHAT_ID_21")
if not CHANNEL_PROGNOZ:
    CHANNEL_PROGNOZ = os.getenv("CHANNEL_PROGNOZ")

CHANNEL_STATS = os.getenv("CHANNEL_STATS")


if not BOT_TOKEN:
    print("❌ BOT_TOKEN не задан", flush=True)
    sys.exit(1)

if not CHANNEL_PROGNOZ:
    print("❌ CHANNEL_PROGNOZ не задан", flush=True)
    sys.exit(1)

if not CHANNEL_STATS:
    print("❌ CHANNEL_STATS не задан", flush=True)
    sys.exit(1)


# =====================================================================
# CONFIG
# =====================================================================

MOSCOW_TZ = pytz.timezone("Europe/Moscow")

PREDICTIONS_FILE = "suit_predictions.json"
OFFSET_FILE = "telegram_offset.txt"

POLL_INTERVAL = 2.0

FINALIZE_WAIT_SECONDS = 30

DOGON_GAMES = 3

TARGET_OFFSET = 10

GAME_CYCLE = 1440

PREDICTION_TIMEOUT_HOURS = 6

# ⚠️ УВЕЛИЧЕНО: чтобы игры для проверки не удалялись
MAX_GAMES_CACHE = 3000


# =====================================================================
# РАСПИСАНИЕ СНА
# =====================================================================
# Сон: с 23:00 до 09:00 (по Москве).
# Последний прогноз создаётся до 22:30, чтобы до 23:00
# бот успел проверить его.
# Ночная очистка кэша: в 03:00.

SLEEP_HOUR = 23
SLEEP_MINUTE = 0

WAKE_HOUR = 9
WAKE_MINUTE = 0

# Последний прогноз — до 22:30
LAST_PREDICTION_HOUR = 22
LAST_PREDICTION_MINUTE = 30

# Ночная очистка
CLEANUP_HOUR = 3
CLEANUP_MINUTE = 0

last_cleanup_date = None


def is_sleep_time(now=None):
    """Сон: с 23:00 до 09:00 (по Москве)."""

    if now is None:
        now = datetime.now(MOSCOW_TZ)

    current = now.time()
    sleep_start = dtime(SLEEP_HOUR, SLEEP_MINUTE)
    wake_start = dtime(WAKE_HOUR, WAKE_MINUTE)

    if sleep_start <= current or current < wake_start:
        return True

    return False


def is_last_prediction_time(now=None):
    """
    Проверяет, наступило ли время, после которого
    новые прогнозы НЕ создаются (22:30).
    """

    if now is None:
        now = datetime.now(MOSCOW_TZ)

    current = now.time()
    cutoff = dtime(LAST_PREDICTION_HOUR, LAST_PREDICTION_MINUTE)
    sleep_start = dtime(SLEEP_HOUR, SLEEP_MINUTE)

    # После 22:30 и до 23:00 — прогнозы не создаём
    if cutoff <= current < sleep_start:
        return True

    return False


def should_cleanup_now(now=None):
    """Ночная очистка (03:00)."""

    global last_cleanup_date

    if now is None:
        now = datetime.now(MOSCOW_TZ)

    if last_cleanup_date == now.date():
        return False

    cleanup_time = dtime(CLEANUP_HOUR, CLEANUP_MINUTE)

    if now.time() >= cleanup_time:
        return True

    return False


def cleanup_nightly():
    """
    Ночная очистка в 03:00.

    Чистит:
      - games_cache
      - pending_games
      - processed_trigger_keys

    Прогнозы:
      - pending → expired (не удаляются — для статистики)
    """

    global games_cache, pending_games, processed_trigger_keys
    global predictions, last_cleanup_date

    now = datetime.now(MOSCOW_TZ)

    print("", flush=True)
    print("🧹 НОЧНАЯ ОЧИСТКА (03:00)", flush=True)

    games_count = len(games_cache)
    games_cache.clear()
    print(f"   🗑️ games_cache: удалено {games_count} игр", flush=True)

    pending_count = len(pending_games)
    pending_games.clear()
    print(f"   🗑️ pending_games: удалено {pending_count}", flush=True)

    triggers_count = len(processed_trigger_keys)
    processed_trigger_keys.clear()
    print(
        f"   🗑️ processed_trigger_keys: удалено {triggers_count}",
        flush=True,
    )

    expired_count = 0
    for p in predictions:
        if p.get("status") == "pending":
            p["status"] = "expired"
            p["closed_at"] = now.isoformat()
            p["close_reason"] = "nightly_cleanup"
            expired_count += 1

    if expired_count:
        save_predictions()

    print(
        f"   🗑️ predictions: pending → expired — {expired_count}",
        flush=True,
    )

    last_cleanup_date = now.date()

    print("✅ Ночная очистка завершена", flush=True)
    print("", flush=True)


# =====================================================================
# ПАРЫ МАСТЕЙ
# =====================================================================

SUIT_PAIRS = {
    "♥️": "♣️",
    "♦️": "♠️",
    "♣️": "♥️",
    "♠️": "♦️",
}


# =====================================================================
# TELEGRAM
# =====================================================================

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
})


# =====================================================================
# GLOBALS
# =====================================================================

games_cache = {}
pending_games = {}

predictions = []

telegram_offset = 0

processed_trigger_keys = set()


# =====================================================================
# SUITS
# =====================================================================

SUITS = {
    "\u2660": "\u2660\ufe0f",
    "\u2663": "\u2663\ufe0f",
    "\u2666": "\u2666\ufe0f",
    "\u2665": "\u2665\ufe0f",
}

SUIT_ALIASES = {
    "♠": "♠️",
    "♠️": "♠️",
    "♣": "♣️",
    "♣️": "♣️",
    "♦": "♦️",
    "♦️": "♦️",
    "♥": "♥️",
    "♥️": "♥️",
}


def normalize_suit(suit):
    if suit is None:
        return None

    value = str(suit).strip()

    if value in SUIT_ALIASES:
        return SUIT_ALIASES[value]

    value = value.replace("\ufe0f", "")

    return SUITS.get(value)


# =====================================================================
# RANK
# =====================================================================
# ⚠️ ИСПРАВЛЕНО: добавлены карты 2, 3, 4, 5

def normalize_rank(rank):
    if rank is None:
        return None

    rank = str(rank).strip().upper()

    if rank == "А":
        rank = "A"

    if rank in {
        "2", "3", "4", "5",
        "6", "7", "8", "9", "10",
        "J", "Q", "K", "A",
    }:
        return rank

    return None


def card_to_text(card):
    if not card:
        return ""

    rank = normalize_rank(card.get("rank"))
    suit = normalize_suit(card.get("suit"))

    if not rank or not suit:
        return ""

    return f"{rank}{suit}"


def cards_to_text(cards):
    result = []

    for card in cards:
        value = card_to_text(card)
        if value:
            result.append(value)

    return " ".join(result)


# =====================================================================
# SCORE
# =====================================================================
# ⚠️ ИСПРАВЛЕНО: добавлены карты 2, 3, 4, 5
# (для Cyber 21: J=2, Q=3, K=4, A=11)

CARD_VALUES = {
    "2": 2, "3": 3, "4": 4, "5": 5,
    "6": 6, "7": 7, "8": 8, "9": 9, "10": 10,
    "J": 2, "Q": 3, "K": 4, "A": 11,
}


def cyber21_score(cards):
    total = 0

    for card in cards:
        rank = normalize_rank(card.get("rank"))
        if rank in CARD_VALUES:
            total += CARD_VALUES[rank]

    return total


# =====================================================================
# PARSE CARDS
# =====================================================================
# ⚠️ ИСПРАВЛЕНО: [6-9AJQK] → [2-9AJQK]

CARD_RE = re.compile(
    r"(10|[2-9AJQK])\s*"
    r"(\u2660|\u2663|\u2666|\u2665)"
    r"\ufe0f?"
)


def parse_cards(text):
    result = []

    if not text:
        return result

    for match in CARD_RE.finditer(text):
        rank = normalize_rank(match.group(1))
        suit = normalize_suit(match.group(2))

        if not rank or not suit:
            continue

        result.append({
            "rank": rank,
            "suit": suit,
        })

    return result


# =====================================================================
# PARSE GAME MESSAGE
# =====================================================================

def parse_game_message(text):
    if not text:
        return None

    number_match = re.search(r"#N(\d+)", text)
    if not number_match:
        return None

    game_number = int(number_match.group(1))

    groups = re.findall(r"\(([^()]*)\)", text)
    if len(groups) < 2:
        return None

    player_text = groups[0]
    dealer_text = groups[1]

    player_cards = parse_cards(player_text)
    dealer_cards = parse_cards(dealer_text)

    if not player_cards:
        return None

    player_score = cyber21_score(player_cards)
    dealer_score = cyber21_score(dealer_cards)

    id_match = re.search(r"ID:\s*(\d+)", text)
    game_id = id_match.group(1) if id_match else None

    is_draw = bool(re.search(r"#X\b", text))
    is_ochko = bool(re.search(r"#O\b", text))

    return {
        "game_number": game_number,
        "game_id": game_id,

        "player_cards": player_cards,
        "dealer_cards": dealer_cards,

        "player_score": player_score,
        "dealer_score": dealer_score,

        "is_draw": is_draw,
        "is_ochko": is_ochko,

        "raw_text": text,

        "received_at": datetime.now(MOSCOW_TZ).isoformat(),
    }


# =====================================================================
# LOG GAME
# =====================================================================

def log_game(game):
    player = game.get("player_cards", [])
    dealer = game.get("dealer_cards", [])

    print("", flush=True)
    print("────────────────────────────────────", flush=True)
    print(f"🎮 ИГРА #N{game['game_number']}", flush=True)
    print(
        f"👤 P: {game['player_score']} "
        f"({cards_to_text(player)})",
        flush=True,
    )
    print(
        f"🎰 D: {game['dealer_score']} "
        f"({cards_to_text(dealer)})",
        flush=True,
    )

    if game.get("is_draw"):
        print("🔰 #X — НИЧЬЯ", flush=True)

    if game.get("is_ochko"):
        print("⭕ #O — ОЧКО", flush=True)

    print("────────────────────────────────────", flush=True)


# =====================================================================
# OFFSET
# =====================================================================

def load_offset():
    try:
        if os.path.exists(OFFSET_FILE):
            with open(OFFSET_FILE, "r", encoding="utf-8") as f:
                value = f.read().strip()
                if value:
                    return int(value)
    except Exception:
        pass

    return 0


def save_offset(offset):
    try:
        with open(OFFSET_FILE, "w", encoding="utf-8") as f:
            f.write(str(offset))
    except Exception as e:
        print(f"⚠️ Ошибка сохранения offset: {e}", flush=True)


# =====================================================================
# PREDICTIONS JSON
# =====================================================================

def load_predictions():
    global predictions

    try:
        if not os.path.exists(PREDICTIONS_FILE):
            predictions = []
            return

        with open(PREDICTIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        predictions = data if isinstance(data, list) else []

    except Exception as e:
        print(f"⚠️ Ошибка чтения {PREDICTIONS_FILE}: {e}", flush=True)
        predictions = []


def save_predictions():
    try:
        tmp = PREDICTIONS_FILE + ".tmp"

        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(predictions, f, ensure_ascii=False, indent=2)

        os.replace(tmp, PREDICTIONS_FILE)

    except Exception as e:
        print(f"⚠️ Ошибка сохранения прогнозов: {e}", flush=True)


# =====================================================================
# DELETE WEBHOOK
# =====================================================================

def delete_webhook():
    try:
        response = SESSION.post(
            f"{TELEGRAM_API}/deleteWebhook",
            json={"drop_pending_updates": False},
            timeout=10,
        )

        data = response.json()

        if data.get("ok"):
            print("✅ Webhook удалён, используем getUpdates", flush=True)
            return True

        print(f"❌ Ошибка deleteWebhook: {data}", flush=True)

    except Exception as e:
        print(f"❌ Ошибка удаления webhook: {e}", flush=True)

    return False


# =====================================================================
# TELEGRAM SEND
# =====================================================================

def telegram_send(text):
    try:
        response = SESSION.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": CHANNEL_PROGNOZ,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )

        data = response.json()

        if data.get("ok"):
            return data["result"]["message_id"]

        print(f"❌ Telegram sendMessage: {data}", flush=True)

    except Exception as e:
        print(f"❌ Ошибка отправки Telegram: {e}", flush=True)

    return None


def telegram_edit(message_id, text):
    if not message_id:
        return False

    try:
        response = SESSION.post(
            f"{TELEGRAM_API}/editMessageText",
            json={
                "chat_id": CHANNEL_PROGNOZ,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=10,
        )

        data = response.json()

        return bool(data.get("ok"))

    except Exception as e:
        print(f"⚠️ Ошибка редактирования Telegram: {e}", flush=True)

    return False


# =====================================================================
# GAME NUMBER
# =====================================================================

def add_game_offset(number, offset):
    return ((int(number) - 1 + int(offset)) % GAME_CYCLE) + 1


# =====================================================================
# TRIGGER: ПЕРВАЯ КАРТА ИГРОКА
# =====================================================================

def get_trigger_suit(game):
    player = game.get("player_cards", [])

    if not player:
        return None

    if game.get("is_ochko"):
        return None

    first_card = player[0]
    first_suit = normalize_suit(first_card.get("suit"))

    if not first_suit:
        return None

    if first_suit not in SUIT_PAIRS:
        return None

    return first_suit


def get_predicted_suit(trigger_suit):
    return SUIT_PAIRS.get(trigger_suit)


# =====================================================================
# ПРАВИЛА ПРОПУСКА
# =====================================================================

def has_double_signal(game):
    """Правило 2: первая и вторая карты игрока одинаковые."""

    player = game.get("player_cards", [])

    if len(player) < 2:
        return False

    first_suit = normalize_suit(player[0].get("suit"))
    second_suit = normalize_suit(player[1].get("suit"))

    if not first_suit or not second_suit:
        return False

    return first_suit == second_suit


def has_predicted_suit_in_trigger(game, predicted_suit):
    """Правило 1: прогнозируемая масть уже есть у игрока."""

    player = game.get("player_cards", [])

    for card in player:
        if normalize_suit(card.get("suit")) == predicted_suit:
            return True

    return False


# =====================================================================
# CREATE PREDICTION
# =====================================================================

def create_prediction(game):
    trigger_suit = get_trigger_suit(game)

    if not trigger_suit:
        return None

    predicted_suit = get_predicted_suit(trigger_suit)

    if not predicted_suit:
        return None

    # Правило 2: задвоение
    if has_double_signal(game):
        print(
            f"⏭️ Пропуск #N{game['game_number']}: "
            f"задвоенный сигнал ({trigger_suit}{trigger_suit})",
            flush=True,
        )
        return None

    # Правило 1: прогнозируемая масть уже есть
    if has_predicted_suit_in_trigger(game, predicted_suit):
        print(
            f"⏭️ Пропуск #N{game['game_number']}: "
            f"у игрока уже есть {predicted_suit}",
            flush=True,
        )
        return None

    trigger_number = game["game_number"]
    trigger_id = game.get("game_id")

    target_number = add_game_offset(trigger_number, TARGET_OFFSET)

    trigger_key = (trigger_id or trigger_number, predicted_suit)

    if trigger_key in processed_trigger_keys:
        return None

    for old in predictions:
        if old.get("status") not in ("pending", "win"):
            continue

        if (
            old.get("target_number") == target_number
            and old.get("predicted_suit") == predicted_suit
        ):
            processed_trigger_keys.add(trigger_key)
            return None

    prediction = {
        "algorithm": "suit_pair",

        "trigger_number": trigger_number,
        "trigger_game_id": trigger_id,
        "trigger_suit": trigger_suit,

        "target_number": target_number,
        "predicted_suit": predicted_suit,

        "target_offset": TARGET_OFFSET,

        "status": "pending",

        "created_at": datetime.now(MOSCOW_TZ).isoformat(),
        "sent_at": None,

        "message_id": None,

        "result_game": None,
        "found_card": None,
        "dogon": None,
    }

    predictions.append(prediction)
    processed_trigger_keys.add(trigger_key)
    save_predictions()

    print("", flush=True)
    print("🔮 ПРОГНОЗ СОЗДАН", flush=True)
    print(f"📌 Триггер: #N{trigger_number} ({trigger_suit})", flush=True)
    print(f"🎯 Цель: #N{target_number}", flush=True)
    print(f"🃏 Масть: {predicted_suit}", flush=True)

    send_prediction(prediction)

    return prediction


# =====================================================================
# SEND PREDICTION
# =====================================================================

def make_prediction_message(prediction):
    target = prediction["target_number"]
    suit = normalize_suit(prediction["predicted_suit"])

    return f"🎯 Игра: <b>#N{target}</b>: {suit}"


def make_result_message(prediction, result):
    target = prediction["target_number"]
    suit = normalize_suit(prediction["predicted_suit"])

    if result == "win":
        mark = " ✅"
    elif result == "lose":
        mark = " ❌"
    else:
        mark = " ⚠️"

    return f"🎯 Игра: <b>#N{target}</b>: {suit}{mark}"


def send_prediction(prediction):
    message = make_prediction_message(prediction)
    message_id = telegram_send(message)

    if not message_id:
        print(
            f"❌ Не удалось отправить "
            f"#N{prediction['target_number']}",
            flush=True,
        )
        return False

    prediction["message_id"] = message_id
    prediction["sent_at"] = datetime.now(MOSCOW_TZ).isoformat()

    save_predictions()

    print(
        f"📤 ПРОГНОЗ ОТПРАВЛЕН: "
        f"#N{prediction['target_number']} "
        f"{prediction['predicted_suit']}",
        flush=True,
    )

    return True


# =====================================================================
# CHECK SUIT IN PLAYER
# =====================================================================

def check_prediction_suit(game, prediction):
    target_suit = normalize_suit(prediction.get("predicted_suit"))

    if not target_suit:
        return None

    player_cards = game.get("player_cards", [])

    for card in player_cards:
        card_suit = normalize_suit(card.get("suit"))

        if card_suit == target_suit:
            return card_to_text(card)

    return None


# =====================================================================
# CHECK PREDICTIONS
# =====================================================================

def check_predictions():
    changed = False

    now = datetime.now(MOSCOW_TZ)

    for prediction in predictions:

        if prediction.get("status") != "pending":
            continue

        target = prediction.get("target_number")

        if not target:
            continue

        # TIMEOUT
        sent_at_str = prediction.get("sent_at")

        if sent_at_str:
            try:
                sent_at = datetime.fromisoformat(sent_at_str)

                if (
                    now - sent_at
                    > timedelta(hours=PREDICTION_TIMEOUT_HOURS)
                ):
                    prediction["status"] = "void"
                    prediction["close_reason"] = "timeout"

                    telegram_edit(
                        prediction.get("message_id"),
                        make_result_message(prediction, "void"),
                    )

                    print(
                        f"⚠️ VOID #N{target} (timeout)",
                        flush=True,
                    )

                    changed = True
                    continue

            except Exception:
                pass

        # ЦЕЛЕВАЯ + 3 ДОГОНА
        checked_games = []
        waiting = False

        for dogon in range(0, DOGON_GAMES + 1):

            game_number = add_game_offset(target, dogon)
            game = games_cache.get(game_number)

            if not game:
                waiting = True
                break

            checked_games.append(game_number)

            found_card = check_prediction_suit(game, prediction)

            if found_card:
                prediction["status"] = "win"
                prediction["result_game"] = game_number
                prediction["found_card"] = found_card
                prediction["dogon"] = dogon

                telegram_edit(
                    prediction.get("message_id"),
                    make_result_message(prediction, "win"),
                )

                print("", flush=True)
                print(f"✅ ПРОГНОЗ ЗАШЁЛ #N{target}", flush=True)
                print(
                    f"🎯 Масть: {prediction['predicted_suit']}",
                    flush=True,
                )
                print(f"🃏 Карта: {found_card}", flush=True)
                print(f"🔄 Догон: {dogon}", flush=True)

                changed = True
                break

        else:
            prediction["status"] = "lose"
            prediction["result_game"] = (
                checked_games[-1]
                if checked_games
                else add_game_offset(target, DOGON_GAMES)
            )
            prediction["dogon"] = DOGON_GAMES

            telegram_edit(
                prediction.get("message_id"),
                make_result_message(prediction, "lose"),
            )

            print("", flush=True)
            print(f"❌ ПРОГНОЗ НЕ ЗАШЁЛ #N{target}", flush=True)
            print(
                f"🎯 Масть: {prediction['predicted_suit']}",
                flush=True,
            )

            changed = True

    if changed:
        save_predictions()


# =====================================================================
# FINALIZE PENDING GAMES
# =====================================================================

def finalize_pending_games():
    now = time.time()
    ready = []

    for game_number, info in list(pending_games.items()):
        first_seen = info.get("first_seen", now)

        if now - first_seen >= FINALIZE_WAIT_SECONDS:
            ready.append(game_number)

    for game_number in ready:

        info = pending_games.pop(game_number, None)

        if not info:
            continue

        text = info.get("text", "")
        game = parse_game_message(text)

        if not game:
            print(
                f"⚠️ #N{game_number} не удалось разобрать",
                flush=True,
            )
            continue

        games_cache[game_number] = game

        log_game(game)

        # Если сейчас ночь — прогноз не создаём
        if is_sleep_time():
            print(
                f"😴 #N{game_number}: сон — прогноз не создаём",
                flush=True,
            )
            continue

        # Если после 22:30 — прогноз не создаём
        if is_last_prediction_time():
            print(
                f"🌙 #N{game_number}: после 22:30 — прогноз не создаём",
                flush=True,
            )
            continue

        create_prediction(game)


# =====================================================================
# UPDATE EXISTING GAME
# =====================================================================

def update_existing_game(game_number, text):
    game = parse_game_message(text)

    if not game:
        return

    games_cache[game_number] = game

    print(f"🔄 Обновлена #N{game_number}", flush=True)


# =====================================================================
# TELEGRAM UPDATES
# =====================================================================

def process_telegram_updates(offset):
    try:
        response = SESSION.get(
            f"{TELEGRAM_API}/getUpdates",
            params={
                "offset": offset,
                "timeout": 3,
                "limit": 50,
                "allowed_updates": json.dumps([
                    "channel_post",
                    "edited_channel_post",
                ]),
            },
            timeout=10,
        )

        data = response.json()

        if not data.get("ok"):
            print(f"❌ Telegram getUpdates: {data}", flush=True)
            return offset

        updates = data.get("result", [])

        for update in updates:

            update_id = update.get("update_id")

            if update_id is not None:
                offset = update_id + 1
                save_offset(offset)

            post = (
                update.get("channel_post")
                or update.get("edited_channel_post")
            )

            if not post:
                continue

            chat = post.get("chat", {})
            chat_id = str(chat.get("id", ""))

            text = post.get("text", "")

            if chat_id != str(CHANNEL_STATS):
                continue

            if not text:
                continue

            number_match = re.search(r"#N(\d+)", text)

            if not number_match:
                continue

            game_number = int(number_match.group(1))

            if game_number in pending_games:
                pending_games[game_number]["text"] = text

                print(
                    f"🔄 Обновлена pending #N{game_number}",
                    flush=True,
                )
                continue

            if game_number in games_cache:
                update_existing_game(game_number, text)
                continue

            has_marker = bool(re.search(r"[✅🔰▶️◀️]", text))

            if has_marker:
                pending_games[game_number] = {
                    "first_seen": time.time(),
                    "text": text,
                }

                print(
                    f"👀 #N{game_number} → pending",
                    flush=True,
                )

    except Exception as e:
        print(f"⚠️ Updates error: {e}", flush=True)

    return offset


# =====================================================================
# CLEANUP
# =====================================================================

def cleanup_games_cache():
    if len(games_cache) <= MAX_GAMES_CACHE:
        return

    items = sorted(
        games_cache.items(),
        key=lambda kv: kv[1].get("received_at", ""),
    )

    for number, _ in items[:-MAX_GAMES_CACHE]:
        del games_cache[number]


def cleanup_predictions():
    global predictions

    if len(predictions) > 2000:
        predictions = predictions[-2000:]
        save_predictions()


# =====================================================================
# MAIN
# =====================================================================

def main():
    global telegram_offset

    print("", flush=True)
    print("==================================================", flush=True)
    print("🚀 SUIT PAIR PREDICTOR BOT", flush=True)
    print("==================================================", flush=True)
    print("📡 Игры: CHANNEL_STATS", flush=True)
    print("📤 Прогнозы: CHANNEL_PROGNOZ", flush=True)
    print(f"⏳ Финализация игры: {FINALIZE_WAIT_SECONDS} сек", flush=True)
    print(f"🔄 Догоны: {DOGON_GAMES}", flush=True)
    print(f"🎯 Сдвиг цели: +{TARGET_OFFSET}", flush=True)
    print(f"⏰ Таймаут прогноза: {PREDICTION_TIMEOUT_HOURS} ч", flush=True)
    print(f"💾 MAX_GAMES_CACHE: {MAX_GAMES_CACHE}", flush=True)
    print("🎯 Пары мастей:", flush=True)

    for trigger, target in SUIT_PAIRS.items():
        print(f"   {trigger} → {target}", flush=True)

    print("🎯 Правила пропуска:", flush=True)
    print("   1. Прогнозируемая масть уже есть у игрока", flush=True)
    print("   2. Первая и вторая карта игрока одинаковые", flush=True)

    print("", flush=True)
    print("⏰ Расписание:", flush=True)
    print(
        f"   😴 Сон: {SLEEP_HOUR:02d}:{SLEEP_MINUTE:02d} — "
        f"{WAKE_HOUR:02d}:{WAKE_MINUTE:02d}",
        flush=True,
    )
    print(
        f"   🌙 Последний прогноз до: "
        f"{LAST_PREDICTION_HOUR:02d}:{LAST_PREDICTION_MINUTE:02d}",
        flush=True,
    )
    print(
        f"   🧹 Ночная очистка: "
        f"{CLEANUP_HOUR:02d}:{CLEANUP_MINUTE:02d}",
        flush=True,
    )
    print("==================================================", flush=True)

    delete_webhook()

    load_predictions()

    telegram_offset = load_offset()

    print(f"📌 Telegram offset: {telegram_offset}", flush=True)
    print(f"📊 Загружено прогнозов: {len(predictions)}", flush=True)

    # Восстановление ключей
    for prediction in predictions:

        if prediction.get("status") not in ("pending", "win"):
            continue

        trigger_id = prediction.get("trigger_game_id")
        trigger_number = prediction.get("trigger_number")
        suit = normalize_suit(prediction.get("predicted_suit"))

        if suit:
            key = (trigger_id or trigger_number, suit)
            processed_trigger_keys.add(key)

    print("==================================================", flush=True)
    print("🟢 БОТ ГОТОВ", flush=True)
    print("==================================================", flush=True)

    while True:
        try:
            # Ночная очистка в 03:00
            if should_cleanup_now():
                cleanup_nightly()

            telegram_offset = process_telegram_updates(telegram_offset)
            finalize_pending_games()
            check_predictions()
            cleanup_games_cache()
            cleanup_predictions()

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("\n🛑 Бот остановлен", flush=True)
            break

        except Exception as e:
            print(f"❌ Критическая ошибка: {e}", flush=True)
            time.sleep(3)


# =====================================================================
# START
# =====================================================================

if __name__ == "__main__":
    main()