import json
import os
import ssl
import urllib.request
from datetime import datetime, timezone

from cassandra.cluster import Cluster
from cassandra.auth import PlainTextAuthProvider
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, split


KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "my-cluster-kafka-bootstrap.kafka.svc:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "my-topic")

ES_URL = os.getenv("ES_URL", "http://elasticsearch.streaming.svc:9200")
ES_INDEX = os.getenv("ES_INDEX", "jobs_streaming")

CASSANDRA_HOST = os.getenv("CASSANDRA_HOST", "demo-dc1-service.k8ssandra-operator.svc")
CASSANDRA_PORT = int(os.getenv("CASSANDRA_PORT", "9042"))
CASSANDRA_USERNAME = os.getenv("CASSANDRA_USERNAME", "cassandra")
CASSANDRA_PASSWORD = os.getenv("CASSANDRA_PASSWORD", "cassandra")
CASSANDRA_KEYSPACE = os.getenv("CASSANDRA_KEYSPACE", "demo_jobs")


def bulk_index(docs):
    if not docs:
        return

    lines = []
    for doc in docs:
        lines.append(json.dumps({"index": {"_index": ES_INDEX}}))
        lines.append(json.dumps(doc, ensure_ascii=False))

    payload = ("\n".join(lines) + "\n").encode("utf-8")
    req = urllib.request.Request(
        f"{ES_URL}/_bulk",
        data=payload,
        headers={"Content-Type": "application/x-ndjson"},
        method="POST",
    )

    context = None
    if ES_URL.startswith("https://"):
        context = ssl._create_unverified_context()

    with urllib.request.urlopen(req, context=context) as resp:
        print(resp.read().decode("utf-8"))


def write_to_cassandra(rows):
    if not rows:
        return

    auth_provider = PlainTextAuthProvider(
        username=CASSANDRA_USERNAME,
        password=CASSANDRA_PASSWORD,
    )
    cluster = Cluster([CASSANDRA_HOST], port=CASSANDRA_PORT, auth_provider=auth_provider)
    session = cluster.connect(CASSANDRA_KEYSPACE)

    prepared = session.prepare(
        """
        INSERT INTO jobs_streaming (job_id, ingested_at, job_title, city, raw_value)
        VALUES (?, ?, ?, ?, ?)
        """
    )

    now = datetime.now(timezone.utc)

    for row in rows:
        session.execute(
            prepared,
            (
                row.get("job_id"),
                now,
                row.get("job_title"),
                row.get("city"),
                row.get("raw_value"),
            ),
        )

    session.shutdown()
    cluster.shutdown()


def write_dual(batch_df, batch_id):
    rows = [json.loads(x) for x in batch_df.toJSON().collect()]
    print(f"batch_id={batch_id}, rows={len(rows)}")

    if not rows:
        return

    write_to_cassandra(rows)
    bulk_index(rows)


spark = SparkSession.builder.appName("kafka-to-cassandra-es").getOrCreate()
spark.sparkContext.setLogLevel("WARN")

raw_df = (
    spark.readStream
    .format("kafka")
    .option("kafka.bootstrap.servers", KAFKA_BOOTSTRAP)
    .option("subscribe", KAFKA_TOPIC)
    .option("startingOffsets", "latest")
    .load()
)

parsed_df = (
    raw_df.selectExpr("CAST(value AS STRING) AS raw_value")
    .select(
        split(col("raw_value"), "\\|").getItem(0).alias("job_id"),
        split(col("raw_value"), "\\|").getItem(1).alias("job_title"),
        split(col("raw_value"), "\\|").getItem(2).alias("city"),
        col("raw_value")
    )
)

query = (
    parsed_df.writeStream
    .outputMode("append")
    .option("checkpointLocation", "/tmp/checkpoints/kafka_to_cassandra_es")
    .foreachBatch(write_dual)
    .start()
)

query.awaitTermination()