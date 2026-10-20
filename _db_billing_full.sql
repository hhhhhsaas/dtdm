--
-- PostgreSQL database dump
--

\restrict 8jJHmU9P3yqsaqcz2qrKHdY8Go6qYbxvszSIemKBaiYhG4aAl44bTPN8kf5a6Kp

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
-- Data for Name: billing_jobs; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.billing_jobs (id, property_id, period, status, total_contracts, processed, succeeded, failed, error, started_at, finished_at, created_by, created_at) FROM stdin;
\.


--
-- Data for Name: invoices; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.invoices (id, invoice_no, property_id, contract_id, room_id, tenant_id, tenant_name, room_number, period, rent_amount, electric_amount, water_amount, service_amount, late_fee_amount, discount_amount, deposit_deducted, total_amount, paid_amount, status, due_date, paid_at, is_final, created_by, created_at, updated_at) FROM stdin;
d0dceaf1-e222-58a2-ab71-fd071e0252a8	HD-202608-0001	e21422b0-e128-5e5f-bdef-729af9b5c5c8	56bade62-35e7-5793-bf54-88eaa141363b	065539b2-ee15-5197-83ed-75bf2b95a88d	dbe5a418-3b45-5af3-a749-b9ef507ad0fb	Nguyễn Văn An	A101	2026-08-01	2500000	125000	135000	170000	0	0	0	2930000	2930000	PAID	2026-09-03	2026-09-04 02:00:00+00	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
7b32636e-53da-5d2b-ab78-4b187cd017ec	HD-202609-0001	e21422b0-e128-5e5f-bdef-729af9b5c5c8	56bade62-35e7-5793-bf54-88eaa141363b	065539b2-ee15-5197-83ed-75bf2b95a88d	dbe5a418-3b45-5af3-a749-b9ef507ad0fb	Nguyễn Văn An	A101	2026-09-01	2500000	135000	150000	170000	0	0	0	2955000	2955000	PAID	2026-10-03	2026-10-04 02:00:00+00	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
04701513-f296-5f87-b6f1-25100429c690	HD-202610-0001	e21422b0-e128-5e5f-bdef-729af9b5c5c8	56bade62-35e7-5793-bf54-88eaa141363b	065539b2-ee15-5197-83ed-75bf2b95a88d	dbe5a418-3b45-5af3-a749-b9ef507ad0fb	Nguyễn Văn An	A101	2026-10-01	2500000	145000	165000	170000	0	0	0	2980000	0	PENDING	2026-11-03	\N	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
8eb25f8e-1a15-55d6-9763-d4cde719c1b9	HD-202608-0002	e21422b0-e128-5e5f-bdef-729af9b5c5c8	b7004827-2b83-59aa-bfff-f45e18fc7ecf	d9df3051-e29c-5447-9295-64a6ae6cbaf7	f49a32f9-0d96-5ec4-857f-b5153b33e340	Trần Thị Bình	A102	2026-08-01	2500000	147500	75000	170000	0	0	0	2892500	2892500	PAID	2026-09-03	2026-09-04 02:00:00+00	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
c4b46900-b111-5c8e-9bd2-31a0d06dc717	HD-202609-0002	e21422b0-e128-5e5f-bdef-729af9b5c5c8	b7004827-2b83-59aa-bfff-f45e18fc7ecf	d9df3051-e29c-5447-9295-64a6ae6cbaf7	f49a32f9-0d96-5ec4-857f-b5153b33e340	Trần Thị Bình	A102	2026-09-01	2500000	157500	90000	170000	0	0	0	2917500	2917500	PAID	2026-10-03	2026-10-04 02:00:00+00	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
cabe2e80-f9ed-5ce1-a877-da76b17452cc	HD-202610-0002	e21422b0-e128-5e5f-bdef-729af9b5c5c8	b7004827-2b83-59aa-bfff-f45e18fc7ecf	d9df3051-e29c-5447-9295-64a6ae6cbaf7	f49a32f9-0d96-5ec4-857f-b5153b33e340	Trần Thị Bình	A102	2026-10-01	2500000	167500	105000	170000	0	0	0	2942500	0	PENDING	2026-11-03	\N	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
a9d93b21-5d76-5885-8541-fe165bcabb10	HD-202608-0003	e21422b0-e128-5e5f-bdef-729af9b5c5c8	253f461e-d71e-53e0-9e7e-17936afceae6	85cb0b69-b128-5e24-a7f4-0abd4ad91366	675fdc06-65f3-55e7-a259-0d52b6b2b00e	Lê Quốc Cường	A103	2026-08-01	2500000	170000	150000	170000	0	0	0	2990000	2990000	PAID	2026-09-03	2026-09-04 02:00:00+00	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
0d38d226-ae84-59dd-8c65-a98748251ca7	HD-202609-0003	e21422b0-e128-5e5f-bdef-729af9b5c5c8	253f461e-d71e-53e0-9e7e-17936afceae6	85cb0b69-b128-5e24-a7f4-0abd4ad91366	675fdc06-65f3-55e7-a259-0d52b6b2b00e	Lê Quốc Cường	A103	2026-09-01	2500000	180000	165000	170000	0	0	0	3015000	0	OVERDUE	2026-10-03	\N	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
3801fc31-dba2-5e9e-845f-3a26daa6dfff	HD-202610-0003	e21422b0-e128-5e5f-bdef-729af9b5c5c8	253f461e-d71e-53e0-9e7e-17936afceae6	85cb0b69-b128-5e24-a7f4-0abd4ad91366	675fdc06-65f3-55e7-a259-0d52b6b2b00e	Lê Quốc Cường	A103	2026-10-01	2500000	190000	180000	170000	875000	0	0	3915000	0	PENDING	2026-11-03	\N	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
9ab312e6-b25d-5b65-b81a-6dfb2c9ba3c6	HD-202608-0004	e21422b0-e128-5e5f-bdef-729af9b5c5c8	0a8236f7-cadb-5494-ae42-5af2785e721b	5d6ec118-a073-5ed6-b3e7-9f53f9944a8b	a5b9b488-4b66-5e4a-9d86-42c6e47081cb	Phạm Thuỳ Dung	A201	2026-08-01	2800000	192500	90000	170000	0	0	500000	2752500	2752500	PAID	2026-09-03	2026-09-04 02:00:00+00	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
2fea4294-684b-5590-be89-bcc496707c48	HD-202609-0004	e21422b0-e128-5e5f-bdef-729af9b5c5c8	0a8236f7-cadb-5494-ae42-5af2785e721b	5d6ec118-a073-5ed6-b3e7-9f53f9944a8b	a5b9b488-4b66-5e4a-9d86-42c6e47081cb	Phạm Thuỳ Dung	A201	2026-09-01	2800000	202500	105000	170000	0	0	0	3277500	3277500	PAID	2026-10-03	2026-10-04 02:00:00+00	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
d937406f-e7fb-50d1-88e0-932a7b4c87fe	HD-202610-0004	e21422b0-e128-5e5f-bdef-729af9b5c5c8	0a8236f7-cadb-5494-ae42-5af2785e721b	5d6ec118-a073-5ed6-b3e7-9f53f9944a8b	a5b9b488-4b66-5e4a-9d86-42c6e47081cb	Phạm Thuỳ Dung	A201	2026-10-01	2800000	212500	120000	170000	0	0	0	3302500	0	PENDING	2026-11-03	\N	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
c5b50011-adf2-5065-bf1b-183da9320219	HD-202608-0005	e21422b0-e128-5e5f-bdef-729af9b5c5c8	894538de-2aba-5e2a-94a5-e14de6d9d349	9cab02e5-0bee-5730-8535-dbb0b9abbafb	9c3b140c-4b88-5ed0-a6c0-512cfbd1fcaf	Hoàng Minh Đức	A-G01	2026-08-01	1800000	215000	165000	170000	0	0	0	2350000	2350000	PAID	2026-09-03	2026-09-04 02:00:00+00	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
f901279e-cb2b-56ab-9c13-7a8423f4cc77	HD-202609-0005	e21422b0-e128-5e5f-bdef-729af9b5c5c8	894538de-2aba-5e2a-94a5-e14de6d9d349	9cab02e5-0bee-5730-8535-dbb0b9abbafb	9c3b140c-4b88-5ed0-a6c0-512cfbd1fcaf	Hoàng Minh Đức	A-G01	2026-09-01	1800000	227400	180000	170000	0	0	0	2377400	2377400	PAID	2026-10-03	2026-10-04 02:00:00+00	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
c1d5561b-21a7-502c-ad3e-ac6bd02b25f2	HD-202610-0005	e21422b0-e128-5e5f-bdef-729af9b5c5c8	894538de-2aba-5e2a-94a5-e14de6d9d349	9cab02e5-0bee-5730-8535-dbb0b9abbafb	9c3b140c-4b88-5ed0-a6c0-512cfbd1fcaf	Hoàng Minh Đức	A-G01	2026-10-01	1800000	239800	195000	170000	0	0	0	2404800	0	PENDING	2026-11-03	\N	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
87565902-6ee3-5e23-8edd-9f28cbd938d1	HD-202608-0006	e21422b0-e128-5e5f-bdef-729af9b5c5c8	44ace439-a6cc-5843-bd5e-0e539011c13e	d85e96a0-be92-51db-a625-9cb21d297df2	dc3cc209-ee2f-5fdf-ba0f-370a4fceea47	Vũ Thị Giang	B101	2026-08-01	2300000	242900	105000	170000	0	0	0	2817900	2817900	PAID	2026-09-03	2026-09-04 02:00:00+00	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
1546f6b3-e036-52d7-9af2-14ac15116479	HD-202609-0006	e21422b0-e128-5e5f-bdef-729af9b5c5c8	44ace439-a6cc-5843-bd5e-0e539011c13e	d85e96a0-be92-51db-a625-9cb21d297df2	dc3cc209-ee2f-5fdf-ba0f-370a4fceea47	Vũ Thị Giang	B101	2026-09-01	2300000	255300	120000	170000	0	0	0	2845300	2845300	PAID	2026-10-03	2026-10-04 02:00:00+00	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
321bc270-397f-5226-a567-fa1b67c85f18	HD-202610-0006	e21422b0-e128-5e5f-bdef-729af9b5c5c8	44ace439-a6cc-5843-bd5e-0e539011c13e	d85e96a0-be92-51db-a625-9cb21d297df2	dc3cc209-ee2f-5fdf-ba0f-370a4fceea47	Vũ Thị Giang	B101	2026-10-01	2300000	267700	135000	170000	0	0	0	2872700	0	PENDING	2026-11-03	\N	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
01abd7c8-4815-5e16-96f3-46ce6dcc2610	HD-202608-0007	e21422b0-e128-5e5f-bdef-729af9b5c5c8	85985dba-e818-5dbb-b36d-ea5dc3408fbb	9d4bdc8a-5d50-5e9c-9a48-e96e8eb2f696	c3d558d4-343b-5ad7-8409-13e3972718c1	Đặng Quang Huy	B102	2026-08-01	2300000	270800	180000	170000	0	200000	0	2720800	2720800	PAID	2026-09-03	2026-09-04 02:00:00+00	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
dddb0ef0-cf55-5151-b08d-9c1882d7ac87	HD-202609-0007	e21422b0-e128-5e5f-bdef-729af9b5c5c8	85985dba-e818-5dbb-b36d-ea5dc3408fbb	9d4bdc8a-5d50-5e9c-9a48-e96e8eb2f696	c3d558d4-343b-5ad7-8409-13e3972718c1	Đặng Quang Huy	B102	2026-09-01	2300000	283200	195000	170000	0	0	0	2948200	0	OVERDUE	2026-10-03	\N	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
b2917d97-14e3-5fc3-9d47-880579dbacbf	HD-202608-0008	e21422b0-e128-5e5f-bdef-729af9b5c5c8	76943dbb-6bff-587b-a373-5404ba4f5f66	cc4699ba-3e26-572b-bbc9-bda010628e6f	e8f4332e-3e5d-529b-8a82-324216778225	Bùi Khánh Linh	B103	2026-08-01	2300000	298700	120000	170000	0	0	0	2888700	2888700	PAID	2026-09-03	2026-09-04 02:00:00+00	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
a67c68f6-36ae-5f8d-b36f-c16cff7a4fdb	HD-202609-0008	e21422b0-e128-5e5f-bdef-729af9b5c5c8	76943dbb-6bff-587b-a373-5404ba4f5f66	cc4699ba-3e26-572b-bbc9-bda010628e6f	e8f4332e-3e5d-529b-8a82-324216778225	Bùi Khánh Linh	B103	2026-09-01	2300000	311100	135000	170000	0	0	0	2916100	2916100	PAID	2026-10-03	2026-10-04 02:00:00+00	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
b8f456fc-1ffb-51e0-812c-5ffc5a3257a5	HD-202610-0008	e21422b0-e128-5e5f-bdef-729af9b5c5c8	76943dbb-6bff-587b-a373-5404ba4f5f66	cc4699ba-3e26-572b-bbc9-bda010628e6f	e8f4332e-3e5d-529b-8a82-324216778225	Bùi Khánh Linh	B103	2026-10-01	2300000	323500	150000	170000	0	0	0	2943500	2943500	PAID	2026-11-03	2026-10-02 01:00:00+00	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
f836e3e0-a315-554f-ae9b-653362147b75	HD-202608-0009	e21422b0-e128-5e5f-bdef-729af9b5c5c8	0b9edd6d-2437-5d93-b5b2-3589f5552a7a	a796ab2f-6f4c-5388-89fe-2b8b65ced493	89477047-a5a1-54f0-ac5a-de83dc53cd83	Đỗ Trung Kiên	B104	2026-08-01	2400000	117500	60000	170000	0	0	0	2747500	2747500	PAID	2026-09-03	2026-09-04 02:00:00+00	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
6f6455f0-3762-5e0a-9aba-652050c0061e	HD-202609-0009	e21422b0-e128-5e5f-bdef-729af9b5c5c8	0b9edd6d-2437-5d93-b5b2-3589f5552a7a	a796ab2f-6f4c-5388-89fe-2b8b65ced493	89477047-a5a1-54f0-ac5a-de83dc53cd83	Đỗ Trung Kiên	B104	2026-09-01	2400000	127500	75000	170000	0	0	0	2772500	2772500	PAID	2026-10-03	2026-10-04 02:00:00+00	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
300c7a83-2837-50a0-8e0d-66096151de25	HD-202610-0009	e21422b0-e128-5e5f-bdef-729af9b5c5c8	0b9edd6d-2437-5d93-b5b2-3589f5552a7a	a796ab2f-6f4c-5388-89fe-2b8b65ced493	89477047-a5a1-54f0-ac5a-de83dc53cd83	Đỗ Trung Kiên	B104	2026-10-01	2400000	137500	90000	170000	0	0	0	2797500	0	PENDING	2026-11-03	\N	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-10 05:41:45.08361+00
9458eec2-1d1b-5629-a80e-c6c5affa8588	HD-202610-0007	e21422b0-e128-5e5f-bdef-729af9b5c5c8	85985dba-e818-5dbb-b36d-ea5dc3408fbb	9d4bdc8a-5d50-5e9c-9a48-e96e8eb2f696	c3d558d4-343b-5ad7-8409-13e3972718c1	Đặng Quang Huy	B102	2026-10-01	2300000	295600	210000	170000	805000	0	0	3780600	100000	PENDING	2026-11-03	\N	t	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-10 05:41:45.08361+00	2026-10-11 12:39:21.376618+00
\.


--
-- Data for Name: invoice_details; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.invoice_details (id, invoice_id, item_type, description, quantity, unit_price, amount, breakdown) FROM stdin;
6c193a77-2aa4-523b-ada0-de2741c0b629	d0dceaf1-e222-58a2-ab71-fd071e0252a8	RENT	Tiền phòng tháng 08/2026	1.00	2500000	2500000	{}
be5aed98-1222-525b-97d8-74e3308e505f	d0dceaf1-e222-58a2-ab71-fd071e0252a8	ELECTRIC	Điện 64 kWh (850 → 914)	64.00	\N	125000	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "14", "amount": "35000"}]}
d0a0ae9b-911f-5eed-82b4-7b29d77b368d	d0dceaf1-e222-58a2-ab71-fd071e0252a8	WATER	Nước 9 m³ (69 → 78)	9.00	\N	135000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "9", "amount": "135000"}]}
d5dced6f-f4a2-5233-ae1f-59a21e523085	d0dceaf1-e222-58a2-ab71-fd071e0252a8	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
a0b0b424-f90b-5663-8174-606f173022cc	d0dceaf1-e222-58a2-ab71-fd071e0252a8	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
c4833f9a-3340-5950-9ec6-9965c4d654ad	d0dceaf1-e222-58a2-ab71-fd071e0252a8	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
531d7ffc-74ed-5f76-bd20-4b2ca4e77f1d	7b32636e-53da-5d2b-ab78-4b187cd017ec	RENT	Tiền phòng tháng 09/2026	1.00	2500000	2500000	{}
d4bdec5a-db8b-545e-8ec2-952cbf694bfe	7b32636e-53da-5d2b-ab78-4b187cd017ec	ELECTRIC	Điện 68 kWh (914 → 982)	68.00	\N	135000	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "18", "amount": "45000"}]}
2bc18821-7984-582a-b12b-1a7e068ab8d2	7b32636e-53da-5d2b-ab78-4b187cd017ec	WATER	Nước 10 m³ (78 → 88)	10.00	\N	150000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "10", "amount": "150000"}]}
51fadee5-094f-5947-8fa9-2a70c7ca3a3a	7b32636e-53da-5d2b-ab78-4b187cd017ec	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
3782cc7f-39b7-534c-9dce-76a58b72d2ce	7b32636e-53da-5d2b-ab78-4b187cd017ec	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
50129c66-1cd6-5d8d-bcaa-df84c3461d07	7b32636e-53da-5d2b-ab78-4b187cd017ec	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
22f144ec-1318-5c90-8f82-d783fc37cb7d	04701513-f296-5f87-b6f1-25100429c690	RENT	Tiền phòng tháng 10/2026	1.00	2500000	2500000	{}
b1e646c4-a609-56f8-a5fe-29f5a83c8de8	04701513-f296-5f87-b6f1-25100429c690	ELECTRIC	Điện 72 kWh (982 → 1054)	72.00	\N	145000	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "22", "amount": "55000"}]}
08300637-851d-5d61-adc0-69e14ad92bc0	04701513-f296-5f87-b6f1-25100429c690	WATER	Nước 11 m³ (88 → 99)	11.00	\N	165000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "11", "amount": "165000"}]}
c3d5c580-03aa-54d8-ba03-a85cdc1ca960	04701513-f296-5f87-b6f1-25100429c690	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
b29fbd90-7771-51f2-82bf-1518fe32bfc2	04701513-f296-5f87-b6f1-25100429c690	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
61f647e2-4122-5058-8831-57d459fc60d2	04701513-f296-5f87-b6f1-25100429c690	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
7423c997-2581-526e-959d-33f3837b3c91	8eb25f8e-1a15-55d6-9763-d4cde719c1b9	RENT	Tiền phòng tháng 08/2026	1.00	2500000	2500000	{}
8a75c0df-cef2-5729-8672-85303b229088	8eb25f8e-1a15-55d6-9763-d4cde719c1b9	ELECTRIC	Điện 73 kWh (900 → 973)	73.00	\N	147500	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "23", "amount": "57500"}]}
796d5d92-a089-54fa-b3e2-d6adbbb5f9ee	8eb25f8e-1a15-55d6-9763-d4cde719c1b9	WATER	Nước 5 m³ (78 → 83)	5.00	\N	75000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "5", "amount": "75000"}]}
a1f71776-2ab9-565e-8d4b-aa657d61cfe1	8eb25f8e-1a15-55d6-9763-d4cde719c1b9	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
01b583dd-3469-51c2-871f-78e613b4f79d	8eb25f8e-1a15-55d6-9763-d4cde719c1b9	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
aeeb33f1-c59e-510b-b3e3-38c96b69f24a	8eb25f8e-1a15-55d6-9763-d4cde719c1b9	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
93d25a58-0c52-53b1-be49-f0a0fa7f8d88	c4b46900-b111-5c8e-9bd2-31a0d06dc717	RENT	Tiền phòng tháng 09/2026	1.00	2500000	2500000	{}
2e1c4c4f-aa73-571f-9140-d18a171e8229	c4b46900-b111-5c8e-9bd2-31a0d06dc717	ELECTRIC	Điện 77 kWh (973 → 1050)	77.00	\N	157500	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "27", "amount": "67500"}]}
46ad3517-d4d4-5114-9dc9-dec42650fe39	c4b46900-b111-5c8e-9bd2-31a0d06dc717	WATER	Nước 6 m³ (83 → 89)	6.00	\N	90000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "6", "amount": "90000"}]}
764eec17-5770-53ab-b77d-783cd47c1349	c4b46900-b111-5c8e-9bd2-31a0d06dc717	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
d273be1f-9e6b-5782-acde-11fd9bcdb376	c4b46900-b111-5c8e-9bd2-31a0d06dc717	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
901709e3-4f11-5f76-b47d-63b0e83bdabc	c4b46900-b111-5c8e-9bd2-31a0d06dc717	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
1e168e60-e1d6-57ff-bbc2-1962fca59d8f	cabe2e80-f9ed-5ce1-a877-da76b17452cc	RENT	Tiền phòng tháng 10/2026	1.00	2500000	2500000	{}
fe339728-2c94-5fa1-8890-825f6a1c1042	cabe2e80-f9ed-5ce1-a877-da76b17452cc	ELECTRIC	Điện 81 kWh (1050 → 1131)	81.00	\N	167500	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "31", "amount": "77500"}]}
3c206cac-528c-54e7-85c7-1f1d8445a7ed	cabe2e80-f9ed-5ce1-a877-da76b17452cc	WATER	Nước 7 m³ (89 → 96)	7.00	\N	105000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "7", "amount": "105000"}]}
134ad399-4432-5a17-b597-f5a47156efce	cabe2e80-f9ed-5ce1-a877-da76b17452cc	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
72a4d715-30fe-53a5-8dcb-e036eba4dd2b	cabe2e80-f9ed-5ce1-a877-da76b17452cc	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
54e18d5d-2e5a-57db-9dbd-886986cd881c	cabe2e80-f9ed-5ce1-a877-da76b17452cc	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
f1a93717-7f0e-59fe-bc40-5a4abde50592	a9d93b21-5d76-5885-8541-fe165bcabb10	RENT	Tiền phòng tháng 08/2026	1.00	2500000	2500000	{}
0743015f-6e2d-5255-902a-4e366878cb84	a9d93b21-5d76-5885-8541-fe165bcabb10	ELECTRIC	Điện 82 kWh (950 → 1032)	82.00	\N	170000	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "32", "amount": "80000"}]}
74eff2fa-649e-5b2f-97a7-40dd62163758	a9d93b21-5d76-5885-8541-fe165bcabb10	WATER	Nước 10 m³ (87 → 97)	10.00	\N	150000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "10", "amount": "150000"}]}
c6223b42-a7e3-5bc1-a001-62efd8073076	a9d93b21-5d76-5885-8541-fe165bcabb10	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
c3e157cb-8761-5fa4-a6fa-27c687ea8297	a9d93b21-5d76-5885-8541-fe165bcabb10	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
b9282d7c-e60a-5c6c-8f6d-4918675d759f	a9d93b21-5d76-5885-8541-fe165bcabb10	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
57166ed8-e8ce-547c-8df4-65ea0d9dcd70	0d38d226-ae84-59dd-8c65-a98748251ca7	RENT	Tiền phòng tháng 09/2026	1.00	2500000	2500000	{}
339780e4-7fdb-5bd6-bfda-a7d3292ff6a4	0d38d226-ae84-59dd-8c65-a98748251ca7	ELECTRIC	Điện 86 kWh (1032 → 1118)	86.00	\N	180000	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "36", "amount": "90000"}]}
aadcc97f-3a4a-565c-9eb5-d429ab698b89	0d38d226-ae84-59dd-8c65-a98748251ca7	WATER	Nước 11 m³ (97 → 108)	11.00	\N	165000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "11", "amount": "165000"}]}
0ca8d0bb-2c4e-503e-84f1-e8678ee1adcb	0d38d226-ae84-59dd-8c65-a98748251ca7	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
fac1f62c-a715-5ef7-99fc-70405d525a55	0d38d226-ae84-59dd-8c65-a98748251ca7	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
ea7a51dd-3a09-5d82-b0ee-44544b6a97f0	0d38d226-ae84-59dd-8c65-a98748251ca7	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
49eae0c4-14a5-5bc1-9cf2-ff706d43d65a	3801fc31-dba2-5e9e-845f-3a26daa6dfff	RENT	Tiền phòng tháng 10/2026	1.00	2500000	2500000	{}
ac363512-c217-5439-b100-23b3ad297179	3801fc31-dba2-5e9e-845f-3a26daa6dfff	ELECTRIC	Điện 90 kWh (1118 → 1208)	90.00	\N	190000	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "40", "amount": "100000"}]}
95852a05-b178-51df-b3f0-44dcdfeb6648	3801fc31-dba2-5e9e-845f-3a26daa6dfff	WATER	Nước 12 m³ (108 → 120)	12.00	\N	180000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "12", "amount": "180000"}]}
798d8beb-3da1-5c9e-9609-40ca7cda4a84	3801fc31-dba2-5e9e-845f-3a26daa6dfff	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
afa90a32-df68-524b-a35d-ac23f582ab3d	3801fc31-dba2-5e9e-845f-3a26daa6dfff	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
c089cda5-42c1-5054-89ec-5a7fc90e3ebe	3801fc31-dba2-5e9e-845f-3a26daa6dfff	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
15e34372-33cf-5f63-b8d8-64a4842f1591	3801fc31-dba2-5e9e-845f-3a26daa6dfff	LATE_FEE	Phí trễ hạn 7 ngày (hóa đơn kỳ 09/2026 chưa thanh toán)	7.00	125000	875000	{"days_late": 7, "rate": "0.05", "cap_days": 30}
c15f5112-c309-5c72-8595-a843d2c9ad9a	9ab312e6-b25d-5b65-b81a-6dfb2c9ba3c6	RENT	Tiền phòng tháng 08/2026	1.00	2800000	2800000	{}
0b2a1543-5a93-5eee-822d-3b40bdeb10fb	9ab312e6-b25d-5b65-b81a-6dfb2c9ba3c6	ELECTRIC	Điện 91 kWh (1000 → 1091)	91.00	\N	192500	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "41", "amount": "102500"}]}
2852fb7f-c608-549d-8d2e-b7648d7ed0a8	9ab312e6-b25d-5b65-b81a-6dfb2c9ba3c6	WATER	Nước 6 m³ (96 → 102)	6.00	\N	90000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "6", "amount": "90000"}]}
7235c491-197b-5e0e-ae81-2190ded6548f	9ab312e6-b25d-5b65-b81a-6dfb2c9ba3c6	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
369d345f-282a-5df6-b31f-0c11b6335792	9ab312e6-b25d-5b65-b81a-6dfb2c9ba3c6	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
74866344-618d-5fcd-9e33-39acb94a7884	9ab312e6-b25d-5b65-b81a-6dfb2c9ba3c6	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
15043b96-2cbd-5399-900a-f714cfba799a	9ab312e6-b25d-5b65-b81a-6dfb2c9ba3c6	DEPOSIT	Trừ tiền cọc	1.00	-500000	-500000	{"deposit_remaining": "2800000"}
bb781a70-a69a-5c5f-8bb0-60d1d16f922d	2fea4294-684b-5590-be89-bcc496707c48	RENT	Tiền phòng tháng 09/2026	1.00	2800000	2800000	{}
c9267316-4dd2-599b-a33c-74683ee2a820	2fea4294-684b-5590-be89-bcc496707c48	ELECTRIC	Điện 95 kWh (1091 → 1186)	95.00	\N	202500	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "45", "amount": "112500"}]}
8f5bce62-dd3e-5580-ad28-73b277aa85c6	2fea4294-684b-5590-be89-bcc496707c48	WATER	Nước 7 m³ (102 → 109)	7.00	\N	105000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "7", "amount": "105000"}]}
716680c2-9648-5452-a41b-cdd7574e21d1	2fea4294-684b-5590-be89-bcc496707c48	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
dcdfc624-14f5-581e-888a-38c63048a007	2fea4294-684b-5590-be89-bcc496707c48	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
a8d288ef-7758-5852-9cbd-039403d4dabd	2fea4294-684b-5590-be89-bcc496707c48	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
3770d481-754c-5901-b89d-c6897438c569	d937406f-e7fb-50d1-88e0-932a7b4c87fe	RENT	Tiền phòng tháng 10/2026	1.00	2800000	2800000	{}
400c9b23-fdfc-50f4-b6e2-283a9489f5fb	d937406f-e7fb-50d1-88e0-932a7b4c87fe	ELECTRIC	Điện 99 kWh (1186 → 1285)	99.00	\N	212500	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "49", "amount": "122500"}]}
aa2b6203-09e4-515a-8cd5-af4bdc677f25	d937406f-e7fb-50d1-88e0-932a7b4c87fe	WATER	Nước 8 m³ (109 → 117)	8.00	\N	120000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "8", "amount": "120000"}]}
a2962d1a-ac0c-53cf-afe1-6781398ef3cd	d937406f-e7fb-50d1-88e0-932a7b4c87fe	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
1163aa07-716a-54a3-a797-530607aa54e0	d937406f-e7fb-50d1-88e0-932a7b4c87fe	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
f31dba62-42ce-511f-abcf-5a4fea918589	d937406f-e7fb-50d1-88e0-932a7b4c87fe	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
4bde1fc7-d3e7-5757-91fc-dd7e6f125dfc	c5b50011-adf2-5065-bf1b-183da9320219	RENT	Tiền phòng tháng 08/2026	1.00	1800000	1800000	{}
2b170cb6-5f55-5e19-8020-f3282f9b009a	c5b50011-adf2-5065-bf1b-183da9320219	ELECTRIC	Điện 100 kWh (1050 → 1150)	100.00	\N	215000	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "50", "amount": "125000"}]}
aa81813c-d55b-5cbe-8013-690aff01bd40	c5b50011-adf2-5065-bf1b-183da9320219	WATER	Nước 11 m³ (105 → 116)	11.00	\N	165000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "11", "amount": "165000"}]}
0c75519d-8a1f-5bd7-96c0-926de354da8c	c5b50011-adf2-5065-bf1b-183da9320219	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
f6ac5a96-fb3b-59af-8987-c762840a4a22	c5b50011-adf2-5065-bf1b-183da9320219	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
d9a07cdd-49de-56ca-a29b-295a07d97898	c5b50011-adf2-5065-bf1b-183da9320219	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
25324c35-fcd1-56a3-8287-852b22d2a3ee	f901279e-cb2b-56ab-9c13-7a8423f4cc77	RENT	Tiền phòng tháng 09/2026	1.00	1800000	1800000	{}
f14996b1-ca7b-5457-bc86-5d093c1fdcce	f901279e-cb2b-56ab-9c13-7a8423f4cc77	ELECTRIC	Điện 104 kWh (1150 → 1254)	104.00	\N	227400	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "50", "amount": "125000"}, {"up_to": "200", "unit_price": "3100", "qty": "4", "amount": "12400"}]}
96984b00-b3ce-5cab-a4ad-f7ebad905fff	f901279e-cb2b-56ab-9c13-7a8423f4cc77	WATER	Nước 12 m³ (116 → 128)	12.00	\N	180000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "12", "amount": "180000"}]}
082ab796-5f6e-5040-bbbe-2de8864a36df	f901279e-cb2b-56ab-9c13-7a8423f4cc77	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
49e99419-6a74-59e7-8ebb-2489e3df6b18	f901279e-cb2b-56ab-9c13-7a8423f4cc77	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
064397e1-756d-54f4-8fd9-0f698391db6b	f901279e-cb2b-56ab-9c13-7a8423f4cc77	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
047aa8ef-85ee-5f78-96ea-edd0ca971867	c1d5561b-21a7-502c-ad3e-ac6bd02b25f2	RENT	Tiền phòng tháng 10/2026	1.00	1800000	1800000	{}
452671c7-9741-5001-a73a-c3f020f1a543	c1d5561b-21a7-502c-ad3e-ac6bd02b25f2	ELECTRIC	Điện 108 kWh (1254 → 1362)	108.00	\N	239800	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "50", "amount": "125000"}, {"up_to": "200", "unit_price": "3100", "qty": "8", "amount": "24800"}]}
e771235e-5847-53bf-b5dd-b4849a83e60f	c1d5561b-21a7-502c-ad3e-ac6bd02b25f2	WATER	Nước 13 m³ (128 → 141)	13.00	\N	195000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "13", "amount": "195000"}]}
d0c8cd6f-04c1-53cb-b685-0de0551f8877	c1d5561b-21a7-502c-ad3e-ac6bd02b25f2	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
1220eb7a-0e05-5fca-b906-6e2f9faef133	c1d5561b-21a7-502c-ad3e-ac6bd02b25f2	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
2aa7d325-22a4-562f-a693-7017aba2c4a5	c1d5561b-21a7-502c-ad3e-ac6bd02b25f2	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
61fbcfea-3e77-522d-8932-893e3283245b	87565902-6ee3-5e23-8edd-9f28cbd938d1	RENT	Tiền phòng tháng 08/2026	1.00	2300000	2300000	{}
ede1c998-69eb-52b7-9fad-474a590178ef	87565902-6ee3-5e23-8edd-9f28cbd938d1	ELECTRIC	Điện 109 kWh (1100 → 1209)	109.00	\N	242900	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "50", "amount": "125000"}, {"up_to": "200", "unit_price": "3100", "qty": "9", "amount": "27900"}]}
0211ca70-7d1b-5ed0-940b-761f3bf1e7d1	87565902-6ee3-5e23-8edd-9f28cbd938d1	WATER	Nước 7 m³ (114 → 121)	7.00	\N	105000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "7", "amount": "105000"}]}
f4bce2e2-c6ae-5e29-ad1a-27475cdc0ce9	87565902-6ee3-5e23-8edd-9f28cbd938d1	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
201ab658-341d-5262-93b1-d3926ee8a71e	87565902-6ee3-5e23-8edd-9f28cbd938d1	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
a9e63c06-87b8-57af-bdc0-2efe70bc5224	87565902-6ee3-5e23-8edd-9f28cbd938d1	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
620ad7d3-5e6a-5fc0-9c9c-78f4891ac475	1546f6b3-e036-52d7-9af2-14ac15116479	RENT	Tiền phòng tháng 09/2026	1.00	2300000	2300000	{}
a12cf422-e55c-55f1-8ebe-a4e66cc2d019	b8f456fc-1ffb-51e0-812c-5ffc5a3257a5	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
5a9dd6cf-7489-557a-9e4c-ea2917cbc256	1546f6b3-e036-52d7-9af2-14ac15116479	ELECTRIC	Điện 113 kWh (1209 → 1322)	113.00	\N	255300	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "50", "amount": "125000"}, {"up_to": "200", "unit_price": "3100", "qty": "13", "amount": "40300"}]}
49af6aa4-5519-5e7a-a0b4-375b7db48b19	1546f6b3-e036-52d7-9af2-14ac15116479	WATER	Nước 8 m³ (121 → 129)	8.00	\N	120000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "8", "amount": "120000"}]}
cf4659a9-5b24-5630-8089-6293873d9adb	1546f6b3-e036-52d7-9af2-14ac15116479	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
cf749b1b-6d8f-5170-86dd-cff3fc840a59	1546f6b3-e036-52d7-9af2-14ac15116479	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
dfbde5d2-0290-57e6-8b70-fa7f7b91e162	1546f6b3-e036-52d7-9af2-14ac15116479	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
1e9b1f9e-4ddb-514d-8c5d-2392e58a852c	321bc270-397f-5226-a567-fa1b67c85f18	RENT	Tiền phòng tháng 10/2026	1.00	2300000	2300000	{}
83befb3b-51b5-565b-8a7c-cd1ac655e9cf	321bc270-397f-5226-a567-fa1b67c85f18	ELECTRIC	Điện 117 kWh (1322 → 1439)	117.00	\N	267700	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "50", "amount": "125000"}, {"up_to": "200", "unit_price": "3100", "qty": "17", "amount": "52700"}]}
d77c9f3b-d6e3-5c76-814e-1a06c28d90f0	321bc270-397f-5226-a567-fa1b67c85f18	WATER	Nước 9 m³ (129 → 138)	9.00	\N	135000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "9", "amount": "135000"}]}
3d85f306-a394-5130-b55d-3503a1db2225	321bc270-397f-5226-a567-fa1b67c85f18	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
df0ddda2-341d-5510-aad1-10c1e0b09424	321bc270-397f-5226-a567-fa1b67c85f18	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
36e9dba0-1ef2-577d-86d9-2ee0e2d08381	321bc270-397f-5226-a567-fa1b67c85f18	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
89d2d8c1-bb3c-5a0d-960d-2f2974ab2790	01abd7c8-4815-5e16-96f3-46ce6dcc2610	RENT	Tiền phòng tháng 08/2026	1.00	2300000	2300000	{}
2f4fe896-0dd9-5e21-b06f-08ce5b76316c	01abd7c8-4815-5e16-96f3-46ce6dcc2610	ELECTRIC	Điện 118 kWh (1150 → 1268)	118.00	\N	270800	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "50", "amount": "125000"}, {"up_to": "200", "unit_price": "3100", "qty": "18", "amount": "55800"}]}
5e5b45ac-5fec-5106-9e7f-25f2a2df62bf	01abd7c8-4815-5e16-96f3-46ce6dcc2610	WATER	Nước 12 m³ (123 → 135)	12.00	\N	180000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "12", "amount": "180000"}]}
8e1a6116-4ef3-5040-a34f-01ca9c0de09e	01abd7c8-4815-5e16-96f3-46ce6dcc2610	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
ecd7187e-bd30-5604-9e87-1eda4a50187c	01abd7c8-4815-5e16-96f3-46ce6dcc2610	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
d685c842-c51c-5298-a1af-09da3884f9f4	01abd7c8-4815-5e16-96f3-46ce6dcc2610	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
a273ee6a-c40c-54ea-9472-e014e546ed0d	01abd7c8-4815-5e16-96f3-46ce6dcc2610	DISCOUNT	Khuyến mãi nhập trọ	1.00	-200000	-200000	{}
7d869730-0458-5044-a17c-adbf00130fb9	dddb0ef0-cf55-5151-b08d-9c1882d7ac87	RENT	Tiền phòng tháng 09/2026	1.00	2300000	2300000	{}
6618ba6a-5855-59ea-be80-952c43c143f3	dddb0ef0-cf55-5151-b08d-9c1882d7ac87	ELECTRIC	Điện 122 kWh (1268 → 1390)	122.00	\N	283200	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "50", "amount": "125000"}, {"up_to": "200", "unit_price": "3100", "qty": "22", "amount": "68200"}]}
8f9a999e-7527-56b0-95aa-164659cc30fd	dddb0ef0-cf55-5151-b08d-9c1882d7ac87	WATER	Nước 13 m³ (135 → 148)	13.00	\N	195000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "13", "amount": "195000"}]}
9076e9c8-65e1-5d01-be0c-522b86b0e9f3	dddb0ef0-cf55-5151-b08d-9c1882d7ac87	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
ed30d918-5ab2-5efd-a99e-cb90f9317038	dddb0ef0-cf55-5151-b08d-9c1882d7ac87	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
6c654ae4-f44e-5354-9c05-1b60b3399d03	dddb0ef0-cf55-5151-b08d-9c1882d7ac87	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
8e1260ea-bb0d-5695-9649-7ce972d3df07	9458eec2-1d1b-5629-a80e-c6c5affa8588	RENT	Tiền phòng tháng 10/2026	1.00	2300000	2300000	{}
67cdfbfe-33e4-5c6e-b73e-2794f8eb4c91	9458eec2-1d1b-5629-a80e-c6c5affa8588	ELECTRIC	Điện 126 kWh (1390 → 1516)	126.00	\N	295600	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "50", "amount": "125000"}, {"up_to": "200", "unit_price": "3100", "qty": "26", "amount": "80600"}]}
d4e3d5f7-6f59-59ad-9dac-809e008380df	9458eec2-1d1b-5629-a80e-c6c5affa8588	WATER	Nước 14 m³ (148 → 162)	14.00	\N	210000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "14", "amount": "210000"}]}
57fcb76d-ad1c-5280-8154-807fbcda4c4d	9458eec2-1d1b-5629-a80e-c6c5affa8588	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
93b1977b-1b02-52f1-89ad-06294c7781de	9458eec2-1d1b-5629-a80e-c6c5affa8588	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
2e2eba8a-5ffb-5e1a-bb5e-5c23065b0412	9458eec2-1d1b-5629-a80e-c6c5affa8588	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
78cdea24-41f8-5dfd-a98f-b8d604c09cdb	9458eec2-1d1b-5629-a80e-c6c5affa8588	LATE_FEE	Phí trễ hạn 7 ngày (hóa đơn kỳ 09/2026 chưa thanh toán)	7.00	115000	805000	{"days_late": 7, "rate": "0.05", "cap_days": 30}
e1ac4967-2a20-5bd2-96e5-30b264fadaee	b2917d97-14e3-5fc3-9d47-880579dbacbf	RENT	Tiền phòng tháng 08/2026	1.00	2300000	2300000	{}
0f7bc5f8-1935-5964-8da5-8e41f977ee39	b2917d97-14e3-5fc3-9d47-880579dbacbf	ELECTRIC	Điện 127 kWh (1200 → 1327)	127.00	\N	298700	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "50", "amount": "125000"}, {"up_to": "200", "unit_price": "3100", "qty": "27", "amount": "83700"}]}
1def26e1-6a6c-555b-acd9-9d2cb35f594b	b2917d97-14e3-5fc3-9d47-880579dbacbf	WATER	Nước 8 m³ (132 → 140)	8.00	\N	120000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "8", "amount": "120000"}]}
9cfa02d6-2492-5aa7-a565-799fa2db5f45	b2917d97-14e3-5fc3-9d47-880579dbacbf	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
27bde3ad-dcd9-5ea3-908c-941a404d03a9	b2917d97-14e3-5fc3-9d47-880579dbacbf	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
77a24f94-8243-5b00-a03c-f271de6ac280	b2917d97-14e3-5fc3-9d47-880579dbacbf	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
df3b8e3f-8ba9-59f2-b3ce-f2148a206fb7	a67c68f6-36ae-5f8d-b36f-c16cff7a4fdb	RENT	Tiền phòng tháng 09/2026	1.00	2300000	2300000	{}
b4790f40-e773-5cca-bdcc-b76416ee3ee7	a67c68f6-36ae-5f8d-b36f-c16cff7a4fdb	ELECTRIC	Điện 131 kWh (1327 → 1458)	131.00	\N	311100	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "50", "amount": "125000"}, {"up_to": "200", "unit_price": "3100", "qty": "31", "amount": "96100"}]}
a0d2e6c2-7379-54b7-aa94-90d5fdffe9e9	a67c68f6-36ae-5f8d-b36f-c16cff7a4fdb	WATER	Nước 9 m³ (140 → 149)	9.00	\N	135000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "9", "amount": "135000"}]}
884b562e-b4a6-5594-8cc5-cc47cc40e540	a67c68f6-36ae-5f8d-b36f-c16cff7a4fdb	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
b8d17f97-c98b-5a1a-a4c2-515632da779e	a67c68f6-36ae-5f8d-b36f-c16cff7a4fdb	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
460ea0b2-762c-5c6b-85df-eec470412384	a67c68f6-36ae-5f8d-b36f-c16cff7a4fdb	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
73a6d654-a34d-5fd8-8fca-259c75ebaa11	b8f456fc-1ffb-51e0-812c-5ffc5a3257a5	RENT	Tiền phòng tháng 10/2026	1.00	2300000	2300000	{}
6f26f873-4aaf-5672-8cfb-2a9e6b191225	b8f456fc-1ffb-51e0-812c-5ffc5a3257a5	ELECTRIC	Điện 135 kWh (1458 → 1593)	135.00	\N	323500	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "50", "amount": "125000"}, {"up_to": "200", "unit_price": "3100", "qty": "35", "amount": "108500"}]}
dd99e81d-4d52-5847-b3e6-3b5986397d62	b8f456fc-1ffb-51e0-812c-5ffc5a3257a5	WATER	Nước 10 m³ (149 → 159)	10.00	\N	150000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "10", "amount": "150000"}]}
cc791ed8-ed05-5d8d-8ae8-3e32f305ca3a	b8f456fc-1ffb-51e0-812c-5ffc5a3257a5	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
6acc752a-050e-5342-817e-5e53687c05c7	b8f456fc-1ffb-51e0-812c-5ffc5a3257a5	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
eec8df48-c760-518d-b6f1-f4be2cb0a12d	f836e3e0-a315-554f-ae9b-653362147b75	RENT	Tiền phòng tháng 08/2026	1.00	2400000	2400000	{}
ffe40d63-9ea6-53eb-ac62-5c1bf401fd2a	f836e3e0-a315-554f-ae9b-653362147b75	ELECTRIC	Điện 61 kWh (1250 → 1311)	61.00	\N	117500	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "11", "amount": "27500"}]}
a2536a14-0bed-5d73-8b39-1c3d3ca5571c	f836e3e0-a315-554f-ae9b-653362147b75	WATER	Nước 4 m³ (141 → 145)	4.00	\N	60000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "4", "amount": "60000"}]}
295d38cf-2624-520b-9d84-3b03aaac6988	f836e3e0-a315-554f-ae9b-653362147b75	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
932da4df-9cdd-50f6-8b89-9a70a5ce2aea	f836e3e0-a315-554f-ae9b-653362147b75	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
4baf77b1-74a4-5bda-bbd3-a8c1a5f4a6c5	f836e3e0-a315-554f-ae9b-653362147b75	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
9c1c7a5a-b60f-51ab-acc8-c863a7d2125b	6f6455f0-3762-5e0a-9aba-652050c0061e	RENT	Tiền phòng tháng 09/2026	1.00	2400000	2400000	{}
a1636fdb-7885-50f1-a283-faa6f1908ca1	6f6455f0-3762-5e0a-9aba-652050c0061e	ELECTRIC	Điện 65 kWh (1311 → 1376)	65.00	\N	127500	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "15", "amount": "37500"}]}
44965af7-03e8-5765-9323-84bc151ee24f	6f6455f0-3762-5e0a-9aba-652050c0061e	WATER	Nước 5 m³ (145 → 150)	5.00	\N	75000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "5", "amount": "75000"}]}
80c526d2-39eb-5ec3-955a-74dc82d52b6c	6f6455f0-3762-5e0a-9aba-652050c0061e	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
ca1aacdc-1b84-5c29-9f4e-66703f58122b	6f6455f0-3762-5e0a-9aba-652050c0061e	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
7cb09628-962a-5b8c-acfd-d420965f64e2	6f6455f0-3762-5e0a-9aba-652050c0061e	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
f7455b06-b71c-590a-971f-76576570d128	300c7a83-2837-50a0-8e0d-66096151de25	RENT	Tiền phòng tháng 10/2026	1.00	2400000	2400000	{}
efb10482-7ff4-5a24-a567-a4789f6cf39c	300c7a83-2837-50a0-8e0d-66096151de25	ELECTRIC	Điện 69 kWh (1376 → 1445)	69.00	\N	137500	{"tiers": [{"up_to": "50", "unit_price": "1800", "qty": "50", "amount": "90000"}, {"up_to": "100", "unit_price": "2500", "qty": "19", "amount": "47500"}]}
9d230eb5-3ddd-534e-b940-04e10b828904	300c7a83-2837-50a0-8e0d-66096151de25	WATER	Nước 6 m³ (150 → 156)	6.00	\N	90000	{"tiers": [{"up_to": "\\u221e", "unit_price": "15000", "qty": "6", "amount": "90000"}]}
ae1688dd-235a-5f63-8395-d9eb3a322928	300c7a83-2837-50a0-8e0d-66096151de25	SERVICE	Internet cáp quang	1.00	100000	100000	{"code": "INTERNET"}
938b7b02-7e2f-534e-9b84-3f38f5bc022e	300c7a83-2837-50a0-8e0d-66096151de25	SERVICE	Vệ sinh chung	1.00	50000	50000	{"code": "CLEANING"}
fd2f3a9f-485e-514c-a05c-3692e9ee6243	300c7a83-2837-50a0-8e0d-66096151de25	SERVICE	Phí thu gom rác	1.00	20000	20000	{"code": "TRASH"}
\.


--
-- Data for Name: meter_readings; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.meter_readings (id, property_id, room_id, utility_type, period, reading_value, previous_value, read_by, read_at, note) FROM stdin;
859a3d6b-46f6-513a-b8c0-20b31e15a092	e21422b0-e128-5e5f-bdef-729af9b5c5c8	065539b2-ee15-5197-83ed-75bf2b95a88d	ELECTRIC	2026-08-01	914.00	850.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-08-05 02:30:00+00	\N
3b759160-7768-564c-a221-0940dfbd3d36	e21422b0-e128-5e5f-bdef-729af9b5c5c8	065539b2-ee15-5197-83ed-75bf2b95a88d	WATER	2026-08-01	78.00	69.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-08-05 02:30:00+00	\N
23a55d09-376e-58d2-bbfb-9d36c2dd1ffb	e21422b0-e128-5e5f-bdef-729af9b5c5c8	065539b2-ee15-5197-83ed-75bf2b95a88d	ELECTRIC	2026-09-01	982.00	914.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-09-05 02:30:00+00	\N
bab57df2-26ef-57a8-9274-a171b26ff915	e21422b0-e128-5e5f-bdef-729af9b5c5c8	065539b2-ee15-5197-83ed-75bf2b95a88d	WATER	2026-09-01	88.00	78.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-09-05 02:30:00+00	\N
759148e0-bd0e-5b92-9c04-67438c0750ca	e21422b0-e128-5e5f-bdef-729af9b5c5c8	065539b2-ee15-5197-83ed-75bf2b95a88d	ELECTRIC	2026-10-01	1054.00	982.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-10-05 02:30:00+00	\N
91baa6c0-3fe7-5e66-9b61-89196ef619ab	e21422b0-e128-5e5f-bdef-729af9b5c5c8	065539b2-ee15-5197-83ed-75bf2b95a88d	WATER	2026-10-01	99.00	88.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-10-05 02:30:00+00	\N
e851cddd-612d-5c22-ad3a-32cd9eccb68d	e21422b0-e128-5e5f-bdef-729af9b5c5c8	d9df3051-e29c-5447-9295-64a6ae6cbaf7	ELECTRIC	2026-08-01	973.00	900.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-08-05 02:30:00+00	\N
2b5d1ce1-c53d-5b9b-a234-4775ee2879d7	e21422b0-e128-5e5f-bdef-729af9b5c5c8	d9df3051-e29c-5447-9295-64a6ae6cbaf7	WATER	2026-08-01	83.00	78.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-08-05 02:30:00+00	\N
2318fbb2-02c0-5f50-ae81-3ac6ea915564	e21422b0-e128-5e5f-bdef-729af9b5c5c8	d9df3051-e29c-5447-9295-64a6ae6cbaf7	ELECTRIC	2026-09-01	1050.00	973.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-09-05 02:30:00+00	\N
5a409289-a1bd-5152-8622-f9951174b6b9	e21422b0-e128-5e5f-bdef-729af9b5c5c8	d9df3051-e29c-5447-9295-64a6ae6cbaf7	WATER	2026-09-01	89.00	83.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-09-05 02:30:00+00	\N
201716a0-864d-5eba-bb45-029e1eec0cb6	e21422b0-e128-5e5f-bdef-729af9b5c5c8	d9df3051-e29c-5447-9295-64a6ae6cbaf7	ELECTRIC	2026-10-01	1131.00	1050.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-10-05 02:30:00+00	\N
f6cc35a8-fe21-5b74-b668-492cb92bb854	e21422b0-e128-5e5f-bdef-729af9b5c5c8	d9df3051-e29c-5447-9295-64a6ae6cbaf7	WATER	2026-10-01	96.00	89.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-10-05 02:30:00+00	\N
42534db1-9f46-516f-bc2e-14afa0d65231	e21422b0-e128-5e5f-bdef-729af9b5c5c8	85cb0b69-b128-5e24-a7f4-0abd4ad91366	ELECTRIC	2026-08-01	1032.00	950.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-08-05 02:30:00+00	\N
43bc85ca-45eb-53d5-8a24-3ffe5bfdf0b6	e21422b0-e128-5e5f-bdef-729af9b5c5c8	85cb0b69-b128-5e24-a7f4-0abd4ad91366	WATER	2026-08-01	97.00	87.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-08-05 02:30:00+00	\N
a6b4e90b-79f8-5c06-bf14-5ec8c6270c19	e21422b0-e128-5e5f-bdef-729af9b5c5c8	85cb0b69-b128-5e24-a7f4-0abd4ad91366	ELECTRIC	2026-09-01	1118.00	1032.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-09-05 02:30:00+00	\N
f8fa620f-0845-5970-ab7d-0a3c92c278af	e21422b0-e128-5e5f-bdef-729af9b5c5c8	85cb0b69-b128-5e24-a7f4-0abd4ad91366	WATER	2026-09-01	108.00	97.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-09-05 02:30:00+00	\N
ebbb1715-2450-5654-b370-e35ec18697d7	e21422b0-e128-5e5f-bdef-729af9b5c5c8	85cb0b69-b128-5e24-a7f4-0abd4ad91366	ELECTRIC	2026-10-01	1208.00	1118.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-10-05 02:30:00+00	\N
d51173ac-006b-5a44-b20c-881bc309b922	e21422b0-e128-5e5f-bdef-729af9b5c5c8	85cb0b69-b128-5e24-a7f4-0abd4ad91366	WATER	2026-10-01	120.00	108.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-10-05 02:30:00+00	\N
9d60cbf8-d9ee-5e02-b790-07600ed41bb7	e21422b0-e128-5e5f-bdef-729af9b5c5c8	5d6ec118-a073-5ed6-b3e7-9f53f9944a8b	ELECTRIC	2026-08-01	1091.00	1000.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-08-05 02:30:00+00	\N
0d3c2685-d988-5cd9-95d5-6f11eddec759	e21422b0-e128-5e5f-bdef-729af9b5c5c8	5d6ec118-a073-5ed6-b3e7-9f53f9944a8b	WATER	2026-08-01	102.00	96.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-08-05 02:30:00+00	\N
5570ffc6-a96a-5495-a209-db56185576ab	e21422b0-e128-5e5f-bdef-729af9b5c5c8	5d6ec118-a073-5ed6-b3e7-9f53f9944a8b	ELECTRIC	2026-09-01	1186.00	1091.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-09-05 02:30:00+00	\N
9c846d01-f884-5002-b3d0-b016fef6e5cf	e21422b0-e128-5e5f-bdef-729af9b5c5c8	5d6ec118-a073-5ed6-b3e7-9f53f9944a8b	WATER	2026-09-01	109.00	102.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-09-05 02:30:00+00	\N
539e45b8-47de-5468-8896-221ff2b7c0fd	e21422b0-e128-5e5f-bdef-729af9b5c5c8	5d6ec118-a073-5ed6-b3e7-9f53f9944a8b	ELECTRIC	2026-10-01	1285.00	1186.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-10-05 02:30:00+00	\N
77c32642-ee33-5ff9-a042-25eb549d144b	e21422b0-e128-5e5f-bdef-729af9b5c5c8	5d6ec118-a073-5ed6-b3e7-9f53f9944a8b	WATER	2026-10-01	117.00	109.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-10-05 02:30:00+00	\N
fa430770-ecfb-509c-a9eb-2893b269cd82	e21422b0-e128-5e5f-bdef-729af9b5c5c8	9cab02e5-0bee-5730-8535-dbb0b9abbafb	ELECTRIC	2026-08-01	1150.00	1050.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-08-05 02:30:00+00	\N
3d6f29f7-811f-50e5-8aec-06ce7154c3ea	e21422b0-e128-5e5f-bdef-729af9b5c5c8	9cab02e5-0bee-5730-8535-dbb0b9abbafb	WATER	2026-08-01	116.00	105.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-08-05 02:30:00+00	\N
7d2583b6-1624-50b8-965c-e6d855c5a8ce	e21422b0-e128-5e5f-bdef-729af9b5c5c8	9cab02e5-0bee-5730-8535-dbb0b9abbafb	ELECTRIC	2026-09-01	1254.00	1150.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-09-05 02:30:00+00	\N
18db11c8-46c4-5d75-85e5-aa6bbb00bb44	e21422b0-e128-5e5f-bdef-729af9b5c5c8	9cab02e5-0bee-5730-8535-dbb0b9abbafb	WATER	2026-09-01	128.00	116.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-09-05 02:30:00+00	\N
7e1d7fa3-5608-58c3-a143-d3a48cc6c0cf	e21422b0-e128-5e5f-bdef-729af9b5c5c8	9cab02e5-0bee-5730-8535-dbb0b9abbafb	ELECTRIC	2026-10-01	1362.00	1254.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-10-05 02:30:00+00	\N
a2981819-d931-558e-8fa6-0a7dd8acda68	e21422b0-e128-5e5f-bdef-729af9b5c5c8	9cab02e5-0bee-5730-8535-dbb0b9abbafb	WATER	2026-10-01	141.00	128.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-10-05 02:30:00+00	\N
54f9dd74-e87d-5f3d-8e8c-41f80b22ca5e	e21422b0-e128-5e5f-bdef-729af9b5c5c8	d85e96a0-be92-51db-a625-9cb21d297df2	ELECTRIC	2026-08-01	1209.00	1100.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-08-05 02:30:00+00	\N
0140649f-be19-5932-b390-68fe5d6bea1a	e21422b0-e128-5e5f-bdef-729af9b5c5c8	d85e96a0-be92-51db-a625-9cb21d297df2	WATER	2026-08-01	121.00	114.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-08-05 02:30:00+00	\N
2f7eb9e9-93db-5a93-8f72-e8d4421ed6de	e21422b0-e128-5e5f-bdef-729af9b5c5c8	d85e96a0-be92-51db-a625-9cb21d297df2	ELECTRIC	2026-09-01	1322.00	1209.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-09-05 02:30:00+00	\N
f51a9fa9-b40b-58be-9347-e4a74b3f5c90	e21422b0-e128-5e5f-bdef-729af9b5c5c8	d85e96a0-be92-51db-a625-9cb21d297df2	WATER	2026-09-01	129.00	121.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-09-05 02:30:00+00	\N
2ec2de25-e3c4-5d7a-987e-fb2fd12e2658	e21422b0-e128-5e5f-bdef-729af9b5c5c8	d85e96a0-be92-51db-a625-9cb21d297df2	ELECTRIC	2026-10-01	1439.00	1322.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-10-05 02:30:00+00	\N
af262b75-4dbd-534c-b6de-ee5a1cd93e42	e21422b0-e128-5e5f-bdef-729af9b5c5c8	d85e96a0-be92-51db-a625-9cb21d297df2	WATER	2026-10-01	138.00	129.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-10-05 02:30:00+00	\N
63eba958-7e0a-567a-93f9-80b36545a625	e21422b0-e128-5e5f-bdef-729af9b5c5c8	9d4bdc8a-5d50-5e9c-9a48-e96e8eb2f696	ELECTRIC	2026-08-01	1268.00	1150.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-08-05 02:30:00+00	\N
f9299bf7-5bba-5a84-8c79-3f21ccee45b2	e21422b0-e128-5e5f-bdef-729af9b5c5c8	9d4bdc8a-5d50-5e9c-9a48-e96e8eb2f696	WATER	2026-08-01	135.00	123.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-08-05 02:30:00+00	\N
e66cddc3-698d-50cb-81d1-63808a8a5efa	e21422b0-e128-5e5f-bdef-729af9b5c5c8	9d4bdc8a-5d50-5e9c-9a48-e96e8eb2f696	ELECTRIC	2026-09-01	1390.00	1268.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-09-05 02:30:00+00	\N
ed362301-3d3c-55b1-a371-3981f5d708a5	e21422b0-e128-5e5f-bdef-729af9b5c5c8	9d4bdc8a-5d50-5e9c-9a48-e96e8eb2f696	WATER	2026-09-01	148.00	135.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-09-05 02:30:00+00	\N
18f568b5-fe02-5791-8400-d4b4fdd028e6	e21422b0-e128-5e5f-bdef-729af9b5c5c8	9d4bdc8a-5d50-5e9c-9a48-e96e8eb2f696	ELECTRIC	2026-10-01	1516.00	1390.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-10-05 02:30:00+00	\N
bb32f578-2dbc-5ff6-bad3-e8a4deb9fcb6	e21422b0-e128-5e5f-bdef-729af9b5c5c8	9d4bdc8a-5d50-5e9c-9a48-e96e8eb2f696	WATER	2026-10-01	162.00	148.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-10-05 02:30:00+00	\N
a9046b1b-2ecb-5436-b270-bb24217790eb	e21422b0-e128-5e5f-bdef-729af9b5c5c8	cc4699ba-3e26-572b-bbc9-bda010628e6f	ELECTRIC	2026-08-01	1327.00	1200.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-08-05 02:30:00+00	\N
b5177fda-4b4c-5026-97c3-18ec744d31bc	e21422b0-e128-5e5f-bdef-729af9b5c5c8	cc4699ba-3e26-572b-bbc9-bda010628e6f	WATER	2026-08-01	140.00	132.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-08-05 02:30:00+00	\N
f233c67f-8bdf-5f89-ad7a-f55174d33766	e21422b0-e128-5e5f-bdef-729af9b5c5c8	cc4699ba-3e26-572b-bbc9-bda010628e6f	ELECTRIC	2026-09-01	1458.00	1327.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-09-05 02:30:00+00	\N
8b6d24f5-d08f-5004-9f1a-938577c5e861	e21422b0-e128-5e5f-bdef-729af9b5c5c8	cc4699ba-3e26-572b-bbc9-bda010628e6f	WATER	2026-09-01	149.00	140.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-09-05 02:30:00+00	\N
aeff66ca-b9d0-547a-9c82-586621903d1c	e21422b0-e128-5e5f-bdef-729af9b5c5c8	cc4699ba-3e26-572b-bbc9-bda010628e6f	ELECTRIC	2026-10-01	1593.00	1458.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-10-05 02:30:00+00	\N
8167ba96-748c-5ac6-b710-e5b94c0bda33	e21422b0-e128-5e5f-bdef-729af9b5c5c8	cc4699ba-3e26-572b-bbc9-bda010628e6f	WATER	2026-10-01	159.00	149.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-10-05 02:30:00+00	\N
f186e71d-ac4e-553f-aa92-989ebebec3d0	e21422b0-e128-5e5f-bdef-729af9b5c5c8	a796ab2f-6f4c-5388-89fe-2b8b65ced493	ELECTRIC	2026-08-01	1311.00	1250.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-08-05 02:30:00+00	\N
8e0876d3-2775-5594-97e5-91401ebaec54	e21422b0-e128-5e5f-bdef-729af9b5c5c8	a796ab2f-6f4c-5388-89fe-2b8b65ced493	WATER	2026-08-01	145.00	141.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-08-05 02:30:00+00	\N
415f812e-b990-5edb-b095-5c46fc88348f	e21422b0-e128-5e5f-bdef-729af9b5c5c8	a796ab2f-6f4c-5388-89fe-2b8b65ced493	ELECTRIC	2026-09-01	1376.00	1311.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-09-05 02:30:00+00	\N
69fc9258-0996-5445-9d0e-57686fa0f3a2	e21422b0-e128-5e5f-bdef-729af9b5c5c8	a796ab2f-6f4c-5388-89fe-2b8b65ced493	WATER	2026-09-01	150.00	145.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-09-05 02:30:00+00	\N
2599a85a-d356-54ca-93b9-0f9438c2deea	e21422b0-e128-5e5f-bdef-729af9b5c5c8	a796ab2f-6f4c-5388-89fe-2b8b65ced493	ELECTRIC	2026-10-01	1445.00	1376.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-10-05 02:30:00+00	\N
3360bd2f-1d87-5a62-b833-595646977451	e21422b0-e128-5e5f-bdef-729af9b5c5c8	a796ab2f-6f4c-5388-89fe-2b8b65ced493	WATER	2026-10-01	156.00	150.00	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-10-05 02:30:00+00	\N
\.


--
-- Data for Name: outbox; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.outbox (id, event_type, payload, aggregate_type, aggregate_id, correlation_id, schema_version, status, attempts, created_at, published_at, last_error) FROM stdin;
4212075f-bf5c-403e-924a-0319e359751a	payment.received	{"data": {"amount": "100000", "method": "CASH", "room_id": "9d4bdc8a-5d50-5e9c-9a48-e96e8eb2f696", "entity_id": "f1b442e0-bed9-4e39-a768-0af6a6b78bea", "tenant_id": "c3d558d4-343b-5ad7-8409-13e3972718c1", "invoice_id": "9458eec2-1d1b-5629-a80e-c6c5affa8588", "invoice_no": "HD-202610-0007", "payment_id": "f1b442e0-bed9-4e39-a768-0af6a6b78bea", "contract_id": "85985dba-e818-5dbb-b36d-ea5dc3408fbb", "entity_type": "payment", "property_id": "e21422b0-e128-5e5f-bdef-729af9b5c5c8", "tenant_name": "Đặng Quang Huy", "invoice_paid": false}, "event_id": "4212075f-bf5c-403e-924a-0319e359751a", "producer": "billing-service", "event_type": "payment.received", "occurred_at": "2026-10-11T12:39:21.428645+00:00", "causation_id": null, "correlation_id": null, "schema_version": 1}	payment	f1b442e0-bed9-4e39-a768-0af6a6b78bea	\N	1	PUBLISHED	0	2026-10-11 12:39:21.376618+00	2026-10-11 12:39:22.565885+00	\N
\.


--
-- Data for Name: payments; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.payments (id, invoice_id, amount, method, reference, receipt_no, received_by, received_at, note) FROM stdin;
a61ed7fa-2d0f-56d6-9ea5-e28e062532ff	d0dceaf1-e222-58a2-ab71-fd071e0252a8	2930000	BANK_TRANSFER	\N	PT-202608-01	0593a5e9-2ac1-52af-897c-8060f6258317	2026-09-04 02:00:00+00	\N
9450c3e3-8eae-5617-96d8-131409573e09	7b32636e-53da-5d2b-ab78-4b187cd017ec	2955000	MOMO	\N	PT-202609-01	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-10-04 02:00:00+00	\N
07d66f74-2b8c-5020-8550-186a614b3f1a	8eb25f8e-1a15-55d6-9763-d4cde719c1b9	2892500	MOMO	\N	PT-202608-02	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-09-04 02:00:00+00	\N
40d01b37-ad59-59cf-bb62-1c0457ac6d8d	c4b46900-b111-5c8e-9bd2-31a0d06dc717	2917500	CASH	\N	PT-202609-02	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-04 02:00:00+00	\N
4757c779-62ff-5126-b28e-af1c9ab632b8	a9d93b21-5d76-5885-8541-fe165bcabb10	2990000	CASH	\N	PT-202608-03	0593a5e9-2ac1-52af-897c-8060f6258317	2026-09-04 02:00:00+00	\N
106ecf2b-dc8d-5755-898b-db3e4a71b62d	9ab312e6-b25d-5b65-b81a-6dfb2c9ba3c6	2752500	BANK_TRANSFER	\N	PT-202608-04	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-09-04 02:00:00+00	\N
7034cf6b-638b-5ac3-b8ea-7095b423b914	2fea4294-684b-5590-be89-bcc496707c48	3277500	MOMO	\N	PT-202609-04	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-04 02:00:00+00	\N
65d34858-5b39-5c7a-98a7-4023d109f98f	c5b50011-adf2-5065-bf1b-183da9320219	2350000	MOMO	\N	PT-202608-05	0593a5e9-2ac1-52af-897c-8060f6258317	2026-09-04 02:00:00+00	\N
eaebbe92-ec2c-571c-9891-d4e5c5f3745c	f901279e-cb2b-56ab-9c13-7a8423f4cc77	2377400	CASH	\N	PT-202609-05	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-10-04 02:00:00+00	\N
360a0395-fdeb-51c6-8224-a49381aaa7db	87565902-6ee3-5e23-8edd-9f28cbd938d1	2817900	CASH	\N	PT-202608-06	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-09-04 02:00:00+00	\N
2016a83a-2f93-5ada-9645-f5300788882c	1546f6b3-e036-52d7-9af2-14ac15116479	2845300	BANK_TRANSFER	\N	PT-202609-06	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-04 02:00:00+00	\N
4a94a610-164d-5398-a04e-6751ecaa7a59	01abd7c8-4815-5e16-96f3-46ce6dcc2610	2720800	BANK_TRANSFER	\N	PT-202608-07	0593a5e9-2ac1-52af-897c-8060f6258317	2026-09-04 02:00:00+00	\N
ad007aba-03c6-50f3-9295-bad8f66d5150	b2917d97-14e3-5fc3-9d47-880579dbacbf	2888700	MOMO	\N	PT-202608-08	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-09-04 02:00:00+00	\N
a9b62d52-0606-5ae9-a72a-bd2d627b5e2e	a67c68f6-36ae-5f8d-b36f-c16cff7a4fdb	2916100	CASH	\N	PT-202609-08	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-04 02:00:00+00	\N
08763a52-7b95-5d7e-9e02-f2f4ae69b290	b8f456fc-1ffb-51e0-812c-5ffc5a3257a5	2943500	BANK_TRANSFER	\N	PT-202610-08	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-10-02 01:00:00+00	\N
165aad24-5a69-5de9-94c9-7ef59f06dd3f	f836e3e0-a315-554f-ae9b-653362147b75	2747500	CASH	\N	PT-202608-09	0593a5e9-2ac1-52af-897c-8060f6258317	2026-09-04 02:00:00+00	\N
4b6db00d-878c-51ce-98e4-8018395aaecf	6f6455f0-3762-5e0a-9aba-652050c0061e	2772500	BANK_TRANSFER	\N	PT-202609-09	398a2def-31c1-5af4-ba43-594e33d4db9b	2026-10-04 02:00:00+00	\N
f1b442e0-bed9-4e39-a768-0af6a6b78bea	9458eec2-1d1b-5629-a80e-c6c5affa8588	100000	CASH	\N	\N	0593a5e9-2ac1-52af-897c-8060f6258317	2026-10-11 12:39:21.376618+00	\N
\.


--
-- Data for Name: price_tiers; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.price_tiers (id, property_id, utility_type, tier_index, up_to_qty, unit_price, effective_from, effective_to, created_at) FROM stdin;
a68c2857-f6d8-5143-8079-4d1e797d8901	e21422b0-e128-5e5f-bdef-729af9b5c5c8	ELECTRIC	1	50.00	1800	2026-05-01	\N	2026-10-10 05:41:45.08361+00
ec95d7c3-32d6-56ef-aff2-d574df531ac4	e21422b0-e128-5e5f-bdef-729af9b5c5c8	ELECTRIC	2	100.00	2500	2026-05-01	\N	2026-10-10 05:41:45.08361+00
7b939167-2b57-51df-a469-8c76f7946628	e21422b0-e128-5e5f-bdef-729af9b5c5c8	ELECTRIC	3	200.00	3100	2026-05-01	\N	2026-10-10 05:41:45.08361+00
9300d348-5b43-5bb0-81d4-67b3372a84d7	e21422b0-e128-5e5f-bdef-729af9b5c5c8	ELECTRIC	4	\N	3500	2026-05-01	\N	2026-10-10 05:41:45.08361+00
abd861cf-649b-5970-850b-17ae5bf3013e	e21422b0-e128-5e5f-bdef-729af9b5c5c8	WATER	1	\N	15000	2026-05-01	\N	2026-10-10 05:41:45.08361+00
\.


--
-- Data for Name: processed_events; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.processed_events (event_id, event_type, consumer, processed_at) FROM stdin;
\.


--
-- Data for Name: service_fees; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.service_fees (id, property_id, code, name, amount, is_mandatory, is_active, created_at) FROM stdin;
fa252f24-22ae-5c28-be97-5b97f8b95e8a	e21422b0-e128-5e5f-bdef-729af9b5c5c8	INTERNET	Internet cáp quang	100000	t	t	2026-10-10 05:41:45.08361+00
4e7fef96-b487-52c0-9bb4-cc4e043d0e54	e21422b0-e128-5e5f-bdef-729af9b5c5c8	CLEANING	Vệ sinh chung	50000	t	t	2026-10-10 05:41:45.08361+00
e35ff109-aa20-5129-81fc-bc8d809a65e7	e21422b0-e128-5e5f-bdef-729af9b5c5c8	TRASH	Phí thu gom rác	20000	t	t	2026-10-10 05:41:45.08361+00
91e5911d-53d9-5215-b518-d36aaf57cfbb	e21422b0-e128-5e5f-bdef-729af9b5c5c8	PARKING	Gửi xe máy	100000	f	t	2026-10-10 05:41:45.08361+00
\.


--
-- PostgreSQL database dump complete
--

\unrestrict 8jJHmU9P3yqsaqcz2qrKHdY8Go6qYbxvszSIemKBaiYhG4aAl44bTPN8kf5a6Kp

