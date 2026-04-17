# Smoke test checklist - Elastic stack (TV5)

## Kubernetes / ECK
- [ ] `kubectl get nodes` thấy node `Ready`
- [ ] `kubectl get pods -n elastic-system` thấy `elastic-operator-0` là `Running`
- [ ] `kubectl get storageclass` thấy có `standard (default)` hoặc equivalent

## Elasticsearch / Kibana
- [ ] `kubectl get pods -n elastic-stack` thấy pod Elasticsearch `1/1 Running`
- [ ] `kubectl get pods -n elastic-stack` thấy pod Kibana `1/1 Running`
- [ ] `kubectl get pvc -n elastic-stack` thấy PVC `Bound`

## Truy cập local
- [ ] Port-forward Elasticsearch chạy được:
  - `kubectl port-forward -n elastic-stack service/topcv-es-http 9200`
- [ ] Port-forward Kibana chạy được:
  - `kubectl port-forward -n elastic-stack service/topcv-kb-http 5601`
- [ ] Mở được `https://localhost:9200`
- [ ] Mở được `https://localhost:5601`

## Authentication
- [ ] Lấy được password:
  - `kubectl get secret topcv-es-elastic-user -n elastic-stack -o go-template='{{.data.elastic | base64decode}}'`

## Index / Data
- [ ] Tạo được index `jobs_historical`
- [ ] Insert được ít nhất 1 document
- [ ] Search trong Elasticsearch ra document đó
- [ ] Tạo được data view `jobs_historical`
- [ ] Discover trong Kibana thấy document
