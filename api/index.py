import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("telemetry-api")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Expose-Headers": "Access-Control-Allow-Origin",
}


@app.middleware("http")
async def add_cors_headers(request, call_next):
    response = await call_next(request)
    response.headers.update(CORS_HEADERS)
    return response


class RequestBody(BaseModel):
    regions: list[str]
    threshold_ms: float


DATA_FILE = Path(__file__).resolve().parent.parent / "q-vercel-latency.json"


def log_event(event: str, **fields: Any) -> None:
    logger.info(json.dumps({"event": event, **fields}, default=str))


def load_telemetry() -> tuple[list[dict[str, Any]], str | None]:
    log_event(
        "loading_telemetry_dataset",
        dataset_path=str(DATA_FILE),
        dataset_exists=DATA_FILE.exists(),
    )

    try:
        with DATA_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as exc:
        logger.exception("Telemetry dataset file was not found")
        return [], str(exc)
    except json.JSONDecodeError as exc:
        logger.exception("Telemetry dataset file is not valid JSON")
        return [], str(exc)

    if not isinstance(data, list):
        error = "Telemetry dataset must be a JSON array"
        log_event("invalid_telemetry_dataset", error=error, loaded_type=type(data).__name__)
        return [], error

    regions = sorted(
        {
            str(record.get("region"))
            for record in data
            if isinstance(record, dict) and record.get("region") is not None
        }
    )
    log_event(
        "telemetry_dataset_loaded",
        row_count=len(data),
        unique_regions=regions,
    )
    return data, None


telemetry, telemetry_load_error = load_telemetry()


def unique_regions() -> list[str]:
    return sorted(
        {
            str(record.get("region"))
            for record in telemetry
            if isinstance(record, dict) and record.get("region") is not None
        }
    )


def matching_records(region: str) -> list[dict[str, Any]]:
    requested_region = region.casefold()
    return [
        record
        for record in telemetry
        if str(record.get("region", "")).casefold() == requested_region
    ]


def build_metrics(body: RequestBody) -> list[dict[str, Any]]:
    log_event(
        "received_aggregate_request",
        requested_regions=body.regions,
        threshold_ms=body.threshold_ms,
        loaded_row_count=len(telemetry),
        available_regions=unique_regions(),
    )

    results = []

    for region in body.regions:
        records = matching_records(region)
        log_event(
            "filtered_records_for_region",
            requested_region=region,
            matched_records=len(records),
        )

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

    return {"regions": results}


@app.post("/")
def aggregate_metrics(body: RequestBody):
    return build_metrics(body)


@app.options("/{path:path}")
def options_handler(path: str):
    response = Response()
    response.headers.update(CORS_HEADERS)
    return response


@app.get("/cors-test")
def cors_test():
    return {"status": "ok"}


@app.get("/debug")
def debug():
    return {
        "dataset_path": str(DATA_FILE),
        "dataset_exists": DATA_FILE.exists(),
        "dataset_load_error": telemetry_load_error,
        "row_count": len(telemetry),
        "unique_regions": unique_regions(),
        "sample_records": telemetry[:3],
        "routes": [route.path for route in app.routes],
    }


@app.post("/debug-request")
def debug_request(body: RequestBody):
    match_counts = {region: len(matching_records(region)) for region in body.regions}
    case_insensitive_available_regions = [
        region.casefold() for region in unique_regions()
    ]

    return {
        "received_payload": body.model_dump(),
        "validation": "passed",
        "dataset_loaded": telemetry_load_error is None,
        "dataset_path": str(DATA_FILE),
        "dataset_exists": DATA_FILE.exists(),
        "row_count": len(telemetry),
        "unique_regions": unique_regions(),
        "case_insensitive_available_regions": case_insensitive_available_regions,
        "match_counts": match_counts,
        "metrics": build_metrics(body),
    }
