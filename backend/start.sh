#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ ! -d ".venv" ]; then
    echo "❌ Виртуальное окружение не найдено. Сначала выполните: bash setup.sh"
    exit 1
fi

source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port "${PORT:-8000}"