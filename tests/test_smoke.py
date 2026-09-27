import uuid


def test_predict_smoke(client, good_row):
    r = client.post("/v1/predict", json=good_row)
    assert r.status_code == 200
    body = r.json()
    classes = client.app.state.meta["classes"]
    assert body["antibiotic_class"] in classes
    # score — вероятность выбранного класса, она не может быть ниже равномерной
    assert 1 / len(classes) <= body["score"] <= 1.0
    assert body["antibiotic_class"] == "aminoglycoside"
    assert body["model_version"] == client.get("/health").json()["model_version"]
    assert body["latency_ms"] >= 0
    uuid.UUID(body["request_id"])


def test_predict_is_deterministic(client, good_row):
    s1 = client.post("/v1/predict", json=good_row).json()["score"]
    s2 = client.post("/v1/predict", json=good_row).json()["score"]
    assert abs(s1 - s2) < 1e-12