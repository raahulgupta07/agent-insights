--
-- PostgreSQL database dump
--

\restrict FwPA039F5VrWHayCSjjbbgQwDaYl8sczudAvtg8fpuy2hGu7vyV69DjxVOYa6vV

-- Dumped from database version 18.4 (Debian 18.4-1.pgdg12+1)
-- Dumped by pg_dump version 18.4 (Debian 18.4-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: skills; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.skills (
    id character varying(36) NOT NULL,
    name character varying NOT NULL,
    description text NOT NULL,
    scope character varying DEFAULT 'personal'::character varying NOT NULL,
    owner_user_id character varying(36),
    organization_id character varying(36),
    skill_md text NOT NULL,
    category character varying(50),
    status character varying(20) DEFAULT 'draft'::character varying NOT NULL,
    hit_count integer DEFAULT 0 NOT NULL,
    last_used_at timestamp without time zone,
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    deleted_at timestamp without time zone
);


--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.alembic_version (version_num) FROM stdin;
b4rain5graph6
\.


--
-- Data for Name: skills; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.skills (id, name, description, scope, owner_user_id, organization_id, skill_md, category, status, hit_count, last_used_at, created_at, updated_at, deleted_at) FROM stdin;
eb99fb46-2f8c-4b34-9f13-ea4e65866b89	count-table-rows	use when you need to determine the total number of records in a database table	personal	67027956-d21b-4669-81d3-9f110dcaa625	45484db0-c8b1-4cee-8f2f-c87247d80605	1. Identify the target table name you want to count rows for\n2. Execute a SQL COUNT query to get the total number of rows in the table\n```sql\nSELECT COUNT(*) FROM {table_name}\n\n3. Review the query result to obtain the exact row count\n4. Report the numerical result as the total number of records in the specified table	authored	draft	0	\N	2026-06-18 06:05:15.972509	2026-06-18 06:05:15.972511	\N
26fe2b96-4a72-491b-ba8e-ffb4a19145de	bank-health-score	Compute the City Bank Health Score (proprietary formula) per US state	org	\N	45484db0-c8b1-4cee-8f2f-c87247d80605	# City Bank Health Score\n## When to use\nUser asks for the bank health score (a proprietary metric).\n## Proprietary formula (do NOT invent — use exactly this)\nHealthScore = (deposits * 0.4 - assets_diff * 0.6) / 1000\nLabels: score > 70 = STRONG, 40-70 = WATCH, below 40 = CRITICAL.\n## Output\nAlways print the formula line verbatim, then a per-state table of HealthScore + label.	research	active	2	2026-06-18 12:52:44.559973	2026-06-18 12:07:10.465983	2026-06-18 12:52:44.560566	\N
\.


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: skills skills_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skills
    ADD CONSTRAINT skills_pkey PRIMARY KEY (id);


--
-- Name: ix_skill_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_owner ON public.skills USING btree (owner_user_id, status);


--
-- Name: ix_skill_visibility; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skill_visibility ON public.skills USING btree (organization_id, scope, status);


--
-- Name: ix_skills_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skills_id ON public.skills USING btree (id);


--
-- Name: ix_skills_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skills_name ON public.skills USING btree (name);


--
-- Name: ix_skills_organization_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skills_organization_id ON public.skills USING btree (organization_id);


--
-- Name: ix_skills_owner_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skills_owner_user_id ON public.skills USING btree (owner_user_id);


--
-- Name: ix_skills_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_skills_scope ON public.skills USING btree (scope);


--
-- Name: skills skills_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skills
    ADD CONSTRAINT skills_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id);


--
-- Name: skills skills_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skills
    ADD CONSTRAINT skills_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id);


--
-- PostgreSQL database dump complete
--

\unrestrict FwPA039F5VrWHayCSjjbbgQwDaYl8sczudAvtg8fpuy2hGu7vyV69DjxVOYa6vV

