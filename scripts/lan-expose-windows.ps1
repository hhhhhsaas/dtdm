# ============================================================================
#  MỞ QLPT CHO MẠNG NỘI BỘ (LAN) — chạy trên Windows, TỰ XIN QUYỀN ADMIN
#  Dùng:  powershell -ExecutionPolicy Bypass -File .\scripts\lan-expose-windows.ps1
#
#  Việc script làm (1 chạm):
#    1) Tự nâng quyền Admin (UAC) nếu phiên hiện tại chưa có.
#    2) Mở firewall Windows cho TCP 80/443 — NHƯNG CHỈ từ dải mạng nội bộ
#       (RemoteAddress=LocalSubnet) → vẫn an toàn kể cả khi ra WiFi quán.
#    3) Cài portproxy: gói tới 0.0.0.0:80/443 trên Windows → WSL2 IP hiện tại
#       (WSL2 chạy chế độ NAT nên Windows phải đóng vai "cầu nối").
#    4) Đảm bảo chứng chỉ TLS có SAN = IP LAN hiện tại (tạo lại + tin cậy nếu cần).
#    5) In ra địa chỉ để máy khác trong LAN truy cập.
#
#  ⭐ Chạy LẠI khi: vừa bật máy (WSL đổi IP), hoặc đổi mạng WiFi khác.
#  ⭐ Phải lưu UTF-8 CÓ BOM (PowerShell 5.1 đọc theo mã vùng nếu thiếu BOM).
# ============================================================================
[CmdletBinding()]
param([switch]$SkipUAC)

$adminId = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $adminId.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    if (-not $SkipUAC) {
        Write-Host "Dang xin quyen Admin (UAC)... NEU DUOC HOI thi chon 'Yes'." -ForegroundColor Yellow
        Start-Process powershell -Verb RunAs -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath, '-SkipUAC') | Out-Null
        exit 0
    }
    Write-Host "Khong co quyen Admin - khong the cau hinh firewall/portproxy." -ForegroundColor Red
    exit 1
}

$ErrorActionPreference = 'Continue'
function Info($m) { Write-Host $m -ForegroundColor Cyan }
function Ok($m)   { Write-Host $m -ForegroundColor Green }
function Warn($m) { Write-Host $m -ForegroundColor Yellow }

Write-Host ""
Write-Host "===== MO QLPT CHO MANG NOI BO (LAN) =====" -ForegroundColor Cyan

# --- 1. Lay IP WSL2 + IP LAN cua Windows ------------------------------------
$wslIp = ''
try {
    $raw = & wsl -e bash -lc "hostname -I" 2>$null
    $wslIp = ("$raw".Trim() -split '\s+' | Select-Object -First 1)
} catch { }
if ($wslIp -notmatch '^\d{1,3}(\.\d{1,3}){3}$') {
    Warn "[1/5] Khong lay duoc IP cua WSL. Hay chay 'start-windows.ps1' truoc roi thu lai."
    exit 1
}
Info "[1/5] IP WSL2 hien tai: $wslIp"

$lanIp = ''
try {
    $cand = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object {
        $_.IPAddress -notmatch '^127\.' -and
        $_.IPAddress -notmatch '^169\.254' -and
        $_.IPAddress -notmatch '^172\.(1[6-9]|2[0-9]|3[01])\.' -and
        $_.IPAddress -ne $wslIp
    } | Select-Object -ExpandProperty IPAddress
    $lanIp = @($cand | Select-Object -First 1)[0]
} catch { }
if ($lanIp) { Info "[1/5] IP LAN cua Windows: $lanIp" }
else        { Warn "[1/5] Khong tim thay IP LAN cua Windows (co the dang khong o WiFi/LAN?)." }

# --- 2. Firewall: TCP 80/443 CHI tu mang noi bo -----------------------------
foreach ($port in 80, 443) {
    $name = "QLPT-Inbound-TCP-$port"
    Remove-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Out-Null
    New-NetFirewallRule -DisplayName $name -Direction Inbound -Protocol TCP -LocalPort $port `
        -RemoteAddress LocalSubnet -Action Allow -Profile Any | Out-Null
    Ok "[2/5] Firewall: cho phep TCP $port tu LocalSubnet (rule: $name)"
}

# --- 3. Portproxy: 0.0.0.0:LISTEN -> WSL2 -----------------------------------
foreach ($port in 80, 443) {
    netsh interface portproxy delete v4tov4 listenport=$port listenaddress=0.0.0.0 2>$null | Out-Null
    netsh interface portproxy add v4tov4 listenport=$port listenaddress=0.0.0.0 `
        connectport=$port connectaddress=$wslIp | Out-Null
    Ok "[3/5] Portproxy 0.0.0.0:$port -> ${wslIp}:${port}"
}

# --- 4. Dam bao chung chi TLS co SAN = IP LAN hien tai ----------------------
if ($lanIp) {
    $certFile = '/opt/qlpt/infra/nginx/certs/fullchain.pem'
    $san = (& wsl -u root -e bash -lc "openssl x509 -in $certFile -noout -ext subjectAltName 2>/dev/null") -join ' '
    if ($san -match [regex]::Escape($lanIp)) {
        Ok "[4/5] Cert TLS da co SAN IP $lanIp — khong can tao lai."
    } else {
        Warn "[4/5] Cert chua co IP $lanIp -> tao lai + tin cay lai..."
        & wsl -u root -e bash -lc "cd /opt/qlpt && { grep -q '^LAN_IPS=' .env && sed -i 's|^LAN_IPS=.*|LAN_IPS=$lanIp|' .env || printf '\nLAN_IPS=$lanIp\n' >> .env; }; FORCE=1 LAN_IPS=$lanIp bash scripts/06-generate-cert.sh >/dev/null && docker exec qlpt-nginx nginx -s reload" | Out-Null
        $tmp = Join-Path $env:TEMP 'qlpt-lan.crt'
        (& wsl -u root -e bash -lc "cat $certFile") | Set-Content -Path $tmp -Encoding Ascii
        $store = New-Object System.Security.Cryptography.X509Certificates.X509Store('Root', 'CurrentUser')
        try {
            $store.Open('ReadWrite')
            foreach ($c in @($store.Certificates)) {
                if ($c.Subject -match 'CN=qlpt|CN=QLPT') { $store.Remove($c) }
            }
        } finally { $store.Close() }
        certutil -user -addstore -f Root $tmp | Out-Null
        Ok "[4/5] Da tao lai cert co IP $lanIp + import vao CurrentUser\Root."
    }
} else {
    Warn "[4/5] Bo qua buoc cert (khong co IP LAN)."
}

# --- 5. Tom tat + huong dan --------------------------------------------------
Write-Host ""
netsh interface portproxy show v4tov4
Write-Host ""
if ($lanIp) {
    Write-Host "  Nguoi khac trong LAN truy cap:" -ForegroundColor Cyan
    Write-Host "    https://$lanIp/" -ForegroundColor Green
    Write-Host "    (mat khau admin: xem /opt/qlpt/secrets/admin_password.txt)" -ForegroundColor DarkGray
}
Write-Host ""
Ok "HOAN TAT."
Warn "Luu y: chay lai script nay moi khi bat may (WSL doi IP) hoac doi mang WiFi."
