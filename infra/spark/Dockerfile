# infra/spark/Dockerfile
# ========================
# Build image Spark cho Speed Layer.
#
# Build:
#   docker build -t spark-kafka-es:demo -f infra/spark/Dockerfile .
#
# Test:
#   docker run --rm spark-kafka-es:demo python3 --version
#   docker run --rm spark-kafka-es:demo python3 -c "import cassandra; print('cassandra ok')"

FROM apache/spark:4.1.1-python3

USER root

# Symlink python → python3
RUN pybin="$(command -v python3)" \
 && ln -sf "$pybin" /usr/bin/python \
 && ln -sf "$pybin" /usr/local/bin/python \
 && python --version \
 && python3 --version

# Cài thư viện
RUN pip3 install --no-cache-dir \
    cassandra-driver==3.29.2 \
    kafka-python==2.0.2 \
    requests==2.31.0 \
    beautifulsoup4==4.12.3

ENV HOME=/tmp
ENV PATH="/usr/local/bin:/usr/bin:${PATH}"
ENV PYSPARK_PYTHON=python3
ENV PYSPARK_DRIVER_PYTHON=python3

# Copy code
COPY apps/ /opt/spark/work-dir/apps/

RUN touch /opt/spark/work-dir/apps/__init__.py \
 && touch /opt/spark/work-dir/apps/stream/__init__.py \
 && touch /opt/spark/work-dir/apps/ingestion/__init__.py

ENV PYTHONPATH="/opt/spark/work-dir"

USER spark