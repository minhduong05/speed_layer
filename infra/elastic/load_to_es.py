#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True, help="Path to JSON or NDJSON input")
    p.add_argument("--host", default="https://localhost:9200")
    p.add_argument("--index", default="jobs_historical")
    p.add_argument("--user", default="elastic")
    p.add_argument("--password", required=True)
    p.add_argument("--ndjson", action="store_true", help="Treat input as NDJSON")
    return p.parse_args()


def read_docs(path: Path, ndjson: bool):
    if ndjson:
        docs = []
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                docs.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid NDJSON at line {i}: {exc}") from exc
        return docs

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return data
    raise ValueError("JSON input must be an object or a list of objects")


def validate_doc(doc: dict) -> None:
    required = [
        "job_id",
        "job_url",
        "content_hash",
        "job_title",
        "company_name",
        "city",
        "event_date",
        "fetched_at",
    ]
    missing = [k for k in required if k not in doc]
    if missing:
        raise ValueError(f"Missing required fields: {missing}")


def main() -> int:
    args = parse_args()
    path = Path(args.file)
    if not path.exists():
        print(f"Input file not found: {path}", file=sys.stderr)
        return 1

    docs = read_docs(path, args.ndjson)
    payload_lines = []
    for doc in docs:
        validate_doc(doc)
        payload_lines.append(json.dumps({"index": {"_index": args.index, "_id": doc["job_id"]}}, ensure_ascii=False))
        payload_lines.append(json.dumps(doc, ensure_ascii=False))
    payload = "\n".join(payload_lines) + "\n"

    url = args.host.rstrip("/") + "/_bulk"
    resp = requests.post(
        url,
        auth=(args.user, args.password),
        headers={"Content-Type": "application/x-ndjson"},
        data=payload.encode("utf-8"),
        verify=False,
        timeout=60,
    )

    try:
        resp.raise_for_status()
    except requests.HTTPError:
        print(resp.text, file=sys.stderr)
        return 1

    result = resp.json()
    if result.get("errors"):
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2

    print(f"Inserted {len(result.get('items', []))} documents into {args.index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
