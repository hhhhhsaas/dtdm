# ============================================================================
#  KIỂM CHỨNG TỪ PHÍA WINDOWS — chạy trong PowerShell
#  Dùng:  powershell -ExecutionPolicy Bypass -File .\scripts\verify-windows.ps1
#
#  Mục đích: xác nhận từ MÁY CHỦ Windows (không qua WSL) rằng
#    - https://localhost (Nginx gateway) trả lời 200,
#    - từng service 8001-8008 trỏ qua localhostForwarding của WSL2,
#    - chứng chỉ tự ký hoạt động (bỏ qua xác minh: curl.exe -k).
#  Nếu toàn bộ PASS thì mở https://localhost/ trên trình duyệt là dùng được.
#
#  ⭐ 3 BÀI HỌC MÃ NGUỒN (đã gặp thật, đừng quay lại):
#  1) File này phải lưu UTF-8 CÓ BOM. PowerShell 5.1 đọc .ps1 theo mã vùng
#     nếu KHÔNG có BOM -> chữ tiếng Việt hỏng mã hoá, phá vỡ parser.
#  2) KHÔNG truyền JSON trực tiếp qua curl.exe: body có dấu " nhưng KHÔNG
#     có dấu cách nên PowerShell không bọc tham số, curl nhận body mất ngoặc
#     -> HTTP 422. Giải pháp: ghi body ra file tạm rồi -d "@file".
#  3) Mật khẩu admin KHÔNG nằm trên Windows (thư mục secrets/ không được copy
#     sang bản nguồn) mà nằm trong WSL: /opt/qlpt/secrets/admin_password.txt
#     -> phải đọc từ WSL, nếu không sẽ dùng nhầm mật khẩu mặc định -> 401.
# ============================================================================
[CmdletBinding()]
param()

$G = 'Green'; $R = 'Red'; $Y = 'Yellow'
$script:fail = 0

function Get-AdminPassword {
    # 1) file secret cục bộ (nếu bạn đã sinh secrets ngay trên Windows)
    $p = Join-Path $PSScriptRoot '..\secrets\admin_password.txt'
    if (Test-Path $p) {
        $v = (Get-Content $p -Raw).Trim()
        if ($v) { return $v }
    }
    # 2) biến môi trường (tùy chọn cho CI)
    if ($env:QLPT_ADMIN_PASSWORD) { return $env:QLPT_ADMIN_PASSWORD.Trim() }
    # 3) đọc từ WSL — nơi stack thật sự đang chạy
    try {
        $w = & wsl -d Ubuntu -u root -- cat /opt/qlpt/secrets/admin_password.txt 2>$null |
             Select-Object -First 1
        if ($w) {
            $v = "$w".Trim()
            if ($v) { return $v }
        }
    } catch { }
    return 'Admin@12345'
}

function Test-Uri {
    param([string]$Label, [string]$Url, [int[]]$OkCodes)
    # curl.exe có sẵn trên Windows 10+; -k bỏ qua chứng chỉ tự ký.
    $out = & curl.exe -k -s -o - -w "`n%{http_code}" -m 10 $Url 2>$null
    if (-not $out) {
        Write-Host "  [FAIL] $Label - khong noi duoc ($Url)" -ForegroundColor $R
        $script:fail++
        return
    }
    $lines = $out -split "`n"
    $code = $lines[-1].Trim()
    if ($OkCodes -contains [int]$code) {
        Write-Host "  [ OK ] $Label - HTTP $code" -ForegroundColor $G
    } else {
        Write-Host "  [FAIL] $Label - HTTP $code (mong doi: $($OkCodes -join '/'))" -ForegroundColor $R
        $script:fail++
    }
}

Write-Host "`nBUOC 1 - Gateway Nginx (HTTPS tren localhost)" -ForegroundColor Cyan
Test-Uri "Trang chu (SPA)"       "https://localhost/"                      @(200)
Test-Uri "Tim phong trong (API)" "https://localhost/api/v1/rooms/available" @(200)
Test-Uri "Swagger /docs"         "https://localhost/docs"                  @(404)

Write-Host "`nBUOC 2 - 8 service qua localhostForwarding cua WSL2" -ForegroundColor Cyan
$ports = @{
    8001 = 'auth'; 8002 = 'room'; 8003 = 'tenant'; 8004 = 'contract'
    8005 = 'billing'; 8006 = 'notification'; 8007 = 'maintenance'; 8008 = 'report'
}
foreach ($p in ($ports.Keys | Sort-Object)) {
    Test-Uri ("{0}:{1}/health" -f $ports[$p], $p) "http://localhost:$p/health" @(200)
}

Write-Host "`nBUOC 3 - Dang nhap tai khoan demo qua gateway" -ForegroundColor Cyan
$pw = Get-AdminPassword
if ($pw -eq 'Admin@12345') {
    Write-Host "  [WARN] khong doc duoc secret tu WSL - dung mat khau mac dinh" -ForegroundColor $Y
}

# Body JSON ghi ra file tam -> curl -d "@file": không qua tham số shell nên
# không bị mất dấu ngoặc kép (xem ghi chú 2 ở đầu file).
$bodyFile = Join-Path $env:TEMP ('qlpt_login_' + [guid]::NewGuid().ToString() + '.json')
[System.IO.File]::WriteAllText($bodyFile, '{"username":"admin","password":"' + $pw + '"}')
try {
    $code = & curl.exe -k -s -o NUL -w "%{http_code}" -m 10 -X POST `
              "https://localhost/api/v1/auth/login" `
              -H "Content-Type: application/json" `
              -d "@$bodyFile" 2>$null
} finally {
    Remove-Item $bodyFile -Force -ErrorAction SilentlyContinue
}
if ($code -eq '200') {
    Write-Host "  [ OK ] admin dang nhap - HTTP 200 + access_token" -ForegroundColor $G
} else {
    Write-Host "  [FAIL] admin dang nhap - HTTP $code (chay 'make seed' chua?)" -ForegroundColor $R
    $script:fail++
}

Write-Host ""
if ($script:fail -eq 0) {
    Write-Host "====================================================================" -ForegroundColor $G
    Write-Host "  KET QUA: TAT CA DAT - mo https://localhost/ tren trinh duyet" -ForegroundColor $G
    Write-Host "====================================================================" -ForegroundColor $G
    exit 0
} else {
    Write-Host "  KET QUA: $($script:fail) hang muc KHONG dat" -ForegroundColor $R
    Write-Host "  Goi y: vao WSL -> cd /opt/qlpt -> make laptop-up -> make seed -> make reload-nginx" -ForegroundColor $Y
    exit 1
}
