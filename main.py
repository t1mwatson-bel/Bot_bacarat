import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен из переменных окружения
BOT_TOKEN = os.environ.get('BOT_TOKEN')
INPUT_CHANNEL_ID = int(os.environ.get('INPUT_CHANNEL_ID', '0'))
OUTPUT_CHANNEL_ID = int(os.environ.get('OUTPUT_CHANNEL_ID', '0'))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просто логирует всё что приходит"""
    logger.info(f"Сообщение получено!")

def main():
    """Запуск бота"""
    logger.info("🚀 Бот запускается...")
    
    # Создаем приложение
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Добавляем обработчик
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    
    # Запускаем polling (для Railway тоже работает)
    logger.info("✅ Бот запущен и слушает сообщения...")
    app.run_polling()

if __name__ == "__main__":
    main()