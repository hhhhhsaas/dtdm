# ============================================================================
#  KHỞI ĐỘNG HỆ THỐNG QLPT TỪ WINDOWS — chạy trong PowerShell
#  Dùng:  powershell -ExecutionPolicy Bypass -File .\scripts\start-windows.ps1
#  Hoặc: nhấp đúp file START-QLPT.bat ở thư mục gốc dự án.
#
#  Việc script làm (1 chạm):
#    1) Bật WSL2 (Ubuntu) nếu chưa chạy,
#    2) Khởi động lại stack nếu cần (chế độ laptop, KHÔNG build lại),
#    3) Đợi gateway https://localhost/ trả lời 200,
#    4) Mở trình duyệt + in tài khoản demo.
#
#  ⭐ LƯU Ý: file này phải lưu UTF-8 CÓ BOM (PowerShell 5.1 đọc theo mã vùng
#     nếu thiếu BOM -> tiếng Việt hỏng mã hoá, phá vỡ parser).
# ============================================================================
[CmdletBinding()]
param(
    # Bỏ qua bước mở trình duyệt (dùng khi muốn chạy nền / CI).
    [switch]$NoBrowser,
    # Chỉ đợi, KHÔNG gọi compose up (khi đã chắc chắn stack đang chạy).
    [switch]$NoUp
)

$ErrorActionPreference = 'Continue'

function Info($m) { Write-Host $m -ForegroundColor Cyan }
function Ok($m)   { Write-Host $m -ForegroundColor Green }
function Warn($m) { Write-Host $m -ForegroundColor Yellow }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   KHOI DONG HE THONG QUAN LY PHONG TRO (QLPT - WSL2)"       -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# --- 1. Xác định bản phân phối WSL (mặc định Ubuntu) -------------------------
$distro = 'Ubuntu'
try {
    $found = & wsl -l -q 2>$null | ForEach-Object { "$_".Trim() } |
             Where-Object { $_ -match '^(Ubuntu|Ubuntu-24\.04)$' } | Select-Object -First 1
    if ($found) { $distro = $found }
} catch { }

# --- 2. Bật WSL -------------------------------------------------------------
Info "[1/4] Bat WSL ($distro) ..."
& wsl -d $distro -u root -- true 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Warn "[1/4] Khong bat duoc WSL. Kiem tra da cai Ubuntu trong 'wsl -l -v' chua."
    Warn "      Thu mo Ubuntu tu Start Menu mot lan, sau do chay lai script nay."
    exit 1
}
Ok "[1/4] WSL da san sang."

# --- 3. Khởi động stack (nếu cần) ------------------------------------------
if ($NoUp) {
    Info "[2/4] Bo qua 'compose up' (-NoUp)."
} else {
    Info "[2/4] Khoi dong 16 container (che do laptop, khong build lai) ..."
    & wsl -d $distro -u root -- bash -lc "cd /opt/qlpt && systemctl start docker >/dev/null 2>&1; docker compose -f docker-compose.yml -f docker-compose.laptop.yml up -d --remove-orphans" 2>&1 |
        Out-Null
    Ok "[2/4] Da gui lenh khoi dong."
}

# --- 4. Đợi gateway sẵn sàng ------------------------------------------------
Info "[3/4] Doi gateway https://localhost/ san sang (toi da ~3 phut) ..."
$ready = $false
for ($i = 1; $i -le 60; $i++) {
    $code = (& curl.exe -k -s -o NUL -w "%{http_code}" -m 5 https://localhost/ 2>$null)
    if ("$code".Trim() -eq '200') { $ready = $true; break }
    Write-Host -NoNewline "."
    Start-Sleep -Seconds 3
}
Write-Host ""
if ($ready) {
    Ok "[3/4] Gateway tra loi HTTP 200."
} else {
    Warn "[3/4] Gateway chua tra loi 200. Van mo trinh duyet de ban kiem tra;"
    Warn "      co the can them 1-2 phut, hoac xem log:  make -C /opt/qlpt status"
}

# --- 5. Tài khoản demo + mở trình duyệt ------------------------------------
$adminPwd = ''
try {
    $adminPwd = (& wsl -d $distro -u root -- cat /opt/qlpt/secrets/admin_password.txt 2>$null |
            Select-Object -First 1)
    if ($adminPwd) { $adminPwd = "$adminPwd".Trim() }
} catch { }

Write-Host ""
Write-Host "  Dia chi truy cap:" -ForegroundColor Cyan
Write-Host "    Ung dung web   : https://localhost/"
Write-Host "    Tai lieu API   : http://localhost:8001/docs  (tat o che do prod)"
Write-Host "    Grafana        : http://localhost:3000"
Write-Host ""
Write-Host "  Tai khoan demo:" -ForegroundColor Cyan
if ($adminPwd) {
    Write-Host "    admin  / $adminPwd   (quan tri)"
    Write-Host "    quanly / $adminPwd   (quan ly 1 co so)"
} else {
    Write-Host "    admin  / <xem /opt/qlpt/secrets/admin_password.txt>"
    Write-Host "    quanly / <cung mat khau admin>"
}
Write-Host "    khach01..khach12 / Tenant@12345   (khach thue)"
Write-Host ""
Write-Host "  Muon NGUOI KHAC trong WIFI truy cap: chay scripts\lan-expose-windows.ps1" -ForegroundColor Yellow
Write-Host ""

if (-not $NoBrowser) {
    Info "[4/4] Mo trinh duyet ..."
    Start-Process "https://localhost/" | Out-Null
    Ok "Xong. Neu trang bao loi chung chi tu ky, chon 'Advanced' → 'Proceed'."
    Write-Host "     (Muon HET han canh bao: chay scripts\trust-cert-windows.ps1)"
} else {
    Info "[4/4] Bo qua mo trinh duyet (-NoBrowser)."
}
