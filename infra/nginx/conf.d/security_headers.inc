# ============================================================================
#  HEADER BẢO MẬT DÙNG CHUNG
#
#  ⭐ Vì sao tách file thay vì chỉ khai ở khối http?
#     nginx KHÔNG cộng dồn add_header: location nào có add_header riêng
#     (VD Cache-Control) sẽ BỎ HẾT header kế thừa từ http. Trước đây
#     index.html chính vì vậy mà thiếu HSTS/X-Frame-Options. Location nào
#     có add_header riêng thì phải include lại file này.
#
#  Đuôi .inc (không phải .conf) để `include conf.d/*.conf` không nạp trùng.
# ============================================================================
add_header X-Content-Type-Options    "nosniff"                                 always;
add_header X-Frame-Options           "SAMEORIGIN"                              always;
add_header Referrer-Policy           "strict-origin-when-cross-origin"         always;
add_header Permissions-Policy        "geolocation=(), microphone=(), camera=()" always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains"     always;
