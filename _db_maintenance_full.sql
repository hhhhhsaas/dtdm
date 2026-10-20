--
-- PostgreSQL database dump
--

\restrict Sr1HROZ9BHsEkk60zH8XFkvevCH9ZiCHuTAEpibSzGOzfCeMNnfmvHEhy6W02Ib

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
-- Data for Name: incidents; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.incidents (id, ticket_no, property_id, room_id, reported_by_tenant_id, reported_by_user_id, reported_by_name, reported_by_phone, category, priority, title, description, photos, status, assigned_to, assigned_to_name, assigned_at, started_at, resolved_at, closed_at, resolution, cost, rating, rating_comment, created_at, updated_at, deleted_at) FROM stdin;
\.


--
-- Data for Name: maintenance_schedules; Type: TABLE DATA; Schema: public; Owner: qlpt
--

COPY public.maintenance_schedules (id, property_id, scope, target_id, title, task_template, frequency, next_due_date, anchor_day, last_done_at, times_completed, notify_tenants, note, is_active, created_at, updated_at, deleted_at) FROM stdin;
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
28621bbf-2f5e-4148-a88c-4d70a95375e5	room.status_changed	maintenance-service:room-events	2026-10-11 12:20:53.266391+00
ffbbe97a-619b-43a5-ad06-665340f56c76	room.status_changed	maintenance-service:room-events	2026-10-11 12:20:58.290974+00
\.


--
-- PostgreSQL database dump complete
--

\unrestrict Sr1HROZ9BHsEkk60zH8XFkvevCH9ZiCHuTAEpibSzGOzfCeMNnfmvHEhy6W02Ib

