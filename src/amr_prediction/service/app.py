import time
import uuid

from contextlib import asynccontextmanager
from fastapi import BackgroundTasks, FastAPI, HTTPException
import joblib
import pandas as pd
from pydantic import BaseModel

from amr_prediction import db
from amr_prediction.config import settings


class Features(BaseModel):
    model_config = {"extra": "forbid"}

    sequence: str


class Prediction(BaseModel):
    #model_config = {"protected_namespaces": ()}

    score: float
    antibiotic_class: str
    model_version: str
    request_id: str
    latency_ms: float


@asynccontextmanager
async def lifespan(app: FastAPI):
    bundle = joblib.load(settings.model_path)
    app.state.pipeline = bundle["pipeline"]
    app.state.meta = bundle["metadata"]
    app.state.version = bundle["metadata"]["version"]

    db.init()
    yield
    app.state.pipeline = None


app = FastAPI(title="amr_prediction-service", version="1.0", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "model_version": getattr(app.state, "version", "unknown")}


@app.get("/ready")
def ready():
    if getattr(app.state, "pipeline", "None") is  None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    return {"status": "ready"}


@app.post("/v1/predict")
def predict(x: Features, bg: BackgroundTasks) -> Prediction:
    t0 = time.perf_counter()
    request_id = str(uuid.uuid4())
    payload = x.model_dump()  # x.dict() in pydantic v1

    try:
        frame = pd.DataFrame([payload]).reindex(columns=app.state.meta["features"])
        proba = app.state.pipeline.predict_proba(frame["sequence"].tolist())[0]
        pred_idx = proba.argmax()
        antibiotic_class = app.state.meta["classes"][pred_idx]
        score = float(proba[pred_idx])
    except Exception:
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        db.save_prediction(request_id, payload, None, app.state.version, latency_ms, 500)
        raise HTTPException(status_code=500, detail="Prediction failed")

    latency_ms = round((time.perf_counter() - t0) * 1000, 2)

    bg.add_task(db.save_prediction, request_id, payload, score, app.state.version, latency_ms, 200)

    return Prediction(
        score=score,
        antibiotic_class=antibiotic_class,
        model_version=app.state.version,
        request_id=request_id,
        latency_ms=latency_ms,
    )