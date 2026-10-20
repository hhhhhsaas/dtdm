--
-- PostgreSQL database dump
--

\restrict wQAcqaUdedhO78pcWR60Mtg8DpsHGdelW3y25fIiwvaE4ZHTsGLQrhTW8bAm1df

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
-- Data for Name: daily_contract_flow; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.daily_contract_flow (property_id, stat_date, created, activated, terminated, expired, cancelled, renewed, updated_at) FROM stdin;
\.


--
-- Data for Name: daily_financials; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.daily_financials (property_id, stat_date, invoices_issued, invoiced_amount, payments_received, collected_amount, refunded_amount, outstanding, overdue_count, overdue_amount, updated_at) FROM stdin;
e21422b0-e128-5e5f-bdef-729af9b5c5c8	2026-09-04	0	0	9	25089900	0	0	0	0	2026-10-20 06:51:16.819847+00
e21422b0-e128-5e5f-bdef-729af9b5c5c8	2026-10-02	0	0	1	2943500	0	0	0	0	2026-10-20 06:51:16.819847+00
e21422b0-e128-5e5f-bdef-729af9b5c5c8	2026-10-03	0	0	0	0	0	0	2	5963200	2026-10-20 06:51:16.819847+00
e21422b0-e128-5e5f-bdef-729af9b5c5c8	2026-10-04	0	0	7	20061300	0	0	0	0	2026-10-20 06:51:16.819847+00
e21422b0-e128-5e5f-bdef-729af9b5c5c8	2026-10-10	27	79053500	0	0	0	79053500	0	0	2026-10-20 06:51:16.819847+00
e21422b0-e128-5e5f-bdef-729af9b5c5c8	2026-10-11	0	0	1	100000	0	78953500	0	0	2026-10-20 06:51:16.819847+00
\.


--
-- Data for Name: daily_incident_stats; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.daily_incident_stats (property_id, stat_date, created, urgent, resolved, cost, resolution_hours, updated_at) FROM stdin;
\.


--
-- Data for Name: daily_occupancy; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.daily_occupancy (property_id, stat_date, total_rooms, available, occupied, maintenance, reserved, source, captured_at, other) FROM stdin;
e21422b0-e128-5e5f-bdef-729af9b5c5c8	2026-10-11	20	11	9	0	0	snapshot	2026-10-11 12:53:40.684542+00	0
00000000-0000-0000-0000-000000000000	2026-10-11	20	11	9	0	0	snapshot	2026-10-11 12:53:40.691803+00	0
e21422b0-e128-5e5f-bdef-729af9b5c5c8	2026-10-13	20	11	9	0	0	snapshot	2026-10-13 11:16:28.908214+00	0
00000000-0000-0000-0000-000000000000	2026-10-13	20	11	9	0	0	snapshot	2026-10-13 11:16:28.949869+00	0
e21422b0-e128-5e5f-bdef-729af9b5c5c8	2026-10-14	20	11	9	0	0	snapshot	2026-10-13 17:17:09.521208+00	0
00000000-0000-0000-0000-000000000000	2026-10-14	20	11	9	0	0	snapshot	2026-10-13 17:17:09.543345+00	0
e21422b0-e128-5e5f-bdef-729af9b5c5c8	2026-10-20	20	11	9	0	0	snapshot	2026-10-20 06:51:16.769269+00	0
00000000-0000-0000-0000-000000000000	2026-10-20	20	11	9	0	0	snapshot	2026-10-20 06:51:16.778724+00	0
\.


--
-- Data for Name: monthly_financials; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.monthly_financials (property_id, period, invoices_issued, invoiced_amount, payments_received, collected_amount, refunded_amount, days_covered, updated_at) FROM stdin;
\.


--
-- Data for Name: open_invoices; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.open_invoices (invoice_id, property_id, contract_id, room_id, tenant_id, tenant_name, invoice_no, period, total_amount, paid_amount, due_date, issued_date, status, is_overdue_notified, created_at, updated_at) FROM stdin;
04701513-f296-5f87-b6f1-25100429c690	e21422b0-e128-5e5f-bdef-729af9b5c5c8	56bade62-35e7-5793-bf54-88eaa141363b	065539b2-ee15-5197-83ed-75bf2b95a88d	dbe5a418-3b45-5af3-a749-b9ef507ad0fb	Nguyễn Văn An	HD-202610-0001	2026-10-01	2980000	0	2026-11-03	2026-10-10	OPEN	f	2026-10-20 06:51:16.819847+00	2026-10-20 06:51:16.819847+00
cabe2e80-f9ed-5ce1-a877-da76b17452cc	e21422b0-e128-5e5f-bdef-729af9b5c5c8	b7004827-2b83-59aa-bfff-f45e18fc7ecf	d9df3051-e29c-5447-9295-64a6ae6cbaf7	f49a32f9-0d96-5ec4-857f-b5153b33e340	Trần Thị Bình	HD-202610-0002	2026-10-01	2942500	0	2026-11-03	2026-10-10	OPEN	f	2026-10-20 06:51:16.819847+00	2026-10-20 06:51:16.819847+00
0d38d226-ae84-59dd-8c65-a98748251ca7	e21422b0-e128-5e5f-bdef-729af9b5c5c8	253f461e-d71e-53e0-9e7e-17936afceae6	85cb0b69-b128-5e24-a7f4-0abd4ad91366	675fdc06-65f3-55e7-a259-0d52b6b2b00e	Lê Quốc Cường	HD-202609-0003	2026-09-01	3015000	0	2026-10-03	2026-10-10	OVERDUE	t	2026-10-20 06:51:16.819847+00	2026-10-20 06:51:16.819847+00
3801fc31-dba2-5e9e-845f-3a26daa6dfff	e21422b0-e128-5e5f-bdef-729af9b5c5c8	253f461e-d71e-53e0-9e7e-17936afceae6	85cb0b69-b128-5e24-a7f4-0abd4ad91366	675fdc06-65f3-55e7-a259-0d52b6b2b00e	Lê Quốc Cường	HD-202610-0003	2026-10-01	3915000	0	2026-11-03	2026-10-10	OPEN	f	2026-10-20 06:51:16.819847+00	2026-10-20 06:51:16.819847+00
d937406f-e7fb-50d1-88e0-932a7b4c87fe	e21422b0-e128-5e5f-bdef-729af9b5c5c8	0a8236f7-cadb-5494-ae42-5af2785e721b	5d6ec118-a073-5ed6-b3e7-9f53f9944a8b	a5b9b488-4b66-5e4a-9d86-42c6e47081cb	Phạm Thuỳ Dung	HD-202610-0004	2026-10-01	3302500	0	2026-11-03	2026-10-10	OPEN	f	2026-10-20 06:51:16.819847+00	2026-10-20 06:51:16.819847+00
c1d5561b-21a7-502c-ad3e-ac6bd02b25f2	e21422b0-e128-5e5f-bdef-729af9b5c5c8	894538de-2aba-5e2a-94a5-e14de6d9d349	9cab02e5-0bee-5730-8535-dbb0b9abbafb	9c3b140c-4b88-5ed0-a6c0-512cfbd1fcaf	Hoàng Minh Đức	HD-202610-0005	2026-10-01	2404800	0	2026-11-03	2026-10-10	OPEN	f	2026-10-20 06:51:16.819847+00	2026-10-20 06:51:16.819847+00
321bc270-397f-5226-a567-fa1b67c85f18	e21422b0-e128-5e5f-bdef-729af9b5c5c8	44ace439-a6cc-5843-bd5e-0e539011c13e	d85e96a0-be92-51db-a625-9cb21d297df2	dc3cc209-ee2f-5fdf-ba0f-370a4fceea47	Vũ Thị Giang	HD-202610-0006	2026-10-01	2872700	0	2026-11-03	2026-10-10	OPEN	f	2026-10-20 06:51:16.819847+00	2026-10-20 06:51:16.819847+00
dddb0ef0-cf55-5151-b08d-9c1882d7ac87	e21422b0-e128-5e5f-bdef-729af9b5c5c8	85985dba-e818-5dbb-b36d-ea5dc3408fbb	9d4bdc8a-5d50-5e9c-9a48-e96e8eb2f696	c3d558d4-343b-5ad7-8409-13e3972718c1	Đặng Quang Huy	HD-202609-0007	2026-09-01	2948200	0	2026-10-03	2026-10-10	OVERDUE	t	2026-10-20 06:51:16.819847+00	2026-10-20 06:51:16.819847+00
300c7a83-2837-50a0-8e0d-66096151de25	e21422b0-e128-5e5f-bdef-729af9b5c5c8	0b9edd6d-2437-5d93-b5b2-3589f5552a7a	a796ab2f-6f4c-5388-89fe-2b8b65ced493	89477047-a5a1-54f0-ac5a-de83dc53cd83	Đỗ Trung Kiên	HD-202610-0009	2026-10-01	2797500	0	2026-11-03	2026-10-10	OPEN	f	2026-10-20 06:51:16.819847+00	2026-10-20 06:51:16.819847+00
9458eec2-1d1b-5629-a80e-c6c5affa8588	e21422b0-e128-5e5f-bdef-729af9b5c5c8	85985dba-e818-5dbb-b36d-ea5dc3408fbb	9d4bdc8a-5d50-5e9c-9a48-e96e8eb2f696	c3d558d4-343b-5ad7-8409-13e3972718c1	Đặng Quang Huy	HD-202610-0007	2026-10-01	3780600	100000	2026-11-03	2026-10-10	OPEN	f	2026-10-20 06:51:16.819847+00	2026-10-20 06:51:16.819847+00
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
28621bbf-2f5e-4148-a88c-4d70a95375e5	room.status_changed	report-service:read-model	2026-10-11 12:20:53.266752+00
ffbbe97a-619b-43a5-ad06-665340f56c76	room.status_changed	report-service:read-model	2026-10-11 12:20:58.291266+00
4212075f-bf5c-403e-924a-0319e359751a	payment.received	report-service:read-model	2026-10-11 12:39:22.657364+00
\.


--
-- Data for Name: sync_runs; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.sync_runs (id, kind, property_id, status, rows_synced, detail, message, started_at, finished_at, duration_ms, triggered_by) FROM stdin;
13	reconcile	\N	SUCCESS	0	{"occupancy_synced": 0, "invoices_synced": 0, "invoices_closed": 0, "errors": []}	\N	2026-10-11 11:05:00.222336+00	2026-10-11 11:05:00.347361+00	139	scheduler
14	reconcile	\N	SUCCESS	0	{"occupancy_synced": 0, "invoices_synced": 0, "invoices_closed": 0, "errors": []}	\N	2026-10-11 11:10:08.537893+00	2026-10-11 11:10:08.646652+00	127	scheduler
15	reconcile	\N	SUCCESS	0	{"occupancy_synced": 0, "invoices_synced": 0, "invoices_closed": 0, "errors": []}	\N	2026-10-11 11:10:08.66543+00	2026-10-11 11:10:08.713148+00	49	scheduler
16	reconcile	\N	SUCCESS	0	{"occupancy_synced": 0, "invoices_synced": 0, "invoices_closed": 0, "errors": []}	\N	2026-10-11 11:15:33.645535+00	2026-10-11 11:15:33.728192+00	93	scheduler
17	reconcile	\N	SUCCESS	0	{"occupancy_synced": 0, "invoices_synced": 0, "invoices_closed": 0, "errors": []}	\N	2026-10-11 11:15:33.74234+00	2026-10-11 11:15:33.764523+00	23	scheduler
18	reconcile	\N	SUCCESS	0	{"occupancy_synced": 0, "invoices_synced": 0, "invoices_closed": 0, "errors": []}	\N	2026-10-11 11:29:55.90785+00	2026-10-11 11:29:56.296936+00	448	scheduler
19	reconcile	\N	SUCCESS	0	{"occupancy_synced": 0, "invoices_synced": 0, "invoices_closed": 0, "errors": []}	\N	2026-10-11 11:29:56.366404+00	2026-10-11 11:29:56.551531+00	189	scheduler
20	reconcile	\N	SUCCESS	0	{"occupancy_synced": 0, "invoices_synced": 0, "invoices_closed": 0, "errors": []}	\N	2026-10-11 11:30:28.552113+00	2026-10-11 11:30:28.756857+00	209	scheduler
21	reconcile	\N	SUCCESS	0	{"occupancy_synced": 0, "invoices_synced": 0, "invoices_closed": 0, "errors": []}	\N	2026-10-11 11:30:28.841322+00	2026-10-11 11:30:28.958576+00	123	scheduler
22	reconcile	\N	SUCCESS	1	{"occupancy_synced": 1, "invoices_synced": 0, "invoices_closed": 0, "errors": []}	\N	2026-10-11 11:41:52.31718+00	2026-10-11 11:41:53.027824+00	788	scheduler
23	reconcile	\N	SUCCESS	1	{"occupancy_synced": 1, "invoices_synced": 0, "invoices_closed": 0, "errors": []}	\N	2026-10-11 11:42:59.139366+00	2026-10-11 11:42:59.201283+00	64	scheduler
24	reconcile	\N	SUCCESS	1	{"occupancy_synced": 1, "invoices_synced": 0, "invoices_closed": 0, "errors": []}	\N	2026-10-11 11:42:59.212061+00	2026-10-11 11:42:59.239522+00	29	scheduler
25	reconcile	\N	SUCCESS	2	{"occupancy_synced": 2, "invoices_synced": 0, "invoices_closed": 0, "errors": []}	\N	2026-10-11 12:23:48.843375+00	2026-10-11 12:23:49.138692+00	373	scheduler
26	reconcile	\N	SUCCESS	2	{"occupancy_synced": 2, "invoices_synced": 0, "invoices_closed": 0, "errors": []}	\N	2026-10-11 12:23:49.212046+00	2026-10-11 12:23:49.308717+00	99	scheduler
27	reconcile	\N	SUCCESS	2	{"occupancy_synced": 2, "invoices_synced": 0, "invoices_closed": 0, "errors": []}	\N	2026-10-11 12:23:58.250022+00	2026-10-11 12:23:58.320467+00	72	scheduler
28	reconcile	\N	SUCCESS	2	{"occupancy_synced": 2, "invoices_synced": 0, "invoices_closed": 0, "errors": []}	\N	2026-10-11 12:23:58.330444+00	2026-10-11 12:23:58.364256+00	35	scheduler
29	reconcile	\N	SUCCESS	18	{"occupancy_synced": 2, "financials_synced": 6, "invoices_synced": 10, "errors": []}	\N	2026-10-11 12:53:40.558929+00	2026-10-11 12:53:40.802219+00	251	scheduler
30	reconcile	\N	SUCCESS	18	{"occupancy_synced": 2, "financials_synced": 6, "invoices_synced": 10, "errors": []}	\N	2026-10-13 00:48:57.660461+00	2026-10-13 00:48:57.85268+00	205	scheduler
31	reconcile	\N	SUCCESS	18	{"occupancy_synced": 2, "financials_synced": 6, "invoices_synced": 10, "errors": []}	\N	2026-10-13 00:53:30.196504+00	2026-10-13 00:53:30.401908+00	214	scheduler
32	reconcile	\N	SUCCESS	18	{"occupancy_synced": 2, "financials_synced": 6, "invoices_synced": 10, "errors": []}	\N	2026-10-13 00:53:30.419326+00	2026-10-13 00:53:30.558127+00	140	scheduler
33	reconcile	\N	SUCCESS	18	{"occupancy_synced": 2, "financials_synced": 6, "invoices_synced": 10, "errors": []}	\N	2026-10-13 00:56:56.270371+00	2026-10-13 00:56:56.420371+00	159	scheduler
34	reconcile	\N	SUCCESS	18	{"occupancy_synced": 2, "financials_synced": 6, "invoices_synced": 10, "errors": []}	\N	2026-10-13 00:56:56.442785+00	2026-10-13 00:56:56.521446+00	80	scheduler
35	reconcile	\N	SUCCESS	18	{"occupancy_synced": 2, "financials_synced": 6, "invoices_synced": 10, "errors": []}	\N	2026-10-13 00:58:58.159937+00	2026-10-13 00:58:58.255706+00	97	scheduler
36	reconcile	\N	SUCCESS	18	{"occupancy_synced": 2, "financials_synced": 6, "invoices_synced": 10, "errors": []}	\N	2026-10-13 00:58:58.265224+00	2026-10-13 00:58:58.332533+00	68	scheduler
37	reconcile	\N	SUCCESS	18	{"occupancy_synced": 2, "financials_synced": 6, "invoices_synced": 10, "errors": []}	\N	2026-10-13 00:59:24.688958+00	2026-10-13 00:59:24.795812+00	108	scheduler
38	reconcile	\N	SUCCESS	18	{"occupancy_synced": 2, "financials_synced": 6, "invoices_synced": 10, "errors": []}	\N	2026-10-13 00:59:24.805334+00	2026-10-13 00:59:24.873046+00	69	scheduler
39	reconcile	\N	SUCCESS	18	{"occupancy_synced": 2, "financials_synced": 6, "invoices_synced": 10, "errors": []}	\N	2026-10-13 01:38:46.977346+00	2026-10-13 01:38:47.181788+00	215	scheduler
40	reconcile	\N	SUCCESS	18	{"occupancy_synced": 2, "financials_synced": 6, "invoices_synced": 10, "errors": []}	\N	2026-10-13 01:38:47.196328+00	2026-10-13 01:38:47.27814+00	83	scheduler
41	reconcile	\N	SUCCESS	18	{"occupancy_synced": 2, "financials_synced": 6, "invoices_synced": 10, "errors": []}	\N	2026-10-13 02:24:46.491955+00	2026-10-13 02:24:46.687149+00	201	scheduler
42	reconcile	\N	SUCCESS	18	{"occupancy_synced": 2, "financials_synced": 6, "invoices_synced": 10, "errors": []}	\N	2026-10-13 02:24:46.703143+00	2026-10-13 02:24:46.809479+00	107	scheduler
43	reconcile	\N	SUCCESS	18	{"occupancy_synced": 2, "financials_synced": 6, "invoices_synced": 10, "errors": []}	\N	2026-10-13 05:09:44.304559+00	2026-10-13 05:09:47.54101+00	3664	scheduler
44	reconcile	\N	SUCCESS	18	{"occupancy_synced": 2, "financials_synced": 6, "invoices_synced": 10, "errors": []}	\N	2026-10-13 11:16:27.519666+00	2026-10-13 11:16:29.560426+00	2169	scheduler
45	reconcile	\N	SUCCESS	18	{"occupancy_synced": 2, "financials_synced": 6, "invoices_synced": 10, "errors": []}	\N	2026-10-13 17:17:08.970971+00	2026-10-13 17:17:11.123096+00	1033	scheduler
46	reconcile	\N	SUCCESS	18	{"occupancy_synced": 2, "financials_synced": 6, "invoices_synced": 10, "errors": []}	\N	2026-10-20 00:48:14.899745+00	2026-10-20 00:48:15.834395+00	980	scheduler
47	reconcile	\N	SUCCESS	18	{"occupancy_synced": 2, "financials_synced": 6, "invoices_synced": 10, "errors": []}	\N	2026-10-20 00:48:15.915963+00	2026-10-20 00:48:19.608303+00	712	scheduler
48	reconcile	\N	SUCCESS	18	{"occupancy_synced": 2, "financials_synced": 6, "invoices_synced": 10, "errors": []}	\N	2026-10-20 06:51:16.434941+00	2026-10-20 06:51:16.703497+00	295	scheduler
49	reconcile	\N	SUCCESS	18	{"occupancy_synced": 2, "financials_synced": 6, "invoices_synced": 10, "errors": []}	\N	2026-10-20 06:51:16.733429+00	2026-10-20 06:51:16.960661+00	230	scheduler
\.


--
-- Name: sync_runs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: qlpt
--

SELECT pg_catalog.setval('public.sync_runs_id_seq', 49, true);


--
-- PostgreSQL database dump complete
--

\unrestrict wQAcqaUdedhO78pcWR60Mtg8DpsHGdelW3y25fIiwvaE4ZHTsGLQrhTW8bAm1df

