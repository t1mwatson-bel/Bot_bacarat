import os
import sys
import signal

# Для Railway - корректный останов
def signal_handler(sig, frame):
    logger.info("👋 Бот останавливается...")
    release_lock()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)