"""
apps/stream/spark_consumer.py
==============================
BƯỚC 2: CONSUMER (Spark Structured Streaming)
Đọc từ Kafka topic "jobs_raw", xử lý, ghi kết quả ra Elasticsearch + Cassandra.

Kiến trúc pub-sub:
    [Crawler Producer] --> Kafka topic: jobs_raw --> [THIS FILE - Spark Consumer]
                                                          |
                                                          +--> Elasticsearch (jobs_realtime_v1)
                                                          +--> Cassandra (jobs_streaming)
                                                          +--> Kafka (jobs_dead_letter) nếu lỗi

Cách chạy với spark-submit:
    spark-submit \\
      --packages org.apache.spark:spark-sql-kafka-0-10_2.13:4.1.1 \\
      --conf spark.executor.instances=1 \\
      apps/stream/spark_consumer.py

Hoặc qua script:
    bash scripts/submit_consumer.sh

Cài thư viện:
    pip install cassandra-driver
"""

import json
import ssl
import os
import urllib.request
import logging
import sys
from datetime import datetime, timezone

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, from_json, get_json_object
from pyspark.sql.types import (
    StructType, StructField,
    StringType, IntegerType, BooleanType,
    ArrayType, MapType, DoubleType,
)

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("spark_consumer")

# ── Cấu hình – đọc từ environment variables (inject qua Kubernetes ConfigMap) ──
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP",  "my-cluster-kafka-bootstrap.kafka.svc:9092")
TOPIC_RAW       = os.getenv("KAFKA_TOPIC_RAW",  "jobs_raw")
TOPIC_DLQ       = os.getenv("KAFKA_TOPIC_DLQ",  "jobs_dead_letter")
ES_URL          = os.getenv("ES_URL",            "http://elasticsearch.streaming.svc:9200")
ES_INDEX        = os.getenv("ES_INDEX",          "jobs_realtime_v1")
CASSANDRA_HOST  = os.getenv("CASSANDRA_HOST",    "demo-dc1-service.k8ssandra-operator.svc")
CASSANDRA_PORT  = int(os.getenv("CASSANDRA_PORT", "9042"))
CASSANDRA_USER  = os.getenv("CASSANDRA_USERNAME", "cassandra")
CASSANDRA_PASS  = os.getenv("CASSANDRA_PASSWORD", "cassandra")
CASSANDRA_KS    = os.getenv("CASSANDRA_KEYSPACE", "demo_jobs")
CHECKPOINT_DIR  = os.getenv("CHECKPOINT_DIR",    "/tmp/checkpoints/spark_consumer")
TRIGGER_SEC     = int(os.getenv("TRIGGER_SEC",    "10"))


# ════════════════════════════════════════════════════════════════════════════
# PHẦN 1: SCHEMA – Spark cần biết cấu trúc JSON trước khi parse
# ════════════════════════════════════════════════════════════════════════════

# Schema cho "payload" bên trong RawEnvelope
PAYLOAD_SCHEMA = StructType([
    StructField("domain",           StringType(), True),
    StructField("fetch_method",     StringType(), True),
    StructField("title",            StringType(), True),
    StructField("company_name",     StringType(), True),
    StructField("salary",           StringType(), True),
    StructField("location",         StringType(), True),
    StructField("experience",       StringType(), True),
    StructField("deadline",         StringType(), True),
    StructField("job_type",         StringType(), True),   # audit only
    StructField("description",      StringType(), True),
    StructField("requirements",     StringType(), True),
    StructField("benefits",         StringType(), True),
    StructField("skills",           ArrayType(StringType()), True),
    StructField("categories",       ArrayType(StringType()), True),
    StructField("requirement_items",ArrayType(StringType()), True),
    StructField("benefit_items",    ArrayType(StringType()), True),
    StructField("page_text",        StringType(), True),
])

# Schema tổng thể của 1 Kafka message value (RawEnvelope)
ENVELOPE_SCHEMA = StructType([
    StructField("source",                StringType(), True),
    StructField("source_url",            StringType(), True),
    StructField("normalized_source_url", StringType(), True),
    StructField("crawl_version",         IntegerType(), True),
    StructField("ingest_ts",             StringType(), True),
    StructField("event_ts",              StringType(), True),
    StructField("payload",               PAYLOAD_SCHEMA, True),
])


# ════════════════════════════════════════════════════════════════════════════
# PHẦN 2: XỬ LÝ TỪNG BATCH (foreachBatch)
# Đây là trái tim của Consumer – chạy mỗi TRIGGER_SEC giây
# ════════════════════════════════════════════════════════════════════════════

def process_batch(batch_df, batch_id: int):
    """
    Spark gọi hàm này mỗi micro-batch.
    batch_df: DataFrame các rows đã parse từ Kafka
    batch_id: số thứ tự batch (dùng để log)
    """
    if batch_df.isEmpty():
        return

    rows = batch_df.collect()
    log.info("batch_id=%d | %d messages", batch_id, len(rows))

    ok_docs   = []   # ghi vào ES + Cassandra
    dlq_msgs  = []   # ghi vào dead letter topic

    for row in rows:
        # row.raw_json = chuỗi JSON gốc từ Kafka
        # row.job_id   = đã tính sẵn ở tầng Spark SQL (xem phần đọc stream bên dưới)
        try:
            doc = _transform_row(row)
            ok_docs.append(doc)
        except Exception as e:
            log.warning("Transform lỗi job_id=%s: %s", getattr(row, "job_id", "?"), e)
            dlq_msgs.append({
                "original_topic":   TOPIC_RAW,
                "original_message": getattr(row, "raw_json", ""),
                "error_type":       type(e).__name__,
                "error_message":    str(e),
                "failed_at":        datetime.utcnow().isoformat(),
            })

    # ── Ghi kết quả ─────────────────────────────────────────────────────────
    if ok_docs:
        _write_elasticsearch(ok_docs)
        _write_cassandra(ok_docs)

    if dlq_msgs:
        _write_dlq_kafka(dlq_msgs)

    log.info("batch_id=%d | ok=%d dlq=%d", batch_id, len(ok_docs), len(dlq_msgs))


def _transform_row(row) -> dict:
    """
    Biến 1 Spark Row thành document sẵn sàng index vào ES / upsert Cassandra.
    Các bước: validate required → parse salary → normalize city → filter skills.
    """
    p = row.payload   # nested struct

    # ── Validate: title bắt buộc ────────────────────────────────────────────
    if not p.title:
        raise ValueError("payload.title rỗng")

    # ── Parse salary ────────────────────────────────────────────────────────
    salary_min, salary_max, currency = _parse_salary(p.salary or "")

    # ── Normalize city ──────────────────────────────────────────────────────
    city = _normalize_city(p.location or "")

    # ── Filter skills ────────────────────────────────────────────────────────
    skills = _filter_skills(p.skills or [])

    return {
        # Keys
        "job_id":        row.job_id,
        "job_url":       row.source_url,
        "content_hash":  row.hash_content,
        # Job info
        "job_title":     p.title,
        "company_name":  p.company_name or "",
        "city":          city,
        "employment_type": "FULL_TIME",   # sẽ parse chính xác hơn ở batch ETL
        # Salary
        "salary_text":   p.salary or "",
        "salary_min":    salary_min,
        "salary_max":    salary_max,
        "currency":      currency,
        # Skills (đã lọc)
        "skills":        skills,
        # Timestamps
        "event_date":    (row.event_ts or "")[:10],
        "fetched_at":    row.ingest_ts or datetime.utcnow().isoformat(),
    }


# ════════════════════════════════════════════════════════════════════════════
# PHẦN 3: CÁC HÀM TRANSFORM NHỎ
# ════════════════════════════════════════════════════════════════════════════

# Các token nhiễu thường xuất hiện trong skill chips của TopCV
_NOISE = {
    "xem thêm", "nổi bật", "quyền lợi", "quyền lợi:",
    "hà nội", "hcm", "hồ chí minh", "đà nẵng",
    "toàn thời gian", "bán thời gian", "thực tập",
}

# Map tên tỉnh/thành → canonical
_CITY_MAP = {
    "hà nội": "Hà Nội",   "ha noi": "Hà Nội",   "hn": "Hà Nội",
    "hồ chí minh": "Hồ Chí Minh", "hcm": "Hồ Chí Minh",
    "tp hcm": "Hồ Chí Minh", "tp. hcm": "Hồ Chí Minh",
    "đà nẵng": "Đà Nẵng", "da nang": "Đà Nẵng",
    "cần thơ": "Cần Thơ", "hải phòng": "Hải Phòng",
    "bình dương": "Bình Dương", "đồng nai": "Đồng Nai",
    "remote": "Remote", "toàn quốc": "Toàn quốc",
}


def _parse_salary(text: str):
    """
    Parse 'XX - YY triệu' hoặc 'XX - YY USD' → (min, max, currency).
    Trả về (None, None, 'VND') nếu không parse được.
    """
    import re
    if not text:
        return None, None, "VND"

    t = text.lower()
    if "thỏa thuận" in t or "thoả thuận" in t:
        return None, None, "VND"

    currency = "USD" if ("usd" in t or "$" in t) else "VND"
    nums = re.findall(r"[\d]+(?:[,\.]\d+)?", text)
    nums = [float(n.replace(",", "")) for n in nums]

    if len(nums) >= 2:
        return min(nums[0], nums[1]), max(nums[0], nums[1]), currency
    if len(nums) == 1:
        return nums[0], None, currency
    return None, None, currency


def _normalize_city(text: str) -> str:
    """Tra bảng, trả về tên canonical hoặc giữ nguyên."""
    key = text.strip().lower()
    # Exact match
    if key in _CITY_MAP:
        return _CITY_MAP[key]
    # Partial match (ưu tiên key dài nhất)
    best, best_len = None, 0
    for k, v in _CITY_MAP.items():
        if k in key and len(k) > best_len:
            best, best_len = v, len(k)
    return best or text.strip()


def _filter_skills(raw: list) -> list:
    """Bỏ noise tokens, dedup, giữ lại skill hợp lệ."""
    seen, result = set(), []
    for s in raw:
        s = s.strip()
        if not s or len(s) < 2 or len(s) > 60:
            continue
        if s.lower() in _NOISE:
            continue
        key = s.lower()
        if key not in seen:
            seen.add(key)
            result.append(s)
    return result


# ════════════════════════════════════════════════════════════════════════════
# PHẦN 4: SINKS – ghi kết quả ra đích
# ════════════════════════════════════════════════════════════════════════════

def _write_elasticsearch(docs: list):
    """Ghi batch docs vào ES qua _bulk API."""
    lines = []
    for doc in docs:
        meta = {"index": {"_index": ES_INDEX, "_id": doc["job_id"]}}
        lines.append(json.dumps(meta))
        lines.append(json.dumps(doc, ensure_ascii=False, default=str))

    body = ("\n".join(lines) + "\n").encode("utf-8")
    req  = urllib.request.Request(
        f"{ES_URL}/_bulk",
        data=body,
        headers={"Content-Type": "application/x-ndjson"},
        method="POST",
    )
    ctx = ssl._create_unverified_context() if ES_URL.startswith("https") else None
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            result = json.loads(resp.read())
            if result.get("errors"):
                log.warning("ES bulk có lỗi: %s errors", result.get("errors"))
            else:
                log.info("ES: indexed %d docs vào %s", len(docs), ES_INDEX)
    except Exception as e:
        log.error("ES write failed: %s", e)


def _write_cassandra(docs: list):
    """
    Upsert docs vào Cassandra table jobs_streaming.
    Dùng INSERT (Cassandra upsert by primary key tự động).
    """
    try:
        from cassandra.cluster import Cluster
        from cassandra.auth import PlainTextAuthProvider

        auth    = PlainTextAuthProvider(username=CASSANDRA_USER, password=CASSANDRA_PASS)
        cluster = Cluster([CASSANDRA_HOST], port=CASSANDRA_PORT, auth_provider=auth)
        session = cluster.connect(CASSANDRA_KS)

        stmt = session.prepare("""
            INSERT INTO jobs_streaming
                (job_id, ingested_at, job_title, company_name, city,
                 salary_min, salary_max, employment_type, skills, event_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """)

        now = datetime.now(timezone.utc)
        for d in docs:
            session.execute(stmt, (
                d["job_id"], now,
                d["job_title"], d["company_name"], d["city"],
                d["salary_min"], d["salary_max"],
                d["employment_type"],
                d["skills"],
                d["event_date"],
            ))

        session.shutdown()
        cluster.shutdown()
        log.info("Cassandra: upserted %d rows", len(docs))
    except Exception as e:
        log.error("Cassandra write failed: %s", e)


def _write_dlq_kafka(dlq_msgs: list):
    """Gửi các message lỗi vào dead letter topic để debug sau."""
    try:
        from kafka import KafkaProducer
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode(),
            acks=1,
        )
        for msg in dlq_msgs:
            producer.send(TOPIC_DLQ, value=msg)
        producer.flush()
        producer.close()
        log.warning("DLQ: sent %d failed messages to %s", len(dlq_msgs), TOPIC_DLQ)
    except Exception as e:
        log.error("DLQ write failed: %s", e)


# ════════════════════════════════════════════════════════════════════════════
# PHẦN 5: MAIN – khởi động Spark Streaming
# ════════════════════════════════════════════════════════════════════════════

def main():
    spark = (
        SparkSession.builder
        .appName("speed-layer-consumer")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    log.info("Consumer bắt đầu đọc từ Kafka topic: %s", TOPIC_RAW)

    # ── 1. Đọc stream từ Kafka ───────────────────────────────────────────────
    raw_stream = (
        spark.readStream
        .format("kafka")
        .option("kafka.bootstrap.servers", KAFKA_BOOTSTRAP)
        .option("subscribe", TOPIC_RAW)
        .option("startingOffsets", "latest")      # chỉ đọc messages mới
        .option("failOnDataLoss", "false")         # không fail nếu Kafka purge
        .option("maxOffsetsPerTrigger", 500)       # giới hạn batch size
        .load()
    )

    # ── 2. Parse Kafka bytes → struct ────────────────────────────────────────
    # Kafka message: key (bytes) + value (bytes)
    # value = JSON string của RawEnvelope
    parsed = (
        raw_stream
        .selectExpr(
            "CAST(value AS STRING) AS raw_json",
            "CAST(key AS STRING)   AS kafka_key",
            "timestamp             AS kafka_ts",
        )
        # Parse JSON theo ENVELOPE_SCHEMA đã định nghĩa ở trên
        .withColumn("env", from_json(col("raw_json"), ENVELOPE_SCHEMA))
        # Tính job_id ngay tại đây bằng Spark SQL để dùng làm partition key
        # sha256 thuần Python không có trong Spark SQL nên dùng kafka_key đã có sẵn
        # (Producer đã gửi job_id làm Kafka key)
        .withColumn("job_id",       col("kafka_key"))
        .withColumn("source_url",   col("env.source_url"))
        .withColumn("hash_content", col("env.normalized_source_url"))
        .withColumn("ingest_ts",    col("env.ingest_ts"))
        .withColumn("event_ts",     col("env.event_ts"))
        .withColumn("payload",      col("env.payload"))
        # Chỉ giữ các cột cần thiết
        .select(
            "job_id", "source_url", "hash_content",
            "ingest_ts", "event_ts", "payload", "raw_json",
        )
        # Bỏ rows không parse được (JSON lỗi → env sẽ null)
        .filter(col("env.source_url").isNotNull())
    )

    # ── 3. Write stream – mỗi TRIGGER_SEC giây gọi process_batch ────────────
    query = (
        parsed.writeStream
        .outputMode("append")
        .option("checkpointLocation", CHECKPOINT_DIR)
        .foreachBatch(process_batch)
        .trigger(processingTime=f"{TRIGGER_SEC} seconds")
        .start()
    )

    log.info(
        "Streaming query đang chạy | trigger=%ds | checkpoint=%s",
        TRIGGER_SEC, CHECKPOINT_DIR,
    )
    query.awaitTermination()


if __name__ == "__main__":
    main()