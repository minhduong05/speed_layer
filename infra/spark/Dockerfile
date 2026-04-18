FROM apache/spark:4.0.2-python3

USER root
RUN pybin="$(command -v python3)" && \
    echo "python3 at: $pybin" && \
    ln -sf "$pybin" /usr/bin/python && \
    ln -sf "$pybin" /usr/local/bin/python && \
    python --version && \
    python3 --version

ENV HOME=/tmp
ENV PATH="/usr/local/bin:/usr/bin:${PATH}"
ENV PYSPARK_PYTHON=python
ENV PYSPARK_DRIVER_PYTHON=python

COPY apps/spark/kafka_to_es.py /opt/spark/work-dir/kafka_to_es.py

USER spark