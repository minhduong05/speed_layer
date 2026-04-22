"""
apps/stream/realtime_aggregator.py
====================================
BƯỚC 3: AGGREGATOR (Consumer thứ 2 - Consumer Group riêng)
Đọc từ jobs_clean, tính aggregate theo time window, ghi ra Cassandra + ES.

Kiến trúc:
    Kafka: jobs_clean --> [THIS FILE]
                              +--> Cassandra: realtime_skill_counts
                              +--> Cassandra: realtime_job_counts_10m
                              +--> ES: gold_skill_counts_daily_v1

Chạy:
    spark-submit \\
      --packages org.apache.spark:spark-sql-kafka-0-10_2.13:4.1.1 \\
      apps/stream/realtime_aggregator.py
"""

import json, os, logging, sys, ssl, urllib.request
from datetime import datetime, timezone

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.functions import (
    col, from_json, explode, window,
    count, countDistinct, avg,
    coalesce, current_timestamp, to_timestamp,
)
from pyspark.sql.types import (
    StructType, StructField,
    StringType, DoubleType, ArrayType,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("realtime_aggregator")

# ── Config ───────────────────────────────────────────────────────────────────
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP",   "my-cluster-kafka-bootstrap.kafka.svc:9092")
TOPIC_CLEAN     = os.getenv("KAFKA_TOPIC_CLEAN",  "jobs_clean")
ES_URL          = os.getenv("ES_URL",              "http://elasticsearch.streaming.svc:9200")
CASSANDRA_HOST  = os.getenv("CASSANDRA_HOST",      "demo-dc1-service.k8ssandra-operator.svc")
CASSANDRA_PORT  = int(os.getenv("CASSANDRA_PORT",  "9042"))
CASSANDRA_USER  = os.getenv("CASSANDRA_USERNAME",  "cassandra")
CASSANDRA_PASS  = os.getenv("CASSANDRA_PASSWORD",  "cassandra")
CASSANDRA_KS    = os.getenv("CASSANDRA_KEYSPACE",  "demo_jobs")
CHECKPOINT_DIR  = os.getenv("CHECKPOINT_DIR",      "/tmp/checkpoints/aggregator")
TRIGGER_SEC     = int(os.getenv("TRIGGER_SEC",     "30"))
WATERMARK_DELAY = os.getenv("WATERMARK_DELAY",    "10 minutes")
WINDOW_DURATION = os.getenv("WINDOW_DURATION",    "10 minutes")
SLIDE_DURATION  = os.getenv("SLIDE_DURATION",     "1 minute")


# ── Schema của message trên jobs_clean ───────────────────────────────────────
CLEAN_SCHEMA = StructType([
    StructField("job_id",          StringType(), True),
    StructField("company_name",    StringType(), True),
    StructField("city",            StringType(), True),
    StructField("employment_type", StringType(), True),
    StructField("salary_min",      DoubleType(), True),
    StructField("salary_max",      DoubleType(), True),
    StructField("skills",          ArrayType(StringType()), True),
    StructField("event_ts",        StringType(), True),
])


# ════════════════════════════════════════════════════════════════════════════
# SINKS
# ════════════════════════════════════════════════════════════════════════════

def _bulk_es(docs: list, index: str):
    if not docs:
        return
    lines = []
    for d in docs:
        lines.append(json.dumps({"index": {"_index": index}}))
        lines.append(json.dumps(d, ensure_ascii=False, default=str))
    body = ("\n".join(lines) + "\n").encode("utf-8")
    req  = urllib.request.Request(
        f"{ES_URL}/_bulk", data=body,
        headers={"Content-Type": "application/x-ndjson"}, method="POST",
    )
    ctx = ssl._create_unverified_context() if ES_URL.startswith("https") else None
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            r = json.loads(resp.read())
            if not r.get("errors"):
                log.info("ES [%s]: %d docs", index, len(docs))
    except Exception as e:
        log.error("ES write failed: %s", e)


def _cassandra_session():
    from cassandra.cluster import Cluster
    from cassandra.auth import PlainTextAuthProvider
    auth = PlainTextAuthProvider(CASSANDRA_USER, CASSANDRA_PASS)
    cluster = Cluster([CASSANDRA_HOST], port=CASSANDRA_PORT, auth_provider=auth)
    return cluster, cluster.connect(CASSANDRA_KS)


def _write_skill_counts(rows: list):
    if not rows:
        return
    try:
        cluster, session = _cassandra_session()
        stmt = session.prepare("""
            INSERT INTO realtime_skill_counts
                (time_bucket, city, skill, job_count,
                 distinct_company_count, avg_salary_min, avg_salary_max, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """)
        now = datetime.now(timezone.utc)
        for r in rows:
            session.execute(stmt, (
                r["time_bucket"], r["city"], r["skill"],
                r["job_count"],   r["distinct_company_count"],
                r.get("avg_salary_min"), r.get("avg_salary_max"), now,
            ))
        session.shutdown(); cluster.shutdown()
        log.info("Cassandra realtime_skill_counts: %d rows", len(rows))
    except Exception as e:
        log.error("Cassandra skill_counts: %s", e)


def _write_job_counts(rows: list):
    if not rows:
        return
    try:
        cluster, session = _cassandra_session()
        stmt = session.prepare("""
            INSERT INTO realtime_job_counts_10m
                (time_bucket, city, employment_type,
                 job_count, distinct_company_count, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """)
        now = datetime.now(timezone.utc)
        for r in rows:
            session.execute(stmt, (
                r["time_bucket"], r["city"], r["employment_type"],
                r["job_count"],   r["distinct_company_count"], now,
            ))
        session.shutdown(); cluster.shutdown()
        log.info("Cassandra realtime_job_counts_10m: %d rows", len(rows))
    except Exception as e:
        log.error("Cassandra job_counts: %s", e)


# ════════════════════════════════════════════════════════════════════════════
# BATCH HANDLERS
# ════════════════════════════════════════════════════════════════════════════

def handle_job_counts(batch_df: DataFrame, batch_id: int):
    if batch_df.isEmpty():
        return
    rows = batch_df.collect()
    log.info("job_counts batch_id=%d | %d rows", batch_id, len(rows))

    cassandra_rows, es_docs = [], []
    for r in rows:
        tb  = r.window.start.strftime("%Y-%m-%dT%H:%M:00Z") if r.window else ""
        rec = {
            "time_bucket":            tb,
            "city":                   r.city            or "",
            "employment_type":        r.employment_type or "",
            "job_count":              int(r.job_count),
            "distinct_company_count": int(r.distinct_company_count),
        }
        cassandra_rows.append(rec)
        es_docs.append({**rec, "indexed_at": datetime.utcnow().isoformat()})

    _write_job_counts(cassandra_rows)
    _bulk_es(es_docs, "realtime_job_counts_v1")


def handle_skill_counts(batch_df: DataFrame, batch_id: int):
    if batch_df.isEmpty():
        return
    rows = batch_df.collect()
    log.info("skill_counts batch_id=%d | %d rows", batch_id, len(rows))

    cassandra_rows, es_docs = [], []
    for r in rows:
        tb  = r.window.start.strftime("%Y-%m-%dT%H:%M:00Z") if r.window else ""
        rec = {
            "time_bucket":            tb,
            "skill":                  r.skill or "",
            "city":                   r.city  or "",
            "job_count":              int(r.job_count),
            "distinct_company_count": int(r.distinct_company_count),
            "avg_salary_min":         float(r.avg_salary_min) if r.avg_salary_min else None,
            "avg_salary_max":         float(r.avg_salary_max) if r.avg_salary_max else None,
        }
        cassandra_rows.append(rec)
        es_docs.append({**rec, "indexed_at": datetime.utcnow().isoformat()})

    _write_skill_counts(cassandra_rows)
    _bulk_es(es_docs, "gold_skill_counts_daily_v1")


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

def main():
    spark = (
        SparkSession.builder
        .appName("speed-layer-aggregator")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    log.info("Aggregator đọc từ topic: %s", TOPIC_CLEAN)

    # 1. Đọc stream
    raw = (
        spark.readStream
        .format("kafka")
        .option("kafka.bootstrap.servers", KAFKA_BOOTSTRAP)
        .option("subscribe", TOPIC_CLEAN)
        .option("startingOffsets", "latest")
        .option("failOnDataLoss", "false")
        .load()
    )

    # 2. Parse JSON → struct, thêm event_time timestamp
    parsed = (
        raw
        .selectExpr("CAST(value AS STRING) AS raw_json")
        .withColumn("d", from_json(col("raw_json"), CLEAN_SCHEMA))
        .select("d.*")
        .withColumn(
            "event_time",
            coalesce(to_timestamp(col("event_ts")), current_timestamp()),
        )
        .filter(col("job_id").isNotNull())
    )

    # 3a. Query: job counts theo window + city + employment_type
    job_counts_df = (
        parsed
        .withWatermark("event_time", WATERMARK_DELAY)
        .groupBy(
            window(col("event_time"), WINDOW_DURATION, SLIDE_DURATION),
            col("city"),
            col("employment_type"),
        )
        .agg(
            count("job_id").alias("job_count"),
            countDistinct("company_name").alias("distinct_company_count"),
        )
    )

    q1 = (
        job_counts_df.writeStream
        .outputMode("update")
        .option("checkpointLocation", f"{CHECKPOINT_DIR}/job_counts")
        .foreachBatch(handle_job_counts)
        .trigger(processingTime=f"{TRIGGER_SEC} seconds")
        .start()
    )

    # 3b. Query: skill counts – explode skills array trước rồi group
    skill_counts_df = (
        parsed
        .withWatermark("event_time", WATERMARK_DELAY)
        .select(
            col("job_id"), col("company_name"), col("city"),
            col("salary_min"), col("salary_max"), col("event_time"),
            explode(col("skills")).alias("skill"),
        )
        .filter(col("skill").isNotNull() & (col("skill") != ""))
        .groupBy(
            window(col("event_time"), WINDOW_DURATION, SLIDE_DURATION),
            col("skill"), col("city"),
        )
        .agg(
            count("job_id").alias("job_count"),
            countDistinct("company_name").alias("distinct_company_count"),
            avg("salary_min").alias("avg_salary_min"),
            avg("salary_max").alias("avg_salary_max"),
        )
    )

    q2 = (
        skill_counts_df.writeStream
        .outputMode("update")
        .option("checkpointLocation", f"{CHECKPOINT_DIR}/skill_counts")
        .foreachBatch(handle_skill_counts)
        .trigger(processingTime=f"{TRIGGER_SEC} seconds")
        .start()
    )

    log.info("2 queries đang chạy | window=%s watermark=%s",
             WINDOW_DURATION, WATERMARK_DELAY)
    spark.streams.awaitAnyTermination()


if __name__ == "__main__":
    main()