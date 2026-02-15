import logging
import re
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CallbackContext

# Настройки
INPUT_CHANNEL_ID = -1003469691743  # ID входного канала
OUTPUT_CHANNEL_ID = -1003842401391  # ID выходного канала
TOKEN = "5482422004:AAHXLYyZ-qoCsycse1k9Qt6YRi9jmB24B-k"

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG
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
    normalized = (num - 1) % 1440 + 1
    logger.debug(f"Нормализация: {num} → {normalized}")
    return normalized

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
    result = mapping.get(suit, suit)
    logger.debug(f"Кастомное правило: {suit} → {result}")
    return result

def get_opposite(suit: str, rule: str) -> str:
    """Возвращает противоположную масть по правилу."""
    opposites = {
        "red_black": {"♥️": "♣️", "♦️": "♠️", "♣️": "♥️", "♠️": "♦️"},
        "custom_rule": {"♥️": "♣️", "♦️": "♠️", "♠️": "♦️", "♣️": "♥️"}
    }
    result = opposites[rule][suit]
    logger.debug(f"Правило {rule}: {suit} → {result}")
    return result

def get_rule(donor_num: int) -> str:
    """Определяет правило замены по номеру донора."""
    normalized_num = norm(donor_num)
    in_range = is_in_main_range(normalized_num)
    rule = "custom_rule" if in_range else "red_black"
    logger.debug(f"Номер {donor_num} (нормализовано: {normalized_num}) → в диапазоне: {in_range} → правило: {rule}")
    return rule

def parse_baccarat_message(text: str) -> dict or None:
    """Парсит сообщение с игрой Baccarat."""
    logger.debug(f"Парсинг сообщения: {text}")

    # Улучшенный шаблон для парсинга всех вариантов сообщений
    pattern = r'#N(\d+)\.\s*(\d+)\([^)]*\)(?:\s*🔰\s*\d+\([^)]*\))?\s*-?\s*✅?(\d+)\([^)]*\)\s*#T(\d+)'
    match = re.search(pattern, text)

    if match:
        game_data = {
            'number': int(match.group(1)),
            'player_score': match.group(2),
            'bankerscore': match.group(3),
            'table': match.group(4)
        }
        logger.info(f"Игра распознана: {game_data}")
        return game_data
    else:
        logger.warning(f"Сообщение не соответствует формату игры: {text}")
        return None

async def handle_game(update: Update, context: CallbackContext):
    """Обрабатывает сообщения с играми."""
    # Проверяем, что сообщение из нужного канала
    if update.message.chat_id != INPUT_CHANNEL_ID:
        return

    text = update.message.text
    game_data = parse_baccarat_message(text)

    if game_data:
        # Сохраняем как донора, если это первая игра
        if not get_donor(update.message.chat_id):
            set_donor(update.message.chat_id, game_data)
            logger.info(f"Установлен донор: игра #{game_data['number']}")

        # Здесь ваша логика обработки игры
        # Например, отправка в выходной канал
        output_message = f"Распознана игра #{game_data['number']}: Player {game_data['playerscore']} - Banker {game_data['bankerscore']} (Table {game_data['table']})"
        await context.bot.send_message(chat_id=OUTPUT_CHANNEL_ID, text=output_message)

async def debug_handler(update: Update, context: CallbackContext):
    """Отладочный обработчик — показывает все получаемые сообщения."""
    message_text = update.message.text
    chat_id = update.message.chat_id
    logger.info(f"Получено сообщение из чата {chat_id}: {message_text}")

async def start_command(update: Update, context: CallbackContext):
    """Обработчик команды /start."""
    await update.message.reply_text("Бот запущен и готов к работе!")

def main():
    """Основная функция запуска бота."""
    try:
        application = Application.builder().token(TOKEN).build()

        # Обработчики
        application.add_handler(CommandHandler("start", start_command))
        # Сначала отладочный обработчик (можно закомментировать после отладки)
        application.add_handler(MessageHandler(filters.TEXT, debug_handler))
        # Основной обработчик игр
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_game))

        logger.info("Бот запускается...")
        application.run_polling()
    except Exception as e:
        if "Conflict" in str(e):
            logger.error("❌ Ошибка конфликта: уже запущен другой экземпляр бота!")
            logger.error("Убедитесь, что только один экземпляр запущен.")
        else:
            logger.error(f"Неизвестная ошибка: {e}")


if __name__ == "__main__":
    main()
