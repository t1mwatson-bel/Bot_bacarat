import re

from datetime import datetime

from config import (
    CARD_VALUES,
    SUITS,
    SUIT_ALIASES,
    DIGIT_RANKS,
    GAME_CYCLE,
    TARGET_OFFSET,
    MOSCOW_TZ,
)


# =====================================================================
# РЕГУЛЯРКА ДЛЯ КАРТ: 10 / 2-9 / A J Q K + масть
# =====================================================================

CARD_RE = re.compile(
    r"(10|[2-9AJQK])\s*"
    r"(\u2660|\u2663|\u2666|\u2665)"
    r"\ufe0f?"
)


# =====================================================================
# НОРМАЛИЗАЦИЯ
# =====================================================================

def normalize_suit(suit):
    """Приводит масть к единому виду: ♠️ ♣️ ♦️ ♥️"""

    if suit is None:
        return None

    value = str(suit).strip()

    if value in SUIT_ALIASES:
        return SUIT_ALIASES[value]

    value = value.replace("\ufe0f", "")

    return SUITS.get(value)


def normalize_rank(rank):
    """Приводит ранг карты к единому виду: 2-10, J, Q, K, A."""

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


# =====================================================================
# КАРТЫ → ТЕКСТ
# =====================================================================

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
# СЧЁТ CYBER 21
# =====================================================================

def cyber21_score(cards):
    """Считает сумму очков по правилам Cyber 21 (J=2, Q=3, K=4, A=11)."""

    total = 0

    for card in cards:
        rank = normalize_rank(card.get("rank"))
        if rank in CARD_VALUES:
            total += CARD_VALUES[rank]

    return total


# =====================================================================
# ПАРСИНГ КАРТ ИЗ ТЕКСТА
# =====================================================================

def parse_cards(text):
    """Извлекает все карты из строки."""

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
# ПАРСИНГ ИГРОВОГО СООБЩЕНИЯ
# =====================================================================

def parse_game_message(text):
    """
    Разбирает сообщение вида:
    #N1411 ✅9 (5♣️K♥️4♥️) - 7 (10♥️7♣️) #П1 #T16 (ID: 758978530)

    Возвращает dict с полями:
      game_number, game_id,
      player_cards, dealer_cards,
      player_score, dealer_score,
      is_draw, is_ochko,
      raw_text, received_at
    """

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
# ЛОГ ИГРЫ (вывод в консоль)
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
# СДВИГ НОМЕРА ИГРЫ
# =====================================================================

def add_game_offset(number, offset):
    """Прибавляет сдвиг к номеру игры с учётом цикла."""

    return ((int(number) - 1 + int(offset)) % GAME_CYCLE) + 1


# =====================================================================
# ТРИГГЕР: 3 КАРТЫ ИГРОКА, 1-Я И 3-Я ЦИФРЫ, 1-Я > 3-Я
# =====================================================================

def find_trigger(game):
    """
    Проверяет, есть ли триггер в игре.

    Условия:
      - у игрока ровно 3 карты
      - 1-я карта — цифра 2..9
      - 3-я карта — цифра 2..9
      - 1-я карта СТАРШЕ 3-й (по номиналу)

    Возвращает dict {'trigger_card', 'predicted_suit'} или None.
    """

    player = game.get("player_cards", [])

    if len(player) != 3:
        return None

    first = player[0]
    third = player[2]

    first_rank = normalize_rank(first.get("rank"))
    third_rank = normalize_rank(third.get("rank"))

    # Обе карты должны быть цифрами 2..9
    if first_rank not in DIGIT_RANKS:
        return None

    if third_rank not in DIGIT_RANKS:
        return None

    # Первая должна быть СТАРШЕ третьей
    if int(first_rank) <= int(third_rank):
        return None

    predicted_suit = normalize_suit(third.get("suit"))

    if not predicted_suit:
        return None

    return {
        "trigger_card": card_to_text(first),
        "third_card": card_to_text(third),
        "predicted_suit": predicted_suit,
    }


# =====================================================================
# ПОИСК МАСТИ У ИГРОКА
# =====================================================================

def find_suit_in_player(game, suit):
    """
    Ищет масть у игрока (левые скобки).
    Возвращает текст карты или None.
    """

    target = normalize_suit(suit)

    if not target:
        return None

    for card in game.get("player_cards", []):
        if normalize_suit(card.get("suit")) == target:
            return card_to_text(card)

    return None