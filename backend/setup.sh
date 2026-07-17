#!/bin/bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

if [ ! -f .env ]; then
    cp .env.example .env
    echo "✅ Создан .env из .env.example — отредактируйте под свой кластер"
else
    echo "✅ .env уже существует"
fi

echo "✅ Установка завершена. Запуск: source .venv/bin/activate && uvicorn app.main:app --reload --port 8000"