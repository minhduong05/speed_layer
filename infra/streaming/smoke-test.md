# Smoke test - Kafka -> Spark -> Elasticsearch

## 1. Kiểm tra namespace và pods

```powershell
kubectl get pods -n kafka
kubectl get pods -n spark
kubectl get pods -n streaming
```

Kỳ vọng:
- Kafka pod Running
- Spark driver pod Running
- Elasticsearch pod Running

## 2. Kiểm tra Elasticsearch local access

```powershell
kubectl port-forward svc/elasticsearch -n streaming 9200:9200
curl.exe http://localhost:9200
```

Kỳ vọng:
- Elasticsearch trả về JSON cluster info

## 3. Kiểm tra Spark log

```powershell
kubectl logs -f <driver-pod-name> -n spark --container spark-kubernetes-driver
```

Kỳ vọng:
- Có log `batch_id=...`

## 4. Gửi dữ liệu test vào Kafka

```powershell
kubectl run kafka-producer -ti --image=quay.io/strimzi/kafka:0.51.0-kafka-4.2.0 --rm=true --restart=Never -n kafka -- bin/kafka-console-producer.sh --bootstrap-server my-cluster-kafka-bootstrap:9092 --topic my-topic
```

Gửi:

```text
job_101|Data Engineer|Ha Noi
job_102|Backend Developer|HCM
job_103|Data Analyst|Da Nang
```

## 5. Xác nhận Spark đã đọc dữ liệu

Trong log driver, kỳ vọng:

```text
batch_id=1, rows=3
```

## 6. Xác nhận Elasticsearch đã lưu document

```powershell
curl.exe http://localhost:9200/jobs_streaming/_search?pretty
```

Kỳ vọng:
- Có document với các field:
  - `job_id`
  - `job_title`
  - `city`
  - `raw_value`

## 7. Kết luận pass

Smoke test pass nếu:
- Spark driver Running
- Executor được tạo thành công
- Log có `rows > 0`
- Elasticsearch trả về document đã index
