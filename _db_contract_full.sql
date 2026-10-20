--
-- PostgreSQL database dump
--

\restrict nUfaWdZafAEdbsbXmaAiOUhPpAikg1xih2RZ92MSFyFyyYFwa3fr0dVlqUvyteU

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
-- Data for Name: contracts; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.contracts (id, contract_no, property_id, room_id, primary_tenant_id, primary_tenant_name, primary_tenant_phone, primary_tenant_email, start_date, end_date, monthly_price, deposit_amount, deposit_paid_at, deposit_deducted, payment_cycle, status, terminated_reason, terminated_at, renewed_from_id, renewed_to_id, terms, document_key, created_by, created_at, updated_at, activated_at) FROM stdin;
56bade62-35e7-5793-bf54-88eaa141363b	HDMB-2026-001	e21422b0-e128-5e5f-bdef-729af9b5c5c8	065539b2-ee15-5197-83ed-75bf2b95a88d	dbe5a418-3b45-5af3-a749-b9ef507ad0fb	Nguyễn Văn An	0901000001	an.nguyen@example.com	2025-10-15	2026-10-15	2500000	2500000	2025-10-17 02:00:00+00	0	MONTHLY	ACTIVE	\N	\N	\N	\N	{"thanh_toan": "Ti\\u1ec1n ph\\u00f2ng tr\\u1ea3 theo th\\u00e1ng, ch\\u1eadm nh\\u1ea5t ng\\u00e0y 5", "notice_days": 30, "rules": ["Kh\\u00f4ng nu\\u00f4i ch\\u00f3 m\\u00e8o khi ch\\u01b0a \\u0111\\u01b0\\u1ee3c ch\\u1ee7 tr\\u1ecd \\u0111\\u1ed3ng \\u00fd", "Gi\\u1eef g\\u00ecn v\\u1ec7 sinh chung, kh\\u00f4ng g\\u00e2y \\u1ed3n sau 22h", "\\u0110\\u00f3ng \\u0111\\u1ee7 ti\\u1ec1n \\u0111i\\u1ec7n n\\u01b0\\u1edbc theo ch\\u1ec9 s\\u1ed1 \\u0111\\u1ed3ng h\\u1ed3 cu\\u1ed1i th\\u00e1ng"]}	\N	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:41.215921+00	2026-10-10 05:41:41.215921+00	2025-10-17 02:00:00+00
b7004827-2b83-59aa-bfff-f45e18fc7ecf	HDMB-2026-002	e21422b0-e128-5e5f-bdef-729af9b5c5c8	d9df3051-e29c-5447-9295-64a6ae6cbaf7	f49a32f9-0d96-5ec4-857f-b5153b33e340	Trần Thị Bình	0901000002	binh.tran@example.com	2026-04-18	2027-04-18	2500000	2500000	2026-04-20 02:00:00+00	0	MONTHLY	ACTIVE	\N	\N	\N	\N	{"thanh_toan": "Ti\\u1ec1n ph\\u00f2ng tr\\u1ea3 theo th\\u00e1ng, ch\\u1eadm nh\\u1ea5t ng\\u00e0y 5", "notice_days": 30, "rules": ["Kh\\u00f4ng nu\\u00f4i ch\\u00f3 m\\u00e8o khi ch\\u01b0a \\u0111\\u01b0\\u1ee3c ch\\u1ee7 tr\\u1ecd \\u0111\\u1ed3ng \\u00fd", "Gi\\u1eef g\\u00ecn v\\u1ec7 sinh chung, kh\\u00f4ng g\\u00e2y \\u1ed3n sau 22h", "\\u0110\\u00f3ng \\u0111\\u1ee7 ti\\u1ec1n \\u0111i\\u1ec7n n\\u01b0\\u1edbc theo ch\\u1ec9 s\\u1ed1 \\u0111\\u1ed3ng h\\u1ed3 cu\\u1ed1i th\\u00e1ng"]}	\N	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:41.215921+00	2026-10-10 05:41:41.215921+00	2026-04-20 02:00:00+00
253f461e-d71e-53e0-9e7e-17936afceae6	HDMB-2026-003	e21422b0-e128-5e5f-bdef-729af9b5c5c8	85cb0b69-b128-5e24-a7f4-0abd4ad91366	675fdc06-65f3-55e7-a259-0d52b6b2b00e	Lê Quốc Cường	0901000003	cuong.le@example.com	2026-08-26	2027-08-26	2500000	2500000	2026-08-28 02:00:00+00	0	MONTHLY	ACTIVE	\N	\N	\N	\N	{"thanh_toan": "Ti\\u1ec1n ph\\u00f2ng tr\\u1ea3 theo th\\u00e1ng, ch\\u1eadm nh\\u1ea5t ng\\u00e0y 5", "notice_days": 30, "rules": ["Kh\\u00f4ng nu\\u00f4i ch\\u00f3 m\\u00e8o khi ch\\u01b0a \\u0111\\u01b0\\u1ee3c ch\\u1ee7 tr\\u1ecd \\u0111\\u1ed3ng \\u00fd", "Gi\\u1eef g\\u00ecn v\\u1ec7 sinh chung, kh\\u00f4ng g\\u00e2y \\u1ed3n sau 22h", "\\u0110\\u00f3ng \\u0111\\u1ee7 ti\\u1ec1n \\u0111i\\u1ec7n n\\u01b0\\u1edbc theo ch\\u1ec9 s\\u1ed1 \\u0111\\u1ed3ng h\\u1ed3 cu\\u1ed1i th\\u00e1ng"]}	\N	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:41.215921+00	2026-10-10 05:41:41.215921+00	2026-08-28 02:00:00+00
0a8236f7-cadb-5494-ae42-5af2785e721b	HDMB-2026-004	e21422b0-e128-5e5f-bdef-729af9b5c5c8	5d6ec118-a073-5ed6-b3e7-9f53f9944a8b	a5b9b488-4b66-5e4a-9d86-42c6e47081cb	Phạm Thuỳ Dung	0901000004	dung.pham@example.com	2026-03-09	2027-03-09	2800000	2800000	2026-03-11 02:00:00+00	500000	MONTHLY	ACTIVE	\N	\N	\N	\N	{"thanh_toan": "Ti\\u1ec1n ph\\u00f2ng tr\\u1ea3 theo th\\u00e1ng, ch\\u1eadm nh\\u1ea5t ng\\u00e0y 5", "notice_days": 30, "rules": ["Kh\\u00f4ng nu\\u00f4i ch\\u00f3 m\\u00e8o khi ch\\u01b0a \\u0111\\u01b0\\u1ee3c ch\\u1ee7 tr\\u1ecd \\u0111\\u1ed3ng \\u00fd", "Gi\\u1eef g\\u00ecn v\\u1ec7 sinh chung, kh\\u00f4ng g\\u00e2y \\u1ed3n sau 22h", "\\u0110\\u00f3ng \\u0111\\u1ee7 ti\\u1ec1n \\u0111i\\u1ec7n n\\u01b0\\u1edbc theo ch\\u1ec9 s\\u1ed1 \\u0111\\u1ed3ng h\\u1ed3 cu\\u1ed1i th\\u00e1ng"]}	\N	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:41.215921+00	2026-10-10 05:41:41.215921+00	2026-03-11 02:00:00+00
894538de-2aba-5e2a-94a5-e14de6d9d349	HDMB-2026-005	e21422b0-e128-5e5f-bdef-729af9b5c5c8	9cab02e5-0bee-5730-8535-dbb0b9abbafb	9c3b140c-4b88-5ed0-a6c0-512cfbd1fcaf	Hoàng Minh Đức	0901000005	duc.hoang@example.com	2026-01-13	2027-01-13	1800000	1800000	2026-01-15 02:00:00+00	0	MONTHLY	ACTIVE	\N	\N	\N	\N	{"thanh_toan": "Ti\\u1ec1n ph\\u00f2ng tr\\u1ea3 theo th\\u00e1ng, ch\\u1eadm nh\\u1ea5t ng\\u00e0y 5", "notice_days": 30, "rules": ["Kh\\u00f4ng nu\\u00f4i ch\\u00f3 m\\u00e8o khi ch\\u01b0a \\u0111\\u01b0\\u1ee3c ch\\u1ee7 tr\\u1ecd \\u0111\\u1ed3ng \\u00fd", "Gi\\u1eef g\\u00ecn v\\u1ec7 sinh chung, kh\\u00f4ng g\\u00e2y \\u1ed3n sau 22h", "\\u0110\\u00f3ng \\u0111\\u1ee7 ti\\u1ec1n \\u0111i\\u1ec7n n\\u01b0\\u1edbc theo ch\\u1ec9 s\\u1ed1 \\u0111\\u1ed3ng h\\u1ed3 cu\\u1ed1i th\\u00e1ng"]}	\N	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:41.215921+00	2026-10-10 05:41:41.215921+00	2026-01-15 02:00:00+00
44ace439-a6cc-5843-bd5e-0e539011c13e	HDMB-2026-006	e21422b0-e128-5e5f-bdef-729af9b5c5c8	d85e96a0-be92-51db-a625-9cb21d297df2	dc3cc209-ee2f-5fdf-ba0f-370a4fceea47	Vũ Thị Giang	0901000006	giang.vu@example.com	2025-11-04	2026-11-04	2300000	2300000	2025-11-06 02:00:00+00	0	MONTHLY	ACTIVE	\N	\N	\N	\N	{"thanh_toan": "Ti\\u1ec1n ph\\u00f2ng tr\\u1ea3 theo th\\u00e1ng, ch\\u1eadm nh\\u1ea5t ng\\u00e0y 5", "notice_days": 30, "rules": ["Kh\\u00f4ng nu\\u00f4i ch\\u00f3 m\\u00e8o khi ch\\u01b0a \\u0111\\u01b0\\u1ee3c ch\\u1ee7 tr\\u1ecd \\u0111\\u1ed3ng \\u00fd", "Gi\\u1eef g\\u00ecn v\\u1ec7 sinh chung, kh\\u00f4ng g\\u00e2y \\u1ed3n sau 22h", "\\u0110\\u00f3ng \\u0111\\u1ee7 ti\\u1ec1n \\u0111i\\u1ec7n n\\u01b0\\u1edbc theo ch\\u1ec9 s\\u1ed1 \\u0111\\u1ed3ng h\\u1ed3 cu\\u1ed1i th\\u00e1ng"]}	\N	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:41.215921+00	2026-10-10 05:41:41.215921+00	2025-11-06 02:00:00+00
85985dba-e818-5dbb-b36d-ea5dc3408fbb	HDMB-2026-007	e21422b0-e128-5e5f-bdef-729af9b5c5c8	9d4bdc8a-5d50-5e9c-9a48-e96e8eb2f696	c3d558d4-343b-5ad7-8409-13e3972718c1	Đặng Quang Huy	0901000007	huy.dang@example.com	2026-04-28	2027-04-28	2300000	2300000	2026-04-30 02:00:00+00	0	MONTHLY	ACTIVE	\N	\N	\N	\N	{"thanh_toan": "Ti\\u1ec1n ph\\u00f2ng tr\\u1ea3 theo th\\u00e1ng, ch\\u1eadm nh\\u1ea5t ng\\u00e0y 5", "notice_days": 30, "rules": ["Kh\\u00f4ng nu\\u00f4i ch\\u00f3 m\\u00e8o khi ch\\u01b0a \\u0111\\u01b0\\u1ee3c ch\\u1ee7 tr\\u1ecd \\u0111\\u1ed3ng \\u00fd", "Gi\\u1eef g\\u00ecn v\\u1ec7 sinh chung, kh\\u00f4ng g\\u00e2y \\u1ed3n sau 22h", "\\u0110\\u00f3ng \\u0111\\u1ee7 ti\\u1ec1n \\u0111i\\u1ec7n n\\u01b0\\u1edbc theo ch\\u1ec9 s\\u1ed1 \\u0111\\u1ed3ng h\\u1ed3 cu\\u1ed1i th\\u00e1ng"]}	\N	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:41.215921+00	2026-10-10 05:41:41.215921+00	2026-04-30 02:00:00+00
76943dbb-6bff-587b-a373-5404ba4f5f66	HDMB-2026-008	e21422b0-e128-5e5f-bdef-729af9b5c5c8	cc4699ba-3e26-572b-bbc9-bda010628e6f	e8f4332e-3e5d-529b-8a82-324216778225	Bùi Khánh Linh	0901000008	linh.bui@example.com	2026-06-27	2027-06-27	2300000	2300000	2026-06-29 02:00:00+00	0	MONTHLY	ACTIVE	\N	\N	\N	\N	{"thanh_toan": "Ti\\u1ec1n ph\\u00f2ng tr\\u1ea3 theo th\\u00e1ng, ch\\u1eadm nh\\u1ea5t ng\\u00e0y 5", "notice_days": 30, "rules": ["Kh\\u00f4ng nu\\u00f4i ch\\u00f3 m\\u00e8o khi ch\\u01b0a \\u0111\\u01b0\\u1ee3c ch\\u1ee7 tr\\u1ecd \\u0111\\u1ed3ng \\u00fd", "Gi\\u1eef g\\u00ecn v\\u1ec7 sinh chung, kh\\u00f4ng g\\u00e2y \\u1ed3n sau 22h", "\\u0110\\u00f3ng \\u0111\\u1ee7 ti\\u1ec1n \\u0111i\\u1ec7n n\\u01b0\\u1edbc theo ch\\u1ec9 s\\u1ed1 \\u0111\\u1ed3ng h\\u1ed3 cu\\u1ed1i th\\u00e1ng"]}	\N	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:41.215921+00	2026-10-10 05:41:41.215921+00	2026-06-29 02:00:00+00
0b9edd6d-2437-5d93-b5b2-3589f5552a7a	HDMB-2026-009	e21422b0-e128-5e5f-bdef-729af9b5c5c8	a796ab2f-6f4c-5388-89fe-2b8b65ced493	89477047-a5a1-54f0-ac5a-de83dc53cd83	Đỗ Trung Kiên	0901000009	kien.do@example.com	2026-04-08	2027-04-08	2400000	2400000	2026-04-10 02:00:00+00	0	MONTHLY	ACTIVE	\N	\N	\N	\N	{"thanh_toan": "Ti\\u1ec1n ph\\u00f2ng tr\\u1ea3 theo th\\u00e1ng, ch\\u1eadm nh\\u1ea5t ng\\u00e0y 5", "notice_days": 30, "rules": ["Kh\\u00f4ng nu\\u00f4i ch\\u00f3 m\\u00e8o khi ch\\u01b0a \\u0111\\u01b0\\u1ee3c ch\\u1ee7 tr\\u1ecd \\u0111\\u1ed3ng \\u00fd", "Gi\\u1eef g\\u00ecn v\\u1ec7 sinh chung, kh\\u00f4ng g\\u00e2y \\u1ed3n sau 22h", "\\u0110\\u00f3ng \\u0111\\u1ee7 ti\\u1ec1n \\u0111i\\u1ec7n n\\u01b0\\u1edbc theo ch\\u1ec9 s\\u1ed1 \\u0111\\u1ed3ng h\\u1ed3 cu\\u1ed1i th\\u00e1ng"]}	\N	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:41.215921+00	2026-10-10 05:41:41.215921+00	2026-04-10 02:00:00+00
553d8119-da6f-5cf2-af03-a6699dec8874	HDMB-2026-010	e21422b0-e128-5e5f-bdef-729af9b5c5c8	691e094b-f125-5a59-a47e-aa925c1dafe2	6e07db76-edfe-56de-97c2-a4c8be955c72	Ngô Mai Lan	0901000010	lan.ngo@example.com	2025-08-25	2026-08-26	2800000	2800000	2025-08-27 02:00:00+00	0	MONTHLY	EXPIRED	\N	\N	\N	\N	{"thanh_toan": "Ti\\u1ec1n ph\\u00f2ng tr\\u1ea3 theo th\\u00e1ng, ch\\u1eadm nh\\u1ea5t ng\\u00e0y 5", "notice_days": 30, "rules": ["Kh\\u00f4ng nu\\u00f4i ch\\u00f3 m\\u00e8o khi ch\\u01b0a \\u0111\\u01b0\\u1ee3c ch\\u1ee7 tr\\u1ecd \\u0111\\u1ed3ng \\u00fd", "Gi\\u1eef g\\u00ecn v\\u1ec7 sinh chung, kh\\u00f4ng g\\u00e2y \\u1ed3n sau 22h", "\\u0110\\u00f3ng \\u0111\\u1ee7 ti\\u1ec1n \\u0111i\\u1ec7n n\\u01b0\\u1edbc theo ch\\u1ec9 s\\u1ed1 \\u0111\\u1ed3ng h\\u1ed3 cu\\u1ed1i th\\u00e1ng"]}	\N	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:41.215921+00	2026-10-10 05:41:41.215921+00	2025-08-27 02:00:00+00
0a415dab-b314-52cd-95f8-9cac8060eccb	HDMB-2026-011	e21422b0-e128-5e5f-bdef-729af9b5c5c8	996c582e-eca4-5597-8409-38da7d330846	a9f510fa-8027-5331-98e8-1b565c3f309f	Dương Hải Nam	0901000011	nam.duong@example.com	2026-10-10	2027-10-10	2800000	2800000	\N	0	MONTHLY	DRAFT	\N	\N	\N	\N	{"thanh_toan": "Ti\\u1ec1n ph\\u00f2ng tr\\u1ea3 theo th\\u00e1ng, ch\\u1eadm nh\\u1ea5t ng\\u00e0y 5", "notice_days": 30, "rules": ["Kh\\u00f4ng nu\\u00f4i ch\\u00f3 m\\u00e8o khi ch\\u01b0a \\u0111\\u01b0\\u1ee3c ch\\u1ee7 tr\\u1ecd \\u0111\\u1ed3ng \\u00fd", "Gi\\u1eef g\\u00ecn v\\u1ec7 sinh chung, kh\\u00f4ng g\\u00e2y \\u1ed3n sau 22h", "\\u0110\\u00f3ng \\u0111\\u1ee7 ti\\u1ec1n \\u0111i\\u1ec7n n\\u01b0\\u1edbc theo ch\\u1ec9 s\\u1ed1 \\u0111\\u1ed3ng h\\u1ed3 cu\\u1ed1i th\\u00e1ng"]}	\N	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:41.215921+00	2026-10-10 05:41:41.215921+00	\N
\.


--
-- Data for Name: contract_payments; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.contract_payments (id, contract_id, amount, method, receipt_no, note, received_by, paid_at) FROM stdin;
ae01232c-3435-530a-95a4-278c4cede83f	56bade62-35e7-5793-bf54-88eaa141363b	2500000	BANK_TRANSFER	PT-2026-01	Tiền cọc 1 tháng	0593a5e9-2ac1-52af-897c-8060f6258317	2025-10-17 02:00:00+00
d185e6cd-f33e-5bc6-9a3c-d393600af30e	b7004827-2b83-59aa-bfff-f45e18fc7ecf	2500000	MOMO	PT-2026-02	Tiền cọc 1 tháng	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-04-20 02:00:00+00
10c69c8c-9014-59a1-8bf3-650f176e3ad2	253f461e-d71e-53e0-9e7e-17936afceae6	2500000	CASH	PT-2026-03	Tiền cọc 1 tháng	0593a5e9-2ac1-52af-897c-8060f6258317	2026-08-28 02:00:00+00
78e9a17d-1790-573f-85e5-422a847b1950	0a8236f7-cadb-5494-ae42-5af2785e721b	2800000	BANK_TRANSFER	PT-2026-04	Tiền cọc 1 tháng	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-03-11 02:00:00+00
a7251f36-8b1d-5e99-ace8-50d0f439bdaf	894538de-2aba-5e2a-94a5-e14de6d9d349	1800000	MOMO	PT-2026-05	Tiền cọc 1 tháng	0593a5e9-2ac1-52af-897c-8060f6258317	2026-01-15 02:00:00+00
1cfdf84b-89dd-5faf-8342-a3d992a24d12	44ace439-a6cc-5843-bd5e-0e539011c13e	2300000	CASH	PT-2026-06	Tiền cọc 1 tháng	398a2def-31c1-5af4-ba43-594e33d4db9b	2025-11-06 02:00:00+00
877dd2ee-9925-51fd-ac36-ddc0127802f3	85985dba-e818-5dbb-b36d-ea5dc3408fbb	2300000	BANK_TRANSFER	PT-2026-07	Tiền cọc 1 tháng	0593a5e9-2ac1-52af-897c-8060f6258317	2026-04-30 02:00:00+00
12311d16-ec30-53cf-bd0a-3331e743e427	76943dbb-6bff-587b-a373-5404ba4f5f66	2300000	MOMO	PT-2026-08	Tiền cọc 1 tháng	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-06-29 02:00:00+00
f2476d65-a938-5d1a-8eda-fc758dbf8ba0	0b9edd6d-2437-5d93-b5b2-3589f5552a7a	2400000	CASH	PT-2026-09	Tiền cọc 1 tháng	0593a5e9-2ac1-52af-897c-8060f6258317	2026-04-10 02:00:00+00
dee3fe0a-1a8b-5671-b88b-8976521d8d2f	553d8119-da6f-5cf2-af03-a6699dec8874	2800000	BANK_TRANSFER	PT-2026-10	Tiền cọc 1 tháng	398a2def-31c1-5af4-ba43-594e33d4db9b	2025-08-27 02:00:00+00
\.


--
-- Data for Name: contract_roommates; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.contract_roommates (id, contract_id, tenant_id, full_name, phone, id_card_number, is_guarantor, created_at) FROM stdin;
409bb1fc-c587-5f6c-96c2-3dc63fe643da	44ace439-a6cc-5843-bd5e-0e539011c13e	86df3dbb-b8c0-5bab-83f8-0c58933bb830	Lý Thu Hà	0901000012	\N	f	2026-10-10 05:41:41.215921+00
40175a71-13bb-5680-beb2-6356bab1893e	b7004827-2b83-59aa-bfff-f45e18fc7ecf	\N	Trần Văn Bảo	0968111222	\N	f	2026-10-10 05:41:41.215921+00
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
\.


--
-- Data for Name: tenants_snapshot; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.tenants_snapshot (id, tenant_id, full_name, id_card_number, phone, email, address, captured_at) FROM stdin;
bf5ecbae-ca6f-5e03-b21b-aa778a938658	dbe5a418-3b45-5af3-a749-b9ef507ad0fb	Nguyễn Văn An	079201001001	0901000001	an.nguyen@example.com	Hà Nội, Việt Nam	2026-10-10 05:41:41.215921+00
c612fa06-d710-53c7-a3e5-dd36a8810bf2	f49a32f9-0d96-5ec4-857f-b5153b33e340	Trần Thị Bình	079201001002	0901000002	binh.tran@example.com	Nam Định, Việt Nam	2026-10-10 05:41:41.215921+00
070d3560-127d-5a90-9c8c-ae8ea24ee51b	675fdc06-65f3-55e7-a259-0d52b6b2b00e	Lê Quốc Cường	079201001003	0901000003	cuong.le@example.com	Hải Phòng, Việt Nam	2026-10-10 05:41:41.215921+00
d9a3d2ec-0dac-5239-af86-872c0ebe4fe3	a5b9b488-4b66-5e4a-9d86-42c6e47081cb	Phạm Thuỳ Dung	079201001004	0901000004	dung.pham@example.com	Thanh Hoá, Việt Nam	2026-10-10 05:41:41.215921+00
4fc95f83-bae5-5a4f-827e-f9889360a1ff	9c3b140c-4b88-5ed0-a6c0-512cfbd1fcaf	Hoàng Minh Đức	079201001005	0901000005	duc.hoang@example.com	Nghệ An, Việt Nam	2026-10-10 05:41:41.215921+00
bce4540f-844b-5808-8a20-b506ede50492	dc3cc209-ee2f-5fdf-ba0f-370a4fceea47	Vũ Thị Giang	079201001006	0901000006	giang.vu@example.com	Thái Bình, Việt Nam	2026-10-10 05:41:41.215921+00
dc2cdd44-403c-5dfb-8406-38f5ac0cd80d	c3d558d4-343b-5ad7-8409-13e3972718c1	Đặng Quang Huy	079201001007	0901000007	huy.dang@example.com	Hà Nội, Việt Nam	2026-10-10 05:41:41.215921+00
995ab77e-e88b-5fe3-9e2f-08a52ac1866f	e8f4332e-3e5d-529b-8a82-324216778225	Bùi Khánh Linh	079201001008	0901000008	linh.bui@example.com	Hưng Yên, Việt Nam	2026-10-10 05:41:41.215921+00
ea0f02a3-854d-5678-b5e0-33365b4fd9f0	89477047-a5a1-54f0-ac5a-de83dc53cd83	Đỗ Trung Kiên	079201001009	0901000009	kien.do@example.com	Bắc Ninh, Việt Nam	2026-10-10 05:41:41.215921+00
5a0d836a-be7c-538c-83d9-4a009b6290fe	6e07db76-edfe-56de-97c2-a4c8be955c72	Ngô Mai Lan	079201001010	0901000010	lan.ngo@example.com	Nam Định, Việt Nam	2026-10-10 05:41:41.215921+00
\.


--
-- PostgreSQL database dump complete
--

\unrestrict nUfaWdZafAEdbsbXmaAiOUhPpAikg1xih2RZ92MSFyFyyYFwa3fr0dVlqUvyteU

