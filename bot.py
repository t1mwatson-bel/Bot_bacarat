import os
import sys
import re
import json
import time
import requests
import pytz

from datetime import datetime, timedelta


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

PATTERNS_FILE = "pattern_results_suits.json"

PREDICTIONS_FILE = "premium_predictions.json"
OFFSET_FILE = "telegram_offset.txt"

POLL_INTERVAL = 2.0

FINALIZE_WAIT_SECONDS = 30

DOGON_GAMES = 3

PREDICTION_TIMEOUT_HOURS = 24

MAX_GAMES_CACHE = 500


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

processed_prediction_keys = set()


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
    "spade": "♠️",
    "spades": "♠️",

    "♣": "♣️",
    "♣️": "♣️",
    "club": "♣️",
    "clubs": "♣️",

    "♦": "♦️",
    "♦️": "♦️",
    "diamond": "♦️",
    "diamonds": "♦️",

    "♥": "♥️",
    "♥️": "♥️",
    "heart": "♥️",
    "hearts": "♥️",
}


def normalize_suit(suit):
    if suit is None:
        return None

    value = str(suit).strip()

    if value in SUIT_ALIASES:
        return SUIT_ALIASES[value]

    value = value.replace("\ufe0f", "")

    return SUITS.get(value)


def suit_short(suit):
    suit = normalize_suit(suit)

    if suit == "♠️":
        return "♠"

    if suit == "♣️":
        return "♣"

    if suit == "♦️":
        return "♦"

    if suit == "♥️":
        return "♥"

    return None


def normalize_pattern_suit(value):
    if value is None:
        return None

    value = str(value).strip()

    for alias, normalized in SUIT_ALIASES.items():
        if value == alias:
            return normalized

    if value in ("♠", "♠️"):
        return "♠️"

    if value in ("♣", "♣️"):
        return "♣️"

    if value in ("♦", "♦️"):
        return "♦️"

    if value in ("♥", "♥️"):
        return "♥️"

    return None


# =====================================================================
# RANK
# =====================================================================

def normalize_rank(rank):
    if rank is None:
        return None

    rank = str(rank).strip().upper()

    if rank == "А":
        rank = "A"

    if rank in {
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
# CYBER 21 SCORE
# =====================================================================

CARD_VALUES = {
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "10": 10,
    "J": 2,
    "Q": 3,
    "K": 4,
    "A": 11,
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

CARD_RE = re.compile(
    r"(10|[6-9AJQK])\s*"
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

    number_match = re.search(
        r"#N(\d+)",
        text
    )

    if not number_match:
        return None

    game_number = int(
        number_match.group(1)
    )

    groups = re.findall(
        r"\(([^()]*)\)",
        text
    )

    if len(groups) < 2:
        return None

    player_text = groups[0]
    dealer_text = groups[1]

    player_cards = parse_cards(
        player_text
    )

    dealer_cards = parse_cards(
        dealer_text
    )

    if not player_cards:
        return None

    player_score = cyber21_score(
        player_cards
    )

    dealer_score = cyber21_score(
        dealer_cards
    )

    id_match = re.search(
        r"ID:\s*(\d+)",
        text
    )

    game_id = (
        id_match.group(1)
        if id_match
        else None
    )

    is_draw = bool(
        re.search(
            r"#X\b",
            text
        )
    )

    is_ochko = bool(
        re.search(
            r"#O\b",
            text
        )
    )

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

        "received_at": datetime.now(
            MOSCOW_TZ
        ).isoformat(),
    }


# =====================================================================
# LOG GAME
# =====================================================================

def log_game(game):

    player = game.get(
        "player_cards",
        []
    )

    dealer = game.get(
        "dealer_cards",
        []
    )

    print("", flush=True)

    print(
        "────────────────────────────────────",
        flush=True,
    )

    print(
        f"🎮 ИГРА #N{game['game_number']}",
        flush=True,
    )

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

        print(
            "🔰 #X — НИЧЬЯ",
            flush=True,
        )

    if game.get("is_ochko"):

        print(
            "⭕ #O — ОЧКО",
            flush=True,
        )

    print(
        "────────────────────────────────────",
        flush=True,
    )


# =====================================================================
# OFFSET
# =====================================================================

def load_offset():

    try:

        if os.path.exists(
            OFFSET_FILE
        ):

            with open(
                OFFSET_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                value = f.read().strip()

                if value:
                    return int(value)

    except Exception:
        pass

    return 0


def save_offset(offset):

    try:

        with open(
            OFFSET_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                str(offset)
            )

    except Exception as e:

        print(
            f"⚠️ Ошибка сохранения offset: {e}",
            flush=True,
        )


# =====================================================================
# PREDICTIONS JSON
# =====================================================================

def load_predictions():

    global predictions

    try:

        if not os.path.exists(
            PREDICTIONS_FILE
        ):

            predictions = []
            return

        with open(
            PREDICTIONS_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(
            data,
            list
        ):

            predictions = data

        else:

            predictions = []

    except Exception as e:

        print(
            f"⚠️ Ошибка чтения "
            f"{PREDICTIONS_FILE}: {e}",
            flush=True,
        )

        predictions = []


def save_predictions():

    try:

        tmp = (
            PREDICTIONS_FILE
            + ".tmp"
        )

        with open(
            tmp,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                predictions,
                f,
                ensure_ascii=False,
                indent=2,
            )

        os.replace(
            tmp,
            PREDICTIONS_FILE,
        )

    except Exception as e:

        print(
            f"⚠️ Ошибка сохранения "
            f"прогнозов: {e}",
            flush=True,
        )


# =====================================================================
# DELETE WEBHOOK
# =====================================================================

def delete_webhook():

    try:

        response = SESSION.post(
            f"{TELEGRAM_API}/deleteWebhook",

            json={
                "drop_pending_updates": False
            },

            timeout=10,
        )

        data = response.json()

        if data.get("ok"):

            print(
                "✅ Webhook удалён, "
                "используем getUpdates",
                flush=True,
            )

            return True

        print(
            f"❌ Ошибка deleteWebhook: "
            f"{data}",
            flush=True,
        )

    except Exception as e:

        print(
            f"❌ Ошибка удаления webhook: "
            f"{e}",
            flush=True,
        )

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

            return data[
                "result"
            ]["message_id"]

        print(
            f"❌ Telegram sendMessage: "
            f"{data}",
            flush=True,
        )

    except Exception as e:

        print(
            f"❌ Ошибка отправки Telegram: "
            f"{e}",
            flush=True,
        )

    return None


def telegram_edit(
    message_id,
    text
):

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

        return bool(
            data.get("ok")
        )

    except Exception as e:

        print(
            f"⚠️ Ошибка редактирования "
            f"Telegram: {e}",
            flush=True,
        )

    return False


# =====================================================================
# GAME NUMBER
# =====================================================================

def add_game_offset(
    number,
    offset
):

    return (
        (
            int(number)
            - 1
            + int(offset)
        ) % 1440
    ) + 1


# =====================================================================
# LOAD PATTERNS
# =====================================================================

patterns = []


def get_pattern_text(item):

    if not isinstance(
        item,
        dict
    ):
        return None

    for key in (
        "pattern",
        "key",
        "name",
    ):

        value = item.get(
            key
        )

        if isinstance(
            value,
            str
        ):

            return value.strip()

    return None


def get_pattern_suit(
    item,
    fallback=None
):

    if isinstance(
        item,
        dict
    ):

        for key in (
            "suit",
            "target_suit",
            "predicted_suit",
            "target",
            "forecast_suit",
        ):

            value = item.get(
                key
            )

            suit = normalize_pattern_suit(
                value
            )

            if suit:
                return suit

    return normalize_pattern_suit(
        fallback
    )


def parse_pattern_string(
    pattern_text
):

    if not pattern_text:
        return []

    parts = pattern_text.split("|")

    result = []

    for part in parts:

        match = re.match(
            r"G(\d+)\[(.*?)\]",
            part.strip(),
        )

        if not match:
            continue

        position = int(
            match.group(1)
        )

        feature = match.group(
            2
        ).strip()

        result.append({
            "position": position,
            "feature": feature,
        })

    result.sort(
        key=lambda x: x["position"]
    )

    return result


def load_patterns():

    global patterns

    patterns = []

    if not os.path.exists(
        PATTERNS_FILE
    ):

        print(
            f"❌ Не найден "
            f"{PATTERNS_FILE}",
            flush=True,
        )

        return

    try:

        with open(
            PATTERNS_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

    except Exception as e:

        print(
            f"❌ Ошибка чтения "
            f"{PATTERNS_FILE}: {e}",
            flush=True,
        )

        return

    # ================================================================
    # LIST
    # ================================================================

    if isinstance(
        data,
        list
    ):

        for item in data:

            pattern_text = get_pattern_text(
                item
            )

            if not pattern_text:
                continue

            parsed = parse_pattern_string(
                pattern_text
            )

            if not parsed:
                continue

            suit = get_pattern_suit(
                item
            )

            if not suit:
                continue

            patterns.append({
                "pattern": pattern_text,
                "parts": parsed,
                "suit": suit,

                "occurrences": item.get(
                    "occurrences",
                    0,
                ),

                "hits": item.get(
                    "hits",
                    0,
                ),

                "rate": item.get(
                    "rate",
                    item.get(
                        "confidence",
                        0,
                    ),
                ),
            })

    # ================================================================
    # DICT
    # ================================================================

    elif isinstance(
        data,
        dict
    ):

        for key, value in data.items():

            fallback_suit = (
                normalize_pattern_suit(
                    key
                )
            )

            if not isinstance(
                value,
                list
            ):
                continue

            for item in value:

                if isinstance(
                    item,
                    str
                ):

                    pattern_text = item

                    parsed = (
                        parse_pattern_string(
                            pattern_text
                        )
                    )

                    if (
                        parsed
                        and fallback_suit
                    ):

                        patterns.append({
                            "pattern": pattern_text,
                            "parts": parsed,
                            "suit": fallback_suit,
                            "occurrences": 0,
                            "hits": 0,
                            "rate": 0,
                        })

                    continue

                if not isinstance(
                    item,
                    dict
                ):
                    continue

                pattern_text = (
                    get_pattern_text(
                        item
                    )
                )

                if not pattern_text:
                    continue

                parsed = (
                    parse_pattern_string(
                        pattern_text
                    )
                )

                if not parsed:
                    continue

                suit = get_pattern_suit(
                    item,
                    fallback_suit,
                )

                if not suit:
                    continue

                patterns.append({
                    "pattern": pattern_text,
                    "parts": parsed,
                    "suit": suit,

                    "occurrences": item.get(
                        "occurrences",
                        0,
                    ),

                    "hits": item.get(
                        "hits",
                        0,
                    ),

                    "rate": item.get(
                        "rate",
                        item.get(
                            "confidence",
                            0,
                        ),
                    ),
                })

    print("", flush=True)

    print(
        f"🧠 Загружено паттернов: "
        f"{len(patterns)}",
        flush=True,
    )

    suits_count = {}

    for pattern in patterns:

        suit = pattern[
            "suit"
        ]

        suits_count[suit] = (
            suits_count.get(
                suit,
                0
            ) + 1
        )

    for suit, count in (
        suits_count.items()
    ):

        print(
            f"   {suit}: {count}",
            flush=True,
        )


# =====================================================================
# FEATURE ENGINE
# =====================================================================

def get_card_ranks(cards):

    return [
        normalize_rank(
            c.get("rank")
        )
        for c in cards
    ]


def get_card_suits(cards):

    return [
        suit_short(
            c.get("suit")
        )
        for c in cards
    ]


def normalize_card_pattern(
    value
):

    value = str(
        value
    ).strip()

    match = re.fullmatch(
        r"(10|[6-9AJQK])"
        r"(♠️?|♣️?|♦️?|♥️?)",
        value,
    )

    if not match:
        return value

    rank = normalize_rank(
        match.group(1)
    )

    suit = normalize_suit(
        match.group(2)
    )

    if not rank or not suit:
        return value

    return (
        f"{rank}{suit}"
    )


def feature_value(
    game,
    feature
):

    if not game:
        return None

    if ":" not in feature:
        return None

    prefix, body = feature.split(
        ":",
        1,
    )

    prefix = prefix.strip().upper()
    body = body.strip()

    if prefix == "P":

        cards = game.get(
            "player_cards",
            [],
        )

    elif prefix == "D":

        cards = game.get(
            "dealer_cards",
            [],
        )

    else:

        return None

    ranks = get_card_ranks(
        cards
    )

    suits = get_card_suits(
        cards
    )

    # ================================================================
    # COUNT
    # ================================================================

    if body == "COUNT":
        return len(cards)

    if body.startswith("COUNT="):

        try:

            return (
                len(cards)
                ==
                int(
                    body.split(
                        "=",
                        1
                    )[1]
                )
            )

        except Exception:
            return False

    # ================================================================
    # FIRST
    # ================================================================

    if body == "FIRST":

        return (
            normalize_card_pattern(
                card_to_text(
                    cards[0]
                )
            )
            if cards
            else None
        )

    if body.startswith("FIRST="):

        expected = (
            body.split(
                "=",
                1
            )[1].strip()
        )

        if not cards:
            return False

        actual = normalize_card_pattern(
            card_to_text(
                cards[0]
            )
        )

        expected = normalize_card_pattern(
            expected
        )

        return actual == expected

    # ================================================================
    # FIRST_RANK
    # ================================================================

    if body == "FIRST_RANK":

        return (
            ranks[0]
            if ranks
            else None
        )

    if body.startswith(
        "FIRST_RANK="
    ):

        expected = body.split(
            "=",
            1
        )[1].strip()

        return (
            bool(ranks)
            and
            ranks[0] == expected
        )

    # ================================================================
    # FIRST_SUIT
    # ================================================================

    if body == "FIRST_SUIT":

        return (
            suits[0]
            if suits
            else None
        )

    if body.startswith(
        "FIRST_SUIT="
    ):

        expected = suit_short(
            body.split(
                "=",
                1
            )[1].strip()
        )

        return (
            bool(suits)
            and
            suits[0] == expected
        )

    # ================================================================
    # FIRST2
    # ================================================================

    if body == "FIRST2":

        if len(cards) < 2:
            return None

        return (
            f"{ranks[0]}{suits[0]},"
            f"{ranks[1]}{suits[1]}"
        )

    if body.startswith(
        "FIRST2="
    ):

        if len(cards) < 2:
            return False

        expected = body.split(
            "=",
            1
        )[1].strip()

        actual = (
            f"{ranks[0]}{suits[0]},"
            f"{ranks[1]}{suits[1]}"
        )

        expected_parts = [
            normalize_card_pattern(x)
            for x in expected.split(",")
        ]

        actual_parts = [
            normalize_card_pattern(x)
            for x in actual.split(",")
        ]

        return (
            actual_parts
            ==
            expected_parts
        )

    # ================================================================
    # FIRST2_RANKS
    # ================================================================

    if body == "FIRST2_RANKS":

        if len(ranks) < 2:
            return None

        return (
            f"{ranks[0]},"
            f"{ranks[1]}"
        )

    if body.startswith(
        "FIRST2_RANKS="
    ):

        if len(ranks) < 2:
            return False

        expected = body.split(
            "=",
            1
        )[1].strip()

        actual = (
            f"{ranks[0]},"
            f"{ranks[1]}"
        )

        return actual == expected

    # ================================================================
    # FIRST2_SUITS
    # ================================================================

    if body == "FIRST2_SUITS":

        if len(suits) < 2:
            return None

        return (
            f"{suits[0]},"
            f"{suits[1]}"
        )

    if body.startswith(
        "FIRST2_SUITS="
    ):

        if len(suits) < 2:
            return False

        expected = body.split(
            "=",
            1
        )[1].strip()

        expected_parts = [
            suit_short(
                x.strip()
            )
            for x in expected.split(",")
        ]

        return (
            suits[:2]
            ==
            expected_parts
        )

    # ================================================================
    # FIRST3
    # ================================================================

    if body == "FIRST3":

        if len(cards) < 3:
            return None

        return (
            f"{ranks[0]}{suits[0]},"
            f"{ranks[1]}{suits[1]},"
            f"{ranks[2]}{suits[2]}"
        )

    if body.startswith(
        "FIRST3="
    ):

        if len(cards) < 3:
            return False

        expected = body.split(
            "=",
            1
        )[1].strip()

        actual = (
            f"{ranks[0]}{suits[0]},"
            f"{ranks[1]}{suits[1]},"
            f"{ranks[2]}{suits[2]}"
        )

        expected_parts = [
            normalize_card_pattern(x)
            for x in expected.split(",")
        ]

        actual_parts = [
            normalize_card_pattern(x)
            for x in actual.split(",")
        ]

        return (
            actual_parts
            ==
            expected_parts
        )

    # ================================================================
    # FIRST3_RANKS
    # ================================================================

    if body == "FIRST3_RANKS":

        if len(ranks) < 3:
            return None

        return ",".join(
            ranks[:3]
        )

    if body.startswith(
        "FIRST3_RANKS="
    ):

        if len(ranks) < 3:
            return False

        expected = body.split(
            "=",
            1
        )[1].strip()

        return (
            ",".join(ranks[:3])
            ==
            expected
        )

    # ================================================================
    # FIRST3_SUITS
    # ================================================================

    if body == "FIRST3_SUITS":

        if len(suits) < 3:
            return None

        return ",".join(
            suits[:3]
        )

    if body.startswith(
        "FIRST3_SUITS="
    ):

        if len(suits) < 3:
            return False

        expected = body.split(
            "=",
            1
        )[1].strip()

        expected_parts = [
            suit_short(
                x.strip()
            )
            for x in expected.split(",")
        ]

        return (
            suits[:3]
            ==
            expected_parts
        )

    # ================================================================
    # RANKS
    # ================================================================

    if body == "RANKS":

        return ",".join(
            ranks
        )

    if body.startswith(
        "RANKS="
    ):

        expected = body.split(
            "=",
            1
        )[1].strip()

        return (
            ",".join(ranks)
            ==
            expected
        )

    # ================================================================
    # SUITS
    # ================================================================

    if body == "SUITS":

        return ",".join(
            suits
        )

    if body.startswith(
        "SUITS="
    ):

        expected = body.split(
            "=",
            1
        )[1].strip()

        expected_parts = [
            suit_short(
                x.strip()
            )
            for x in expected.split(",")
        ]

        return (
            suits
            ==
            expected_parts
        )

    # ================================================================
    # EXACT
    # ================================================================

    if body == "EXACT":

        return " ".join(
            card_to_text(c)
            for c in cards
        )

    if body.startswith(
        "EXACT="
    ):

        expected = body.split(
            "=",
            1
        )[1].strip()

        actual = " ".join(
            card_to_text(c)
            for c in cards
        )

        return (
            normalize_card_pattern(actual)
            ==
            normalize_card_pattern(expected)
        )

    # ================================================================
    # HAS
    # ================================================================

    if body == "HAS_J":
        return "J" in ranks

    if body == "HAS_Q":
        return "Q" in ranks

    if body == "HAS_K":
        return "K" in ranks

    if body == "HAS_A":
        return "A" in ranks

    return None


def feature_matches(
    game,
    feature
):

    value = feature_value(
        game,
        feature
    )

    if "=" in feature:

        if isinstance(
            value,
            bool
        ):

            return value

        return bool(value)

    return value is not None


# =====================================================================
# PATTERN MATCH
# =====================================================================

def get_game_for_position(
    trigger_number,
    position
):

    game_number = add_game_offset(
        trigger_number,
        position
    )

    return games_cache.get(
        game_number
    )


def pattern_matches(
    pattern,
    trigger_number
):

    for part in pattern["parts"]:

        position = part[
            "position"
        ]

        feature = part[
            "feature"
        ]

        game = get_game_for_position(
            trigger_number,
            position - 1
        )

        if not game:
            return False

        if not feature_matches(
            game,
            feature
        ):
            return False

    return True


# =====================================================================
# FIND MATCHING PATTERNS
# =====================================================================

def find_matching_patterns(
    trigger_number
):

    matched = []

    for pattern in patterns:

        if pattern_matches(
            pattern,
            trigger_number
        ):

            matched.append(
                pattern
            )

    return matched


def pattern_length(
    pattern
):

    if not pattern.get(
        "parts"
    ):

        return 0

    return max(
        part["position"]
        for part in pattern["parts"]
    )


# =====================================================================
# CREATE PREDICTION
# =====================================================================

def create_pattern_prediction(
    trigger_number,
    pattern
):

    length = pattern_length(
        pattern
    )

    if length <= 0:
        return None

    target_number = add_game_offset(
        trigger_number,
        length
    )

    suit = pattern[
        "suit"
    ]

    return {
        "algorithm": "pattern_suit",

        "pattern": pattern[
            "pattern"
        ],

        "pattern_suit": suit,

        "trigger_number": trigger_number,

        "pattern_length": length,

        "target_number": target_number,

        "status": "pending",

        "created_at": datetime.now(
            MOSCOW_TZ
        ).isoformat(),

        "sent_at": None,

        "message_id": None,

        "result_game": None,

        "found_card": None,

        "dogon": None,
    }


# =====================================================================
# CREATE PREDICTIONS FROM MATCH
# =====================================================================

def create_predictions_for_game(
    trigger_number
):

    matches = find_matching_patterns(
        trigger_number
    )

    if not matches:
        return

    print("", flush=True)

    print(
        f"🧠 НАЙДЕНО ПАТТЕРНОВ: "
        f"#N{trigger_number} → "
        f"{len(matches)}",
        flush=True,
    )

    grouped = {}

    for pattern in matches:

        suit = pattern[
            "suit"
        ]

        current = grouped.get(
            suit
        )

        if current is None:

            grouped[suit] = pattern
            continue

        current_key = (
            pattern_length(
                current
            ),
            current.get(
                "occurrences",
                0
            ),
        )

        new_key = (
            pattern_length(
                pattern
            ),
            pattern.get(
                "occurrences",
                0
            ),
        )

        if new_key > current_key:

            grouped[suit] = pattern

    for suit, pattern in (
        grouped.items()
    ):

        prediction = (
            create_pattern_prediction(
                trigger_number,
                pattern
            )
        )

        if not prediction:
            continue

        target_number = prediction[
            "target_number"
        ]

        prediction_key = (
            trigger_number,
            target_number,
            suit,
        )

        if (
            prediction_key
            in processed_prediction_keys
        ):
            continue

        exists = False

        for old in predictions:

            if old.get(
                "status"
            ) not in (
                "pending",
                "win",
            ):

                continue

            if (
                old.get(
                    "trigger_number"
                )
                == trigger_number
                and
                old.get(
                    "target_number"
                )
                == target_number
                and
                normalize_suit(
                    old.get(
                        "pattern_suit"
                    )
                )
                == suit
            ):

                exists = True
                break

        if exists:

            processed_prediction_keys.add(
                prediction_key
            )

            continue

        predictions.append(
            prediction
        )

        processed_prediction_keys.add(
            prediction_key
        )

        save_predictions()

        print(
            f"🎯 ПАТТЕРН → {suit}",
            flush=True,
        )

        print(
            f"📌 Триггер: "
            f"#N{trigger_number}",
            flush=True,
        )

        print(
            f"📐 Паттерн: "
            f"{pattern['pattern']}",
            flush=True,
        )

        print(
            f"🎯 Цель: "
            f"#N{target_number}",
            flush=True,
        )

        send_prediction(
            prediction
        )


# =====================================================================
# CHECK RECENT PATTERN WINDOWS
# =====================================================================

def check_patterns_ending_with(
    newest_game_number
):

    """
    Критически важная функция.

    Если пришла #N1384, а паттерн:

        G1 = #N1382
        G2 = #N1383
        G3 = #N1384

    то триггером является #N1382,
    а прогноз должен быть на #N1385.

    Поэтому после появления новой игры
    проверяем не только её как G1,
    а все возможные начала паттернов.
    """

    if not patterns:
        return

    possible_triggers = set()

    for pattern in patterns:

        length = pattern_length(
            pattern
        )

        if length <= 0:
            continue

        trigger_number = add_game_offset(
            newest_game_number,
            -(length - 1)
        )

        possible_triggers.add(
            trigger_number
        )

    for trigger_number in sorted(
        possible_triggers
    ):

        create_predictions_for_game(
            trigger_number
        )


# =====================================================================
# SEND PREDICTION
# =====================================================================

def make_prediction_message(
    prediction
):

    target = prediction[
        "target_number"
    ]

    suit = normalize_suit(
        prediction[
            "pattern_suit"
        ]
    )

    return (
        f"🎯 Игра: "
        f"<b>#N{target}</b>: "
        f"{suit}"
    )


def make_result_message(
    prediction,
    result
):

    target = prediction[
        "target_number"
    ]

    suit = normalize_suit(
        prediction[
            "pattern_suit"
        ]
    )

    if result == "win":

        mark = " ✅"

    elif result == "lose":

        mark = " ❌"

    else:

        mark = " ⚠️"

    return (
        f"🎯 Игра: "
        f"<b>#N{target}</b>: "
        f"{suit}"
        f"{mark}"
    )


def send_prediction(
    prediction
):

    message = make_prediction_message(
        prediction
    )

    message_id = telegram_send(
        message
    )

    if not message_id:

        print(
            f"❌ Не удалось отправить "
            f"#N{prediction['target_number']}",
            flush=True,
        )

        return False

    prediction[
        "message_id"
    ] = message_id

    prediction[
        "sent_at"
    ] = datetime.now(
        MOSCOW_TZ
    ).isoformat()

    save_predictions()

    print(
        f"📤 ПРОГНОЗ ОТПРАВЛЕН: "
        f"#N{prediction['target_number']} "
        f"{prediction['pattern_suit']}",
        flush=True,
    )

    return True


# =====================================================================
# CHECK SUIT IN PLAYER
# =====================================================================

def check_prediction_suit(
    game,
    prediction
):

    target_suit = normalize_suit(
        prediction.get(
            "pattern_suit"
        )
    )

    if not target_suit:
        return None

    player_cards = game.get(
        "player_cards",
        []
    )

    for card in player_cards:

        card_suit = normalize_suit(
            card.get("suit")
        )

        if card_suit == target_suit:

            return card_to_text(
                card
            )

    return None


# =====================================================================
# CHECK PREDICTIONS
# =====================================================================

def check_predictions():

    changed = False

    now = datetime.now(
        MOSCOW_TZ
    )

    for prediction in predictions:

        if prediction.get(
            "status"
        ) != "pending":

            continue

        target = prediction.get(
            "target_number"
        )

        if not target:
            continue

        # ============================================================
        # TIMEOUT
        # ============================================================

        sent_at_str = prediction.get(
            "sent_at"
        )

        if sent_at_str:

            try:

                sent_at = datetime.fromisoformat(
                    sent_at_str
                )

                if (
                    now - sent_at
                    >
                    timedelta(
                        hours=PREDICTION_TIMEOUT_HOURS
                    )
                ):

                    prediction[
                        "status"
                    ] = "void"

                    telegram_edit(
                        prediction.get(
                            "message_id"
                        ),
                        make_result_message(
                            prediction,
                            "void",
                        ),
                    )

                    print(
                        f"⚠️ VOID "
                        f"#N{target} "
                        f"(timeout)",
                        flush=True,
                    )

                    changed = True

                    continue

            except Exception:
                pass

        # ============================================================
        # MAIN + 3 DOGONS
        # ============================================================

        checked_games = []

        waiting = False

        for dogon in range(
            0,
            DOGON_GAMES + 1
        ):

            game_number = add_game_offset(
                target,
                dogon
            )

            game = games_cache.get(
                game_number
            )

            if not game:

                waiting = True

                break

            checked_games.append(
                game_number
            )

            found_card = (
                check_prediction_suit(
                    game,
                    prediction
                )
            )

            if found_card:

                prediction[
                    "status"
                ] = "win"

                prediction[
                    "result_game"
                ] = game_number

                prediction[
                    "found_card"
                ] = found_card

                prediction[
                    "dogon"
                ] = dogon

                telegram_edit(
                    prediction.get(
                        "message_id"
                    ),
                    make_result_message(
                        prediction,
                        "win"
                    ),
                )

                print("", flush=True)

                print(
                    f"✅ ПРОГНОЗ ЗАШЁЛ "
                    f"#N{target}",
                    flush=True,
                )

                print(
                    f"🎯 Масть: "
                    f"{prediction['pattern_suit']}",
                    flush=True,
                )

                print(
                    f"🃏 Карта: "
                    f"{found_card}",
                    flush=True,
                )

                print(
                    f"🔄 Догон: "
                    f"{dogon}",
                    flush=True,
                )

                changed = True

                break

        else:

            prediction[
                "status"
            ] = "lose"

            prediction[
                "result_game"
            ] = (
                checked_games[-1]
                if checked_games
                else add_game_offset(
                    target,
                    DOGON_GAMES
                )
            )

            prediction[
                "dogon"
            ] = DOGON_GAMES

            telegram_edit(
                prediction.get(
                    "message_id"
                ),
                make_result_message(
                    prediction,
                    "lose"
                ),
            )

            print("", flush=True)

            print(
                f"❌ ПРОГНОЗ НЕ ЗАШЁЛ "
                f"#N{target}",
                flush=True,
            )

            print(
                f"🎯 Масть: "
                f"{prediction['pattern_suit']}",
                flush=True,
            )

            print(
                f"🔄 Проверено: "
                f"{DOGON_GAMES + 1} игр",
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

    for game_number, info in list(
        pending_games.items()
    ):

        first_seen = info.get(
            "first_seen",
            now
        )

        if (
            now - first_seen
            >= FINALIZE_WAIT_SECONDS
        ):

            ready.append(
                game_number
            )

    for game_number in ready:

        info = pending_games.pop(
            game_number,
            None
        )

        if not info:
            continue

        text = info.get(
            "text",
            ""
        )

        game = parse_game_message(
            text
        )

        if not game:

            print(
                f"⚠️ #N{game_number} "
                f"не удалось разобрать",
                flush=True,
            )

            continue

        games_cache[
            game_number
        ] = game

        log_game(
            game
        )

        # ============================================================
        # ВАЖНО:
        #
        # Если сейчас пришла #N1384,
        # проверяется:
        #
        # G1=#N1382
        # G2=#N1383
        # G3=#N1384
        #
        # а прогноз будет #N1385.
        # ============================================================

        check_patterns_ending_with(
            game_number
        )


# =====================================================================
# UPDATE EXISTING GAME
# =====================================================================

def update_existing_game(
    game_number,
    text
):

    game = parse_game_message(
        text
    )

    if not game:
        return

    games_cache[
        game_number
    ] = game

    print(
        f"🔄 Обновлена #N{game_number}",
        flush=True,
    )

    # ---------------------------------------------------------------
    # Если это была отредактированная
    # последняя игра паттерна —
    # повторно проверяем паттерны.
    # ---------------------------------------------------------------

    check_patterns_ending_with(
        game_number
    )


# =====================================================================
# TELEGRAM UPDATES
# =====================================================================

def process_telegram_updates(
    offset
):

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

            print(
                f"❌ Telegram getUpdates: "
                f"{data}",
                flush=True,
            )

            return offset

        updates = data.get(
            "result",
            []
        )

        for update in updates:

            update_id = update.get(
                "update_id"
            )

            if update_id is not None:

                offset = (
                    update_id + 1
                )

                save_offset(
                    offset
                )

            post = (
                update.get(
                    "channel_post"
                )
                or
                update.get(
                    "edited_channel_post"
                )
            )

            if not post:
                continue

            chat = post.get(
                "chat",
                {}
            )

            chat_id = str(
                chat.get(
                    "id",
                    ""
                )
            )

            # ========================================================
            # ИГРЫ ТОЛЬКО ИЗ CHANNEL_STATS
            # ========================================================

            if chat_id != str(
                CHANNEL_STATS
            ):

                continue

            text = post.get(
                "text",
                ""
            )

            if not text:
                continue

            number_match = re.search(
                r"#N(\d+)",
                text
            )

            if not number_match:
                continue

            game_number = int(
                number_match.group(1)
            )

            # ========================================================
            # УЖЕ ОЖИДАЕТСЯ
            # ========================================================

            if (
                game_number
                in pending_games
            ):

                pending_games[
                    game_number
                ]["text"] = text

                print(
                    f"🔄 [STATS] "
                    f"Обновлена "
                    f"#N{game_number}",
                    flush=True,
                )

                continue

            # ========================================================
            # УЖЕ СОХРАНЕНА
            # ========================================================

            if (
                game_number
                in games_cache
            ):

                update_existing_game(
                    game_number,
                    text
                )

                continue

            # ========================================================
            # ЖДЁМ ФИНАЛЬНУЮ ВЕРСИЮ
            # ========================================================

            if re.search(
                r"[✅🔰]",
                text
            ):

                pending_games[
                    game_number
                ] = {
                    "first_seen": time.time(),
                    "text": text,
                }

                print("", flush=True)

                print(
                    f"👀 [STATS] "
                    f"НОВАЯ ИГРА "
                    f"#N{game_number}",
                    flush=True,
                )

                print(
                    f"⏳ Ждём "
                    f"{FINALIZE_WAIT_SECONDS} сек",
                    flush=True,
                )

    except Exception as e:

        print(
            f"⚠️ Updates error: {e}",
            flush=True,
        )

    return offset


# =====================================================================
# CLEANUP
# =====================================================================

def cleanup_games_cache():

    if (
        len(games_cache)
        <= MAX_GAMES_CACHE
    ):

        return

    numbers = sorted(
        games_cache.keys()
    )

    keep = set(
        numbers[-MAX_GAMES_CACHE:]
    )

    for number in list(
        games_cache.keys()
    ):

        if number not in keep:

            del games_cache[
                number
            ]


def cleanup_predictions():

    global predictions

    if len(
        predictions
    ) > 2000:

        predictions = (
            predictions[-2000:]
        )

        save_predictions()


# =====================================================================
# STARTUP INFO
# =====================================================================

def print_pattern_info():

    print("", flush=True)

    print(
        "==================================================",
        flush=True,
    )

    print(
        "🧠 PATTERN ENGINE",
        flush=True,
    )

    print(
        "==================================================",
        flush=True,
    )

    print(
        f"📂 Файл: "
        f"{PATTERNS_FILE}",
        flush=True,
    )

    print(
        f"🧠 Паттернов: "
        f"{len(patterns)}",
        flush=True,
    )

    print(
        f"🔄 Догонов: "
        f"{DOGON_GAMES}",
        flush=True,
    )

    print(
        "🎯 Результат: "
        "только масть игрока",
        flush=True,
    )

    print(
        "==================================================",
        flush=True,
    )


# =====================================================================
# MAIN
# =====================================================================

def main():

    global telegram_offset

    print("", flush=True)

    print(
        "==================================================",
        flush=True,
    )

    print(
        "🚀 OLD — LOW MEMORY SUIT PATTERN BOT",
        flush=True,
    )

    print(
        "==================================================",
        flush=True,
    )

    print(
        "📡 Игры: CHANNEL_STATS",
        flush=True,
    )

    print(
        "📤 Прогнозы: CHANNEL_PROGNOZ",
        flush=True,
    )

    print(
        f"⏳ Финализация игры: "
        f"{FINALIZE_WAIT_SECONDS} сек",
        flush=True,
    )

    print(
        f"🔄 Догоны: "
        f"{DOGON_GAMES}",
        flush=True,
    )

    print(
        "🎯 Проверка: "
        "масть игрока",
        flush=True,
    )

    print(
        "==================================================",
        flush=True,
    )

    # ================================================================
    # САМОЕ ВАЖНОЕ:
    #
    # Удаляем webhook перед getUpdates.
    # ================================================================

    delete_webhook()

    # ================================================================
    # LOAD
    # ================================================================

    load_patterns()

    print_pattern_info()

    load_predictions()

    telegram_offset = load_offset()

    print(
        f"📌 Telegram offset: "
        f"{telegram_offset}",
        flush=True,
    )

    print(
        f"📊 Загружено прогнозов: "
        f"{len(predictions)}",
        flush=True,
    )

    # ================================================================
    # ВОССТАНОВЛЕНИЕ КЛЮЧЕЙ
    # ================================================================

    for prediction in predictions:

        if prediction.get(
            "status"
        ) not in (
            "pending",
            "win",
        ):

            continue

        trigger = prediction.get(
            "trigger_number"
        )

        target = prediction.get(
            "target_number"
        )

        suit = normalize_suit(
            prediction.get(
                "pattern_suit"
            )
        )

        if (
            trigger is not None
            and target is not None
            and suit
        ):

            processed_prediction_keys.add(
                (
                    trigger,
                    target,
                    suit,
                )
            )

    print(
        "==================================================",
        flush=True,
    )

    print(
        "🟢 БОТ ГОТОВ",
        flush=True,
    )

    print(
        "==================================================",
        flush=True,
    )

    # ================================================================
    # MAIN LOOP
    # ================================================================

    while True:

        try:

            telegram_offset = (
                process_telegram_updates(
                    telegram_offset
                )
            )

            finalize_pending_games()

            check_predictions()

            cleanup_games_cache()

            cleanup_predictions()

            time.sleep(
                POLL_INTERVAL
            )

        except KeyboardInterrupt:

            print(
                "\n🛑 Бот остановлен",
                flush=True,
            )

            break

        except Exception as e:

            print(
                f"❌ Критическая ошибка: "
                f"{e}",
                flush=True,
            )

            time.sleep(3)


# =====================================================================
# START
# =====================================================================

if __name__ == "__main__":

    main()