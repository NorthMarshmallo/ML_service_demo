from psycopg.types.json import Json
from psycopg_pool import ConnectionPool

from amr_prediction.config import settings

DDL = """
CREATE TABLE IF NOT EXISTS predictions (

    request_id      uuid PRIMARY KEY,
    ts      timestamptz NOT NULL DEFAULT now(),
    model_version       text NOT NULL,
    features        jsonb NOT NULL,
    score       double precision,
    latency_ms real,
    status_code integer NOT NULL
)
"""

# пул соединений на процесс: открывается при старте, запросы берут готовое соединение
pool: ConnectionPool | None = None


def init() -> None:
    global pool
    if not settings.database_url:
        return
    # 6 реплик по HPA * 5 = 30 соединений, у Postgres max_connections = 100
    # check: перед выдачей соединение проверяется, иначе после перезапуска Postgres запись падает на мёртвом соединении
    pool = ConnectionPool(settings.database_url, min_size=1, max_size=5, open=True, check=ConnectionPool.check_connection)
    with pool.connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(7001)")
        conn.execute(DDL)


def close() -> None:
    if pool is not None:
        pool.close()


def save_prediction(request_id : str, features : dict, score : float | None, model_version : str, latency_ms : float, status_code : int) -> None:
    if pool is None:
        return
    with pool.connection() as conn:
            conn.execute(
            "INSERT INTO predictions (request_id, model_version, features, score, latency_ms, status_code) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (request_id, model_version, Json(features), score, latency_ms, status_code),
        )