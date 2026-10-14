# AMR prediction service

![ci](https://github.com/NorthMarshmallo/ML_service_demo/actions/workflows/ci.yml/badge.svg)

Сервис предсказывает класс антибиотиков, к которому белок даёт устойчивость (AMR), по его аминокислотной последовательности. FastAPI + scikit-learn: TF-IDF по символам последовательности и `MLPClassifier`, 7 классов, macro F1 0.953 на отложенной выборке. Каждое предсказание с `request_id` логируется в PostgreSQL.

Модель обучается скриптом [`train.py`](src/amr_prediction/train.py) и регистрируется в MLflow; в сервис попадает только версия, прошедшая гейт по macro F1 (алиас `champion`). Сервис при старте загружает `champion` из реестра, поэтому смена модели - это перестановка алиаса и перезапуск подов, без пересборки образа. Всё работает в локальном кластере kind: Traefik на порту 80, MLflow, Airflow, S3 (RustFS), Prometheus и Grafana поднимаются одной командой, деплой сервиса - GitHub Actions на self-hosted runner.

> Статус: в разработке - [Roadmap](#roadmap), история изменений - [REPORT.md](REPORT.md).

## Интерфейсы

| Что | Адрес | Вход |
|---|---|---|
| Сервис | http://amr.localhost | - |
| MLflow | http://mlflow.localhost | - |
| Airflow | http://airflow.localhost | - |
| Grafana | http://grafana.localhost | admin / admin |
| Консоль S3 | http://s3-console.localhost/rustfs/console/index.html | dvcadmin / dvc-secret-123 |
| Prometheus | `kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 9090` → http://localhost:9090 | - |

## API

| Метод | Путь | Что делает |
|---|---|---|
| GET | `/health` | Процесс жив; версия модели и откуда она загружена |
| GET | `/ready` | Модель загружена, сервис готов принимать запросы |
| POST | `/v1/predict` | Предсказание модели по переданной последовательности |
| GET | `/metrics` | Метрики Prometheus |

```bash
curl -X POST http://amr.localhost/v1/predict -H "Content-Type: application/json" -d @good.json
```

```json
{"score": 0.998, "antibiotic_class": "aminoglycoside", "model_version": "amr_prediction-v4", "request_id": "7948713f-ad45-4961-a94e-1cd49c08c5c7", "latency_ms": 3.26}
```

`score` - вероятность предсказанного класса. Вход: только 20 стандартных аминокислот, длина от 20 символов, иначе ответ 422.

`/health` в кластере: `"model_version": "amr_prediction-v4", "model_source": "models:/amr_prediction@champion"`; без `MODEL_NAME` - версия бандла и путь к файлу.

## Модель

Классы: `aminoglycoside`, `bacitracin`, `beta_lactam`, `chloramphenicol`, `macrolide-lincosamide-streptogramin`, `multidrug`, `polymyxin`. Это фиксированный список `CLASSES` в [`train.py`](src/amr_prediction/train.py): 7 самых частых классов исходного датасета (90% записей) выбраны один раз при исследовании и не пересчитываются при новом обучении. Добавить класс - осознанное изменение списка и новая версия модели.

Пайплайн: `TfidfVectorizer(analyzer='char')` + `MLPClassifier`. Исследование: [experiments/notebooks/amr-prediction.ipynb](experiments/notebooks/amr-prediction.ipynb), обучение с регистрацией в MLflow: [src/amr_prediction/train.py](src/amr_prediction/train.py).

Данные: 17 000 белковых последовательностей, 26 классов антибиотиков. Строки остальных классов, последовательности с нестандартными аминокислотами (`X`, `Z`) или короче 20 и полные дубликаты отбрасываются, число отброшенных по каждому фильтру пишется в прогон MLflow. Очищенный слой перед обучением проверяется схемами pandera: длина, состав аминокислот, уникальность последовательности, объём выгрузки, медиана длины и доли классов. Разбиение train/test 80/20 со стратификацией по классу; TF-IDF обучается на train, затем редкие классы дополняются upsampling до размера самого частого.

Метрики на test (3 032 последовательности): **macro F1 0.953**, accuracy 0.97. Слабее всего `multidrug` (F1 0.89).

Реестр: каждое обучение регистрирует версию модели `amr_prediction` с алиасом `challenger`; алиас `champion` она получает, если macro F1 выше, чем у текущего champion, хотя бы на 0.005. Сервис при старте загружает `amr_prediction@champion` из реестра, если задан `MODEL_NAME`, а без него - бандл из `artifact/`, чтобы тесты, CI и compose работали без MLflow.

Ограничения: модель всегда отвечает одним из 7 классов, даже если белок не связан с устойчивостью к ним; признаки - только частоты аминокислот, порядок в последовательности не учитывается.

## Архитектура

```
                         ┌─ amr.localhost ──► Service amr-prediction-service :80 ─┬─► под api #1 :8000 ─┐
127.0.0.1:80 ─► kind :30080 ─► Traefik ─┤                                                    └─► под api #2 :8000 ─┴─► postgres :5432
                         ├─ mlflow.localhost ──► MLflow :5000          ◄── поды api: models:/amr_prediction@champion
                         ├─ airflow.localhost ─► Airflow :8080
                         ├─ grafana.localhost ─► Grafana :80 ◄── Prometheus ◄── /metrics каждого пода api, раз в 15 с
                         └─ s3.localhost ──────► RustFS :9000 (бакет dvc)
```

Namespace: сервис и Postgres - `default`; MLflow, Airflow, RustFS - `mlops`; Prometheus и Grafana - `monitoring`; Traefik - `traefik`.

## Мониторинг

Сервис отдаёт `/metrics`, Prometheus забирает его с каждого пода по [`ServiceMonitor`](k8s/monitoring/servicemonitor.yaml), Grafana подхватывает [дашборд](k8s/monitoring/dashboard.yaml) из ConfigMap с меткой `grafana_dashboard: "1"`.

| Метрика | Тип | Что показывает |
|---|---|---|
| `http_requests_total` | counter | запросы по ручке и коду ответа (`prometheus-fastapi-instrumentator`) |
| `http_request_duration_seconds` | histogram | задержка внутри сервиса; бакеты через 5 мс от 5 до 50 мс (p50 ≈ 25 мс, p95 ≈ 40 мс), дальше до 1 с |
| `amr_model_info{version}` | gauge | версия модели, загруженная подом |
| `amr_predictions_total{antibiotic_class}` | counter | предсказания по классам |
| `amr_score` | histogram | уверенность модели: вероятность предсказанного класса |

В метках только значения из короткого фиксированного списка: класс и версия. `request_id` и сама последовательность в метки не попадают, иначе каждый запрос создавал бы новый временной ряд.

## CI/CD

[.github/workflows/ci.yml](.github/workflows/ci.yml):

```
PR:           tests (ruff + pytest с Postgres) → build (образ собирается)
push в main:  tests → build (образ в ghcr, тег sha-<коммит>), deploy пропускается
Run workflow: tests → build → deploy на self-hosted runner в кластер mlops
```

Шаги `deploy`: образ в узел kind → Secret → Postgres → `k8s/` → `k8s/monitoring/` → smoke через Ingress (`Host: amr.localhost` на `mlops-control-plane:30080`). Smoke проверяет версию из реестра в `/health`, класс и `score` на `good.json`, строку в базе с этим `request_id` и метрику `amr_model_info` в `/metrics`.

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

Нужны `docker`, `kind`, `kubectl`, `helm`, `uv`. Команды из корня репозитория.

**Тесты**

```bash
uv run pytest
```

**Сервис + Postgres без кластера**

Модель из файла `artifact/`, MLflow не нужен.

```bash
docker compose up --build -d
curl -X POST localhost:8000/v1/predict -H "Content-Type: application/json" -d @good.json
docker compose exec db psql -U postgres -d amr_prediction -c "SELECT * FROM predictions ORDER BY ts DESC LIMIT 5;"
```

**Платформа**

```bash
bash platform/up.sh
kubectl get pods -A
```

[`platform/up.sh`](platform/up.sh) создаёт кластер `mlops` с портом 80 на `127.0.0.1` и ставит Traefik, MLflow, Airflow, RustFS, kube-prometheus-stack и metrics-server, затем создаёт бакет `dvc`. Повторный запуск только обновляет то, что уже стоит. Если Python не находит `*.localhost` (`getaddrinfo failed`), в hosts нужна строка `127.0.0.1 mlflow.localhost s3.localhost amr.localhost`.

**Обучение с регистрацией в MLflow**

```bash
MLFLOW_TRACKING_URI=http://mlflow.localhost uv run python -m amr_prediction.train
```

Гиперпараметр `HIDDEN_DIM` (по умолчанию 256), запас гейта `GATE_MIN_GAIN` (по умолчанию 0.005).

**Данные (DVC)**

Датасет `datasets/dataset.csv` хранится в DVC, в git - только `datasets/dataset.csv.dvc`. Хранилище - бакет `dvc` в RustFS внутри кластера, два remote на один бакет:

| Remote | Адрес | Откуда |
|---|---|---|
| `laptop` (по умолчанию) | `http://s3.localhost` → Traefik → `rustfs:9000` | с ноутбука |
| `cluster` | `http://rustfs.mlops:9000` | из подов кластера |

```bash
uv run dvc remote modify --local laptop access_key_id dvcadmin
uv run dvc remote modify --local laptop secret_access_key dvc-secret-123
uv run dvc pull                                  # скачать версию данных из текущего коммита
git checkout <коммит> -- datasets/dataset.csv.dvc && uv run dvc checkout   # данные другой версии
uv run dvc add datasets/dataset.csv && uv run dvc push    # новая версия данных, до git push
```

**Проверка данных**

```bash
MLFLOW_TRACKING_URI=http://mlflow.localhost uv run python -m amr_prediction.data
DATA_PATH=<другой файл> MLFLOW_TRACKING_URI=http://mlflow.localhost uv run python -m amr_prediction.data
```

Схемы pandera - в [`data.py`](src/amr_prediction/data.py). Прогон в эксперименте `amr_prediction_data` с тегом `valid`; при нарушениях - артефакт `failure_cases.csv` и код выхода 1.

**Деплой**

Job `deploy` выполняется на self-hosted runner в Docker-сети `kind`, рядом с кластером. Токен регистрации: Settings → Actions → Runners → New self-hosted runner.

```bash
export RUNNER_TOKEN=<токен со страницы New self-hosted runner, действует час>
docker run -d --name gh-runner --network kind --restart unless-stopped \
  --group-add "$(stat -c %g /var/run/docker.sock)" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e REPO_URL=https://github.com/<владелец>/<репозиторий> -e RUNNER_TOKEN \
  ghcr.io/actions/actions-runner:2.337.0 \
  bash -c '[ -f .runner ] || ./config.sh --unattended --replace --url "$REPO_URL" --token "$RUNNER_TOKEN" --name mlops-kind --labels kind; ./run.sh'
docker logs -f gh-runner     # ждать "Listening for Jobs"
```

`--network kind` - runner видит узел кластера по имени `mlops-control-plane`; сокет Docker и `--group-add` с группой его владельца - runner кладёт образ в узел через `kind load`; `--replace` - перерегистрация с тем же именем после пересоздания контейнера. На Docker Desktop группа сокета - `0`. В Settings → Secrets and variables → Actions нужен секрет `DB_PASSWORD`.

Запуск: Actions → ci → Run workflow → main. Проверка:

```bash
curl http://amr.localhost/health
curl -X POST http://amr.localhost/v1/predict -H "Content-Type: application/json" -d @good.json
```

**Трафик для дашборда**

```bash
uv run python scripts/traffic.py --rps 5 --bad 0.05     # Ctrl+C - стоп
```

Дашборд: http://grafana.localhost → Dashboards → AMR service.

**Нагрузка и HPA**

```bash
uv run --with locust locust -f locustfile.py --headless -u 60 -r 20 -t 4m --host http://amr.localhost
kubectl get hpa -w
```

HPA ([`k8s/hpa.yaml`](k8s/hpa.yaml)) применяется вместе с `k8s/`, metrics-server ставит `up.sh`.

## Структура

```
src/amr_prediction/   код сервиса (API, метрики, настройки, работа с БД) и обучения
artifact/             бандл модели для запуска без MLflow
experiments/          ноутбук исследования
datasets/             датасет под DVC (в git и в образе только .dvc-файл)
tests/                unit- и интеграционные тесты
k8s/                  манифесты сервиса и Postgres, HPA
k8s/monitoring/       ServiceMonitor и дашборд Grafana
platform/             кластер kind и платформа: up.sh, Traefik, MLflow, Airflow, RustFS, Prometheus/Grafana
scripts/              генератор трафика
.github/workflows/    CI/CD
```

## Roadmap

- [x] FastAPI-сервис, логирование предсказаний в Postgres
- [x] Docker, compose, Kubernetes (2 реплики, пробы, ресурсы)
- [x] CI/CD: тесты, образ в ghcr, деплой в kind
- [x] Обучение с регистрацией в MLflow и гейтом champion/challenger
- [x] Сервис загружает модель из реестра по алиасу champion
- [x] Деплой по кнопке в свой кластер через self-hosted runner, smoke через Ingress
- [x] Версии данных в DVC, `data_md5` в прогоне MLflow
- [x] HPA по CPU, нагрузка locust через Ingress
- [x] Платформа одной командой: Traefik, MLflow, Airflow, RustFS, Prometheus, Grafana
- [x] Метрики сервиса и модели, дашборд Grafana, smoke по метрике версии модели
- [x] Данные DVC в S3 кластера, в образе только указатели
- [x] Проверка данных схемами pandera, прогон validate в MLflow

## История изменений

Этапы, инциденты и принятые решения: [REPORT.md](REPORT.md).
