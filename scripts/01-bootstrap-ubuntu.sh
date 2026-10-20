#!/usr/bin/env bash
# ============================================================================
#  BƯỚC 1 — CHUẨN BỊ UBUNTU SERVER
#  Chạy 1 lần duy nhất trên máy chủ mới:
#      sudo bash scripts/01-bootstrap-ubuntu.sh
#
#  ⚠️  CẦN ROOT. Script này cài đặt, đổi firewall, tạo user — hãy đọc trước khi chạy.
# ============================================================================
set -Eeuo pipefail

APP_USER="${APP_USER:-qlpt}"
APP_DIR="${APP_DIR:-/opt/qlpt}"
SWAP_SIZE="${SWAP_SIZE:-4G}"
POSTGRES_VERSION="${POSTGRES_VERSION:-16}"

info()  { printf '\033[1;34m[INFO]\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m[ OK ]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[WARN]\033[0m %s\n' "$*"; }
fail()  { printf '\033[1;31m[FAIL]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fail "Cần chạy với quyền root: sudo bash $0"

trap 'fail "Lỗi tại dòng $LINENO"' ERR

# ============================================================================
info "1/10  Cập nhật danh mục gói và nâng cấp hệ thống"
# ============================================================================
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get -y -qq full-upgrade
apt-get -y -qq autoremove --purge
apt-get clean

# ============================================================================
info "2/10  Cài đặt gói cơ bản"
# ============================================================================
apt-get install -y -qq \
    ca-certificates curl gnupg lsb-release \
    build-essential git vim htop tree unzip \
    jq chrony rsync logrotate iproute2 \
    dnsutils net-tools \
    unattended-upgrades \
    software-properties-common

# Bật tự cập nhật bảo mật tự động (quan trọng cho máy chủ public)
systemctl enable --now unattended-upgrades
ok "unattended-upgrades đã bật"

# ============================================================================
info "3/10  Thiết lập múi giờ Asia/Ho_Chi_Minh"
# ============================================================================
timedatectl set-timezone Asia/Ho_Chi_Minh
timedatectl set-ntp true
ok "Giờ hệ thống: $(date '+%Y-%m-%d %H:%M:%S %Z')"

# ============================================================================
info "4/10  Tạo swap (bắt buộc — tránh OOM kill container)"
# ============================================================================
if ! swapon --show | grep -q .; then
    fallocate -l "$SWAP_SIZE" /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=4096
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    ok "Đã tạo swap $SWAP_SIZE"
else
    ok "Swap đã tồn tại"
fi

# swap: dùng cho các tiến trình ẩn, KHÔNG dùng cho PostgreSQL
cat > /etc/sysctl.d/99-qlpt.conf <<'EOF'
# --- Bộ nhớ ---
vm.swappiness = 10                    # Ưu tiên RAM thật, chỉ dùng swap khi thật sự thiếu
vm.vfs_cache_pressure = 50
vm.overcommit_memory = 1

# --- Bảo mật mạng ---
net.ipv4.tcp_syncookies = 1
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.ip_forward = 1               # cần cho Docker bridge network
net.bridge.bridge-nf-call-iptables = 1

# --- Kết nối ---
net.core.somaxconn = 4096             # hàng đợi listen lớn hơn
net.ipv4.tcp_max_syn_backlog = 4096
net.ipv4.ip_local_port_range = 10000 65535   # tránh xung đột với port của container
fs.file-max = 100000
EOF
sysctl --system >/dev/null
ok "sysctl đã áp dụng"

# ============================================================================
info "5/10  Giới hạn số tiến trình (bắt buộc khi chạy nhiều container)"
# ============================================================================
cat > /etc/security/limits.d/99-qlpt.conf <<EOF
*                soft    nofile          65535
*                hard    nofile          65535
root             soft    nofile          65535
root             hard    nofile          65535
${APP_USER}      soft    nofile          65535
${APP_USER}      hard    nofile          65535
*                soft    nproc           65535
*                hard    nproc           65535
EOF
systemctl set-property --runtime qlpt 2>/dev/null || true
ok "Đã đặt giới hạn nofile"

# ============================================================================
info "6/10  Cài Docker Engine + Compose v2 từ kho chính thức Docker"
# ============================================================================
if ! command -v docker >/dev/null; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
        > /etc/apt/sources.list.d/docker.list

    apt-get update -qq
    apt-get install -y -qq \
        docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin

    systemctl enable --now docker
    ok "Docker đã cài: $(docker --version)"
else
    ok "Docker đã có: $(docker --version)"
fi

# ============================================================================
info "7/10  Cấu hình daemon Docker (log, storage driver, live-restore)"
# ============================================================================
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "5" },
  "storage-driver": "overlay2",
  "storage-opts": { "overlay2.mount_program": "" },
  "live-restore": true,
  "default-address-pools": [
    { "base": "172.20.0.0/16", "size": 24 }
  ],
  "dns": ["1.1.1.1", "8.8.8.8"],
  "userland-proxy": false,
  "exec-opts": ["native.cgroupdriver=systemd"]
}
EOF

# ⭐ QUAN TRỌNG: nếu restart docker sẽ KHÔNG giết container đang chạy.
#    live-restore = true chỉ hoạt động với cgroup driver systemd.
if [[ "$(docker info --format '{{.CgroupDriver}}')" == "systemd" ]]; then
    systemctl restart docker
    ok "live-restore: bật"
else
    warn "Cgroup driver không phải systemd → live-restore không hoạt động"
    warn "Cài systemd-cgroup: sudo apt install systemd-cgroup && sửa GRUB_CMDLINE_LINUX_DEFAULT"
fi

# ============================================================================
info "8/10  Tạo user ${APP_USER} (không chạy hệ thống bằng root)"
# ============================================================================
if id -u "$APP_USER" >/dev/null 2>&1; then
    ok "User ${APP_USER} đã tồn tại"
else
    adduser --disabled-password --gecos "" "$APP_USER"
    adduser "$APP_USER" docker
    ok "Đã tạo user ${APP_USER} (thuộc nhóm docker)"
fi

# ============================================================================
info "9/10  Cấu hình firewall UFW"
# ============================================================================
if command -v ufw >/dev/null; then
    ufw --force reset >/dev/null
    ufw default deny incoming        # ⭐ mặc định CHẶN tất cả vào
    ufw default allow outgoing
    ufw allow 22/tcp    comment 'SSH'
    ufw allow 80/tcp    comment 'HTTP (web + ACME)'
    ufw allow 443/tcp   comment 'HTTPS'
    ufw allow 3000/tcp  comment 'Grafana'
    ufw allow 9000/tcp  comment 'Portainer'
    # KHÔNG mở: 5432 (PostgreSQL), 6379 (Redis), 5672/15672 (RabbitMQ),
    #            8001-8008 (service), 9090 (Prometheus), 9001 (MinIO console)
    ufw --force enable
    ok "UFW: chỉ mở 22, 80, 443, 3000, 9000"
    warn "Các cổng DB/queue chỉ truy cập được qua SSH tunnel"
else
    warn "ufu chưa có — hãy cài: apt install ufw"
fi

# ============================================================================
info "10/10  Logrotate + thư mục ứng dụng"
# ============================================================================
cat > /etc/logrotate.d/qlpt <<'EOF'
/var/log/qlpt/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
EOF

mkdir -p "$APP_DIR" /var/log/qlpt /backup/qlpt/{daily,weekly} /opt/qlpt/secrets
chown -R "$APP_USER:$APP_USER" "$APP_DIR" /var/log/qlpt /backup/qlpt
chmod 700 /opt/qlpt/secrets
chmod 750 /backup/qlpt

# ============================================================================
ok "════════════════════════════════════════════════════════"
ok " HOÀN TẤT CHUẨN BỊ UBUNTU SERVER"
ok "════════════════════════════════════════════════════════"
cat <<EOF

  Docker:    $(docker --version)
  Compose:   $(docker compose version --short 2>/dev/null || echo 'chưa cài')
  User:      $APP_USER
  Thư mục:   $APP_DIR

  BƯỚC TIẾP THEO:
    1. Copy mã nguồn:   rsync -avz --exclude secrets --exclude infra/nginx/certs ./ $APP_USER@<server>:$APP_DIR/
    2. Sửa cấu hình:    cp .env.example .env && nano .env   (đặt DOMAIN, PUBLIC_IP, REDIS_PASSWORD)
    3. Tạo bí mật:      make secrets
    4. Tạo cert TLS:    make certs     (BẮT BUỘC — nginx không chạy được nếu thiếu)
    5. Khởi động:       make prod-up   (hoặc make up cho môi trường dev)
    6. Nạp dữ liệu:     make seed
    7. Kiểm tra:        make health && make urls

  ⭐ NHỚ: KHÔNG bao giờ mở cổng PostgreSQL/Redis/RabbitMQ ra Internet.
     Nếu quên, hệ thống của bạn sẽ bị tấn công tự động trong vài giờ.

EOF
