#!/usr/bin/env bash
# scripts/submit_consumer.sh
# ============================
# Submit các Spark job của Speed Layer lên Kubernetes.
#
# Usage:
#   bash scripts/submit_consumer.sh consumer     # main pipeline
#   bash scripts/submit_consumer.sh aggregator   # realtime aggregation
#   bash scripts/submit_consumer.sh all          # cả hai
#
# Prerequisites:
#   1. Kafka đang chạy trong namespace kafka
#   2. Elasticsearch đang chạy trong namespace streaming
#   3. Cassandra đang chạy trong namespace k8ssandra-operator
#   4. Spark RBAC đã apply: kubectl apply -f infra/spark/10-rbac.yaml
#   5. Docker image đã build và load:
#        docker build -t spark-kafka-es:demo -f infra/spark/Dockerfile .
#        minikube image load spark-kafka-es:demo

set -euo pipefail

# Lấy Kubernetes API server URL
K8S_API=$(kubectl cluster-info | grep -oP 'https://\S+' | head -1)
echo "→ K8s API: $K8S_API"

# Kafka package cho Spark (phải match Scala version của Spark image)
PACKAGES="org.apache.spark:spark-sql-kafka-0-10_2.13:4.1.1"

# Common options dùng cho mọi job
common_opts() {
    echo "--master k8s://${K8S_API}"
    echo "--deploy-mode cluster"
    echo "--packages ${PACKAGES}"
    echo "--conf spark.kubernetes.namespace=spark"
    echo "--conf spark.kubernetes.authenticate.driver.serviceAccountName=spark"
    echo "--conf spark.kubernetes.container.image=spark-kafka-es:demo"
    echo "--conf spark.kubernetes.container.image.pullPolicy=IfNotPresent"
    echo "--conf spark.executor.instances=1"
    echo "--conf spark.executor.memory=1g"
    echo "--conf spark.driver.memory=1g"
    # Python path trong container (phải match COPY trong Dockerfile)
    echo "--conf spark.kubernetes.driverEnv.PYTHONPATH=/opt/spark/work-dir"
    echo "--conf spark.executorEnv.PYTHONPATH=/opt/spark/work-dir"
    echo "--conf spark.kubernetes.driverEnv.PYSPARK_PYTHON=python3"
    echo "--conf spark.kubernetes.driverEnv.PYSPARK_DRIVER_PYTHON=python3"
    echo "--conf spark.executorEnv.PYSPARK_PYTHON=python3"
    echo "--conf spark.kubernetes.driverEnv.HOME=/tmp"
    echo "--conf spark.kubernetes.driverEnv.PATH=/usr/local/bin:/usr/bin:/bin"
    echo "--conf spark.executorEnv.PATH=/usr/local/bin:/usr/bin:/bin"
    # Java workarounds
    echo "--conf spark.driver.extraJavaOptions=-Duser.home=/tmp"
}

# Env vars cho Kafka / ES / Cassandra (inject vào driver pod)
kafka_env() {
    echo "--conf spark.kubernetes.driverEnv.KAFKA_BOOTSTRAP=my-cluster-kafka-bootstrap.kafka.svc:9092"
    echo "--conf spark.kubernetes.driverEnv.KAFKA_TOPIC_RAW=jobs_raw"
    echo "--conf spark.kubernetes.driverEnv.KAFKA_TOPIC_CLEAN=jobs_clean"
    echo "--conf spark.kubernetes.driverEnv.KAFKA_TOPIC_DLQ=jobs_dead_letter"
}

es_env() {
    echo "--conf spark.kubernetes.driverEnv.ES_URL=http://elasticsearch.streaming.svc:9200"
    echo "--conf spark.kubernetes.driverEnv.ES_INDEX=jobs_realtime_v1"
}

cassandra_env() {
    echo "--conf spark.kubernetes.driverEnv.CASSANDRA_HOST=demo-dc1-service.k8ssandra-operator.svc"
    echo "--conf spark.kubernetes.driverEnv.CASSANDRA_PORT=9042"
    echo "--conf spark.kubernetes.driverEnv.CASSANDRA_KEYSPACE=demo_jobs"
    # NOTE: username/password nên dùng Kubernetes Secret thay vì hardcode
    echo "--conf spark.kubernetes.driverEnv.CASSANDRA_USERNAME=cassandra"
    echo "--conf spark.kubernetes.driverEnv.CASSANDRA_PASSWORD=cassandra"
}

# ── Submit main Consumer (kafka_raw → ES + Cassandra) ────────────────────────
submit_consumer() {
    echo "=== Submitting CONSUMER (spark_consumer.py) ==="
    spark-submit \
        $(common_opts) \
        $(kafka_env) \
        $(es_env) \
        $(cassandra_env) \
        --name "speed-consumer" \
        --conf spark.kubernetes.driverEnv.TRIGGER_SEC=10 \
        --conf spark.kubernetes.driverEnv.CHECKPOINT_DIR=/tmp/checkpoints/consumer \
        local:///opt/spark/work-dir/apps/stream/spark_consumer.py
}

# ── Submit Aggregator (jobs_clean → Cassandra aggregate) ─────────────────────
submit_aggregator() {
    echo "=== Submitting AGGREGATOR (realtime_aggregator.py) ==="
    spark-submit \
        $(common_opts) \
        $(kafka_env) \
        $(es_env) \
        $(cassandra_env) \
        --name "speed-aggregator" \
        --conf spark.kubernetes.driverEnv.TRIGGER_SEC=30 \
        --conf spark.kubernetes.driverEnv.WINDOW_DURATION="10 minutes" \
        --conf spark.kubernetes.driverEnv.SLIDE_DURATION="1 minute" \
        --conf spark.kubernetes.driverEnv.WATERMARK_DELAY="10 minutes" \
        --conf spark.kubernetes.driverEnv.CHECKPOINT_DIR=/tmp/checkpoints/aggregator \
        local:///opt/spark/work-dir/apps/stream/realtime_aggregator.py
}

# ── Entry point ───────────────────────────────────────────────────────────────
case "${1:-all}" in
    consumer)   submit_consumer ;;
    aggregator) submit_aggregator ;;
    all)
        submit_consumer &
        sleep 10
        submit_aggregator &
        wait
        ;;
    *)
        echo "Usage: $0 {consumer|aggregator|all}"
        exit 1
        ;;
esac