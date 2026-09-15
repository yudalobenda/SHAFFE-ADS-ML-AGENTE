"""Manual/daily Data Foundation runner. ML/Ads access is read-only."""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from pathlib import Path
import tempfile
import time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from core.erp_client import ERPClient
from core.ml_client import MLClient
from core.shadow_daily_pipeline import ShadowDailyPipeline

BASE = Path(__file__).resolve().parent


def atomic_json(path: Path, value: dict):
    fd, temporary = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).date().isoformat())
    parser.add_argument("--sku", action="append", default=[])
    parser.add_argument("--campaign", action="append", default=[])
    parser.add_argument("--item", action="append", default=[])
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()

    load_dotenv(BASE / ".env")
    token_path = BASE / "memory" / "ml_tokens.json"
    tokens = json.loads(token_path.read_text(encoding="utf-8"))
    ml = MLClient(tokens)
    erp = ERPClient(
        os.environ.get("ERP_BASE_URL", "http://127.0.0.1:3000"),
        os.environ.get("ERP_EMAIL", ""), os.environ.get("ERP_PASSWORD", ""),
    )
    pipeline = ShadowDailyPipeline(ml, erp)
    started = time.perf_counter()
    scope = {"skus": sorted(args.sku), "campaigns": sorted(args.campaign), "items": sorted(args.item)}
    try:
        payload = pipeline.collect(
            date.fromisoformat(args.date), target_skus=args.sku,
            campaign_ids=args.campaign, explicit_item_ids=args.item,
        )
    except Exception as error:
        failure = {"status": "failed", "error": str(error), "scope": scope,
                   "collectionMetadata": pipeline.call_stats,
                   "durationSeconds": round(time.perf_counter() - started, 2)}
        try:
            attempt_key = f"{args.date}:failed:{int(time.time())}"
            run = erp.create_ingestion_run({
                "source": "mercadolibre_ads_daily_foundation", "idempotencyKey": attempt_key,
                "extractorVersion": "foundation-v1", "mode": "shadow",
                "dateFrom": args.date, "dateTo": args.date,
                "sourceTimezone": "America/Argentina/Buenos_Aires",
                "metadata": {"scope": scope, **pipeline.call_stats},
            })
            erp.finish_ingestion_run(run["id"], {"status": "failed", "recordsRead": 0,
                "recordsWritten": 0, "errorDetail": {"message": str(error)},
                "metadata": {"scope": scope, **pipeline.call_stats}})
            failure["runId"] = run["id"]
        except Exception as persistence_error:
            failure["runPersistenceError"] = str(persistence_error)
        output = Path(args.output) if args.output else BASE / "logs" / f"foundation_{args.date}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(output, failure)
        atomic_json(token_path, ml.tokens_actuales())
        print(json.dumps({**failure, "output": str(output)}, ensure_ascii=False, indent=2))
        raise
    result = {"status": "collected", "fingerprint": payload["fingerprint"]}
    if not args.collect_only:
        result = pipeline.persist(payload)
    result["durationSeconds"] = round(time.perf_counter() - started, 2)
    result["counts"] = {
        "mappings": len(payload["mappings"]),
        "listingSnapshots": len(payload["listingSnapshots"]),
        "adsDailyMetrics": len(payload["adsDailyMetrics"]),
    }
    result["collectionMetadata"] = payload["collectionMetadata"]
    output = Path(args.output) if args.output else BASE / "logs" / f"foundation_{args.date}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(output, {"result": result, "payload": payload})
    atomic_json(token_path, ml.tokens_actuales())
    print(json.dumps({**result, "output": str(output)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
