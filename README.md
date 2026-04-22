# Speed Layer: Real-time Job Data Pipeline

Kiến trúc pub-sub Producer → Kafka → Consumer (Spark):

```
┌─────────────────┐
│ Crawler         │ (apps/ingestion/crawler_producer.py)
│ (TopCV scraper) │─── JSON Envelope ──→ Kafka: jobs_raw
└─────────────────┘
                        │
          ┌─────────────┴─────────────┐
          │                           │
    ┌─────▼──────────┐       ┌────────▼─────────┐
    │ Consumer 1     │       │ Consumer 2       │
    │ (spark_        │       │ (realtime_       │
    │  consumer.py)  │       │  aggregator.py)  │
    └──┬──┬──────────┘       └────┬──┬──────────┘
       │  │                       │  │
       │  ├─→ Elasticsearch       │  ├─→ Cassandra (agg)
       │  └─→ Cassandra          │  └─→ Elasticsearch (agg)
       └──→ Kafka: jobs_clean ───┘
```

## Directory Structure

```
.
├── README.md                           ← This file
├── .gitignore
├── requirements.txt                    ← Python dependencies (local dev)
├── docker-compose.yml                  ← Spin up Kafka/ES/Cassandra locally
├── Makefile                            ← Helper commands (make run-producer, etc)
│
├── apps/
│   ├── __init__.py
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── crawler_producer.py         ← PRODUCER: crawl jobs, send to Kafka
│   │   ├── mock_crawler.py             ← Mock producer for testing
│   │   └── sample_jobs.json            ← Sample data for --from-file
│   │
│   └── stream/
│       ├── __init__.py
│       ├── spark_consumer.py           ← CONSUMER 1: validate → ES + Cassandra
│       ├── realtime_aggregator.py      ← CONSUMER 2: window agg
│       ├── dlq_handler.py              ← (Optional) consume jobs_dead_letter
│       └── test_transformations.py     ← Unit tests (không cần Spark)
│
├── infra/
│   ├── kafka/
│   │   └── strimzi-topics.yaml         ← Kafka topics (K8s deployment)
│   │
│   ├── cassandra/
│   │   ├── cassandra-ddl.cql           ← Create tables, indexes
│   │   └── cassandra-init.sh           ← Init script for local docker-compose
│   │
│   ├── elasticsearch/
│   │   ├── mappings.json               ← Index templates (optional)
│   │   └── elasticsearch-init.sh       ← Init script for docker-compose
│   │
│   └── spark/
│       ├── Dockerfile                  ← Build Spark image (Kafka + ES + Cassandra)
│       ├── 10-rbac.yaml                ← K8s RBAC: ServiceAccount, Role, RoleBinding
│       ├── 20-spark-consumer.yaml      ← K8s SparkApplication (spark-operator)
│       └── 30-aggregator.yaml          ← K8s SparkApplication (aggregator)
│
├── configs/
│   ├── __init__.py
│   ├── config.py                       ← Python dataclass config
│   └── kubernetes/
│       ├── configmap.yaml              ← K8s ConfigMap (env vars)
│       ├── secret-cassandra.yaml       ← K8s Secret (Cassandra creds)
│       └── secret-elasticsearch.yaml   ← K8s Secret (ES creds)
│
├── scripts/
│   ├── submit_consumer.sh              ← spark-submit lên K8s
│   ├── submit_aggregator.sh            ← spark-submit lên K8s
│   ├── local_test.sh                   ← Run locally with docker-compose
│   └── cleanup.sh                      ← Remove Docker containers
│
└── tests/
    ├── __init__.py
    ├── test_producer.py                ← Test crawler_producer (no Kafka needed)
    ├── test_transformations.py         ← Test transform logic (no Spark needed)
    ├── test_spark_consumer.py          ← Integration test (with Spark)
    └── conftest.py                     ← pytest fixtures
```

## Quick Start - Local Development

### 1. Setup Python Environment

```bash
# Clone repo
git clone https://github.com/your-org/speed-layer.git
cd speed-layer

# Python 3.10+
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Spin Up Infrastructure (Docker Compose)

```bash
# Start Kafka + Elasticsearch + Cassandra
docker-compose up -d

# Wait for services to be ready (~30s)
sleep 30

# Init Cassandra tables
bash infra/cassandra/cassandra-init.sh

# Init Elasticsearch (optional)
bash infra/elasticsearch/elasticsearch-init.sh
```

### 3. Run Producer (Demo)

```bash
# Send 1 demo message to Kafka (no internet needed)
python3 apps/ingestion/crawler_producer.py --dry-run

# Send to real Kafka topic (--kafka localhost:29092 for docker-compose)
python3 apps/ingestion/crawler_producer.py --dry-run \
  --kafka localhost:29092

# Load sample data from file
python3 apps/ingestion/crawler_producer.py \
  --from-file apps/ingestion/sample_jobs.json \
  --kafka localhost:29092
```

### 4. Run Consumer (Spark)

```bash
# Local mode (no Spark cluster needed, runs in process)
spark-submit \
  --packages org.apache.spark:spark-sql-kafka-0-10_2.13:4.1.1 \
  --conf spark.kafka.bootstrap.servers=localhost:29092 \
  --conf spark.cassandra.connection.host=localhost \
  --conf spark.elasticsearch.nodes=localhost \
  apps/stream/spark_consumer.py

# Or use Makefile
make run-consumer
```

### 5. Run Aggregator

```bash
spark-submit \
  --packages org.apache.spark:spark-sql-kafka-0-10_2.13:4.1.1 \
  apps/stream/realtime_aggregator.py

# Or
make run-aggregator
```

### 6. Verify Data

```bash
# Check Elasticsearch
curl -s http://localhost:9200/jobs_realtime_v1/_count | jq

# Check Cassandra
cqlsh -e "SELECT COUNT(*) FROM demo_jobs.jobs_streaming;"

# Monitor Kafka (in another terminal)
kafka-console-consumer.sh \
  --bootstrap-server localhost:29092 \
  --topic jobs_raw \
  --from-beginning
```

### Cleanup

```bash
docker-compose down
bash scripts/cleanup.sh
```

---

## Kubernetes Deployment

### Prerequisites

- K8s cluster (minikube, EKS, GKE, etc)
- `kubectl` configured
- Strimzi Kafka operator (for topics)
- K8s Spark operator (optional, for SparkApplication manifests)
- Cassandra + Elasticsearch already deployed

### Deploy

```bash
# 1. Create namespaces
kubectl create namespace spark
kubectl create namespace kafka
kubectl create namespace streaming

# 2. Build & push Docker image
docker build -t your-registry/spark-kafka-es:v1 -f infra/spark/Dockerfile .
docker push your-registry/spark-kafka-es:v1

# 3. Apply RBAC
kubectl apply -f infra/spark/10-rbac.yaml

# 4. Create ConfigMap + Secrets
kubectl apply -f configs/kubernetes/configmap.yaml
kubectl apply -f configs/kubernetes/secret-cassandra.yaml
kubectl apply -f configs/kubernetes/secret-elasticsearch.yaml

# 5. Create Kafka topics
kubectl apply -f infra/kafka/strimzi-topics.yaml

# 6. Submit Spark jobs
bash scripts/submit_consumer.sh consumer
bash scripts/submit_consumer.sh aggregator

# 7. Check status
kubectl logs -f spark-consumer-driver -n spark
kubectl logs -f speed-aggregator-driver -n spark
```

---

## Test

```bash
# Unit tests (no Spark/Kafka needed)
pytest tests/test_producer.py -v
pytest tests/test_transformations.py -v

# Integration test (with docker-compose)
pytest tests/test_spark_consumer.py -v

# Coverage
pytest --cov=apps tests/
```

---

## Configuration

### Environment Variables

Producer:
```bash
KAFKA_BOOTSTRAP=localhost:29092
```

Consumer 1 (spark_consumer.py):
```bash
KAFKA_BOOTSTRAP=my-cluster-kafka-bootstrap.kafka.svc:9092
KAFKA_TOPIC_RAW=jobs_raw
ES_URL=http://elasticsearch.streaming.svc:9200
CASSANDRA_HOST=demo-dc1-service.k8ssandra-operator.svc
CASSANDRA_PORT=9042
CASSANDRA_USERNAME=cassandra
CASSANDRA_PASSWORD=<secret>
TRIGGER_SEC=10
CHECKPOINT_DIR=/tmp/checkpoints/consumer
```

Consumer 2 (realtime_aggregator.py):
```bash
KAFKA_BOOTSTRAP=my-cluster-kafka-bootstrap.kafka.svc:9092
KAFKA_TOPIC_CLEAN=jobs_clean
ES_URL=http://elasticsearch.streaming.svc:9200
CASSANDRA_HOST=demo-dc1-service.k8ssandra-operator.svc
WINDOW_DURATION="10 minutes"
SLIDE_DURATION="1 minute"
WATERMARK_DELAY="10 minutes"
TRIGGER_SEC=30
```

### Files to Customize

1. **docker-compose.yml** - adjust port numbers, volumes
2. **infra/spark/Dockerfile** - pin versions
3. **configs/kubernetes/configmap.yaml** - Kafka brokers, ES URL
4. **infra/cassandra/cassandra-ddl.cql** - replication factor, TTL
5. **infra/kafka/strimzi-topics.yaml** - partition count, retention

---

## Troubleshooting

### Producer can't connect to Kafka

```bash
# Check Kafka is running
docker ps | grep kafka

# Check broker is listening
telnet localhost 29092

# Or use kafka-broker-api-versions.sh
kafka-broker-api-versions.sh \
  --bootstrap-server localhost:29092
```

### Spark Consumer stuck / no output

```bash
# Check checkpoint (resuming from old offset)
rm -rf /tmp/checkpoints/consumer

# Check Kafka topic has messages
kafka-console-consumer.sh --bootstrap-server localhost:29092 --topic jobs_raw --from-beginning

# Monitor Spark
curl http://spark-driver:4040

# Check Cassandra/ES connectivity
spark-shell --packages org.apache.spark:spark-cassandra-connector_2.13:3.5.0 <<EOF
import com.datastax.spark.connector._
sc.cassandraTable("demo_jobs", "jobs_streaming").count()
EOF
```

### Elasticsearch data not appearing

```bash
# Check ES is up
curl http://localhost:9200

# Check index exists
curl http://localhost:9200/_cat/indices

# Check mappings
curl http://localhost:9200/jobs_realtime_v1/_mappings

# Tail driver logs for ES errors
kubectl logs -f spark-consumer-driver -n spark | grep -i elasticsearch
```

---

## Data Flow Example

```json
[CRAWLER] TopCV scraper downloads job posting
     ↓
[ENVELOPE] Wraps in RawEnvelope (source, source_url, payload, ingest_ts)
     ↓
[KAFKA] jobs_raw topic ← key: job_id (sha256), value: RawEnvelope JSON
     ↓
[CONSUMER 1] spark_consumer.py reads stream
     ├─ Validate & transform (normalize city, parse salary, filter skills)
     ├─ Write → Elasticsearch: jobs_realtime_v1
     ├─ Write → Cassandra: jobs_streaming table
     ├─ Publish → Kafka: jobs_clean (for Consumer 2)
     └─ (if error) → Kafka: jobs_dead_letter (DLQ)
     ↓
[CONSUMER 2] realtime_aggregator.py reads jobs_clean
     ├─ Watermark: allow 10 min late data
     ├─ Window: 10 min sliding every 1 min
     ├─ Agg 1: COUNT(*) GROUP BY (window, city, employment_type)
     │         → Cassandra: realtime_job_counts_10m
     ├─ Agg 2: COUNT(*), EXPLODE(skills) GROUP BY (window, skill, city)
     │         → Cassandra: realtime_skill_counts
     └─ Publish aggregates → Elasticsearch: gold_skill_counts_daily_v1
     ↓
[SERVING] API queries Elasticsearch + Cassandra for real-time insights
```

---

## Development

### Adding new field to payload

1. Update `RawPayload` dataclass in `apps/stream/spark_consumer.py`
2. Update HTML parser in `apps/ingestion/crawler_producer.py`
3. Add test case in `tests/test_producer.py`
4. Update schema in `ENVELOPE_SCHEMA`
5. Deploy new Consumer with `bash scripts/submit_consumer.sh consumer`

### Adding new aggregation

1. Add new aggregate SQL in `realtime_aggregator.py`
2. Create new Cassandra table in `infra/cassandra/cassandra-ddl.cql`
3. Add batch handler function in `realtime_aggregator.py`
4. Deploy with `bash scripts/submit_consumer.sh aggregator`

---

## Monitoring

### Metrics to track

- **Consumer lag** (Kafka lag per partition)
- **Spark processing time** (batch duration)
- **Cassandra write latency** (p99)
- **Elasticsearch refresh time**
- **Message errors** (DLQ count)
- **Watermark lateness** (max delay from event_ts to processing_ts)

### Dashboards

- Prometheus + Grafana (Spark metrics exporter)
- Kibana (Elasticsearch log dashboard)
- Nobl9 / Datadog / New Relic (SLO monitoring)

---

## License

MIT