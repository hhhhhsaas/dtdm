# ============================================================================
#  TIN CẬY CHỨNG CHỈ TỰ KÝ CỦA QLPT TRÊN WINDOWS
#  Dùng:  powershell -ExecutionPolicy Bypass -File .\scripts\trust-cert-windows.ps1
#         powershell ... -File .\scripts\trust-cert-windows.ps1 -AllUsers   (cần Admin)
#
#  Vì sao cần? nginx phục vụ HTTPS bằng chứng chỉ TỰ KÝ (self-signed). Trình duyệt
#  không biết "ai" ký nó nên chặn: NET::ERR_CERT_AUTHORITY_INVALID. Cách sạch nhất
#  là khai báo chứng chỉ đó là "tin cậy" trong kho chứng chỉ của Windows
#  (CurrentUser\Root — KHÔNG cần quyền Admin). Sau đó Chrome/Edge hết cảnh báo.
#
#  ⭐ File này phải lưu UTF-8 CÓ BOM (PowerShell 5.1 đọc theo mã vùng nếu thiếu BOM).
# ============================================================================
[CmdletBinding()]
param(
    # Cài cho MỌI người dùng (kho LocalMachine) — cần chạy PowerShell bằng quyền Admin.
    [switch]$AllUsers
)

$ErrorActionPreference = 'Stop'

function Info($m) { Write-Host $m -ForegroundColor Cyan }
function Ok($m)   { Write-Host $m -ForegroundColor Green }
function Warn($m) { Write-Host $m -ForegroundColor Yellow }
function Fail($m) { Write-Host $m -ForegroundColor Red; exit 1 }

Write-Host ""
Info "=== Cai chung chi QLPT vao kho tin cay cua Windows ==="

# --- 1. Tìm chứng chỉ nguồn ------------------------------------------------
$local = Join-Path $PSScriptRoot '..\infra\nginx\certs\fullchain.pem'
$winCert = Join-Path $env:TEMP 'qlpt-localhost.crt'

if (Test-Path $local) {
    Info "[1/4] Dung chung chi tu: $local"
    Copy-Item $local $winCert -Force
} else {
    Info "[1/4] Doc chung chi tu WSL: /opt/qlpt/infra/nginx/certs/fullchain.pem"
    $pem = & wsl -d Ubuntu -u root -- cat /opt/qlpt/infra/nginx/certs/fullchain.pem 2>$null
    if (-not $pem) { Fail "[1/3] Khong lay duoc chung chi. Kiem tra WSL / /opt/qlpt da cai chua." }
    # Đặt .crt để certutil nhận diện; PEM (-----BEGIN CERTIFICATE-----) được chấp nhận.
    Set-Content -Path $winCert -Value $pem -Encoding Ascii
}

# --- 2. Xác nhận nội dung --------------------------------------------------
$text = Get-Content -Path $winCert -Raw
if ($text -notmatch 'BEGIN CERTIFICATE') { Fail "[2/3] File chung chi khong hop le: $winCert" }
$subj = (& certutil -dump $winCert 2>$null | Select-String -Pattern '^Subject:' | Select-Object -First 1)
Info "[2/4] Da co chung chi hop le. $($subj -replace '^','')"

# --- 3. Xoá chứng chỉ QLPT CŨ để không bị nhầm ------------------------------
#   Mỗi lần tạo lại cert (VD thêm IP LAN vào SAN) là một chứng chỉ mới, cùng
#   CN=qlpt.local. Nếu để hai cert song song, trình duyệt có thể chọn nhầm
#   bản CŨ (thiếu SAN IP) khi truy cập qua IP → vẫn cảnh báo dù đã "tin cậy".
function Remove-StaleQlptCerts([string]$storeScope) {
    $storeNames = if ($storeScope -eq 'LocalMachine') { @('Root') } else { @('Root') }
    $store = New-Object System.Security.Cryptography.X509Certificates.X509Store('Root', $storeScope)
    try {
        $store.Open('ReadWrite')
        foreach ($c in @($store.Certificates)) {
            if ($c.Subject -match 'CN=qlpt|CN=QLPT') {
                $store.Remove($c)
                Warn "  Xoa chung chi cu: $($c.Subject)"
            }
        }
    } catch {
        Warn "  (Khong xoa duoc kho 'Root'/${storeScope}: $_)"
    } finally { $store.Close() }
}
if ($AllUsers) { Remove-StaleQlptCerts 'LocalMachine' }
else           { Remove-StaleQlptCerts 'CurrentUser' }

# --- 4. Cài vào kho tin cậy ------------------------------------------------
if ($AllUsers) {
    Info "[4/4] Cai vao LocalMachine\Root (moi nguoi dung) — CAN QUYEN ADMIN ..."
    $r = & certutil -addstore -f Root $winCert 2>&1
    $store = 'LocalMachine\Root'
} else {
    Info "[4/4] Cai vao CurrentUser\Root (chi tai khoan nay, khong can Admin) ..."
    $r = & certutil -user -addstore -f Root $winCert 2>&1
    $store = 'CurrentUser\Root'
}
$r | Out-Null

if ($LASTEXITCODE -eq 0) {
    Ok "Da them chung chi vao kho: $store"
} else {
    Warn "certutil tra ma loi $LASTEXITCODE. Thu lai bang quyen Admin (-AllUsers), hoac bam qua canh bao trong trinh duyet."
    $r | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    exit 1
}

# --- 4. Kiểm chứng ---------------------------------------------------------
Write-Host ""
Ok "HOAN TAT. Buoc cuoi de het canh bao:"
Write-Host "    1) DONG HOAN TOAN trinh duyet (tat het cua so), roi mo lai https://localhost/"
Write-Host "    2) Neu van con canh bao: mo chrome://settings/certificates -> tab 'Authorities'"
Write-Host "       kiem tra co muc 'QLPT' (CN=qlpt.local) la duoc."
Write-Host ""
Warn "Neu Chrome van chan sau khi da dong/mo lai: chay lai script voi -AllUsers (bang Admin)."
