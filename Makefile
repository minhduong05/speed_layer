# Makefile
# ========
# Helper commands để develop + run locally.
#
# Usage:
#   make up          # docker-compose up
#   make down        # docker-compose down
#   make producer    # python crawler_producer.py --dry-run
#   make run-consumer # spark-submit consumer
#   make test        # pytest

.PHONY: help up down init producer run-consumer run-aggregator clean test logs

help:
	@echo "Speed Layer Makefile"
	@echo ""
	@echo "Infrastructure:"
	@echo "  make up              docker-compose up -d"
	@echo "  make down            docker-compose down -v"
	@echo "  make init            init Cassandra tables"
	@echo "  make logs            follow docker logs"
	@echo ""
	@echo "Producers & Consumers:"
	@echo "  make producer        python crawler_producer --dry-run (demo)"
	@echo "  make producer-load   python crawler_producer --from-file sample_jobs.json"
	@echo "  make run-consumer    spark-submit spark_consumer.py"
	@echo "  make run-aggregator  spark-submit realtime_aggregator.py"
	@echo ""
	@echo "Testing & Maintenance:"
	@echo "  make test            pytest"
	@echo "  make clean           rm -rf __pycache__ .pytest_cache checkpoints"
	@echo "  make docker-clean    docker system prune"

# ════════════════════════════════════════════════════════════════════════════
# Infrastructure
# ════════════════════════════════════════════════════════════════════════════

up:
	docker-compose up -d
	@echo "⏳ Waiting for services..."
	@sleep 15
	@echo "✓ Services started"
	@docker-compose ps

down:
	docker-compose down -v
	@echo "✓ Cleaned up"

init: up
	@echo "Initializing Cassandra..."
	bash infra/cassandra/cassandra-init.sh
	@echo "✓ Cassandra initialized"

init-es:
	@echo "Initializing Elasticsearch..."
	curl -X PUT "localhost:9200/jobs_realtime_v1" 2>/dev/null || true

logs:
	docker-compose logs -f

ps:
	docker-compose ps

# ════════════════════════════════════════════════════════════════════════════
# Producer
# ════════════════════════════════════════════════════════════════════════════

producer:
	@python3 apps/ingestion/crawler_producer.py --dry-run

producer-test:
	@python3 apps/ingestion/crawler_producer.py \
		--kafka localhost:29092 \
		--dry-run

producer-load:
	@python3 apps/ingestion/crawler_producer.py \
		--from-file apps/ingestion/sample_jobs.json \
		--kafka localhost:29092

producer-crawl:
	@read -p "Enter URL: " url; \
	python3 apps/ingestion/crawler_producer.py \
		--url "$$url" \
		--kafka localhost:29092

# ════════════════════════════════════════════════════════════════════════════
# Consumers (Spark)
# ════════════════════════════════════════════════════════════════════════════

run-consumer:
	@spark-submit \
		--packages org.apache.spark:spark-sql-kafka-0-10_2.13:4.1.1 \
		--conf spark.kafka.bootstrap.servers=localhost:29092 \
		--conf spark.cassandra.connection.host=localhost \
		--conf spark.elasticsearch.nodes=localhost \
		--conf spark.kubernetes.driverEnv.KAFKA_BOOTSTRAP=localhost:29092 \
		--conf spark.kubernetes.driverEnv.ES_URL=http://localhost:9200 \
		--conf spark.kubernetes.driverEnv.CASSANDRA_HOST=localhost \
		--master local \
		apps/stream/spark_consumer.py

run-aggregator:
	@spark-submit \
		--packages org.apache.spark:spark-sql-kafka-0-10_2.13:4.1.1 \
		--conf spark.kafka.bootstrap.servers=localhost:29092 \
		--conf spark.cassandra.connection.host=localhost \
		--conf spark.elasticsearch.nodes=localhost \
		--conf spark.kubernetes.driverEnv.KAFKA_BOOTSTRAP=localhost:29092 \
		--conf spark.kubernetes.driverEnv.ES_URL=http://localhost:9200 \
		--conf spark.kubernetes.driverEnv.CASSANDRA_HOST=localhost \
		--master local \
		apps/stream/realtime_aggregator.py

# ════════════════════════════════════════════════════════════════════════════
# Testing
# ════════════════════════════════════════════════════════════════════════════

test:
	pytest tests/ -v --tb=short

test-producer:
	pytest tests/test_producer.py -v

test-transform:
	pytest tests/test_transformations.py -v

test-cov:
	pytest --cov=apps --cov-report=html tests/
	@echo "Coverage: open htmlcov/index.html"

# ════════════════════════════════════════════════════════════════════════════
# Monitoring / Debugging
# ════════════════════════════════════════════════════════════════════════════

kafka-monitor:
	@echo "Kafka UI: http://localhost:8080"

kafka-topics:
	kafka-topics.sh --bootstrap-server localhost:29092 --list

kafka-consume:
	kafka-console-consumer.sh \
		--bootstrap-server localhost:29092 \
		--topic jobs_raw \
		--from-beginning

cassandra-query:
	cqlsh -e "SELECT COUNT(*) FROM demo_jobs.jobs_streaming;"

es-count:
	curl -s http://localhost:9200/jobs_realtime_v1/_count | jq .

es-docs:
	curl -s http://localhost:9200/jobs_realtime_v1/_search?size=5 | jq '.hits.hits[0]._source'

# ════════════════════════════════════════════════════════════════════════════
# Cleanup
# ════════════════════════════════════════════════════════════════════════════

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf /tmp/checkpoints/
	@echo "✓ Cleaned up"

docker-clean:
	docker system prune -f
	@echo "✓ Docker cleaned"

# ════════════════════════════════════════════════════════════════════════════
# Development workflow
# ════════════════════════════════════════════════════════════════════════════

dev-setup: up init
	@echo "✓ Development environment ready"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Load sample data:  make producer-load"
	@echo "  2. Run consumer:      make run-consumer"
	@echo "  3. Run aggregator:    make run-aggregator"
	@echo "  4. Monitor:           make kafka-monitor (http://localhost:8080)"
	@echo "  5. Check data:        make es-count"

demo: dev-setup producer-load
	@echo "✓ Demo data loaded"