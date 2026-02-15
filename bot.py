# -*- coding: utf-8 -*-
import logging
import re
import os
import requests
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# ==================== НАСТРОЙКИ (только из env) ====================
TOKEN = os.getenv("5482422004:AAHXLYyZ-qoCsycse1k9Qt6YRi9jmB24B-k")
INPUT_CHANNEL_ID = os.getenv("-1003469691743")
OUTPUT_CHANNEL_ID = os.getenv("-1003855079501")
ADMIN_ID = os.getenv("683219603")

# Проверка обязательных переменных
if not TOKEN:
    raise ValueError("Ошибка: TOKEN не задан в переменных окружения")
if not INPUT_CHANNEL_ID:
    raise ValueError("Ошибка: INPUT_CHANNEL_ID не задан в переменных окружения")
if not OUTPUT_CHANNEL_ID:
    raise ValueError("Ошибка: OUTPUT_CHANNEL_ID не задан в переменных окружения")
if not ADMIN_ID:
    raise ValueError("Ошибка: ADMIN_ID не задан в переменных окружения")

# Приведение к нужным типам
INPUT_CHANNEL_ID = int(INPUT_CHANNEL_ID)
OUTPUT_CHANNEL_ID = int(OUTPUT_CHANNEL_ID)
ADMIN_ID = int(ADMIN_ID)

MAX_GAME_NUMBER = 1440  # Макс. номер игры (не меняется)

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== ХРАНИЛИЩЕ (через context.bot_data) ====================
def get_donor(context: CallbackContext):
    return context.bot_data.get('donor')

def set_donor(context: CallbackContext, donor):
    context.bot_data['donor'] = donor

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def norm(num):
    """Приводит номер игры в диапазон 1..MAX_GAME_NUMBER."""
    while num > MAX_GAME_NUMBER:
        num -= MAX_GAME_NUMBER
    while num < 1:
        num += MAX_GAME_NUMBER
    return num

def get_rule(game_num):
    """Определяет правило: чередование каждые 10 игр."""
    start = (game_num // 10) * 10
    return 'red_black' if (start % 20 == 0) else 'same_color'

def get_opposite(suit, rule):
    """Возвращает противоположную масть по правилу."""
    if rule == 'red_black':
        return {'♥️': '♣️', '♣️': '♥️', '♦️': '♠️', '♠️': '♦️'}.get(suit, suit)
    else:  # same_color
        return {'♥️': '♦️', '♦️': '♥️', '♠️': '♣️', '♣️': '♠️'}.get(suit, suit)

# ==================== ПАРСИНГ СООБЩЕНИЯ ====================
def parse_game(text):
    """
    Извлекает номер игры и масти из текста.
    Возвращает dict или None, если парсинг не удался.
    """
    # Ищем номер игры #N123
    match = re.search(r'#N(\d+)', text)
    if not match:
        logger.warning("Не найден номер игры в сообщении: %s", text)
        return None

    try:
        game_num = int(match.group(1))
        if game_num <= 0:
            logger.warning("Номер игры <= 0: %d", game_num)
            return None
    except ValueError:
        logger.warning("Некорректный номер игры: %s", match.group(1))
        return None

    # Ищем часть до разделителя (-, 👉👈, 👈👉)
    left = text
    for sep in ['-', '👉👈', '👈👉']:
        if sep in text:
            left = text.split(sep)[0].strip()
            break

    # Ищем карты в скобках (10♥️ K♠ ...)
    cards_match = re.search(r'\(([^)]+)\)', left)
    if not cards_match:
        logger.warning("Не найдены карты в сообщении: %s", text)
        return None

    # Извлекаем масти
    suits = []
    for card in re.findall(r'([\dAKQJ]+[♥♠♣♦]?)', cards_match.group(1)):
        if '♥' in card:
            suits.append('♥️')
        elif '♠' in card:
            suits.append('♠️')
        elif '♣' in card:
            suits.append('♣️')
        elif '♦' in card:
            suits.append('♦️')

    if not suits:
        logger.warning("Не извлечены масти из сообщения: %s", text)
        return None

    return {
        'num': game_num,
        'first_suit': suits[0],
        'first_two': suits[:2]  # Первые две масти
    }

# ==================== ОБРАБОТКА СООБЩЕНИЙ ====================
def handle_game(update: Update, context: CallbackContext):
    """Обрабатывает пост в канале."""
    # Проверяем, что это пост из нужного канала
    if (not update.channel_post 
            or update.channel_post.chat_id != INPUT_CHANNEL_ID):
        return

    # Парсим сообщение
    game = parse_game(update.channel_post.text)
    if not game:
        return  # Парсинг не удался — молча игнорируем

    num = game['num']
    logger.info("📥 Игра %d, первая масть %s (message_id=%d)",
                num, game['first_suit'], update.channel_post.message_id)

    donor = get_donor(context)

    # Если нет донора и игра нечётная — запоминаем
    if donor is None and num % 2 == 1:
        donor_data = {'num': num, 'suit': game['first_suit']}
        set_donor(context, donor_data)
        logger.info("📌 Донор %d запомнен, масть %s", num, game['first_suit'])
        return

    # Если есть донор и текущая игра — контроль (донор + 3)
    if donor and num == norm(donor['num'] + 3):
        if donor['suit'] in game['first_two']:
            # Формируем прогноз
            target = norm(num + 2)
            rule = get_rule(donor['num'])
            target_suit = get_opposite(donor['suit'], rule)

            msg = (
                f"🎯 ПРОГНОЗ\n"
                f"Донор: #{donor['num']} ({donor['suit']})\n"
                f"Цель: #{target}\n"
                f"Ставка: {target_suit}"
            )
            context.bot.send_message(chat_id=OUTPUT_CHANNEL_ID, text=msg)
            logger.info("✅ Прогноз на %d: %s", target, target_suit)
        else:
            logger.info("❌ Масть %s не подтвердилась в игре %d", donor['suit'], num)

        # Сбрасываем донора
        set_donor(context, None)

# ==================== КОМАНДЫ ====================
def start(update: Update, context: CallbackContext):
    """Команда /start — только для админа."""
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("⛔ Доступ запрещён")
        return
        
                update.message.reply_text(
            "✅ Бот запущен. Схема работы:\n"
            "1. Нечётная игра → запоминается как донор\n"
            "2. Через 3 игры (контроль) → проверка наличия масти донора\n"
            "3. Через 2 игры после контроля → выдача прогноза"
        )

# ==================== ЗАПУСК БОТА ====================
def main():
    """Точка входа. Настройка и запуск бота."""
    # Попытка сбросить webhook (на случай, если он был установлен ранее)
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True"
        )
        if response.status_code != 200:
            logger.error(f"Не удалось сбросить webhook: HTTP {response.status_code}, ответ: {response.text}")
        else:
            logger.info("Webhook сброшен (если был установлен)")
    except Exception as e:
        logger.error(f"Ошибка при сбросе webhook: {e}")

    # Инициализация бота
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # Регистрация обработчиков
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(
        MessageHandler(
            Filters.chat(INPUT_CHANNEL_ID) & Filters.text & ~Filters.command,
            handle_game
        )
    )

    logger.info("🤖 Бот запущен")
    print("\n🤖 БОТ ЗАПУЩЕН")
    print("✅ Логика: нечётная донор → контроль N+3 → цель N+5")

    # Запуск polling
    updater.start_polling(allowed_updates=['channel_post'])
    updater.idle()

if __name__ == "__main__":
    main()
