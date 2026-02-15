import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CallbackContext
import re

# Настройки
INPUT_CHANNEL_ID = -1003469691743
OUTPUT_CHANNEL_ID = -10038424013911
TOKEN = "5482422004:AAHXLYyZ-qoCsycse1k9Qt6YRi9jmB24B-k"

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Хранилище донора
_donor_storage = {}

def get_donor(chat_id: int) -> dict or None:
    """Получает донора по ID чата."""
    return _donor_storage.get(chat_id)

def set_donor(chat_id: int, donor: dict or None):
    """Сохраняет донора для чата."""
    if donor is None:
        _donor_storage.pop(chat_id, None)
    else:
        _donor_storage[chat_id] = donor

def norm(num: int) -> int:
    """Нормализует номер игры (если > 1440)."""
    return (num - 1) % 1440 + 1

def is_in_main_range(num: int) -> bool:
    """Проверяет, входит ли номер в диапазоны 1-9, 20-29, 40-49, ..., 1440."""
    # Первый диапазон: 1–9
    if 1 <= num <= 9:
        return True
    # Остальные: числа вида 20+20k до 29+20k
    if num >= 20:
        normalized = num % 20
        return 0 <= normalized <= 9 and num <= 1440
    return False

def get_opposite_custom(suit: str) -> str:
    """Кастомное правило: ♥️→♣️, ♦️→♠️, ♠️→♦️, ♣️→♥️."""
    mapping = {
        "♥️": "♣️",
        "♦️": "♠️",
        "♠️": "♦️",
        "♣️": "♥️"
    }
    return mapping.get(suit, suit)

def get_opposite(suit: str, rule: str) -> str:
    """Возвращает противоположную масть по правилу."""
    opposites = {
        "red_black": {"♥️": "♣️", "♦️": "♠️", "♣️": "♥️", "♠️": "♦️"},
        "custom_rule": {"♥️": "♣️", "♦️": "♠️", "♠️": "♦️", "♣️": "♥️"}
    }
    return opposites[rule][suit]

def get_rule(donor_num: int) -> str:
    """Определяет правило замены по номеру донора."""
    normalized_num = norm(donor_num)
    if is_in_main_range(normalized_num):
        return "custom_rule"
    else:
        return "red_black"

def parse_game(text: str) -> dict or None:
    """Парсит сообщение вида #N1071 ✅8 (K♣️8♣️) - 2 (4♦️8♣️)."""
    try:
        num_match = re.search(r"#N(\d+)", text)
        if not num_match:
            logger.debug(f"Не найден номер игры в: {text}")
            return None
        num = int(num_match.group(1))

        first_hand = text.split("-")[0]
        suit_match = re.search(r"[A2-9TJQK]([♥️♦️♣️♠️)", first_hand)
        if not suit_match:
            logger.debug(f"Не найдена первая масть в: {first_hand}")
            return None
        first_suit = suit_match.group(1)

        two_suits = re.findall(r"[A2-9TJQK]([♥️♦️♣️♠️)", first_hand)
        first_two = [s for s in two_suits[:2]]

        return {"num": num, "first_suit": first_suit, "first_two": first_two}
    except Exception as e:
        logger.error(f"Ошибка парсинга: {e}, текст: {text}")
        return None

async def debug_handler(update: Update, context: CallbackContext):
    """Отладочный обработчик — показывает все входящие сообщения."""
    if update.channel_post:
        chat_id = update.channel_post.chat_id
        text = update.channel_post.text
        logger.info(f"[DEBUG] Получено сообщение из канала {chat_id}: {text}")

async def handle_game(update: Update, context: CallbackContext):
    """Основной обработчик сообщений из канала."""
    if not update.channel_post:
        logger.info("Не канал, пропускаем")
        return

    chat_id = update.channel_post.chat_id
    logger.info(f"Получено сообщение из чата: {chat_id}")

    if chat_id != INPUT_CHANNEL_ID:
        logger.info(f"Сообщение не из целевого канала: {chat_id}, ожидаем: {INPUT_CHANNEL_ID}")
        return

    game = parse_game(update.channel_post.text)
    if not game:
        logger.info(f"❌ Не удалось распарсить сообщение: {update.channel_post.text}")
        return

    num = game["num"]
    normalized_num = norm(num)

    logger.info(f"📥 Получено: #{num} (нормализовано до {normalized_num}), масти: {game['first_two']}")

    donor = get_donor(chat_id)

    # 1. Если нет донора и игра нечётная — запоминаем как донор
    if donor is None and num % 2 == 1:
        set_donor(
            chat_id,
            {
                "num": num,
                "suit": game["first_suit"],
                "checked_n3": False,
                "repeated": False,
            },
        )
        logger.info(f"📌 Донор #{num} запомнен, масть {game['first_suit']}")
        return

    # 2. Если есть донор, проверяем N+3
    if donor and not donor["checked_n3"]:
        if num == donor["num"] + 3:
            if donor["suit"] in game["first_two"]:
                donor["repeated"] = True
            donor["checked_n3"] = True
            set_donor(chat_id, donor)

    # 3. Если дошли до N+4 и был повтор — выдаём прогноз
    if num == donor["num"] + 4 and donor["repeated"]:
        rule = get_rule(donor["num"])

        if rule == "custom_rule":
            target_suit = get_opposite_custom(donor["suit"])
        else:
            target_suit = get_opposite(donor["suit"], rule)

        target = norm(num)

        msg = (
            f"🎯 ПРОГНОЗ\n"
            f"Игра: #{target}\n"
            f"Прогноз: {target_suit}\n"
            f"Правило: {rule}"
        )
        try:
            await context.bot.send_message(chat_id=OUTPUT_CHANNEL_ID, text=msg)
            logger.info(f"✅ Прогноз на #{target}: {target_suit} (правило: {rule})")
        except Exception as e:
            logger.error(f"Ошибка отправки прогноза: {e}")

async def start_command(update: Update, context: CallbackContext):
    """Обработчик команды /start."""
    await update.message.reply_text("Бот запущен и готов к работе!")

def main():
    """Основная функция запуска бота."""
    application = Application.builder().token(TOKEN).build()

    # Обработчики
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_game))
    # Отладочный обработчик (можно закомментировать в продакшене)
    application.add_handler(MessageHandler(filters.ALL, debug_handler))

    # Запуск бота
    logger.info("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()
