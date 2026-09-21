# amr_prediction-service

Сервис предсказания устойчивости к антибиотикам (AMR) по аминокислотной последовательности. FastAPI + scikit-learn, логи предсказаний пишутся в PostgreSQL.

Эндпоинты: `GET /health`, `GET /ready`, `POST /v1/predict`.

## Проверка

Нужны `uv`, `docker`, `kind`, `kubectl`. Команды выполняются из корня репозитория сверху вниз.

**1. Тесты**

```bash
uv run pytest
```

**2. Compose** (сервис + Postgres)

```bash
docker compose up --build -d
```

**3. Kind** (2 реплики в кластере)

```bash
docker build -t amr_prediction-service:1.0 . && kind create cluster --name amr && kind load docker-image amr_prediction-service:1.0 --name amr && kubectl apply -f k8s/ && kubectl rollout status deployment/amr-prediction-service
```

## Ручная проверка

Запрос к сервису в compose и выборка из таблицы логов:

```bash
curl -X POST localhost:8000/v1/predict -H "Content-Type: application/json" -d @good.json
docker compose exec db psql -U postgres -d amr_prediction -c "SELECT * FROM predictions ORDER BY ts DESC LIMIT 5;"
```

Запрос к сервису в kind через port-forward:

```bash
kubectl get pods
kubectl port-forward svc/amr-prediction-service 8080:80
curl -X POST localhost:8080/v1/predict -H "Content-Type: application/json" -d @good.json
```

## Отчёт

Скрины чекпоинтов и журнал проблем: [REPORT.md](REPORT.md).
