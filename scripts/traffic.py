"""Поток запросов к сервису из последовательностей датасета, чтобы на дашборде Grafana было что смотреть.

  uv run python scripts/traffic.py --url http://amr.localhost --rps 5 --bad 0.05

Через Ingress запросы делятся между подами и переживают rollout. Через port-forward нет:
он привязан к одному поду и обрывается, когда этот под удаляют.
--bad   доля заведомо плохих запросов, они дают 422 на графике.
"""
import argparse
import json
import random
import time
import urllib.error
import urllib.request

import pandas as pd

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://amr.localhost")
parser.add_argument("--rps", type=float, default=5)
parser.add_argument("--bad", type=float, default=0.0)
args = parser.parse_args()

seq = pd.read_csv("datasets/dataset.csv", sep=";")["sequence"]
seq = seq[seq.str.fullmatch("[ACDEFGHIKLMNPQRSTVWY]+") & (seq.str.len() >= 20)]
rows = [{"sequence": s} for s in seq]

codes: dict[int, int] = {}
start = time.time()
while True:
    row = dict(random.choice(rows))
    if random.random() < args.bad:
        row = {"sequence": "ACDEF"}
    req = urllib.request.Request(f"{args.url}/v1/predict", data=json.dumps(row).encode(),
                                    headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            code = resp.status
    except urllib.error.HTTPError as e:
        code = e.code
    except (urllib.error.URLError, OSError):
        code = 0  # сервис недоступен: под перезапускается или оборвался port-forward
    codes[code] = codes.get(code, 0) + 1
    total = sum(codes.values())
    if total % 50 == 0:
        print(f"{total} запросов за {time.time() - start:.0f} с, коды {codes}", flush=True)
    time.sleep(1 / args.rps)