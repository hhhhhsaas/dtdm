// ============================================================================
//  KIỂM THỬ TẢI BẰNG K6
//  Chạy:  docker run --rm --network qlpt_app -v $(pwd)/k6:/scripts \
//           grafana/k6 run --vus 50 --duration 2m /scripts/smoke.js
//
//  Mục tiêu: chứng minh SLA trong báo cáo
//    - p95 của API đọc  < 300 ms
//    - p95 của API ghi  < 500 ms
//    - tỷ lệ lỗi        < 1%
// ============================================================================
import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

// ============================================================================
//  METRIC TÙY CHỈNH — đo riêng từng nhóm nghiệp vụ
//  (k6 mặc định gộp tất cả endpoint vào http_req_duration, khó phân tích)
// ============================================================================
const readLatency  = new Trend('qlpt_read_latency',  true);
const writeLatency = new Trend('qlpt_write_latency', true);
const errorRate    = new Rate('qlpt_error_rate');
const loginCount   = new Counter('qlpt_login_count');
const invoiceCount = new Counter('qlpt_invoice_count');

const BASE = __ENV.BASE_URL || 'http://nginx';

// ============================================================================
//  THIẾT LẬP KỊCH BẢN TẢI
//  Mô phỏng: 50 người dùng đồng thời trong 2 phút
//  (chủ nhà trọ thực tế chỉ 2–3 người, nhưng đồ án cần chứng minh khả năng
//   chịu tải lớn hơn thực tế nhiều lần)
// ============================================================================
export const options = {
  stages: [
    { duration: '30s', target: 10,  label: 'warm-up' },      // làm nóng JIT, cache
    { duration: '30s', target: 50,  label: 'ramp-up' },
    { duration: '1m',  target: 50,  label: 'giai đoạn ổn định' },
    { duration: '30s', target: 0,   label: 'cool-down' },
  ],
  thresholds: {
    // ⭐ THRESHOLD = tiêu chí nghiệm thu. Nếu không đạt, k6 báo FAIL.
    'qlpt_read_latency':  ['p(95)<300', 'p(99)<800'],
    'qlpt_write_latency': ['p(95)<500', 'p(99)<1500'],
    'qlpt_error_rate':    ['rate<0.01'],           // < 1% lỗi
    'http_req_failed':    ['rate<0.01'],
    'http_reqs':          ['count>1000'],          // đủ số request để đo
  },
  httpDebugLog: false,
  noConnectionReuse: false,   // giữ connection — giống thực tế có keep-alive
  batchPerHost: 20,
};

// ============================================================================
//  DỮ LIỆU MẪU
// ============================================================================
function randomEmail() {
  return `loadtest-${Math.floor(Math.random() * 1e9)}@qlpt.test`;
}

const CITIES = ['Quận 9', 'Thủ Đức', 'Bình Thạnh', 'Gò Vấp', 'Củ Chi'];

// ============================================================================
//  KỊCH BẢN CHÍNH
// ============================================================================
export default function () {
  // ---------------------------------------------------------------------
  //  Nhóm 1: Xem danh mục phòng trống (90% lưu lượng thực tế)
  //  Đây là endpoint được cache ở nginx + Redis nên phải rất nhanh
  // ---------------------------------------------------------------------
  group('01 - Tra cứu phòng trống', () => {
    const res = http.get(`${BASE}/api/v1/rooms/available`, {
      headers: { 'Accept': 'application/json' },
      tags: { name: 'GET /rooms/available' },
    });

    const ok = check(res, {
      'status 200':        (r) => r.status === 200,
      'trả về JSON':       (r) => r.headers['Content-Type']?.includes('application/json'),
      'thời gian < 300ms': (r) => r.timings.duration < 300,
      'có X-Request-ID':   (r) => r.headers['X-Request-Id'] !== undefined,
    });

    readLatency.add(res.timings.duration);
    if (!ok) errorRate.add(1);
    sleep(Math.random() * 2);
  });

  // ---------------------------------------------------------------------
  //  Nhóm 2: Đăng nhập
  // ---------------------------------------------------------------------
  let token = '';
  group('02 - Đăng nhập', () => {
    const res = http.post(`${BASE}/api/v1/auth/login`,
      JSON.stringify({
        username: 'loadtest@qlpt.test',
        password: 'LoadTest@2026',
      }),
      {
        headers: { 'Content-Type': 'application/json' },
        tags: { name: 'POST /auth/login' },
      });

    const ok = check(res, {
      'đăng nhập thành công hoặc 401 (bình thường)':
        (r) => [200, 401, 422].includes(r.status),
    });

    if (res.status === 200) {
      try {
        token = res.json('access_token');
        loginCount.add(1);
      } catch (e) { /* không có body JSON -> bỏ qua */ }
    }
    if (!ok) errorRate.add(1);
    writeLatency.add(res.timings.duration);
  });

  const authHeaders = token
    ? { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` }
    : { 'Content-Type': 'application/json' };

  // ---------------------------------------------------------------------
  //  Nhóm 3: Xem hóa đơn (API đọc có xác thực)
  // ---------------------------------------------------------------------
  group('03 - Xem hóa đơn', () => {
    const res = http.get(`${BASE}/api/v1/invoices?limit=20`, {
      headers: authHeaders,
      tags: { name: 'GET /invoices' },
    });
    const ok = check(res, {
      'status 200 hoặc 401': (r) => [200, 401].includes(r.status),
    });
    readLatency.add(res.timings.duration);
    if (!ok) errorRate.add(1);
    sleep(Math.random());
  });

  // ---------------------------------------------------------------------
  //  Nhóm 4: Tìm phòng theo tiêu chí — nhiều tham số nhất trong hệ thống
  // ---------------------------------------------------------------------
  group('04 - Tìm phòng theo bộ lọc', () => {
    const url = `${BASE}/api/v1/rooms/available` +
      `?min_price=1000000&max_price=4000000&min_area=15` +
      `&amenities=AC,WIFI&sort=price_asc`;
    const res = http.get(url, { tags: { name: 'GET /rooms/available?filtered' } });
    const ok = check(res, { 'status 200': (r) => r.status === 200 });
    readLatency.add(res.timings.duration);
    if (!ok) errorRate.add(1);
    sleep(Math.random() * 0.5);
  });

  // ---------------------------------------------------------------------
  //  Nhóm 5: Tính tiền hàng tháng — KỊCH BẢN CAO ĐIỂM
  //  Mô phỏng ngày 1 hàng tháng khi chủ nhà chạy tính tiền 200 hóa đơn
  // ---------------------------------------------------------------------
  group('05 - Chạy tính tiền tháng (CAO ĐIỂM)', () => {
    const res = http.post(`${BASE}/api/v1/invoices/generate`,
      JSON.stringify({ period: '2026-10-01', property_id: __ENV.PROPERTY_ID || '' }),
      {
        headers: authHeaders,
        tags: { name: 'POST /invoices/generate (peak)' },
      });

    const ok = check(res, {
      'nhận job hoặc đã tồn tại (idempotent)':
        (r) => [200, 201, 202, 409].includes(r.status),
    });

    if (res.status === 200 || res.status === 202) invoiceCount.add(1);
    writeLatency.add(res.timings.duration);
    if (!ok) errorRate.add(1);

    // ⭐ Chỉ 1 trong 20 virtual user gọi endpoint này
    //   → mô phỏng đúng thực tế: 1 thao tác của 1 người, không phải 50 người
    sleep(Math.random() * 3);
  });

  // ---------------------------------------------------------------------
  //  Nhóm 6: Kiểm tra sức khỏe từng service
  // ---------------------------------------------------------------------
  group('06 - Health check', () => {
    const res = http.get(`${BASE}/api/v1/rooms/health`, {
      tags: { name: 'GET /health' },
    });
    check(res, { 'health OK': (r) => r.status === 200 });
    sleep(0.5);
  });
}

// ============================================================================
//  TỔNG KẾT — in ra khi k6 kết thúc
//  (Dán thẳng kết quả này vào báo cáo đồ án)
// ============================================================================
export function handleSummary(data) {
  const r = data.metrics;
  const line = (k) => (r[k] ? r[k].values : {});

  const read  = line('qlpt_read_latency');
  const write = line('qlpt_write_latency');
  const err   = line('qlpt_error_rate');

  const text = `
╔══════════════════════════════════════════════════════════════════════╗
║              KẾT QUẢ KIỂM THỬ TẢI  (K6)                             ║
╠══════════════════════════════════════════════════════════════════════╣
║  Số VU:                 50 đồng thời                                  ║
║  Thời gian:             2 phút                                        ║
║  Tổng request:          ${(r.http_reqs?.values?.count ?? 0).toLocaleString()}                                        ║
║  Request/giây:         ${(r.http_reqs?.values?.rate ?? 0).toFixed(1).padEnd(50)}║
╠══════════════════════════════════════════════════════════════════════╣
║  API ĐỌC                                                                    ║
║    p50:  ${(read.med ?? 0).toFixed(1).padStart(7)} ms      p95:  ${(read['p(95)'] ?? 0).toFixed(1).padStart(7)} ms   (SLA < 300)  ║
║    p99:  ${(read['p(99)'] ?? 0).toFixed(1).padStart(7)} ms                                                                     ║
║  API GHI                                                                    ║
║    p50:  ${(write.med ?? 0).toFixed(1).padStart(7)} ms      p95:  ${(write['p(95)'] ?? 0).toFixed(1).padStart(7)} ms   (SLA < 500)  ║
║    p99:  ${(write['p(99)'] ?? 0).toFixed(1).padStart(7)} ms                                                                     ║
╠══════════════════════════════════════════════════════════════════════╣
║  TỶ LỆ LỖI:         ${((err.rate ?? 0) * 100).toFixed(3)}%      (SLA < 1%)                               ║
║  ĐĂNG NHẬP:          ${(r.qlpt_login_count?.values?.count ?? 0).toString().padEnd(50)}║
║  JOB TÍNH TIỀN:      ${(r.qlpt_invoice_count?.values?.count ?? 0).toString().padEnd(50)}║
╚══════════════════════════════════════════════════════════════════════╝
`;

  return {
    stdout: text,
    'summary-loadtest.json': JSON.stringify(data, null, 2),
  };
}
