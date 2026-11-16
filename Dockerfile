FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QUIZ_CLOUD=1 \
    QUIZ_DB=/data/quiz.sqlite3 \
    PORT=8080
COPY server.py index.html style.css quiz.js homepage-plush-concept.png ./
EXPOSE 8080
CMD ["python", "server.py"]
