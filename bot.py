# -*- coding: utf-8 -*-
import logging
import re
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import os
import requests  # для сброса вебхука

# ==================== НАСТРОЙКИ ====================
TOKEN = os.getenv("TOKEN", "1163348874:AAFgZEXveILvD4MbhQ8jiLTwIxs4puYhmq0")
INPUT_CHANNEL_ID = int(os.getenv("INPUT_CHANNEL_ID", "-1003469691743"))
OUTPUT_CHANNEL_ID = int(os.getenv("OUTPUT_CHANNEL_ID", "-1003842401391"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "683219603"))

# ==================== ЛОГИРОВАНИЕ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== ХРАНИЛИЩЕ ИГР ====================
last_donor = None  # {'num': int, 'first_suit': str, 'range_type': str}


# ==================== РАБОЧИЕ ДИАПАЗОНЫ ====================
def is_working_range(game_num):
    """
    Проверяет, входит ли игра в рабочие диапазоны.
    Диапазоны: 1-9, 30-39, 60-69, 90-99, 120-129, 150-159, 180-189, 210-219, ...
    """
    # Остаток от деления на 30 определяет блок
    remainder = game_num % 30
    if remainder == 0:
        # Игры типа 30, 60, 90... — последние в диапазоне, проверяем отдельно
        return (game_num // 30) % 2 == 1  # нечётные блоки: 30, 90, 150...
    
    # Для остальных проверяем, попадают ли они в первые 9 игр блока
    block_start = (game_num // 30) * 30
    if block_start == 0:
        # Особый случай для 1-9
        return 1 <= game_num <= 9
    else:
        # Для блоков 30-39, 60-69 и т.д.
        return block_start + 1 <= game_num <= block_start + 9


def get_range_type(game_num):
    """
    Определяет тип диапазона по номеру игры.
    type1: 1-9, 30-39, 60-69, 90-99, 120-129... (правило ♥️↔♣️, ♦️↔♠️)
    type2: 10-19, 40-49, 70-79, 100-109, 130-139... (правило красная↔красная, чёрная↔чёрная)
    """
    if not is_working_range(game_num):
        return None
    
    # Определяем блок
    if game_num <= 9:
        return 'type1'
    
    block_start = (game_num // 30) * 30
    if block_start in (30, 60, 90, 120, 150, 180, 210):
        # Для блоков 30-39, 60-69, 90-99, 120-129, 150-159, 180-189, 210-219
        if game_num <= block_start + 9:
            return 'type1'
    
    # Если не подошло под type1, значит type2
    return 'type2'


def get_opposite_suit(suit, range_type):
    """
    Возвращает противоположную масть по правилам диапазона.
    """
    if range_type == 'type1':
        # Правило: ♥️↔♣️, ♦️↔♠️
        if suit == '♥️':
            return '♣️'
        elif suit == '♣️':
            return '♥️'
        elif suit == '♦️':
            return '♠️'
        elif suit == '♠️':
            return '♦️'
    elif range_type == 'type2':
        # Правило: красная↔красная, чёрная↔чёрная
        if suit == '♥️':
            return '♦️'
        elif suit == '♦️':
            return '♥️'
        elif suit == '♠️':
            return '♣️'
        elif suit == '♣️':
            return '♠️'
    return suit  # на всякий случай


# ==================== ПАРСИНГ ИГРЫ ====================
def parse_game(text):
    """
    Извлекает из текста игры:
    - номер игры
    - первую карту игрока (левую руку)
    - первые две карты игрока (для контроля)
    Возвращает словарь или None, если не удалось распарсить.
    """
    if not text or '✅' not in text:
        return None
    
    match = re.search(r'#N(\d+)', text)
    if not match:
        return None
    game_num = int(match.group(1))
    
    # Находим левую часть (игрок) до разделителя
    left_part = text
    if '-' in text:
        left_part = text.split('-')[0].strip()
    
    # Ищем карты в скобках
    cards_match = re.search(r'\(([^)]+)\)', left_part)
    if not cards_match:
        return None
    
    cards_text = cards_match.group(1)
    
    # Извлекаем все карты (может быть 2 или 3)
    cards = cards_text.split()
    if not cards:
        return None
    
    # Извлекаем масти из карт
    suits = []
    for card in cards:
        if '♥' in card:
            suits.append('♥️')
        elif '♠' in card:
            suits.append('♠️')
        elif '♣' in card:
            suits.append('♣️')
        elif '♦' in card:
            suits.append('♦️')
    
    if len(suits) == 0:
        return None
    
    return {
        'num': game_num,
        'first_suit': suits[0],
        'first_two_suits': suits[:2] if len(suits) >= 2 else suits,
        'all_suits': suits,
        'text': text
    }


# ==================== ОСНОВНАЯ ЛОГИКА ====================
def handle_new_game(update: Update, context: CallbackContext):
    global last_donor
    
    try:
        if not update.channel_post or update.channel_post.chat_id != INPUT_CHANNEL_ID:
            return
        
        text = update.channel_post.text
        logger.info(f"📥 Получено: {text[:100]}...")
        
        game = parse_game(text)
        if not game:
            return
        
        game_num = game['num']
        logger.info(f"✅ Распарсена игра #{game_num}, масти: {game['first_two_suits']}")
        
        # Проверяем, входит ли игра в рабочий диапазон
        if not is_working_range(game_num):
            logger.info(f"⏭️ Игра #{game_num} вне рабочего диапазона")
            return
        
        # Если игра нечётная — это потенциальный донор
        if game_num % 2 == 1:
            # Сохраняем как донора
            last_donor = {
                'num': game_num,
                'first_suit': game['first_suit'],
                'range_type': get_range_type(game_num)
            }
            logger.info(f"📌 Запомнен донор #{game_num} с мастью {game['first_suit']}")
            return
        
        # Если игра чётная и у нас есть донор — проверяем, не контрольная ли это
        if last_donor and game_num == last_donor['num'] + 3:
            logger.info(f"🔍 Найден контроль #{game_num} для донора #{last_donor['num']}")
            
            # Проверяем, есть ли масть донора в первых двух картах игрока
            if last_donor['first_suit'] in game['first_two_suits']:
                logger.info(f"✅ Масть {last_donor['first_suit']} подтвердилась!")
                
                # Определяем целевую игру (следующая нечётная после контроля)
                target = game_num + 1
                while target % 2 == 0:
                    target += 1
                
                # Определяем противоположную масть
                target_suit = get_opposite_suit(last_donor['first_suit'], last_donor['range_type'])
                
                # Отправляем прогноз
                msg = (
                    f"🎯 *ПРОГНОЗ*\n"
                    f"━━━━━━━━━━━━━━━\n\n"
                    f"📌 Донор: #{last_donor['num']} (масть {last_donor['first_suit']})\n"
                    f"✅ Контроль: #{game_num} (подтверждено)\n"
                    f"🎯 Цель: #{target}\n"
                    f"🃏 Ставка: масть {target_suit}\n\n"
                    f"⚡️ Ждём у игрока слева"
                )
                
                context.bot.send_message(
                    chat_id=OUTPUT_CHANNEL_ID,
                    text=msg,
                    parse_mode='Markdown'
                )
                logger.info(f"✅ Прогноз отправлен: #{target} → {target_suit}")
            else:
                logger.info(f"❌ Масть {last_donor['first_suit']} не подтвердилась")
            
            # В любом случае сбрасываем донора
            last_donor = None
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")


# ==================== КОМАНДЫ ====================
def start(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("⛔ Доступ запрещён")
        return
    update.message.reply_text(
        "✅ *Бот прогнозов запущен*\n"
        "Рабочие диапазоны: 1-9, 30-39, 60-69, 90-99, 120-129...\n"
        "Логика: донор (нечётная) → контроль N+3 → цель N+5"
    )


def stats(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("⛔ Доступ запрещён")
        return
    update.message.reply_text(f"📊 Текущий донор: {last_donor}")


# ==================== ЗАПУСК ====================
def main():
    # === СБРОС ВЕБХУКА ===
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True"
        response = requests.post(url)
        print(f"✅ Вебхук сброшен: {response.json()}")
    except Exception as e:
        print(f"⚠️ Не удалось сбросить вебхук: {e}")
    # ======================

    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("stats", stats))
    dp.add_handler(MessageHandler(
        Filters.chat(INPUT_CHANNEL_ID) & Filters.text,
        handle_new_game
    ))
    
    print("\n" + "="*60)
    print("🤖 БОТ ЗАПУЩЕН")
    print("="*60)
    print("✅ Рабочие диапазоны: 1-9, 30-39, 60-69, 90-99, 120-129...")
    print("✅ Донор: нечётная игра, первая карта игрока")
    print("✅ Контроль: N+3, первые две карты игрока")
    print("✅ Цель: N+5, противоположная масть")
    print("="*60)
    
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()