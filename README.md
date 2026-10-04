# AMR prediction service

![ci](https://github.com/NorthMarshmallo/ML_service_demo/actions/workflows/ci.yml/badge.svg)

Сервис предсказывает класс антибиотиков, к которому белок даёт устойчивость (AMR), по его аминокислотной последовательности. FastAPI + scikit-learn, каждое предсказание логируется в PostgreSQL.

> Статус: в разработке - [Roadmap](#roadmap), история изменений - [REPORT.md](REPORT.md).

## API

| Метод | Путь | Что делает |
|---|---|---|
| GET | `/health` | Процесс жив; версия модели и путь к ней |
| GET | `/ready` | Модель загружена, сервис готов принимать запросы |
| POST | `/v1/predict` | Предсказание модели по переданной последовательности |

```bash
curl -X POST localhost:8000/v1/predict -H "Content-Type: application/json" -d @good.json
```

```json
{"score": 0.998, "antibiotic_class": "aminoglycoside", "model_version": "1.1.0", "request_id": "7948713f-ad45-4961-a94e-1cd49c08c5c7", "latency_ms": 3.26}
```

`score` - вероятность предсказанного класса. Вход: только 20 стандартных аминокислот, длина от 20 символов, иначе ответ 422.

## Модель

Классы: `aminoglycoside`, `bacitracin`, `beta_lactam`, `chloramphenicol`, `macrolide-lincosamide-streptogramin`, `multidrug`, `polymyxin`.

Пайплайн: `TfidfVectorizer(analyzer='char')` + `MLPClassifier`. Обучение: [experiments/notebooks/amr-prediction.ipynb](experiments/notebooks/amr-prediction.ipynb).

Данные: 17 000 белковых последовательностей, 26 классов антибиотиков. Для обучения взяты 7 самых частых классов (90% записей). Удалены дубликаты и последовательности с нестандартными аминокислотами (`X`, `Z`). Разбиение train/test 80/20 со стратификацией по классу; редкие классы в train дополнены upsampling до размера самого частого.

Метрики на test (3 032 последовательности): **macro F1 0.953**, accuracy 0.97. Слабее всего `multidrug` (F1 0.89).

Ограничения: модель всегда отвечает одним из 7 классов, даже если белок не связан с устойчивостью к ним; признаки - только частоты аминокислот, порядок в последовательности не учитывается.

## Архитектура

```
клиент ─► Service :80 ─┬─► под api #1 (:8000) ─┐
                       └─► под api #2 (:8000) ─┴─► Service postgres :5432 ─► под postgres
```

## CI/CD

[.github/workflows/ci.yml](.github/workflows/ci.yml):

```
PR:    tests (ruff + pytest с Postgres) → build (образ собирается)
main:  tests → build (образ в ghcr, тег sha-<коммит>) → deploy (kind, манифесты, smoke)
```

## Конфигурация

| Переменная | В Kubernetes | По умолчанию |
|---|---|---|
| `MODEL_PATH` | ConfigMap `amr-prediction-config` | `artifact/amr_prediction_bundle.joblib` |
| `LOG_LEVEL` | ConfigMap `amr-prediction-config` | `INFO` |
| `DATABASE_URL` | Secret `amr-prediction-secrets` | нет - предсказания не логируются |

## Запуск

Нужны `uv` и `docker`; для Kubernetes ещё `kind` и `kubectl`. Команды выполняются из корня репозитория.

**Тесты**

```bash
uv run pytest
```

**Локально: сервис + Postgres**

```bash
docker compose up --build -d
curl -X POST localhost:8000/v1/predict -H "Content-Type: application/json" -d @good.json
docker compose exec db psql -U postgres -d amr_prediction -c "SELECT * FROM predictions ORDER BY ts DESC LIMIT 5;"
```

**Kubernetes (kind)**

```bash
docker build -t amr_prediction-service:1.0 .
kind create cluster --name amr
kind load docker-image amr_prediction-service:1.0 --name amr
kubectl create secret generic amr-prediction-secrets \
  --from-literal=POSTGRES_PASSWORD=postgres \
  --from-literal=DATABASE_URL=postgresql://postgres:postgres@postgres:5432/amr_prediction
kubectl apply -f k8s/
kubectl rollout status deployment/amr-prediction-service
```

Запрос через port-forward:

```bash
kubectl get pods
kubectl port-forward svc/amr-prediction-service 8080:80
curl -X POST localhost:8080/v1/predict -H "Content-Type: application/json" -d @good.json
```

**Платформа: kind + Traefik + MLflow**

Нужен ещё `helm`.

```bash
kind create cluster --config platform/kind-config.yaml --name mlops
helm repo add traefik https://traefik.github.io/charts
helm upgrade --install traefik traefik/traefik -n traefik --create-namespace -f platform/traefik-values.yaml
kubectl apply -f platform/mlflow.yaml
kubectl apply -f platform/ingress.yaml
```

MLflow: http://mlflow.localhost

## Структура

```
src/amr_prediction/   код сервиса: API, настройки, работа с БД
artifact/             обученная модель
experiments/          ноутбук обучения
tests/                unit- и интеграционные тесты
k8s/                  манифесты Kubernetes
platform/             кластер kind, Traefik, MLflow, Ingress
.github/workflows/    CI/CD
```

## Roadmap

- [x] FastAPI-сервис, логирование предсказаний в Postgres
- [x] Docker, compose, Kubernetes (2 реплики, пробы, ресурсы)
- [x] CI/CD: тесты, образ в ghcr, деплой в kind
- [x] Платформа в kind: Traefik, MLflow за Ingress

## История изменений

Этапы, инциденты и принятые решения: [REPORT.md](REPORT.md).
