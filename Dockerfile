FROM python:3.12-slim
WORKDIR /app
COPY server.py client.py ./
EXPOSE 8000