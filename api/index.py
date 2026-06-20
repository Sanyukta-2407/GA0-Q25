import json
from pathlib import Path

import numpy as np
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST"],
    allow_headers=["*"],
)


class RequestBody(BaseModel):
    regions: list[str]
    threshold_ms: float


DATA_FILE = Path(__file__).resolve().parent.parent / "q-vercel-latency.json"

with DATA_FILE.open(encoding="utf-8") as f:
    telemetry = json.load(f)


@app.post("/")
def aggregate_metrics(body: RequestBody):
    results = []

    for region in body.regions:
        records = [record for record in telemetry if record["region"] == region]
        if not records:
            continue

        latencies = [record["latency_ms"] for record in records]
        uptimes = [record["uptime_pct"] for record in records]

        results.append(
            {
                "region": region,
                "avg_latency": round(sum(latencies) / len(latencies), 2),
                "p95_latency": round(float(np.percentile(latencies, 95)), 2),
                "avg_uptime": round(sum(uptimes) / len(uptimes), 3),
                "breaches": sum(
                    1 for record in records if record["latency_ms"] > body.threshold_ms
                ),
            }
        )

    return results
