import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CallbackContext
import re

# Настройки
INPUT_CHANNEL_ID = -1003469691743
OUTPUT_CHANNEL_ID = -1003842401391
TOKEN = "5482422004:AAHXLYyZ-qoCsycse1k9Qt6YRi9jmB24B-k"

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Хранилище донора (в реальной реализации лучше использовать БД/Redis)
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

def get_rule(donor_num: int) -> str:
    """Определяет правило замены по номеру донора."""
    normalized_num = (donor_num - 1) % 1440 + 1
    if 1 <= normalized_num <= 9:
        return "red_black"  # ♥️↔♣️, ♦️↔♠️
    elif 10 <= normalized_num <= 19:
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
            logger.debug(f"Не найден номер игры в: {text}")
            return None
        num = int(num_match.group(1))

        # Ищем первую карту в первой руке (после первой скобки)
        first_hand = text.split("-")[0]
        suit_match = re.search(r"[A2-9TJQK]([♥️♦️♣️♠️)", first_hand)
        if not suit_match:
            logger.debug(f"Не найдена первая масть в: {first_hand}")
            return None
        first_suit = suit_match.group(1)

        # Первые две масти в первой руке
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
    logger.info(f"📥 Игра {num}, первая масть {game['first_suit']}, message_id={update.channel_post.message_id}")

    donor = get_donor(chat_id)  # используем ID чата

    # 1. Если нет донора и игра нечётная — запоминаем как донор
    if donor is None and num % 2 == 1:
        set_donor(
            chat_id,
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
            set_donor(chat_id, donor)

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
        try:
            await context.bot.send_message(chat_id=OUTPUT_CHANNEL_ID, text=msg)
            logger.info("✅ Прогноз на %d: %s", target, target_suit)
        except Exception as e:
            logger.error("Ошибка отправки прогноза: %s", e)

    # 4. Сбрасываем донора после обработки N+4
    if num >= donor["num"] + 4:
        set_donor(chat_id, None)

async def error_handler(update: object, context: CallbackContext) -> None:
    """Обработчик ошибок бота."""
    logger.error("Исключение при обработке обновления %s: %s", update, context.error)

def main():
    """Основная функция запуска бота."""
    application = Application.builder().token(TOKEN).build()

    # Добавляем обработчик ошибок
    application.add_error_handler(error_handler)

    # Отладочный обработчик (

async def error_handler(update: object, context: CallbackContext) -> None:
    """Обработчик ошибок бота."""
    logger.error("Исключение при обработке обновления %s: %s", update, context.error)

def main():
    """Основная функция запуска бота."""
    application = Application.builder().token(TOKEN).build()

    # Добавляем обработчик ошибок
    application.add_error_handler(error_handler)

    # Отладочный обработчик (группа 0 — выполняется первым)
    application.add_handler(MessageHandler(filters.TEXT, debug_handler), group=0)

    # Основной обработчик сообщений из канала
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Chat(INPUT_CHANNEL_ID),
            handle_game
        ),
        group=1
    )

    # Команда для проверки статуса бота
    async def status_command(update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        donor = get_donor(chat_id)
        if donor:
            status_msg = (
                f"🤖 Статус бота:\n"
                f"Донор: #{donor['num']} ({donor['suit']})\n"
                f"Проверен N+3: {donor['checked_n3']}\n"
                f"Был повтор: {donor['repeated']}"
            )
        else:
            status_msg = "🤖 Статус бота: донор не установлен"
        await update.message.reply_text(status_msg)

    application.add_handler(CommandHandler("status", status_command))

    # Команда для сброса донора
    async def reset_command(update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        set_donor(chat_id, None)
        await update.message.reply_text("🔄 Донор сброшен")

    application.add_handler(CommandHandler("reset", reset_command))

    logger.info("Бот запущен. Ожидание сообщений...")

    try:
        application.run_polling()
    except Exception as e:
        logger.critical("Критическая ошибка при запуске бота: %s", e)

if __name__ == "__main__":
    # Дополнительная проверка ID каналов перед запуском
    print("=" * 50)
    print("ЗАПУСК БОТА")
    print(f"Входной канал ID: {INPUT_CHANNEL_ID}")
    print(f"Выходной канал ID: {OUTPUT_CHANNEL_ID}")
    print(f"Токен: {TOKEN[:10]}...{TOKEN[-5:]}")  # Показываем только начало и конец токена
    print("=" * 50)

    # Проверка корректности ID каналов
    if abs(INPUT_CHANNEL_ID) < 10**12 or abs(INPUT_CHANNEL_ID) > 10**14:
        logger.warning("⚠️ Внимание: длина INPUT_CHANNEL_ID кажется нестандартной")
    if abs(OUTPUT_CHANNEL_ID) < 10**12 or abs(OUTPUT_CHANNEL_ID) > 10**14:
        logger.warning("⚠️ Внимание: длина OUTPUT_CHANNEL_ID кажется нестандартной")

    main()
