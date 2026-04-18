# Streaming pipeline on Kubernetes

Tài liệu này mô tả cách chạy pipeline:

Kafka -> Spark Structured Streaming -> Elasticsearch

## 1. Điều kiện cần

- Minikube đang chạy
- Namespace `kafka`, `spark`, `streaming` đã được tạo
- Kafka cluster đã chạy trên K8s
- Spark service account đã được cấp quyền trong namespace `spark`
- Elasticsearch đã chạy trong namespace `streaming`

## 2. Kiểm tra cluster

```powershell
minikube status
kubectl get nodes
kubectl get pods -n kafka
kubectl get pods -n spark
kubectl get pods -n streaming
```

## 3. Elasticsearch sink

Elasticsearch được expose nội bộ bằng service:

- `elasticsearch.streaming.svc:9200`

Kiểm tra pod:

```powershell
kubectl get pods -n streaming
```

Port-forward để kiểm tra từ máy local:

```powershell
kubectl port-forward svc/elasticsearch -n streaming 9200:9200
```

Kiểm tra:

```powershell
curl.exe http://localhost:9200
```

## 4. Build image Spark app

Từ root repo:

```powershell
docker build --no-cache -t spark-kafka-es:demo -f infra/spark/Dockerfile .
docker run --rm spark-kafka-es:demo sh -lc "which python && which python3 && python --version && python3 --version"
minikube image load spark-kafka-es:demo
```

## 5. Submit Spark Streaming job

Chạy trong Anaconda Prompt hoặc terminal có `spark-submit`:

```cmd
set PYSPARK_PYTHON=python3
set PYSPARK_DRIVER_PYTHON=python3
set SPARK_SUBMIT_OPTS=-Djava.security.manager=allow
```

Lấy API server:

```powershell
kubectl cluster-info
```

Submit job:

```cmd
spark-submit ^
  --master k8s://https://127.0.0.1:60565 ^
  --deploy-mode cluster ^
  --name kafka-to-es ^
  --packages org.apache.spark:spark-sql-kafka-0-10_2.13:4.1.1 ^
  --conf spark.executor.instances=1 ^
  --conf spark.kubernetes.namespace=spark ^
  --conf spark.kubernetes.authenticate.driver.serviceAccountName=spark ^
  --conf spark.kubernetes.container.image=spark-kafka-es:demo ^
  --conf spark.kubernetes.container.image.pullPolicy=IfNotPresent ^
  --conf spark.driver.extraJavaOptions="-Duser.home=/tmp -Divy.home=/tmp/.ivy2.5.2 -Divy.cache.dir=/tmp/.ivy2.5.2/cache" ^
  --conf spark.kubernetes.driverEnv.HOME=/tmp ^
  --conf spark.kubernetes.driverEnv.PYSPARK_PYTHON=python3 ^
  --conf spark.kubernetes.driverEnv.PYSPARK_DRIVER_PYTHON=python3 ^
  --conf spark.executorEnv.PYSPARK_PYTHON=python3 ^
  --conf spark.kubernetes.driverEnv.PATH=/usr/local/bin:/usr/bin:/bin ^
  --conf spark.executorEnv.PATH=/usr/local/bin:/usr/bin:/bin ^
  --conf spark.kubernetes.driverEnv.KAFKA_BOOTSTRAP=my-cluster-kafka-bootstrap.kafka.svc:9092 ^
  --conf spark.kubernetes.driverEnv.KAFKA_TOPIC=my-topic ^
  --conf spark.kubernetes.driverEnv.ES_URL=http://elasticsearch.streaming.svc:9200 ^
  --conf spark.kubernetes.driverEnv.ES_INDEX=jobs_streaming ^
  local:///opt/spark/work-dir/kafka_to_es.py
```

## 6. Theo dõi Spark pods

```powershell
kubectl get pods -n spark -w
```

Kết quả mong đợi:
- 1 driver pod Running
- 1 executor pod được tạo
- driver log có `batch_id=...`

## 7. Gửi dữ liệu vào Kafka

Mở producer:

```powershell
kubectl delete pod kafka-producer -n kafka --ignore-not-found
kubectl run kafka-producer -ti --image=quay.io/strimzi/kafka:0.51.0-kafka-4.2.0 --rm=true --restart=Never -n kafka -- bin/kafka-console-producer.sh --bootstrap-server my-cluster-kafka-bootstrap:9092 --topic my-topic
```

Gửi dữ liệu test:

```text
job_101|Data Engineer|Ha Noi
job_102|Backend Developer|HCM
job_103|Data Analyst|Da Nang
```

## 8. Kiểm tra log Spark

```powershell
kubectl logs -f <driver-pod-name> -n spark --container spark-kubernetes-driver
```

Kết quả mong đợi:

```text
batch_id=1, rows=3
{"errors":false, ... "result":"created" ...}
```

## 9. Kiểm tra dữ liệu trong Elasticsearch

```powershell
curl.exe http://localhost:9200/jobs_streaming/_search?pretty
```

Hoặc đếm số document:

```powershell
curl.exe http://localhost:9200/jobs_streaming/_count
```

## 10. Kết quả đạt được

Pipeline hoạt động đúng khi:

- Kafka nhận message
- Spark Structured Streaming consume được topic
- Spark transform dữ liệu thành các field:
  - `job_id`
  - `job_title`
  - `city`
  - `raw_value`
- Elasticsearch index document thành công

## 11. Ghi chú

- Spark app đang dùng `startingOffsets=latest`, nên chỉ đọc các message gửi sau khi job đã chạy ổn định.
- Nếu gõ thừa ký tự `>` trong console producer thì dữ liệu sẽ bị lưu nguyên ký tự đó vào field `raw_value`.
- Nếu API server của Minikube đổi port sau khi restart cluster, cần cập nhật lại giá trị `--master k8s://https://127.0.0.1:<port>`.
