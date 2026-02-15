import logging
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
import re

# Настройки
INPUT_CHANNEL_ID = -1003469691743
OUTPUT_CHANNEL_ID = -10038424013911
TOKEN = "5482422004:AAHXLYyZ-qoCsycse1k9Qt6YRi9jmB24B-k"

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Хранилище донора (в реальной реализации лучше использовать БД/Redis)
_donor_storage = {}

def get_donor(context: CallbackContext):
    return _donor_storage.get(context.chat_data["id"])

def set_donor(context: CallbackContext, donor):
    _donor_storage[context.chat_data["id"]] = donor


def norm(num: int) -> int:
    """Нормализует номер игры (если > 1440)."""
    return (num - 1) % 1440 + 1

def get_rule(donor_num: int) -> str:
    """Определяет правило замены по номеру донора."""
    if 1 <= (donor_num - 1) % 1440 + 1 <= 9:
        return "red_black"  # ♥️↔♣️, ♦️↔♠️
    elif 10 <= (donor_num - 1) % 1440 + 1 <= 19:
        return "same_color"  # ♥️↔♦️, ♣️↔♠️
    else:
        return "red_black"

def get_opposite(suit: str, rule: str) -> str:
    """Возвращает противоположную масть по правилу."""
    opposites = {
        "red_black": {"♥️": "♣️", "♦️": "♠️", "♣️": "♥️", "♠️": "♦️"},
        "same_color": {"♥️": "♦️", "♦️": "♥️", "♣️": "♠️", "♠️": "♣️"},
    }
    return opposites[rule][suit]

def parse_game(text: str) -> dict or None:
    """
    Парсит сообщение вида:
    #N1071 ✅8 (K♣️8♣️) - 2 (4♦️8♣️)
    #П1 #T10 #R🔵 #C2_2
    Возвращает dict с num, first_suit, first_two или None.
    """
    try:
        # Ищем номер игры
        num_match = re.search(r"#N(\d+)", text)
        if not num_match:
            return None
        num = int(num_match.group(1))

        # Ищем первую масть (первая карта в первой руке)
        suit_match = re.search(r"\(([A2-9TJQK][♥️♦️♣️♠️])", text)
        if not suit_match:
            return None
        first_suit = suit_match.group(1)[1]  # извлекаем символ масти


        # Ищем первые две масти в первой руке
        two_suits = re.findall(r"[A2-9TJQK]([♥️♦️♣️♠️)", text.split("-")[0])
        first_two = [s[0] for s in two_suits[:2]]  # первые две масти

        return {"num": num, "first_suit": first_suit, "first_two": first_two}
    except Exception as e:
        logger.error(f"Error parsing game: {e}")
        return None

async def handle_game(update: Update, context: CallbackContext):
    if not update.channel_post or update.channel_post.chat_id != INPUT_CHANNEL_ID:
        return

    game = parse_game(update.channel_post.text)
    if not game:
        logger.info(f"Failed to parse message: {update.channel_post.text}")
        return

    num = game["num"]
    logger.info(f"📥 Игра {num}, первая масть {game['first_suit']}, message_id={update.channel_post.message_id}")


    donor = get_donor(context)

    # 1. Если нет донора и игра нечётная — запоминаем как донор
    if donor is None and num % 2 == 1:
        set_donor(
            context,
            {
                "num": num,
                "suit": game["first_suit"],
                "checked_n3": False,  # ещё не проверяли N+3
                "repeated": False,     # пока нет повтора
            },
        )
        logger.info("📌 Донор %d запомнен, масть %s", num, game["first_suit"])
        return

    # 2. Если есть донор, проверяем N+3
    if donor and not donor["checked_n3"]:
        if num == donor["num"] + 3:
            # Проверяем, есть ли масть донора в первых двух картах
            if donor["suit"] in game["first_two"]:
                donor["repeated"] = True
            donor["checked_n3"] = True
            set_donor(context, donor)

    # 3. Если дошли до N+4 и был повтор — выдаём прогноз
    if num == donor["num"] + 4 and donor["repeated"]:
        rule = get_rule(donor["num"])
        target_suit = get_opposite(donor["suit"], rule)
        target = norm(num)  # цель: N+4 (уже нормализовано)

        msg = (
    f"🎯 ПРОГНОЗ\n"
    f"Игра: #{target}\n"
    f"Прогноз: {target_suit}"
        )
        await context.bot.send_message(chat_id=OUTPUT_CHANNEL_ID, text=msg)
        logger.info("✅ Прогноз на %d: %s", target, target_suit)

    # 4. Сбрасываем донора после обработки N+4 (или если пропустили)
    if num >= donor["num"] + 4:
        set_donor(context, None)


def main():
    application = Application.builder().token(TOKEN).build()

    # Обработчик сообщений из канала
    application.add_handler(MessageHandler(filters.TEXT & filters.Chat(INPUT_CHANNEL_ID), handle_game))


    application.run_polling()

if __name__ == "__main__":
    main()
