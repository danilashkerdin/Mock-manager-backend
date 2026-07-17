FROM python:3.12-slim

WORKDIR /app

# Установка Teleport
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://goteleport.com/static/install.sh | bash -s 17 && \
    apt-get clean

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV K8S_NAMESPACE=payment-cards
ENV DATABASE_URL=sqlite:///./mock_manager.db
ENV DEBUG=False

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]