FROM python:3.11-slim

WORKDIR /app

# Исправлено: не указываем жесткую версию 3.1.1, пусть ставит последнюю (она совместима)
RUN pip install aiogram aiohttp python-dotenv

COPY bot.py .

CMD ["python", "bot.py"]