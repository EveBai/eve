FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QUIZ_CLOUD=1 \
    QUIZ_DB=/data/quiz.sqlite3 \
    PORT=8080
COPY server.py *.html style.css quiz.js share.js homepage-plush-concept.png appliance-results.jpg ./
EXPOSE 8080
CMD ["python", "server.py"]
