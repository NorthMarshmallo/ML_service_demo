import csv
import random

from locust import HttpUser, between, task

with open("examples/sample_test_sequences.csv") as f:
    SEQUENCES = [row["sequence"] for row in csv.DictReader(f)]


class PredictUser(HttpUser):
    wait_time = between(0.5, 1.5)

    @task
    def predict(self):
        self.client.post("/v1/predict", json={"sequence": random.choice(SEQUENCES)})
