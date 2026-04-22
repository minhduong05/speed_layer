"""
Redis sink for gold aggregates.

Writes windowed aggregate results into Redis:
- One Redis hash per time window (field=dimension, value=count)
- One sorted-set index per aggregate type for fast latest-window lookup

Layer: GOLD → Speed Views (Redis)
"""

import os

import redis
from dotenv import load_dotenv

load_dotenv()

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_TTL_SECONDS = int(os.getenv("REDIS_TTL_SECONDS", "7200"))


def get_redis_client():
    """Create a Redis client with decoded responses."""
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=True,
    )


def _window_key(prefix: str, row) -> str:
    """Build a Redis key from a windowed aggregate row."""
    start = row["window"]["start"].strftime("%Y%m%dT%H%M%S")
    end = row["window"]["end"].strftime("%Y%m%dT%H%M%S")
    return f"{prefix}:{start}:{end}"


def write_job_counts(batch_df, batch_id: int):
    """
    foreachBatch sink for job_counts_10m.

    Writes each (window, location_city) → count into a Redis hash
    and maintains a sorted-set index keyed by window end time.
    """
    if batch_df.isEmpty():
        print(f"[job_counts] empty batch {batch_id}")
        return

    client = get_redis_client()
    pipe = client.pipeline()

    for row in batch_df.collect():
        key = _window_key("job_counts_10m", row)
        field = row["location_city"] or "unknown"
        value = int(row["count"])

        pipe.hset(key, field, value)
        pipe.expire(key, REDIS_TTL_SECONDS)
        pipe.zadd("index:job_counts_10m", {key: row["window"]["end"].timestamp()})

    pipe.execute()
    print(f"[job_counts] wrote batch {batch_id}")


def write_skill_counts(batch_df, batch_id: int):
    """
    foreachBatch sink for skill_counts_30m.

    Writes each (window, skill) → count into a Redis hash
    and maintains a sorted-set index keyed by window end time.
    """
    if batch_df.isEmpty():
        print(f"[skill_counts] empty batch {batch_id}")
        return

    client = get_redis_client()
    pipe = client.pipeline()

    for row in batch_df.collect():
        key = _window_key("skill_counts_30m", row)
        field = row["skill"]
        value = int(row["count"])

        pipe.hset(key, field, value)
        pipe.expire(key, REDIS_TTL_SECONDS)
        pipe.zadd("index:skill_counts_30m", {key: row["window"]["end"].timestamp()})

    pipe.execute()
    print(f"[skill_counts] wrote batch {batch_id}")
