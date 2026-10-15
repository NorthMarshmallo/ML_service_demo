"""Переобучение модели AMR.

validate  под с образом сервиса: dvc pull датасета из S3, amr_prediction.data - чистка и схемы pandera,
          при нарушениях прогон в MLflow с valid=false и код выхода 1, дальше задачи не идут
train     под с тем же образом: dvc pull, amr_prediction.train - обучение, регистрация в MLflow, гейт
promoted  дальше идём, только если гейт в train.py отдал новой версии алиас champion
rollout   перезапуск amr-prediction-service: новые поды загрузят нового champion из реестра

Образ для подов берётся из переменной amr_image, её выставляет CI при каждом деплое.
"""
from datetime import UTC, datetime

from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.sdk import CronTriggerTimetable, Param, dag, task
from kubernetes.client import models as k8s

# данных в образе нет: DVC берёт их из S3 по адресу изнутри кластера (remote cluster)
PULL = "uv run --no-sync dvc pull -r cluster datasets/dataset.csv && "
MLFLOW = {"MLFLOW_TRACKING_URI": "http://mlflow.mlops:5000"}
COMMON = dict(
    namespace="mlops", in_cluster=True, image="{{ var.value.amr_image }}", image_pull_policy="IfNotPresent",
    # ключи S3 для dvc pull: тот же Secret, из которого RustFS берёт свои
    env_from=[k8s.V1EnvFromSource(secret_ref=k8s.V1SecretEnvSource(name="s3-credentials"))],
    get_logs=True, on_finish_action="delete_pod",
)


@dag(
    # каждый день в 03:00 по Москве; пропущенные запуски не догоняем, в том числе при снятии с паузы
    schedule=CronTriggerTimetable("0 3 * * *", timezone="Europe/Moscow"),
    catchup=False,
    params={"hidden_dim": Param(256, type="integer", minimum=8, description="размер первого скрытого слоя MLP")},
    tags=["amr"],
)
def amr_retrain():
    validate = KubernetesPodOperator(
        task_id="validate", name="amr-validate", env_vars=MLFLOW,
        cmds=["sh", "-c", PULL + "uv run --no-sync python -m amr_prediction.data"], **COMMON,
    )
    train = KubernetesPodOperator(
        task_id="train", name="amr-train", do_xcom_push=True,
        env_vars={**MLFLOW, "HIDDEN_DIM": "{{ params.hidden_dim }}",
                  # коммит из тега образа ...:sha-<коммит> - в поде нет .git
                  "GIT_COMMIT": "{{ var.value.amr_image.split(':sha-')[-1] }}"},
        cmds=["sh", "-c", PULL + "uv run --no-sync python -m amr_prediction.train"], **COMMON,
    )

    @task.short_circuit
    def promoted(result: dict) -> bool:
        print(f"версия {result['version']}, macro F1 {result['macro_f1']}, "
              f"champion до этого {result['champion_before']} с macro F1 {result['champion_f1_before']}")
        return result["promoted"]

    @task
    def rollout():
        from kubernetes import client, config

        config.load_incluster_config()
        now = datetime.now(UTC).isoformat()
        client.AppsV1Api().patch_namespaced_deployment(
            "amr-prediction-service", "default",
            {"spec": {"template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": now}}}}},
        )
        print("amr-prediction-service перезапущен", now)

    validate >> train
    promoted(train.output) >> rollout()


amr_retrain()
