--
-- PostgreSQL database dump
--

\restrict Ve0QhnEb5aKodzqrFtD80c6Eyx8oJybOSKlyeqz2F5OmGHlefh38vHDjtdHqW2A

-- Dumped from database version 16.15
-- Dumped by pg_dump version 16.15

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: notifications; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.notifications (id, property_id, tenant_id, channel, template_code, priority, recipient, recipient_name, subject, body, status, attempts, error, provider_message, queued_at, sent_at, delivered_at, read_at, context, dedupe_key, created_at) FROM stdin;
8512b38d-e2d1-42eb-b948-0d559881dfb6	e21422b0-e128-5e5f-bdef-729af9b5c5c8	\N	IN_APP	ROOM_STATUS_CHANGED	LOW	e21422b0-e128-5e5f-bdef-729af9b5c5c8	\N	\N	Phòng A202 chuyển từ trống sang đang sửa chữa — Test luồng event end-to-end	QUEUED	0	\N	\N	2026-10-11 12:20:53.303801+00	\N	\N	\N	{"room_number": "A202", "from_status": "tr\\u1ed1ng", "to_status": "\\u0111ang s\\u1eeda ch\\u1eefa", "reason": "Test lu\\u1ed3ng event end-to-end", "property_name": "Ban qu\\u1ea3n l\\u00fd"}	\N	2026-10-11 12:20:53.303801+00
a4aa530b-d1c0-4809-b885-41d86e6c751f	e21422b0-e128-5e5f-bdef-729af9b5c5c8	\N	IN_APP	ROOM_STATUS_CHANGED	LOW	e21422b0-e128-5e5f-bdef-729af9b5c5c8	\N	\N	Phòng A202 chuyển từ đang sửa chữa sang trống — Khôi phục sau test	QUEUED	0	\N	\N	2026-10-11 12:20:58.294764+00	\N	\N	\N	{"room_number": "A202", "from_status": "\\u0111ang s\\u1eeda ch\\u1eefa", "to_status": "tr\\u1ed1ng", "reason": "Kh\\u00f4i ph\\u1ee5c sau test", "property_name": "Ban qu\\u1ea3n l\\u00fd"}	\N	2026-10-11 12:20:58.294764+00
26986dc9-7c05-4be6-bc41-20547e1ca331	e21422b0-e128-5e5f-bdef-729af9b5c5c8	c3d558d4-343b-5ad7-8409-13e3972718c1	IN_APP	PAYMENT_RECEIVED	LOW	c3d558d4-343b-5ad7-8409-13e3972718c1	Đặng Quang Huy	\N	Đã ghi nhận thanh toán 100,000đ cho hóa đơn HD-202610-0007 (phương thức tiền mặt).\nPhòng — — người thuê Đặng Quang Huy.	QUEUED	0	\N	\N	2026-10-11 12:39:22.69041+00	\N	\N	\N	{"tenant_name": "\\u0110\\u1eb7ng Quang Huy", "tenant_email": null, "tenant_phone": null, "invoice_no": "HD-202610-0007", "amount": "100,000\\u0111", "method": "ti\\u1ec1n m\\u1eb7t", "room_number": "\\u2014", "property_name": "Ban qu\\u1ea3n l\\u00fd"}	PAYMENT_RECEIVED:f1b442e0-bed9-4e39-a768-0af6a6b78bea	2026-10-11 12:39:22.69041+00
\.


--
-- Data for Name: outbox; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.outbox (id, event_type, payload, aggregate_type, aggregate_id, correlation_id, schema_version, status, attempts, created_at, published_at, last_error) FROM stdin;
\.


--
-- Data for Name: processed_events; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.processed_events (event_id, event_type, consumer, processed_at) FROM stdin;
28621bbf-2f5e-4148-a88c-4d70a95375e5	room.status_changed	notification-service:domain-events	2026-10-11 12:20:53.264698+00
ffbbe97a-619b-43a5-ad06-665340f56c76	room.status_changed	notification-service:domain-events	2026-10-11 12:20:58.290961+00
4212075f-bf5c-403e-924a-0319e359751a	payment.received	notification-service:domain-events	2026-10-11 12:39:22.659+00
\.


--
-- Data for Name: templates; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.templates (code, channel, name, subject, body, description, is_active, locale, created_at, updated_at) FROM stdin;
INVOICE_ISSUED	EMAIL	Phát hành hóa đơn tiền phòng	Hóa đơn {{ invoice_no }} — hạn trả {{ due_date }}	Xin chào {{ tenant_name }},\n\nHóa đơn tiền phòng kỳ {{ period }} đã được phát hành:\n\n  Mã hóa đơn    : {{ invoice_no }}\n  Phòng         : {{ room_number }}\n  Tiền phòng    : {{ rent_amount }}\n  Tiền điện     : {{ electric_amount }}\n  Tiền nước     : {{ water_amount }}\n  Phí dịch vụ   : {{ service_amount }}\n  Phí trễ hạn   : {{ late_fee_amount }}\n  Trừ tiền cọc  : {{ deposit_deducted }}\n  ------------------------------------------\n  TỔNG CỘNG    : {{ total_amount }}\n\nHạn thanh toán: {{ due_date }}. Vui lòng trả trước hạn để tránh phí trễ hạn.\n\nTrân trọng,\nBan quản lý {{ property_name }}\n	Gửi ngay khi billing phát hành hóa đơn (event invoice.issued).	t	vi	2026-10-10 05:31:50.222882+00	2026-10-10 05:31:50.222882+00
INVOICE_OVERDUE	EMAIL	Nhắc hóa đơn quá hạn	Hóa đơn {{ invoice_no }} đã quá hạn {{ days_overdue }} ngày	Xin chào {{ tenant_name }},\n\nHóa đơn {{ invoice_no }} (kỳ {{ period }}) hạn trả {{ due_date }} hiện đã quá hạn {{ days_overdue }} ngày.\n\n  Số tiền còn phải trả: {{ outstanding }}\n\nĐề nghị bạn thanh toán trong thời gian sớm nhất. Nếu đã thanh toán, xin báo lại để chúng tôi đối chiếu và cập nhật.\n\nTrân trọng,\nBan quản lý {{ property_name }}\n	Gửi khi hóa đơn quá hạn (event invoice.overdue).	t	vi	2026-10-10 05:31:50.222882+00	2026-10-10 05:31:50.222882+00
PAYMENT_RECEIVED	IN_APP	Xác nhận đã nhận thanh toán	\N	Đã ghi nhận thanh toán {{ amount }} cho hóa đơn {{ invoice_no }} (phương thức {{ method }}).\nPhòng {{ room_number }} — người thuê {{ tenant_name }}.\n	Gửi cho quản lý khi ghi nhận tiền (event payment.received).	t	vi	2026-10-10 05:31:50.222882+00	2026-10-10 05:31:50.222882+00
CONTRACT_ACTIVATED	IN_APP	Hợp đồng đã có hiệu lực	\N	Hợp đồng {{ contract_no }} của phòng {{ room_number }} đã có hiệu lực.\n  Người thuê : {{ tenant_name }}\n  Kỳ hạn    : {{ start_date }} → {{ end_date }}\n  Tiền phòng: {{ monthly_price }}/tháng\n	Thông báo cho quản lý khi hợp đồng kích hoạt (event contract.activated).	t	vi	2026-10-10 05:31:50.222882+00	2026-10-10 05:31:50.222882+00
CONTRACT_EXPIRING	EMAIL	Nhắc gia hạn hợp đồng	Hợp đồng {{ contract_no }} sắp hết hạn sau {{ days_left }} ngày	Xin chào {{ tenant_name }},\n\nHợp đồng {{ contract_no }} của phòng {{ room_number }} sẽ kết thúc vào ngày {{ end_date }} (còn {{ days_left }} ngày).\n\nNếu bạn muốn tiếp tục ở, vui lòng liên hệ ban quản lý trước ngày {{ end_date }} để ký gia hạn. Nếu không gia hạn, bạn vui lòng trả phòng và bàn giao chìa khoá đúng hạn.\n\nTrân trọng,\nBan quản lý {{ property_name }}\n	Nhắc trước 30/7/1 ngày (event contract.expiring).	t	vi	2026-10-10 05:31:50.222882+00	2026-10-10 05:31:50.222882+00
CONTRACT_EXPIRED	IN_APP	Hợp đồng đã kết thúc	\N	Hợp đồng {{ contract_no }} (phòng {{ room_number }}) đã kết thúc vào ngày {{ end_date }}.\nNgười thuê: {{ tenant_name }}.\nNhớ kiểm tra lại tiền cọc và hoá đơn cuối cùng.\n	Thông báo cho quản lý khi hợp đồng hết hạn (event contract.expired).	t	vi	2026-10-10 05:31:50.222882+00	2026-10-10 05:31:50.222882+00
INCIDENT_CREATED	IN_APP	Có sự cố mới	\N	Sự cố {{ ticket_no }} tại phòng {{ room_number }}: {{ title }}\n  Mức độ   : {{ priority }}\n  Loại     : {{ category }}\n  Người báo: {{ reported_by }}\n	Báo cho quản lý khi người thuê báo sự cố (event incident.created).	t	vi	2026-10-10 05:31:50.222882+00	2026-10-10 05:31:50.222882+00
INCIDENT_URGENT	IN_APP	Sự cố nghiêm trọng — cần xử lý ngay	\N	⚠ SỰ CỐ NGHIÊM TRỌNG — Phòng {{ room_number }} đã tạm ngừng cho thuê.\n  Mã sự cố : {{ ticket_no }}\n  Vấn đề   : {{ title }}\n  Người báo: {{ reported_by }}\n  Lúc      : {{ reported_at }}\n\nHợp đồng của {{ tenant_name }} vẫn giữ nguyên — người thuê KHÔNG mất tiền vì lỗi này.\n	Báo ngay cho quản lý (event incident.urgent / incident.escalated).	t	vi	2026-10-10 05:31:50.222882+00	2026-10-10 05:31:50.222882+00
ROOM_STATUS_CHANGED	IN_APP	Phòng đổi trạng thái	\N	Phòng {{ room_number }} chuyển từ {{ from_status }} sang {{ to_status }}{% if reason %} — {{ reason }}{% endif %}\n	Nhật ký thay đổi trạng thái phòng (event room.status_changed).	t	vi	2026-10-10 05:31:50.222882+00	2026-10-10 05:31:50.222882+00
MANUAL_NOTICE	IN_APP	Thông báo thủ công	\N	{{ title }}\n\n{{ detail }}\n	Khuôn mẫu dùng chung cho thông báo gửi tay từ giao diện quản trị.	t	vi	2026-10-10 05:31:50.222882+00	2026-10-10 05:31:50.222882+00
INCIDENT_URGENT_SMS	SMS	SMS báo sự cố nghiêm trọng (tắt mặc định)	\N	KHAN HIEM {{ property_name }}: phong {{ room_number }} co su co {{ title }}. Vui long lien he quan ly de xu ly gap.	Khuôn mẫu SMS dự phòng, mặc định is_active=false vì kênh SMS chưa được nối cổng. Bật sau khi cấu hình xong.	f	vi	2026-10-10 05:31:50.222882+00	2026-10-10 05:31:50.222882+00
\.


--
-- PostgreSQL database dump complete
--

\unrestrict Ve0QhnEb5aKodzqrFtD80c6Eyx8oJybOSKlyeqz2F5OmGHlefh38vHDjtdHqW2A

