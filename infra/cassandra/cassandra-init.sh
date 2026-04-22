#!/usr/bin/env bash
# infra/cassandra/cassandra-init.sh
# ==================================
# Khởi tạo Cassandra keyspace + tables.
#
# Chạy sau docker-compose up:
#   bash infra/cassandra/cassandra-init.sh

set -euo pipefail

CASSANDRA_HOST=${CASSANDRA_HOST:-localhost}
CASSANDRA_PORT=${CASSANDRA_PORT:-9042}

echo "Waiting for Cassandra to be ready..."
for i in {1..30}; do
    if cqlsh -u cassandra -p cassandra "$CASSANDRA_HOST" "$CASSANDRA_PORT" -e "SELECT cluster_name FROM system.local;" 2>/dev/null; then
        echo "✓ Cassandra is ready"
        break
    fi
    echo "  Attempt $i/30..."
    sleep 2
done

echo "Creating keyspace and tables..."
cqlsh -u cassandra -p cassandra "$CASSANDRA_HOST" "$CASSANDRA_PORT" < infra/cassandra/cassandra-ddl.cql

echo "✓ Cassandra initialized"