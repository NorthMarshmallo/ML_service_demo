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

Классы: `aminoglycoside`, `bacitracin`, `beta_lactam`, `chloramphenicol`, `macrolide-lincosamide-streptogramin`, `multidrug`, `polymyxin`. Это фиксированный список `CLASSES` в [`train.py`](src/amr_prediction/train.py): 7 самых частых классов исходного датасета (90% записей) выбраны один раз при исследовании и не пересчитываются при новом обучении. Если в данных у какого-то класса меньше 100 примеров, обучение останавливается. Добавить класс - осознанное изменение списка и новая версия модели.

Пайплайн: `TfidfVectorizer(analyzer='char')` + `MLPClassifier`. Исследование: [experiments/notebooks/amr-prediction.ipynb](experiments/notebooks/amr-prediction.ipynb), обучение с регистрацией в MLflow: [src/amr_prediction/train.py](src/amr_prediction/train.py).

Данные: 17 000 белковых последовательностей, 26 классов антибиотиков. Строки остальных классов, последовательности с нестандартными аминокислотами (`X`, `Z`) или короче 20 и дубликаты отбрасываются, число отброшенных по каждому фильтру пишется в прогон MLflow. Разбиение train/test 80/20 со стратификацией по классу; TF-IDF обучается на train, затем редкие классы дополняются upsampling до размера самого частого.

Метрики на test (3 032 последовательности): **macro F1 0.953**, accuracy 0.97. Слабее всего `multidrug` (F1 0.89).

Реестр: каждое обучение регистрирует версию модели `amr_prediction` с алиасом `challenger`; алиас `champion` она получает, если macro F1 выше, чем у текущего champion, хотя бы на 0.005. Сервис при старте загружает `amr_prediction@champion` из реестра, если задан `MODEL_NAME`, а без него - бандл из `artifact/`, чтобы тесты и CI работали без MLflow. Загруженная версия видна в `/health`: `amr_prediction-v4` из реестра, `1.1.0` из файла.

Ограничения: модель всегда отвечает одним из 7 классов, даже если белок не связан с устойчивостью к ним; признаки - только частоты аминокислот, порядок в последовательности не учитывается.

## Архитектура

```
клиент ─► Service :80 ─┬─► под api #1 (:8000) ─┐
                       └─► под api #2 (:8000) ─┴─► Service postgres :5432 ─► под postgres
```

## CI/CD

[.github/workflows/ci.yml](.github/workflows/ci.yml):

```
PR:           tests (ruff + pytest с Postgres) → build (образ собирается)
push в main:  tests → build (образ в ghcr, тег sha-<коммит>), deploy пропускается
Run workflow: tests → build → deploy на self-hosted runner в кластер mlops (манифесты, smoke через Ingress)
```

Deploy запускается вручную: Actions → ci → Run workflow → main. Runner - контейнер `gh-runner` в Docker-сети `kind` рядом с кластером, метки `[self-hosted, kind]`.

## Конфигурация

| Переменная | В Kubernetes | По умолчанию |
|---|---|---|
| `MODEL_PATH` | ConfigMap `amr-prediction-config` | `artifact/amr_prediction_bundle.joblib` |
| `LOG_LEVEL` | ConfigMap `amr-prediction-config` | `INFO` |
| `MODEL_NAME` | ConfigMap: `amr_prediction` | нет - модель из файла `MODEL_PATH` |
| `MODEL_ALIAS` | ConfigMap: `champion` | `champion` |
| `MLFLOW_TRACKING_URI` | ConfigMap: `http://mlflow.mlops:5000` | `http://mlflow.mlops:5000` |
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

**Обучение с регистрацией в MLflow**

```bash
MLFLOW_TRACKING_URI=http://mlflow.localhost uv run python -m amr_prediction.train
```

Гиперпараметр `HIDDEN_DIM` (по умолчанию 256), запас гейта `GATE_MIN_GAIN` (по умолчанию 0.005).

## Структура

```
src/amr_prediction/   код сервиса (API, настройки, работа с БД) и обучения
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
- [x] Обучение с регистрацией в MLflow и гейтом champion/challenger
- [x] Сервис загружает модель из реестра по алиасу champion
- [x] Деплой по кнопке в свой кластер через self-hosted runner, smoke через Ingress

## История изменений

Этапы, инциденты и принятые решения: [REPORT.md](REPORT.md).
