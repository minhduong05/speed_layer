# Smoke test checklist - Kafka on Kubernetes (TV5)

## Kubernetes / Helm
- [ ] `kubectl get nodes` thấy node `Ready`
- [ ] `kubectl cluster-info` chạy được
- [ ] Namespace `kafka` đã được tạo

## Strimzi operator
- [ ] `helm install strimzi-cluster-operator ...` chạy thành công
- [ ] `kubectl get deployments -n kafka` thấy deployment `strimzi-cluster-operator`
- [ ] `kubectl get pods -n kafka` thấy pod operator `1/1 Running`

## Kafka cluster
- [ ] `kubectl apply -n kafka -f .../kafka-single-node.yaml` chạy thành công
- [ ] `kubectl get kafka -n kafka` thấy cluster `my-cluster`
- [ ] `kubectl get kafkanodepool -n kafka` chạy được
- [ ] `kubectl get svc -n kafka` thấy bootstrap service
- [ ] `kubectl get pods -n kafka` thấy:
  - [ ] `my-cluster-dual-role-0`
  - [ ] `my-cluster-entity-operator-...`
- [ ] Các pod trên ở trạng thái `Running`

## Producer / Consumer
- [ ] Chạy được Kafka consumer trong pod tạm
- [ ] Chạy được Kafka producer trong pod tạm
- [ ] Producer gửi được message vào topic `my-topic`
- [ ] Consumer nhận được đúng message từ producer

## Dấu hiệu thành công
- [ ] Kafka deploy trên Kubernetes thành công
- [ ] Bootstrap service hoạt động
- [ ] Có thể produce / consume message thành công
