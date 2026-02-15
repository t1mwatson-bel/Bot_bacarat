# -*- coding: utf-8 -*-
import logging
import re
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import os
import requests

# ==================== НАСТРОЙКИ ====================
TOKEN = os.getenv("TOKEN", "1163348874:AAFgZEXveILvD4MbhQ8jiLTwIxs4puYhmq0")
INPUT_CHANNEL_ID = int(os.getenv("INPUT_CHANNEL_ID", "-1003469691743"))
OUTPUT_CHANNEL_ID = int(os.getenv("OUTPUT_CHANNEL_ID", "-1003842401391"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "683219603"))
MAX_GAME_NUMBER = 1440

# ==================== ЛОГИРОВАНИЕ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== ХРАНИЛИЩЕ ИГР ====================
last_donor = None  # {'num': int, 'first_suit': str, 'rule': str}


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def normalize_game_num(num):
    """Приводит номер игры к диапазону 1–1440 (циклически)."""
    while num > MAX_GAME_NUMBER:
        num -= MAX_GAME_NUMBER
    while num < 1:
        num += MAX_GAME_NUMBER
    return num


def get_rule_for_game(game_num):
    """
    Определяет правило смены масти по номеру игры.
    Чередование каждые 10 игр:
    - 1-9, 20-29, 40-49... -> 'red_black'  (♥️↔♣️, ♦️↔♠️)
    - 10-19, 30-39, 50-59... -> 'same_color' (♥️↔♦️, ♠️↔♣️)
    """
    game_num = normalize_game_num(game_num)
    decade_start = (game_num // 10) * 10
    # Если начало диапазона 0, 20, 40, 60... — red_black, иначе same_color
    if decade_start % 20 == 0:
        return 'red_black'
    else:
        return 'same_color'


def get_opposite_suit(suit, rule):
    """
    Возвращает противоположную масть по правилу.
    """
    if rule == 'red_black':
        # красная ↔ чёрная: ♥️↔♣️, ♦️↔♠️
        if suit == '♥️':
            return '♣️'
        elif suit == '♣️':
            return '♥️'
        elif suit == '♦️':
            return '♠️'
        elif suit == '♠️':
            return '♦️'
    elif rule == 'same_color':
        # красная ↔ красная: ♥️↔♦️
        # чёрная ↔ чёрная: ♠️↔♣️
        if suit == '♥️':
            return '♦️'
        elif suit == '♦️':
            return '♥️'
        elif suit == '♠️':
            return '♣️'
        elif suit == '♣️':
            return '♠️'
    return suit


# ==================== ПАРСИНГ ИГРЫ ====================
def parse_game(text):
    """
    Извлекает из текста игры:
    - номер игры
    - первую карту игрока (левую руку)
    - первые две карты игрока (для контроля)
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
    elif '👉👈' in text:
        left_part = text.split('👉👈')[0].strip()
    elif '👈👉' in text:
        left_part = text.split('👈👉')[0].strip()

    # Ищем карты в скобках
    cards_match = re.search(r'\(([^)]+)\)', left_part)
    if not cards_match:
        return None

    cards_text = cards_match.group(1)

    # Разделяем карты (могут быть с пробелами или без)
    cards = re.findall(r'([\dAKQJ]+[♥♠♣♦]?)', cards_text)
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

        # Если игра нечётная — это потенциальный донор (берём по первой карте)
        if game_num % 2 == 1:
            rule = get_rule_for_game(game_num)
            last_donor = {
                'num': game_num,
                'first_suit': game['first_suit'],
                'rule': rule
            }
            logger.info(f"📌 Запомнен донор #{game_num} с мастью {game['first_suit']}, правило: {rule}")
            return

        # Если игра чётная и у нас есть донор — проверяем, не контрольная ли это
        if last_donor:
            expected_control = normalize_game_num(last_donor['num'] + 3)
            if game_num == expected_control:
                logger.info(f"🔍 Найден контроль #{game_num} для донора #{last_donor['num']}")

                # Проверяем, есть ли масть донора в первых двух картах игрока
                if last_donor['first_suit'] in game['first_two_suits']:
                    logger.info(f"✅ Масть {last_donor['first_suit']} подтвердилась!")

                    # Определяем целевую игру (следующая нечётная после контроля)
                    target = game_num + 1
                    while target % 2 == 0:
                        target += 1
                    target = normalize_game_num(target)

                    # Определяем противоположную масть по правилу донора
                    target_suit = get_opposite_suit(last_donor['first_suit'], last_donor['rule'])

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
        f"Игры: 1–{MAX_GAME_NUMBER} (циклически)\n"
        "Логика: донор (нечётная, первая карта) → контроль N+3 → цель N+5\n"
        "Правила смены мастей по диапазонам:\n"
        "• 1-9,20-29,40-49... : красная↔чёрная (♥️↔♣️, ♦️↔♠️)\n"
        "• 10-19,30-39,50-59... : красная↔красная (♥️↔♦️), чёрная↔чёрная (♠️↔♣️)"
    )


def stats(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("⛔ Доступ запрещён")
        return

    if last_donor:
        update.message.reply_text(f"📊 Текущий донор: #{last_donor['num']} масть {last_donor['first_suit']}")
    else:
        update.message.reply_text("📊 Нет активного донора")


# ==================== ЗАПУСК ====================
def main():
    # Сброс вебхука
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True"
        response = requests.post(url)
        print(f"✅ Вебхук сброшен: {response.json()}")
    except Exception as e:
        print(f"⚠️ Не удалось сбросить вебхук: {e}")

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
    print(f"✅ Игры: 1–{MAX_GAME_NUMBER} (циклически)")
    print("✅ Донор: нечётная игра, ПЕРВАЯ карта игрока")
    print("✅ Контроль: N+3, первые две карты игрока")
    print("✅ Цель: N+5, противоположная масть")
    print("✅ Правила по диапазонам:")
    print("   • 1-9,20-29,40-49... : красная↔чёрная (♥️↔♣️, ♦️↔♠️)")
    print("   • 10-19,30-39,50-59... : красная↔красная (♥️↔♦️), чёрная↔чёрная (♠️↔♣️)")
    print("="*60)

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()