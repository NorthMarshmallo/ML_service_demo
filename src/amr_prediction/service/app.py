from contextlib import asynccontextmanager

import joblib
from fastapi import FastAPI

from pydantic import BaseModel

from amr_prediction import db
from amr_prediction.config import settings

class Features(BaseModel):
    model_config = {"extra": "forbid"}

    sequence: str


class Prediction(BaseModel):
    #model_config = {"protected_namespaces": ()}

    score: float
    antibiotic_class: bool
    model_version: str
    request_id: str
    latency_ms: float


@asynccontextmanager
async def lifespan(app: FastAPI):
    bundle = joblib.load(settings.model_path)
    app.state.pipeline = bundle["pipeline"]
    app.state.meta = bundle["metadata"]
    app.state.version = bundle["metadata"]["model_version"]

    db.init()
    yield
    app.state.pipeline = None

