--
-- PostgreSQL database dump
--

\restrict AkchYZttE6Js1dbP8j7sTgb0XPoB3li7PQE5nOD3VsZNFqraqabKvDAH1fJ5IUF

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
-- Data for Name: roommates; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.roommates (id, property_id, room_id, tenant_id, full_name, phone, is_primary, created_at, deleted_at) FROM stdin;
c47725c6-a68b-58fc-a105-44f49ced916b	e21422b0-e128-5e5f-bdef-729af9b5c5c8	d85e96a0-be92-51db-a625-9cb21d297df2	86df3dbb-b8c0-5bab-83f8-0c58933bb830	Lý Thu Hà	0901000012	f	2026-10-10 05:41:35.602665+00	\N
5cb49bd0-4efa-5b54-9575-21eb53f901fa	e21422b0-e128-5e5f-bdef-729af9b5c5c8	065539b2-ee15-5197-83ed-75bf2b95a88d	\N	Nguyễn Minh Châu	0967123456	f	2026-10-10 05:41:35.602665+00	\N
\.


--
-- Data for Name: tenant_history; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.tenant_history (id, tenant_id, property_id, room_id, event_type, event_data, actor_id, note, created_at) FROM stdin;
1	dbe5a418-3b45-5af3-a749-b9ef507ad0fb	e21422b0-e128-5e5f-bdef-729af9b5c5c8	065539b2-ee15-5197-83ed-75bf2b95a88d	MOVED_IN	{"room_number": "A101", "room_id": "065539b2-ee15-5197-83ed-75bf2b95a88d", "contract_id": "56bade62-35e7-5793-bf54-88eaa141363b"}	0593a5e9-2ac1-52af-897c-8060f6258317	Nhận phòng A101	2026-10-10 05:41:35.602665+00
2	f49a32f9-0d96-5ec4-857f-b5153b33e340	e21422b0-e128-5e5f-bdef-729af9b5c5c8	d9df3051-e29c-5447-9295-64a6ae6cbaf7	MOVED_IN	{"room_number": "A102", "room_id": "d9df3051-e29c-5447-9295-64a6ae6cbaf7", "contract_id": "b7004827-2b83-59aa-bfff-f45e18fc7ecf"}	0593a5e9-2ac1-52af-897c-8060f6258317	Nhận phòng A102	2026-10-10 05:41:35.602665+00
3	675fdc06-65f3-55e7-a259-0d52b6b2b00e	e21422b0-e128-5e5f-bdef-729af9b5c5c8	85cb0b69-b128-5e24-a7f4-0abd4ad91366	MOVED_IN	{"room_number": "A103", "room_id": "85cb0b69-b128-5e24-a7f4-0abd4ad91366", "contract_id": "253f461e-d71e-53e0-9e7e-17936afceae6"}	0593a5e9-2ac1-52af-897c-8060f6258317	Nhận phòng A103	2026-10-10 05:41:35.602665+00
4	a5b9b488-4b66-5e4a-9d86-42c6e47081cb	e21422b0-e128-5e5f-bdef-729af9b5c5c8	5d6ec118-a073-5ed6-b3e7-9f53f9944a8b	MOVED_IN	{"room_number": "A201", "room_id": "5d6ec118-a073-5ed6-b3e7-9f53f9944a8b", "contract_id": "0a8236f7-cadb-5494-ae42-5af2785e721b"}	0593a5e9-2ac1-52af-897c-8060f6258317	Nhận phòng A201	2026-10-10 05:41:35.602665+00
5	9c3b140c-4b88-5ed0-a6c0-512cfbd1fcaf	e21422b0-e128-5e5f-bdef-729af9b5c5c8	9cab02e5-0bee-5730-8535-dbb0b9abbafb	MOVED_IN	{"room_number": "A-G01", "room_id": "9cab02e5-0bee-5730-8535-dbb0b9abbafb", "contract_id": "894538de-2aba-5e2a-94a5-e14de6d9d349"}	0593a5e9-2ac1-52af-897c-8060f6258317	Nhận phòng A-G01	2026-10-10 05:41:35.602665+00
6	dc3cc209-ee2f-5fdf-ba0f-370a4fceea47	e21422b0-e128-5e5f-bdef-729af9b5c5c8	d85e96a0-be92-51db-a625-9cb21d297df2	MOVED_IN	{"room_number": "B101", "room_id": "d85e96a0-be92-51db-a625-9cb21d297df2", "contract_id": "44ace439-a6cc-5843-bd5e-0e539011c13e"}	0593a5e9-2ac1-52af-897c-8060f6258317	Nhận phòng B101	2026-10-10 05:41:35.602665+00
7	c3d558d4-343b-5ad7-8409-13e3972718c1	e21422b0-e128-5e5f-bdef-729af9b5c5c8	9d4bdc8a-5d50-5e9c-9a48-e96e8eb2f696	MOVED_IN	{"room_number": "B102", "room_id": "9d4bdc8a-5d50-5e9c-9a48-e96e8eb2f696", "contract_id": "85985dba-e818-5dbb-b36d-ea5dc3408fbb"}	0593a5e9-2ac1-52af-897c-8060f6258317	Nhận phòng B102	2026-10-10 05:41:35.602665+00
8	e8f4332e-3e5d-529b-8a82-324216778225	e21422b0-e128-5e5f-bdef-729af9b5c5c8	cc4699ba-3e26-572b-bbc9-bda010628e6f	MOVED_IN	{"room_number": "B103", "room_id": "cc4699ba-3e26-572b-bbc9-bda010628e6f", "contract_id": "76943dbb-6bff-587b-a373-5404ba4f5f66"}	0593a5e9-2ac1-52af-897c-8060f6258317	Nhận phòng B103	2026-10-10 05:41:35.602665+00
9	89477047-a5a1-54f0-ac5a-de83dc53cd83	e21422b0-e128-5e5f-bdef-729af9b5c5c8	a796ab2f-6f4c-5388-89fe-2b8b65ced493	MOVED_IN	{"room_number": "B104", "room_id": "a796ab2f-6f4c-5388-89fe-2b8b65ced493", "contract_id": "0b9edd6d-2437-5d93-b5b2-3589f5552a7a"}	0593a5e9-2ac1-52af-897c-8060f6258317	Nhận phòng B104	2026-10-10 05:41:35.602665+00
10	6e07db76-edfe-56de-97c2-a4c8be955c72	e21422b0-e128-5e5f-bdef-729af9b5c5c8	691e094b-f125-5a59-a47e-aa925c1dafe2	MOVED_OUT	{"room_number": "A202", "room_id": "691e094b-f125-5a59-a47e-aa925c1dafe2"}	0593a5e9-2ac1-52af-897c-8060f6258317	Đã trả phòng khi hợp đồng hết hạn	2026-10-10 05:41:35.602665+00
11	a9f510fa-8027-5331-98e8-1b565c3f309f	e21422b0-e128-5e5f-bdef-729af9b5c5c8	\N	PROFILE_UPDATED	{"source": "seed"}	0593a5e9-2ac1-52af-897c-8060f6258317	Tạo hồ sơ, chưa phát sinh hợp đồng	2026-10-10 05:41:35.602665+00
12	86df3dbb-b8c0-5bab-83f8-0c58933bb830	e21422b0-e128-5e5f-bdef-729af9b5c5c8	\N	PROFILE_UPDATED	{"source": "seed"}	0593a5e9-2ac1-52af-897c-8060f6258317	Tạo hồ sơ, chưa phát sinh hợp đồng	2026-10-10 05:41:35.602665+00
13	675fdc06-65f3-55e7-a259-0d52b6b2b00e	e21422b0-e128-5e5f-bdef-729af9b5c5c8	\N	RISK_CHANGED	{"from": "LOW", "to": "MEDIUM", "reason": "T\\u1eebng tr\\u1ec5 h\\u1ea1n 2 l\\u1ea7n trong 6 th\\u00e1ng"}	0593a5e9-2ac1-52af-897c-8060f6258317	Cập nhật mức rủi ro do lịch sử thanh toán	2026-10-10 05:41:35.602665+00
14	c3d558d4-343b-5ad7-8409-13e3972718c1	e21422b0-e128-5e5f-bdef-729af9b5c5c8	\N	RISK_CHANGED	{"from": "LOW", "to": "MEDIUM", "reason": "H\\u00f3a \\u0111\\u01a1n th\\u00e1ng 8 ch\\u01b0a thanh to\\u00e1n"}	0593a5e9-2ac1-52af-897c-8060f6258317	Cập nhật mức rủi ro do lịch sử thanh toán	2026-10-10 05:41:35.602665+00
\.


--
-- Data for Name: tenants; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.tenants (id, property_id, previous_property_ids, full_name, date_of_birth, gender, phone, email, address, occupation, note, id_card_enc, id_card_bidx, id_card_last4, id_card_front, id_card_back, emergency_contact_name, emergency_contact_phone, zalo_oa_id, is_active, risk_level, risk_note, current_room_id, current_contract_id, created_at, updated_at, deleted_at) FROM stdin;
dbe5a418-3b45-5af3-a749-b9ef507ad0fb	e21422b0-e128-5e5f-bdef-729af9b5c5c8	[]	Nguyễn Văn An	1991-02-02	M	0901000001	an.nguyen@example.com	Hà Nội, Việt Nam	Nhân viên văn phòng	\N	v1$WCxln53yX12iNU8AbHTKcBmrA3upiIHCrnEleB6gEmWDVDB_2Bk8uA==	3b16644d0bfaacfac85cb5139c05d29662df06d48c5da7e42c72f50eceb027d7	1001	\N	\N	\N	\N	\N	t	LOW	\N	065539b2-ee15-5197-83ed-75bf2b95a88d	56bade62-35e7-5793-bf54-88eaa141363b	2026-10-10 05:41:35.602665+00	2026-10-10 06:03:22.185177+00	\N
f49a32f9-0d96-5ec4-857f-b5153b33e340	e21422b0-e128-5e5f-bdef-729af9b5c5c8	[]	Trần Thị Bình	1992-03-03	F	0901000002	binh.tran@example.com	Nam Định, Việt Nam	Nhân viên kế toán	\N	v1$BgtS7lhc2JVEYp6tz2DWogREST-907d0dthX65EDfbGvjlfMjXzQig==	66dd9b32b2a5b180734b65074844e74f0aa92f1522261d3252b2deaa9dee6269	1002	\N	\N	\N	\N	\N	t	LOW	\N	d9df3051-e29c-5447-9295-64a6ae6cbaf7	b7004827-2b83-59aa-bfff-f45e18fc7ecf	2026-10-10 05:41:35.602665+00	2026-10-10 06:03:22.185177+00	\N
675fdc06-65f3-55e7-a259-0d52b6b2b00e	e21422b0-e128-5e5f-bdef-729af9b5c5c8	[]	Lê Quốc Cường	1993-04-04	M	0901000003	cuong.le@example.com	Hải Phòng, Việt Nam	Kỹ sư xây dựng	\N	v1$UHTxZ7tHSD9CVRYz7ODwMoI7J2FxQY0VvVxgDaGaI3YTX-xYcNZg-Q==	fa70544d454ac0eb1506be61a6ac77137d074217276c7253740dcca63b088380	1003	\N	\N	\N	\N	\N	t	MEDIUM	Từng trễ hạn 2 lần trong 6 tháng	85cb0b69-b128-5e24-a7f4-0abd4ad91366	253f461e-d71e-53e0-9e7e-17936afceae6	2026-10-10 05:41:35.602665+00	2026-10-10 06:03:22.185177+00	\N
a5b9b488-4b66-5e4a-9d86-42c6e47081cb	e21422b0-e128-5e5f-bdef-729af9b5c5c8	[]	Phạm Thuỳ Dung	1994-05-05	F	0901000004	dung.pham@example.com	Thanh Hoá, Việt Nam	Giáo viên	\N	v1$H6ViqkrB7WnM1WDFcEWF-8Js04gWmHNGsQkQx7Ta-FgJ8iIgPKW6kw==	76a695bc41e915b87a386f550663a83313389c4cb4ea254c54eb88f5ff4d960b	1004	\N	\N	\N	\N	\N	t	LOW	\N	5d6ec118-a073-5ed6-b3e7-9f53f9944a8b	0a8236f7-cadb-5494-ae42-5af2785e721b	2026-10-10 05:41:35.602665+00	2026-10-10 06:03:22.185177+00	\N
9c3b140c-4b88-5ed0-a6c0-512cfbd1fcaf	e21422b0-e128-5e5f-bdef-729af9b5c5c8	[]	Hoàng Minh Đức	1995-06-06	M	0901000005	duc.hoang@example.com	Nghệ An, Việt Nam	Kỹ sư phần mềm	\N	v1$9rZliow1rWno9AQOFqrH4nadXlb-0nFa-IIo7fCncetqExIac9moBA==	61b8be2e5ef4c174a0237a3c7471d9046a66f0ecf396090ea2e78851396ec2d3	1005	\N	\N	\N	\N	\N	t	LOW	\N	9cab02e5-0bee-5730-8535-dbb0b9abbafb	894538de-2aba-5e2a-94a5-e14de6d9d349	2026-10-10 05:41:35.602665+00	2026-10-10 06:03:22.185177+00	\N
dc3cc209-ee2f-5fdf-ba0f-370a4fceea47	e21422b0-e128-5e5f-bdef-729af9b5c5c8	[]	Vũ Thị Giang	1996-07-07	F	0901000006	giang.vu@example.com	Thái Bình, Việt Nam	Làm tự do	\N	v1$KsnKszgQErdmmv4kigkoy1uOTwFO2juLfV7LQfh9xgEyEchEErBQsw==	b1a186e1c3be29b2b2b1b4b90fccf16607e1e9298a48924773f7d5bfce2daac9	1006	\N	\N	\N	\N	\N	t	LOW	\N	d85e96a0-be92-51db-a625-9cb21d297df2	44ace439-a6cc-5843-bd5e-0e539011c13e	2026-10-10 05:41:35.602665+00	2026-10-10 06:03:22.185177+00	\N
c3d558d4-343b-5ad7-8409-13e3972718c1	e21422b0-e128-5e5f-bdef-729af9b5c5c8	[]	Đặng Quang Huy	1997-08-08	M	0901000007	huy.dang@example.com	Hà Nội, Việt Nam	Nhân viên bán hàng	\N	v1$OoLhTwLA0oDQiMJUseGmqeI3KcO9tBg0ZgzRfdSniOPo4Rt1IK0MRg==	8f348d6d59958d6a02a1daf0c27c56955e3e36f536313a633260eb9401c2d08f	1007	\N	\N	\N	\N	\N	t	MEDIUM	Hóa đơn tháng 8 chưa thanh toán	9d4bdc8a-5d50-5e9c-9a48-e96e8eb2f696	85985dba-e818-5dbb-b36d-ea5dc3408fbb	2026-10-10 05:41:35.602665+00	2026-10-10 06:03:22.185177+00	\N
e8f4332e-3e5d-529b-8a82-324216778225	e21422b0-e128-5e5f-bdef-729af9b5c5c8	[]	Bùi Khánh Linh	1998-09-09	F	0901000008	linh.bui@example.com	Hưng Yên, Việt Nam	Thiết kế đồ hoạ	\N	v1$nhIemjA8VqGz7X8CBXLFf8WVtI6fsb5exsYbj4Ra-J1kxcB3kEzaBA==	bc47d4740bce30972233949ec0f28ff8831a70bbb7b1aa99067b714f14194fec	1008	\N	\N	\N	\N	\N	t	LOW	\N	cc4699ba-3e26-572b-bbc9-bda010628e6f	76943dbb-6bff-587b-a373-5404ba4f5f66	2026-10-10 05:41:35.602665+00	2026-10-10 06:03:22.185177+00	\N
89477047-a5a1-54f0-ac5a-de83dc53cd83	e21422b0-e128-5e5f-bdef-729af9b5c5c8	[]	Đỗ Trung Kiên	1999-10-10	M	0901000009	kien.do@example.com	Bắc Ninh, Việt Nam	Thợ điện tử	\N	v1$Gr1eO9YqOR881b9MBXafrY37rkkW0PYGw1l014RBaIX3dnTmsb1eYA==	727ca14f3cb9e2b71dd59dc7524daa1f940ddf5dcb56a4b6bb70334094629359	1009	\N	\N	\N	\N	\N	t	LOW	\N	a796ab2f-6f4c-5388-89fe-2b8b65ced493	0b9edd6d-2437-5d93-b5b2-3589f5552a7a	2026-10-10 05:41:35.602665+00	2026-10-10 06:03:22.185177+00	\N
6e07db76-edfe-56de-97c2-a4c8be955c72	e21422b0-e128-5e5f-bdef-729af9b5c5c8	[]	Ngô Mai Lan	1990-11-11	F	0901000010	lan.ngo@example.com	Nam Định, Việt Nam	Chăm sóc khách hàng	\N	v1$jwr3N9fwXSjk7AJtVU5wB2EeW6dlO7UzKFI3qvlV3AaCDqCbDodDfQ==	14be24c271c44a177622dbfd2e3ddb535d0496809eb7ce0e4e2142f6624d830c	1010	\N	\N	\N	\N	\N	f	MEDIUM	Trả phòng giữa kỳ, chuyển nhà nhiều	\N	\N	2026-10-10 05:41:35.602665+00	2026-10-10 06:03:22.185177+00	\N
a9f510fa-8027-5331-98e8-1b565c3f309f	e21422b0-e128-5e5f-bdef-729af9b5c5c8	[]	Dương Hải Nam	1991-12-12	M	0901000011	nam.duong@example.com	Quảng Ninh, Việt Nam	Lái xe	\N	v1$Y08lVEcc0S4qXJo0tmBx2Aj3Psk2TUTRk6epLWIyHhfFaSDjCTA0fQ==	6da7fc9cc764ad9363cea365832666b5777fbf02c915869b0873070d8f1dbf0a	1011	\N	\N	\N	\N	\N	t	LOW	\N	\N	\N	2026-10-10 05:41:35.602665+00	2026-10-10 06:03:22.185177+00	\N
86df3dbb-b8c0-5bab-83f8-0c58933bb830	e21422b0-e128-5e5f-bdef-729af9b5c5c8	[]	Lý Thu Hà	1992-01-13	F	0901000012	ha.ly@example.com	Lạng Sơn, Việt Nam	Sinh viên	\N	v1$MqxFMk6lbZlifhDZ8xGTYQdDo_okpzqcIU7UA6ecVF97ePkvLr8mUA==	013cbe94927e4ffe007a47fc143565aad62ac767b293edecb602d1cc692ee3d9	1012	\N	\N	\N	\N	\N	t	LOW	\N	\N	\N	2026-10-10 05:41:35.602665+00	2026-10-10 06:03:22.185177+00	\N
\.


--
-- Name: tenant_history_id_seq; Type: SEQUENCE SET; Schema: public; Owner: qlpt
--

SELECT pg_catalog.setval('public.tenant_history_id_seq', 14, true);


--
-- PostgreSQL database dump complete
--

\unrestrict AkchYZttE6Js1dbP8j7sTgb0XPoB3li7PQE5nOD3VsZNFqraqabKvDAH1fJ5IUF

