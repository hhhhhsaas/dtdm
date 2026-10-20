# ============================================================================
#  MAKEFILE — lệnh tắt cho toàn bộ vòng đời vận hành
#  Dùng: make help  để xem tất cả lệnh
# ============================================================================
SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE      ?= docker compose
# Môi trường production: overlay docker-compose.prod.yml (restart: always + resource guarantee)
COMPOSE_PROD := docker compose -f docker-compose.yml -f docker-compose.prod.yml
# Môi trường laptop demo (RAM 8 GB): overlay docker-compose.laptop.yml (profile full-monitor + hạ trần RAM)
COMPOSE_LAPTOP := docker compose -f docker-compose.yml -f docker-compose.laptop.yml
PROJECT      := qlpt
ENV_FILE     := .env
BACKUP_DIR   := /backup/qlpt
STAMP        := $(shell date +%Y%m%d_%H%M%S)
API          := http://localhost

# Các service nghiệp vụ
SERVICES     := auth room tenant contract billing notification maintenance report

# --------------------------- 1. KHỞI ĐỘNG -------------------------------
.PHONY: help
help: ## ⭐ Xem danh sách lệnh
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	 | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: check
check: ## Kiểm tra môi trường trước khi triển khai
	@echo "==> Kiểm tra yêu cầu..."
	@command -v docker >/dev/null || { echo "❌ Chưa cài Docker. Chạy: bash scripts/01-bootstrap-ubuntu.sh"; exit 1; }
	@docker compose version >/dev/null 2>&1 || { echo "❌ Chưa có Docker Compose v2. Chạy: sudo apt install docker-compose-v2"; exit 1; }
	@test -f $(ENV_FILE) || { echo "❌ Thiếu .env. Chạy: make env"; exit 1; }
	@test -f secrets/db_password.txt || { echo "❌ Thiếu secrets/. Chạy: make secrets"; exit 1; }
	@test -f infra/nginx/certs/fullchain.pem || { echo "❌ Thiếu chứng chỉ TLS cho nginx. Chạy: make certs"; exit 1; }
	@echo "✅ Môi trường sẵn sàng"

.PHONY: env
env: ## Tạo .env từ mẫu
	@test -f $(ENV_FILE) || { cp .env.example $(ENV_FILE); echo "✅ Đã tạo .env — HÃY SỬA GIÁ TRỊ"; }

.PHONY: secrets
secrets: ## Sinh file bí mật ngẫu nhiên, đặt quyền 600
	@mkdir -p secrets
	@bash scripts/02-generate-secrets.sh

.PHONY: certs
certs: ## 🔐 Tạo chứng chỉ TLS tự ký cho nginx (BẮT BUỘC trước lần up đầu)
	@bash scripts/06-generate-cert.sh

.PHONY: up
up: check ## 🚀 Khởi động TOÀN BỘ hệ thống
	@echo "==> Đang build & khởi động..."
	@$(COMPOSE) up -d --build --remove-orphans
	@echo "==> Đợi các service healthy (tối đa 180s)..."
	@$(MAKE) wait-healthy
	@$(MAKE) reload-nginx
	@$(MAKE) status

.PHONY: up-infra
up-infra: ## Chỉ khởi động lớp hạ tầng (DB, cache, broker, storage)
	@$(COMPOSE) up -d postgres redis rabbitmq minio

.PHONY: deploy
deploy: ## 🚀 Triển khai TRỌN GÓI 1 lệnh (bootstrap→.env→secrets→certs→up→seed→health)
	@bash scripts/00-deploy.sh

.PHONY: down
down: ## ⬇️ Dừng toàn bộ (GIỮ NGUYÊN dữ liệu)
	@$(COMPOSE) down --remove-orphans

.PHONY: destroy
destroy: ## 💥 XÓA TOÀN BỘ kể cả dữ liệu — cẩn thận!
	@read -p "Xóa cả volumes (dữ liệu sẽ MẤT HOÀN TOÀN)? (yes/no): " a; \
	 [ "$$a" = "yes" ] && $(COMPOSE) down -v --remove-orphans && echo "💥 Đã xóa" || echo "Đã hủy"

.PHONY: restart
restart: ## Khởi động lại 1 service (VD: make restart S=billing)
	@test -n "$(S)" || { echo "Dùng: make restart S=<service>"; exit 1; }
	@$(COMPOSE) restart $(S)

.PHONY: wait-healthy
wait-healthy: ## Đợi tất cả service healthy
	@for i in $$(seq 1 60); do \
	   n=$$($(COMPOSE) ps --format '{{.Health}}' 2>/dev/null | grep -c healthy || true); \
	   t=$$($(COMPOSE) ps -q 2>/dev/null | wc -l); \
	   echo "  [$$i/60] healthy $$n/$$t"; \
	   [ "$$n" = "$$t" ] && [ "$$t" != "0" ] && echo "✅ Tất cả healthy" && exit 0; \
	   sleep 3; \
	 done; echo "⚠️  Hết thời gian chờ — xem 'make status'"

.PHONY: status
status: ## 📊 Trạng thái tất cả container
	@$(COMPOSE) ps --format 'table {{.Name}}\t{{.Status}}\t{{.Ports}}'

# -------------------------- 1b. PRODUCTION --------------------------------
# Dùng kèm docker-compose.prod.yml: restart: always + reservations RAM/CPU.
# Các lệnh còn lại (seed, health, test-int, backup…) dùng chung container name
# nên KHÔNG cần biến thể riêng — chạy đúng như bình thường.
.PHONY: prod-up
prod-up: check ## 🏭 Khởi động môi trường PRODUCTION (overlay docker-compose.prod.yml)
	@$(COMPOSE_PROD) up -d --build --remove-orphans
	@echo "==> Đợi các service healthy (tối đa 180s)..."
	@$(MAKE) wait-healthy
	@$(MAKE) status

.PHONY: prod-down
prod-down: ## 🏭 Dừng production (GIỮ NGUYÊN dữ liệu)
	@$(COMPOSE_PROD) down --remove-orphans

.PHONY: prod-restart
prod-restart: ## 🏭 Khởi động lại 1 service (make prod-restart S=billing)
	@test -n "$(S)" || { echo "Dùng: make prod-restart S=<service>"; exit 1; }
	@$(COMPOSE_PROD) restart $(S)

.PHONY: prod-logs
prod-logs: ## 🏭 Log production 1 service (make prod-logs S=billing)
	@$(COMPOSE_PROD) logs -f --tail 100 $(S)

# -------------------------- 1c. LAPTOP DEMO --------------------------------
# Dành cho máy RAM hạn chế (8 GB): tạm bỏ loki/promtail/cAdvisor/node-exporter
# (profile full-monitor) + hạ trần RAM. Các lệnh seed/health/test dùng chung
# container name nên vẫn chạy bình thường.
.PHONY: laptop-up
laptop-up: check ## 💻 Khởi động chế độ LAPTOP (gọn nhẹ, đủ 8 service + Prometheus/Grafana)
	@$(COMPOSE_LAPTOP) up -d --build --remove-orphans
	@echo "==> Đợi các service healthy (tối đa 180s)..."
	@$(MAKE) wait-healthy
	@$(MAKE) reload-nginx
	@$(MAKE) status

.PHONY: reload-nginx
reload-nginx: ## 🔁 Nạp lại cấu hình nginx (cập nhật DNS upstream sau khi recreate backend)
	@docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^qlpt-nginx$$' \
	   && docker exec qlpt-nginx nginx -s reload >/dev/null 2>&1 \
	   && echo "  ✓ nginx đã reload" \
	   || echo "  ⚠ nginx chưa chạy — bỏ qua reload"

.PHONY: laptop-down
laptop-down: ## 💻 Dừng laptop (GIỮ NGUYÊN dữ liệu)
	@$(COMPOSE_LAPTOP) down --remove-orphans

.PHONY: laptop-restart
laptop-restart: ## 💻 Khởi động lại 1 service (make laptop-restart S=billing)
	@test -n "$(S)" || { echo "Dùng: make laptop-restart S=<service>"; exit 1; }
	@$(COMPOSE_LAPTOP) restart $(S)

.PHONY: laptop-logs
laptop-logs: ## 💻 Log 1 service (make laptop-logs S=billing)
	@$(COMPOSE_LAPTOP) logs -f --tail 100 $(S)

.PHONY: laptop-monitor
laptop-monitor: ## 📡 Bật thêm giám sát log+hệ thống (loki/promtail/cAdvisor/node-exporter)
	@$(COMPOSE_LAPTOP) --profile full-monitor up -d --remove-orphans

# ------------------------------ 2. NHẬT KÝ -----------------------------
.PHONY: logs
logs: ## 📋 Theo dõi log toàn hệ thống
	@$(COMPOSE) logs -f --tail 100

.PHONY: logs-s
logs-s: ## 📋 Log 1 service (make logs-s S=billing)
	@$(COMPOSE) logs -f --tail 200 $(S)

.PHONY: shell
shell: ## Vào shell của 1 service
	@$(COMPOSE) exec $(or $(S),billing) /bin/bash

.PHONY: stats
stats: ## 📈 Thống kê tài nguyên container theo thời gian thực
	@docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}'

# --------------------------- 3. DỮ LIỆU MẪU ---------------------------
.PHONY: migrate
migrate: ## 🔀 Chạy migration Alembic cho tất cả DB
	@for s in $(SERVICES); do \
	   echo "==> migrate $$s"; \
	   $(COMPOSE) exec -T $$s alembic upgrade head || true; \
	 done

.PHONY: seed
seed: ## 🌱 Nạp dữ liệu mẫu (tài khoản admin, 1 cơ sở 20 phòng, biểu giá)
	@$(COMPOSE) exec -T room python -m scripts.seed_room
	@$(COMPOSE) exec -T tenant python -m scripts.seed_tenant
	@$(COMPOSE) exec -T contract python -m scripts.seed_contract
	@$(COMPOSE) exec -T billing python -m scripts.seed_billing
	@$(COMPOSE) exec -T auth python -m scripts.seed_auth
	@$(MAKE) reconcile
	@echo "✅ Xem tài khoản: admin / $(cat secrets/admin_password.txt 2>/dev/null || echo 'xem .env')"

.PHONY: reconcile
reconcile: ## ⚡ Chạy đối chiếu read model (report) NGAY — bắt buộc sau khi seed
	@echo "==> Reconcile (report-service)..."
	@$(COMPOSE) exec -T report python -c "\
import urllib.request; \
from common.security import create_internal_token; \
tok = create_internal_token('make-seed'); \
req = urllib.request.Request('http://localhost:8008/internal/v1/reports/reconcile', method='POST', headers={'Authorization': 'Bearer ' + tok}); \
r = urllib.request.urlopen(req, timeout=120); \
print('   ✅', r.status, r.read().decode()[:200])"

.PHONY: reset-db
reset-db: ## Xóa & tạo lại toàn bộ schema (giữ dữ liệu mẫu)
	@$(COMPOSE) exec -T postgres psql -U qlpt -c "DROP DATABASE IF EXISTS db_billing;" -d postgres
	@$(COMPOSE) exec -T postgres psql -U qlpt -c "CREATE DATABASE db_billing OWNER qlpt;" -d postgres
	@$(MAKE) migrate seed

# ------------------------------ 4. KIỂM THỬ -----------------------------
.PHONY: test
test: ## 🧪 Chạy unit test
	@$(COMPOSE) exec -T billing pytest -q --cov=. --cov-report=term-missing

.PHONY: test-int
test-int: ## 🧪 Kiểm thử tích hợp toàn hệ thống
	@PY=$$(command -v python3 || command -v python); $$PY scripts/smoke_test.py

.PHONY: loadtest
loadtest: ## ⚡ Kiểm thử tải bằng k6
	@docker run --rm --network qlpt_app -v $(PWD)/k6:/scripts \
		grafana/k6 run --vus 50 --duration 2m /scripts/smoke.js

.PHONY: security
security: ## 🛡️ Quét bảo mật image bằng Trivy
	@docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
		aquasec/trivy:latest image --severity HIGH,CRITICAL \
		--exit-code 0 qlpt-$(S 2>/dev/null || echo billing)

# --------------------------- 5. SAO LƯU ---------------------------------
.PHONY: backup
backup: ## 💾 Sao lưu toàn bộ (PostgreSQL + MinIO + cấu hình)
	@bash scripts/03-backup.sh

.PHONY: restore
restore: ## ♻️ Khôi phục từ bản sao lưu (make restore F=<file>)
	@test -n "$(F)" || { echo "Dùng: make restore F=/backup/qlpt/daily/qlpt_full_....tar.gz"; exit 1; }
	@bash scripts/04-restore.sh "$(F)"

.PHONY: verify-backup
verify-backup: ## ✅ Kiểm chứng bản sao lưu gần nhất (BẮT BUỘC làm hằng tuần)
	@bash scripts/05-verify-backup.sh

# --------------------------- 6. MỞ RỘNG ---------------------------------
.PHONY: scale
scale: ## 📈 Nhân bản 1 service (make scale S=billing N=3)
	@test -n "$(S)" -a -n "$(N)" || { echo "Dùng: make scale S=<service> N=<số bản>"; exit 1; }
	@$(COMPOSE) up -d --scale $(S)=$(N) $(S)
	@echo "✅ $(S) đang chạy $(N) bản — nginx tự cân bằng tải"

.PHONY: logs-size
logs-size: ## 📏 Xem dung lượng log từng container
	@docker ps -aq --filter name=qlpt | xargs -r docker inspect --format \
		'{{.Name}} {{.LogPath}}' | while read n p; do \
		printf "%-25s %s\n" "$$n" "$$(sudo du -h $$p 2>/dev/null | cut -f1)"; done

.PHONY: disk
disk: ## 💾 Xem dung lượng đĩa
	@df -h / /var/lib/docker 2>/dev/null | grep -v tmpfs

# --------------------------- 7. GIAO DIỆN -------------------------------
.PHONY: urls
urls: ## 🔗 In tất cả đường dẫn truy cập
	@echo ""
	@echo "  🌐 Ứng dụng web     :  https://$$(grep '^DOMAIN=' $(ENV_FILE) | cut -d= -f2)"
	@echo "  📚 Tài liệu API     :  http://localhost:8001/docs  (mỗi service một cổng)"
	@echo "  📈 Prometheus       :  ssh -L 9090:localhost:9090 <user>@<server>  → http://localhost:9090"
	@echo "  📊 Grafana          :  http://<IP-server>:3000   (admin / trong secrets/)"
	@echo "  🐰 RabbitMQ UI      :  ssh -L 15672:localhost:15672 <user>@<server>  → http://localhost:15672"
	@echo "  📦 MinIO Console    :  ssh -L 9001:localhost:9001 <user>@<server>  → http://localhost:9001"
	@echo "  🔧 Portainer        :  http://<IP-server>:9000"
	@echo ""

# --------------------------- 8. CẬP NHẬT -------------------------------
.PHONY: build
build: ## 🔨 Build lại image không chạy
	@$(COMPOSE) build --pull

.PHONY: update
update: ## ⬆️ Kéo code mới, build, triển khai lại (rolling update)
	@$(COMPOSE) build --pull
	@$(COMPOSE) up -d --remove-orphans
	@$(MAKE) wait-healthy

.PHONY: clean
clean: ## 🧹 Dọn image & container đã dừng (giữ dữ liệu)
	@$(COMPOSE) --profile tools run --rm cleanup

# --------------------------- 9. BẢO TRÌ --------------------------------
.PHONY: health
health: ## ❤️ Kiểm tra sức khoẻ tất cả endpoint
	@for p in 8001:auth 8002:room 8003:tenant 8004:contract 8005:billing 8006:notification 8007:maintenance 8008:report; do \
	   port=$${p%%:*}; name=$${p##*:}; \
	   code=$$(curl -s -o /dev/null -w '%{http_code}' http://localhost:$$port/health); \
	   [ "$$code" = "200" ] && printf "  ✅ %-14s :%s\n" $$name $$port || printf "  ❌ %-14s :%s (%s)\n" $$name $$port $$code; \
	 done
	@code=$$($(COMPOSE) exec -T scheduler python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8009/health', timeout=5).status)" 2>/dev/null); \
	 [ "$$code" = "200" ] && printf "  ✅ %-14s :%s\n" scheduler 8009 || printf "  ❌ %-14s :%s\n" scheduler 8009
