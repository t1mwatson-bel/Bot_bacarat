import os
import logging
import asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Переменные окружения
BOT_TOKEN = os.environ.get('BOT_TOKEN')
INPUT_CHANNEL_ID = int(os.environ.get('INPUT_CHANNEL_ID', '0'))
OUTPUT_CHANNEL_ID = int(os.environ.get('OUTPUT_CHANNEL_ID', '0'))

# Публичный URL твоего бота (тот, что создал)
PUBLIC_URL = os.environ.get('PUBLIC_URL', 'https://botbacarat.up.railway.app')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик всех сообщений"""
    logger.info(f"🔥 ПОЛУЧЕНО СООБЩЕНИЕ: {update.message.text if update.message else 'нет текста'}")
    
    if update.channel_post:
        logger.info(f"📢 Канал: {update.channel_post.chat.id}")
        logger.info(f"📝 Текст: {update.channel_post.text}")

async def webhook_handler(request):
    """Обработчик вебхука"""
    return "ok"

async def setup_webhook(app):
    """Настройка вебхука"""
    webhook_url = f"{PUBLIC_URL}/webhook"
    
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        await app.bot.set_webhook(url=webhook_url)
        logger.info(f"✅ Вебхук установлен: {webhook_url}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return False

async def main():
    """Запуск"""
    logger.info("🚀 Бот запускается...")
    
    # Создаем приложение
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Добавляем обработчик
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    
    # Настраиваем вебхук
    await setup_webhook(app)
    
    # Запускаем
    port = int(os.environ.get('PORT', 8080))
    logger.info(f"🔌 Слушаем порт: {port}")
    
    await app.run_webhook(
        listen="0.0.0.0",
        port=port,
        webhook_url=f"{PUBLIC_URL}/webhook"
    )

if __name__ == "__main__":
    asyncio.run(main())