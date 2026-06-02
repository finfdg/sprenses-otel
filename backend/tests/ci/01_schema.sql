--
-- PostgreSQL database dump
--

\restrict JCfJ9egWWkp4mORgUo9YnuytLbY9OrfoohlXFVSzkRVqIxlemVbphkeD2YW9LPu

-- Dumped from database version 15.16
-- Dumped by pg_dump version 15.16

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
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- *not* creating schema, since initdb creates it


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS '';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: advances; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.advances (
    id integer NOT NULL,
    agency_name character varying(200) NOT NULL,
    amount numeric(15,2) NOT NULL,
    currency character varying(5) NOT NULL,
    advance_date date NOT NULL,
    status character varying(20) NOT NULL,
    notes text,
    bank_transaction_id integer,
    received_date date,
    received_amount numeric(15,2),
    created_by integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: advances_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.advances_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: advances_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.advances_id_seq OWNED BY public.advances.id;


--
-- Name: agency_groups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agency_groups (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    members json DEFAULT '[]'::json NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: agency_groups_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agency_groups_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agency_groups_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agency_groups_id_seq OWNED BY public.agency_groups.id;


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: approval_request_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval_request_logs (
    id integer NOT NULL,
    request_id integer NOT NULL,
    step_number smallint NOT NULL,
    action character varying(20) NOT NULL,
    actor_id integer,
    note text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: approval_request_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.approval_request_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: approval_request_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.approval_request_logs_id_seq OWNED BY public.approval_request_logs.id;


--
-- Name: approval_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval_requests (
    id integer NOT NULL,
    workflow_id integer,
    entity_type character varying(50) NOT NULL,
    entity_id integer NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    current_step smallint DEFAULT 1 NOT NULL,
    total_steps smallint DEFAULT 1 NOT NULL,
    requested_by integer,
    requested_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone,
    completed_by integer,
    module_code character varying(50),
    action_type character varying(10),
    payload_json text
);


--
-- Name: approval_requests_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.approval_requests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: approval_requests_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.approval_requests_id_seq OWNED BY public.approval_requests.id;


--
-- Name: approval_workflow_approver_roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval_workflow_approver_roles (
    id integer NOT NULL,
    workflow_id integer NOT NULL,
    role_id integer NOT NULL
);


--
-- Name: approval_workflow_approver_roles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.approval_workflow_approver_roles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: approval_workflow_approver_roles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.approval_workflow_approver_roles_id_seq OWNED BY public.approval_workflow_approver_roles.id;


--
-- Name: approval_workflow_requestor_roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval_workflow_requestor_roles (
    id integer NOT NULL,
    workflow_id integer NOT NULL,
    role_id integer NOT NULL
);


--
-- Name: approval_workflow_requestor_roles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.approval_workflow_requestor_roles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: approval_workflow_requestor_roles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.approval_workflow_requestor_roles_id_seq OWNED BY public.approval_workflow_requestor_roles.id;


--
-- Name: approval_workflow_steps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval_workflow_steps (
    id integer NOT NULL,
    workflow_id integer NOT NULL,
    step_number smallint NOT NULL,
    approver_type character varying(20) NOT NULL,
    approver_user_id integer,
    approver_role_id integer,
    approver_dept_id integer,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: approval_workflow_steps_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.approval_workflow_steps_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: approval_workflow_steps_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.approval_workflow_steps_id_seq OWNED BY public.approval_workflow_steps.id;


--
-- Name: approval_workflows; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval_workflows (
    id integer NOT NULL,
    name character varying(200) NOT NULL,
    entity_type character varying(50),
    description text,
    is_active boolean DEFAULT true NOT NULL,
    conditions_json text,
    created_by integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    module_id integer
);


--
-- Name: approval_workflows_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.approval_workflows_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: approval_workflows_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.approval_workflows_id_seq OWNED BY public.approval_workflows.id;


--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_logs (
    id integer NOT NULL,
    user_id integer,
    action character varying(50) NOT NULL,
    entity_type character varying(50) NOT NULL,
    entity_id integer,
    details text,
    ip_address character varying(50),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: audit_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_logs_id_seq OWNED BY public.audit_logs.id;


--
-- Name: bank_accounts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bank_accounts (
    id integer NOT NULL,
    bank_name character varying(100) NOT NULL,
    branch_name character varying(200),
    account_no character varying(50),
    iban character varying(34) NOT NULL,
    currency character varying(3) DEFAULT 'TRY'::character varying NOT NULL,
    holder_name character varying(300),
    is_active boolean DEFAULT true NOT NULL,
    created_by integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    blocked_amount numeric(15,2)
);


--
-- Name: bank_accounts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bank_accounts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bank_accounts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bank_accounts_id_seq OWNED BY public.bank_accounts.id;


--
-- Name: bank_statements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bank_statements (
    id integer NOT NULL,
    account_id integer NOT NULL,
    file_name character varying(255) NOT NULL,
    file_url character varying(500) NOT NULL,
    file_type character varying(10) NOT NULL,
    period_start date,
    period_end date,
    total_transactions integer DEFAULT 0 NOT NULL,
    new_transactions integer DEFAULT 0 NOT NULL,
    skipped_transactions integer DEFAULT 0 NOT NULL,
    uploaded_by integer,
    uploaded_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: bank_statements_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bank_statements_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bank_statements_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bank_statements_id_seq OWNED BY public.bank_statements.id;


--
-- Name: bank_transactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bank_transactions (
    id integer NOT NULL,
    account_id integer NOT NULL,
    statement_id integer,
    date date NOT NULL,
    receipt_no character varying(50),
    description text NOT NULL,
    amount numeric(15,2) NOT NULL,
    balance numeric(15,2),
    type character varying(10) NOT NULL,
    tx_hash character varying(64) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    category_id integer,
    tag_note character varying(300),
    tag_source character varying(20),
    vendor_id integer,
    payment_method character varying(20),
    match_number integer
);


--
-- Name: bank_transactions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bank_transactions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bank_transactions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bank_transactions_id_seq OWNED BY public.bank_transactions.id;


--
-- Name: budget_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.budget_categories (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    type character varying(10) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: budget_categories_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.budget_categories_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: budget_categories_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.budget_categories_id_seq OWNED BY public.budget_categories.id;


--
-- Name: budgets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.budgets (
    id integer NOT NULL,
    department_id integer NOT NULL,
    category_id integer NOT NULL,
    year integer NOT NULL,
    month integer NOT NULL,
    planned_amount numeric(15,2) DEFAULT 0 NOT NULL,
    actual_amount numeric(15,2) DEFAULT 0 NOT NULL,
    currency character varying(5) DEFAULT 'TRY'::character varying NOT NULL,
    notes text,
    created_by integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: budgets_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.budgets_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: budgets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.budgets_id_seq OWNED BY public.budgets.id;


--
-- Name: cash_flows; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cash_flows (
    id integer NOT NULL,
    title character varying(200) NOT NULL,
    type character varying(20) NOT NULL,
    amount numeric(12,2) NOT NULL,
    description text,
    date date DEFAULT CURRENT_DATE NOT NULL,
    created_by integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: cash_flows_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cash_flows_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cash_flows_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cash_flows_id_seq OWNED BY public.cash_flows.id;


--
-- Name: check_uploads; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.check_uploads (
    id integer NOT NULL,
    file_name character varying(255) NOT NULL,
    file_url character varying(500),
    total_checks integer DEFAULT 0,
    new_checks integer DEFAULT 0,
    skipped_checks integer DEFAULT 0,
    uploaded_by integer,
    uploaded_at timestamp with time zone DEFAULT now()
);


--
-- Name: check_uploads_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.check_uploads_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: check_uploads_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.check_uploads_id_seq OWNED BY public.check_uploads.id;


--
-- Name: checks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.checks (
    id integer NOT NULL,
    upload_id integer NOT NULL,
    check_type character varying(20),
    sequence_no integer,
    check_no character varying(50) NOT NULL,
    vendor_code character varying(50),
    vendor_name character varying(300) NOT NULL,
    description text,
    city character varying(50),
    due_date date NOT NULL,
    amount_tl numeric(15,2) NOT NULL,
    currency character varying(5) DEFAULT 'TL'::character varying,
    amount_currency numeric(15,2) NOT NULL,
    transaction_type character varying(50),
    status character varying(20) DEFAULT 'pending'::character varying,
    created_at timestamp with time zone DEFAULT now(),
    bank_transaction_id integer,
    match_number integer,
    matched_vendor_id integer
);


--
-- Name: checks_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.checks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: checks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.checks_id_seq OWNED BY public.checks.id;


--
-- Name: conversation_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conversation_members (
    id integer NOT NULL,
    conversation_id integer NOT NULL,
    user_id integer NOT NULL,
    last_read_at timestamp with time zone,
    joined_at timestamp with time zone DEFAULT now() NOT NULL,
    is_admin boolean DEFAULT false NOT NULL,
    is_muted boolean DEFAULT false NOT NULL
);


--
-- Name: conversation_members_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.conversation_members_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: conversation_members_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.conversation_members_id_seq OWNED BY public.conversation_members.id;


--
-- Name: conversations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conversations (
    id integer NOT NULL,
    type character varying(20) DEFAULT 'private'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    name character varying(100),
    created_by integer,
    private_user_low integer,
    private_user_high integer
);


--
-- Name: conversations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.conversations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: conversations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.conversations_id_seq OWNED BY public.conversations.id;


--
-- Name: credit_card_statements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.credit_card_statements (
    id integer NOT NULL,
    credit_product_id integer NOT NULL,
    ekstre_no character varying(100),
    kesim_tarihi date NOT NULL,
    son_odeme_tarihi date NOT NULL,
    onceki_bakiye numeric(15,2) NOT NULL,
    donem_harcama numeric(15,2) NOT NULL,
    faiz_ucret numeric(15,2) NOT NULL,
    donem_odeme numeric(15,2) NOT NULL,
    toplam_borc numeric(15,2) NOT NULL,
    asgari_odeme numeric(15,2) NOT NULL,
    is_paid boolean NOT NULL,
    paid_amount numeric(15,2),
    paid_date date,
    file_name character varying(255),
    file_url character varying(500),
    uploaded_by integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: credit_card_statements_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.credit_card_statements_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: credit_card_statements_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.credit_card_statements_id_seq OWNED BY public.credit_card_statements.id;


--
-- Name: credit_card_transactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.credit_card_transactions (
    id integer NOT NULL,
    statement_id integer NOT NULL,
    islem_tarihi date,
    aciklama text NOT NULL,
    kategori character varying(100),
    taksit_bilgi character varying(100),
    tutar numeric(15,2) NOT NULL,
    is_credit boolean NOT NULL,
    bonus numeric(15,2),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: credit_card_transactions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.credit_card_transactions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: credit_card_transactions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.credit_card_transactions_id_seq OWNED BY public.credit_card_transactions.id;


--
-- Name: credit_payments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.credit_payments (
    id integer NOT NULL,
    credit_product_id integer NOT NULL,
    installment_no integer,
    due_date date NOT NULL,
    amount numeric(15,2) NOT NULL,
    principal numeric(15,2),
    interest numeric(15,2),
    is_paid boolean DEFAULT false NOT NULL,
    paid_date date,
    bank_transaction_id integer,
    match_number integer,
    notes character varying(300),
    created_at timestamp with time zone DEFAULT now(),
    bsmv numeric(15,2),
    commission numeric(15,2)
);


--
-- Name: credit_payments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.credit_payments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: credit_payments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.credit_payments_id_seq OWNED BY public.credit_payments.id;


--
-- Name: credit_products; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.credit_products (
    id integer NOT NULL,
    type character varying(30) NOT NULL,
    name character varying(200) NOT NULL,
    bank_name character varying(100),
    company character varying(200),
    currency character varying(5) DEFAULT 'TRY'::character varying NOT NULL,
    total_amount numeric(15,2) DEFAULT '0'::numeric NOT NULL,
    remaining_amount numeric(15,2) DEFAULT '0'::numeric NOT NULL,
    interest_rate numeric(6,4),
    start_date date,
    end_date date,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    details text,
    notes text,
    created_by integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    bsmv_rate numeric(6,4),
    commission_rate numeric(6,4),
    linked_account_id integer,
    closed_date date
);


--
-- Name: credit_products_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.credit_products_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: credit_products_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.credit_products_id_seq OWNED BY public.credit_products.id;


--
-- Name: departments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.departments (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    code character varying(30) NOT NULL,
    manager_id integer,
    is_active boolean DEFAULT true NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: departments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.departments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: departments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.departments_id_seq OWNED BY public.departments.id;


--
-- Name: error_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.error_logs (
    id integer NOT NULL,
    level character varying(20) NOT NULL,
    source character varying(100) NOT NULL,
    message text NOT NULL,
    traceback text,
    method character varying(10),
    path character varying(500),
    user_id integer,
    ip_address character varying(50),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: error_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.error_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: error_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.error_logs_id_seq OWNED BY public.error_logs.id;


--
-- Name: exchange_rates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.exchange_rates (
    id integer NOT NULL,
    date date NOT NULL,
    currency_code character varying(3) NOT NULL,
    currency_name character varying(50),
    unit integer DEFAULT 1 NOT NULL,
    forex_buying numeric(12,4),
    forex_selling numeric(12,4),
    banknote_buying numeric(12,4),
    banknote_selling numeric(12,4),
    source character varying(20) DEFAULT 'tcmb'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: exchange_rates_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.exchange_rates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: exchange_rates_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.exchange_rates_id_seq OWNED BY public.exchange_rates.id;


--
-- Name: finance_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_events (
    id bigint NOT NULL,
    event_date date NOT NULL,
    amount numeric(15,2) NOT NULL,
    direction smallint NOT NULL,
    currency character varying(3) DEFAULT 'TRY'::character varying NOT NULL,
    amount_try numeric(15,2),
    source_type character varying(30) NOT NULL,
    source_id bigint NOT NULL,
    description text,
    bank_name character varying(100),
    account_id integer,
    iban character varying(34),
    receipt_no character varying(50),
    balance numeric(15,2),
    payment_method character varying(50),
    match_number integer,
    check_no character varying(50),
    event_status character varying(20),
    vendor_code character varying(50),
    tag_note text,
    tag_source character varying(20),
    bank_account_id integer,
    vendor_id integer,
    category_id integer,
    category_name character varying(100),
    category_color character varying(20),
    is_realized boolean DEFAULT false NOT NULL,
    is_matched boolean DEFAULT false NOT NULL,
    matched_event_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: finance_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.finance_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: finance_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.finance_events_id_seq OWNED BY public.finance_events.id;


--
-- Name: match_number_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.match_number_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.messages (
    id integer NOT NULL,
    conversation_id integer NOT NULL,
    sender_id integer NOT NULL,
    content text NOT NULL,
    message_type character varying(20) DEFAULT 'text'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    is_edited boolean DEFAULT false NOT NULL,
    edited_at timestamp with time zone,
    is_deleted boolean DEFAULT false NOT NULL,
    file_url character varying(500),
    file_name character varying(255),
    file_size integer,
    file_type character varying(100)
);


--
-- Name: messages_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.messages_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: messages_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.messages_id_seq OWNED BY public.messages.id;


--
-- Name: modules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.modules (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    code character varying(50) NOT NULL,
    description text,
    icon character varying(50),
    parent_id integer,
    sort_order integer DEFAULT 0 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: modules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.modules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: modules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.modules_id_seq OWNED BY public.modules.id;


--
-- Name: notifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notifications (
    id integer NOT NULL,
    user_id integer NOT NULL,
    type character varying(50) NOT NULL,
    title character varying(200) NOT NULL,
    body text NOT NULL,
    link character varying(500),
    is_read boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: notifications_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.notifications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: notifications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.notifications_id_seq OWNED BY public.notifications.id;


--
-- Name: payment_instruction_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.payment_instruction_items (
    id integer NOT NULL,
    list_id integer NOT NULL,
    vendor_id integer,
    hesap_kodu character varying(50),
    hesap_adi character varying(300) NOT NULL,
    amount numeric(15,2) DEFAULT '0'::numeric NOT NULL,
    balance_snapshot numeric(15,2),
    notes character varying(300),
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: payment_instruction_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.payment_instruction_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: payment_instruction_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.payment_instruction_items_id_seq OWNED BY public.payment_instruction_items.id;


--
-- Name: payment_instruction_lists; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.payment_instruction_lists (
    id integer NOT NULL,
    name character varying(200) NOT NULL,
    description text,
    status character varying(20) DEFAULT 'draft'::character varying NOT NULL,
    created_by integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: payment_instruction_lists_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.payment_instruction_lists_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: payment_instruction_lists_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.payment_instruction_lists_id_seq OWNED BY public.payment_instruction_lists.id;


--
-- Name: push_subscriptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.push_subscriptions (
    id integer NOT NULL,
    user_id integer NOT NULL,
    endpoint text NOT NULL,
    p256dh_key character varying(255) NOT NULL,
    auth_key character varying(255) NOT NULL,
    user_agent character varying(500),
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_used_at timestamp with time zone
);


--
-- Name: push_subscriptions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.push_subscriptions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: push_subscriptions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.push_subscriptions_id_seq OWNED BY public.push_subscriptions.id;


--
-- Name: quality_form_values; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quality_form_values (
    id integer NOT NULL,
    form_id integer NOT NULL,
    field_id integer NOT NULL,
    value text,
    corrective_action text,
    correction_note text
);


--
-- Name: quality_form_values_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.quality_form_values_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: quality_form_values_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.quality_form_values_id_seq OWNED BY public.quality_form_values.id;


--
-- Name: quality_forms; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quality_forms (
    id integer NOT NULL,
    template_id integer NOT NULL,
    period_date date NOT NULL,
    status character varying(20) DEFAULT 'draft'::character varying NOT NULL,
    filled_by integer,
    submitted_at timestamp with time zone,
    reviewed_by integer,
    reviewed_at timestamp with time zone,
    review_comment text,
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: quality_forms_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.quality_forms_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: quality_forms_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.quality_forms_id_seq OWNED BY public.quality_forms.id;


--
-- Name: quality_template_assignees; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quality_template_assignees (
    id integer NOT NULL,
    template_id integer NOT NULL,
    assignment_type character varying(20) NOT NULL,
    user_id integer,
    role_id integer,
    CONSTRAINT ck_assignee_user_or_role CHECK ((((user_id IS NOT NULL) AND (role_id IS NULL)) OR ((user_id IS NULL) AND (role_id IS NOT NULL))))
);


--
-- Name: quality_template_assignees_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.quality_template_assignees_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: quality_template_assignees_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.quality_template_assignees_id_seq OWNED BY public.quality_template_assignees.id;


--
-- Name: quality_template_fields; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quality_template_fields (
    id integer NOT NULL,
    section_id integer NOT NULL,
    label character varying(300) NOT NULL,
    field_type character varying(20) NOT NULL,
    unit character varying(30),
    is_required boolean DEFAULT true NOT NULL,
    is_resource boolean DEFAULT false NOT NULL,
    is_guest_count boolean DEFAULT false NOT NULL,
    options text,
    sort_order integer DEFAULT 0 NOT NULL,
    is_month_end_only boolean DEFAULT false NOT NULL,
    is_meter boolean DEFAULT false NOT NULL
);


--
-- Name: quality_template_fields_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.quality_template_fields_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: quality_template_fields_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.quality_template_fields_id_seq OWNED BY public.quality_template_fields.id;


--
-- Name: quality_template_sections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quality_template_sections (
    id integer NOT NULL,
    template_id integer NOT NULL,
    name character varying(200) NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL
);


--
-- Name: quality_template_sections_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.quality_template_sections_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: quality_template_sections_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.quality_template_sections_id_seq OWNED BY public.quality_template_sections.id;


--
-- Name: quality_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quality_templates (
    id integer NOT NULL,
    name character varying(200) NOT NULL,
    description text,
    frequency character varying(20) DEFAULT 'daily'::character varying NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_by integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    footer_text text,
    logo_filename character varying(255),
    increase_threshold double precision DEFAULT '10'::double precision,
    decrease_threshold double precision DEFAULT '10'::double precision
);


--
-- Name: quality_templates_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.quality_templates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: quality_templates_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.quality_templates_id_seq OWNED BY public.quality_templates.id;


--
-- Name: reservation_uploads; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reservation_uploads (
    id integer NOT NULL,
    file_name character varying(255) NOT NULL,
    file_url character varying(500),
    file_type character varying(10),
    hotel_name character varying(100),
    period_checkin_start date,
    period_checkin_end date,
    period_record_start date,
    period_record_end date,
    total_rows integer DEFAULT 0 NOT NULL,
    new_rows integer DEFAULT 0 NOT NULL,
    updated_rows integer DEFAULT 0 NOT NULL,
    uploaded_by integer,
    uploaded_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: reservation_uploads_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.reservation_uploads_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reservation_uploads_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.reservation_uploads_id_seq OWNED BY public.reservation_uploads.id;


--
-- Name: reservations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reservations (
    id integer NOT NULL,
    rec_id integer NOT NULL,
    upload_id integer,
    agency character varying(50),
    room_type character varying(40),
    voucher character varying(40),
    guests text,
    checkin_date date NOT NULL,
    checkout_date date NOT NULL,
    nights integer DEFAULT 0 NOT NULL,
    record_date date NOT NULL,
    board character varying(10),
    vip_type character varying(20),
    rooms integer DEFAULT 1 NOT NULL,
    adult integer DEFAULT 0 NOT NULL,
    child_paid integer DEFAULT 0 NOT NULL,
    child_free integer DEFAULT 0 NOT NULL,
    baby integer DEFAULT 0 NOT NULL,
    nation character varying(10),
    net_amount numeric(12,2),
    currency character varying(5),
    eur_total numeric(12,2) DEFAULT 0 NOT NULL,
    per_room numeric(10,2),
    per_adult numeric(10,2),
    rez_status character varying(20),
    status character varying(20),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: reservations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.reservations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: reservations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.reservations_id_seq OWNED BY public.reservations.id;


--
-- Name: role_module_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.role_module_permissions (
    id integer NOT NULL,
    role_id integer NOT NULL,
    module_id integer NOT NULL,
    can_view boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    can_use boolean DEFAULT false NOT NULL
);


--
-- Name: role_module_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.role_module_permissions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: role_module_permissions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.role_module_permissions_id_seq OWNED BY public.role_module_permissions.id;


--
-- Name: roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.roles (
    id integer NOT NULL,
    name character varying(50) NOT NULL,
    description text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: roles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.roles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: roles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.roles_id_seq OWNED BY public.roles.id;


--
-- Name: room_types; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.room_types (
    id integer NOT NULL,
    code character varying(40) NOT NULL,
    name character varying(120) NOT NULL,
    total_rooms integer DEFAULT 0 NOT NULL,
    max_occupancy integer DEFAULT 2 NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_room_types_max_occupancy_positive CHECK ((max_occupancy >= 1)),
    CONSTRAINT ck_room_types_total_rooms_positive CHECK ((total_rooms >= 0))
);


--
-- Name: room_types_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.room_types_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: room_types_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.room_types_id_seq OWNED BY public.room_types.id;


--
-- Name: scheduled_definitions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scheduled_definitions (
    id integer NOT NULL,
    source_type character varying(30) NOT NULL,
    name character varying(200) NOT NULL,
    category character varying(100),
    amount numeric(15,2) NOT NULL,
    currency character varying(3) DEFAULT 'TRY'::character varying NOT NULL,
    frequency character varying(20) DEFAULT 'monthly'::character varying NOT NULL,
    payment_day integer DEFAULT 1 NOT NULL,
    start_month integer DEFAULT 1 NOT NULL,
    year integer NOT NULL,
    notes text,
    is_active boolean DEFAULT true NOT NULL,
    created_by integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: scheduled_definitions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scheduled_definitions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scheduled_definitions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scheduled_definitions_id_seq OWNED BY public.scheduled_definitions.id;


--
-- Name: scheduled_entries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scheduled_entries (
    id bigint NOT NULL,
    definition_id integer NOT NULL,
    source_type character varying(30) NOT NULL,
    entry_date date NOT NULL,
    amount numeric(15,2) NOT NULL,
    currency character varying(3) DEFAULT 'TRY'::character varying NOT NULL,
    description text,
    is_paid boolean DEFAULT false NOT NULL,
    paid_date date,
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    period_month integer NOT NULL,
    period_year integer NOT NULL
);


--
-- Name: scheduled_entries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scheduled_entries_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scheduled_entries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scheduled_entries_id_seq OWNED BY public.scheduled_entries.id;


--
-- Name: transaction_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.transaction_categories (
    id integer NOT NULL,
    name character varying(50) NOT NULL,
    color character varying(20) NOT NULL,
    sort_order integer DEFAULT 0,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: transaction_categories_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.transaction_categories_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: transaction_categories_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.transaction_categories_id_seq OWNED BY public.transaction_categories.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id integer NOT NULL,
    email character varying(255) NOT NULL,
    hashed_password character varying(255) NOT NULL,
    is_active boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    role_id integer NOT NULL,
    first_name character varying(100) NOT NULL,
    last_name character varying(100) NOT NULL,
    username character varying(50) NOT NULL,
    active_session_id character varying(36),
    last_online_at timestamp with time zone
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: vendor_transactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vendor_transactions (
    id integer NOT NULL,
    vendor_id integer NOT NULL,
    upload_id integer NOT NULL,
    date date NOT NULL,
    evrak_no character varying(100),
    transaction_type character varying(100),
    fis_no character varying(50),
    description text,
    borc numeric(15,2) DEFAULT '0'::numeric,
    alacak numeric(15,2) DEFAULT '0'::numeric,
    bakiye numeric(15,2),
    tx_hash character varying(64) NOT NULL,
    payment_due_date date,
    created_at timestamp with time zone DEFAULT now(),
    match_number integer,
    payment_method character varying(20),
    department_id integer,
    budget_category_id integer,
    dept_status character varying(20),
    dept_assigned_by integer,
    dept_assigned_at timestamp with time zone,
    dept_approved_by integer,
    dept_approved_at timestamp with time zone,
    dept_rejection_note text
);


--
-- Name: vendors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vendors (
    id integer NOT NULL,
    hesap_kodu character varying(50) NOT NULL,
    hesap_adi character varying(300) NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    payment_days integer DEFAULT 90 NOT NULL,
    status character varying(30) DEFAULT 'normal'::character varying NOT NULL
);


--
-- Name: vendor_balances; Type: MATERIALIZED VIEW; Schema: public; Owner: -
--

CREATE MATERIALIZED VIEW public.vendor_balances AS
 SELECT v.id AS vendor_id,
    v.hesap_kodu,
    v.hesap_adi,
    COALESCE(sum(vt.borc), (0)::numeric) AS total_borc,
    COALESCE(sum(vt.alacak), (0)::numeric) AS total_alacak,
    (COALESCE(sum(vt.alacak), (0)::numeric) - COALESCE(sum(vt.borc), (0)::numeric)) AS net_debt,
    count(*) FILTER (WHERE ((vt.payment_due_date IS NOT NULL) AND (vt.alacak > (0)::numeric) AND (vt.match_number IS NULL))) AS pending_invoice_count,
    COALESCE(sum(vt.alacak) FILTER (WHERE ((vt.payment_due_date IS NOT NULL) AND (vt.alacak > (0)::numeric) AND (vt.match_number IS NULL))), (0)::numeric) AS pending_invoice_amount
   FROM (public.vendors v
     LEFT JOIN public.vendor_transactions vt ON ((vt.vendor_id = v.id)))
  GROUP BY v.id, v.hesap_kodu, v.hesap_adi
  WITH NO DATA;


--
-- Name: vendor_transactions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.vendor_transactions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vendor_transactions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.vendor_transactions_id_seq OWNED BY public.vendor_transactions.id;


--
-- Name: vendor_uploads; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vendor_uploads (
    id integer NOT NULL,
    file_name character varying(255) NOT NULL,
    file_url character varying(500) NOT NULL,
    total_vendors integer DEFAULT 0,
    total_transactions integer DEFAULT 0,
    new_transactions integer DEFAULT 0,
    skipped_transactions integer DEFAULT 0,
    uploaded_by integer,
    uploaded_at timestamp with time zone DEFAULT now()
);


--
-- Name: vendor_uploads_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.vendor_uploads_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vendor_uploads_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.vendor_uploads_id_seq OWNED BY public.vendor_uploads.id;


--
-- Name: vendors_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.vendors_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vendors_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.vendors_id_seq OWNED BY public.vendors.id;


--
-- Name: advances id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.advances ALTER COLUMN id SET DEFAULT nextval('public.advances_id_seq'::regclass);


--
-- Name: agency_groups id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agency_groups ALTER COLUMN id SET DEFAULT nextval('public.agency_groups_id_seq'::regclass);


--
-- Name: approval_request_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_request_logs ALTER COLUMN id SET DEFAULT nextval('public.approval_request_logs_id_seq'::regclass);


--
-- Name: approval_requests id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_requests ALTER COLUMN id SET DEFAULT nextval('public.approval_requests_id_seq'::regclass);


--
-- Name: approval_workflow_approver_roles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflow_approver_roles ALTER COLUMN id SET DEFAULT nextval('public.approval_workflow_approver_roles_id_seq'::regclass);


--
-- Name: approval_workflow_requestor_roles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflow_requestor_roles ALTER COLUMN id SET DEFAULT nextval('public.approval_workflow_requestor_roles_id_seq'::regclass);


--
-- Name: approval_workflow_steps id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflow_steps ALTER COLUMN id SET DEFAULT nextval('public.approval_workflow_steps_id_seq'::regclass);


--
-- Name: approval_workflows id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflows ALTER COLUMN id SET DEFAULT nextval('public.approval_workflows_id_seq'::regclass);


--
-- Name: audit_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs ALTER COLUMN id SET DEFAULT nextval('public.audit_logs_id_seq'::regclass);


--
-- Name: bank_accounts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bank_accounts ALTER COLUMN id SET DEFAULT nextval('public.bank_accounts_id_seq'::regclass);


--
-- Name: bank_statements id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bank_statements ALTER COLUMN id SET DEFAULT nextval('public.bank_statements_id_seq'::regclass);


--
-- Name: bank_transactions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bank_transactions ALTER COLUMN id SET DEFAULT nextval('public.bank_transactions_id_seq'::regclass);


--
-- Name: budget_categories id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_categories ALTER COLUMN id SET DEFAULT nextval('public.budget_categories_id_seq'::regclass);


--
-- Name: budgets id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budgets ALTER COLUMN id SET DEFAULT nextval('public.budgets_id_seq'::regclass);


--
-- Name: cash_flows id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_flows ALTER COLUMN id SET DEFAULT nextval('public.cash_flows_id_seq'::regclass);


--
-- Name: check_uploads id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.check_uploads ALTER COLUMN id SET DEFAULT nextval('public.check_uploads_id_seq'::regclass);


--
-- Name: checks id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.checks ALTER COLUMN id SET DEFAULT nextval('public.checks_id_seq'::regclass);


--
-- Name: conversation_members id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_members ALTER COLUMN id SET DEFAULT nextval('public.conversation_members_id_seq'::regclass);


--
-- Name: conversations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversations ALTER COLUMN id SET DEFAULT nextval('public.conversations_id_seq'::regclass);


--
-- Name: credit_card_statements id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credit_card_statements ALTER COLUMN id SET DEFAULT nextval('public.credit_card_statements_id_seq'::regclass);


--
-- Name: credit_card_transactions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credit_card_transactions ALTER COLUMN id SET DEFAULT nextval('public.credit_card_transactions_id_seq'::regclass);


--
-- Name: credit_payments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credit_payments ALTER COLUMN id SET DEFAULT nextval('public.credit_payments_id_seq'::regclass);


--
-- Name: credit_products id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credit_products ALTER COLUMN id SET DEFAULT nextval('public.credit_products_id_seq'::regclass);


--
-- Name: departments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.departments ALTER COLUMN id SET DEFAULT nextval('public.departments_id_seq'::regclass);


--
-- Name: error_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.error_logs ALTER COLUMN id SET DEFAULT nextval('public.error_logs_id_seq'::regclass);


--
-- Name: exchange_rates id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_rates ALTER COLUMN id SET DEFAULT nextval('public.exchange_rates_id_seq'::regclass);


--
-- Name: finance_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_events ALTER COLUMN id SET DEFAULT nextval('public.finance_events_id_seq'::regclass);


--
-- Name: messages id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.messages ALTER COLUMN id SET DEFAULT nextval('public.messages_id_seq'::regclass);


--
-- Name: modules id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.modules ALTER COLUMN id SET DEFAULT nextval('public.modules_id_seq'::regclass);


--
-- Name: notifications id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications ALTER COLUMN id SET DEFAULT nextval('public.notifications_id_seq'::regclass);


--
-- Name: payment_instruction_items id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_instruction_items ALTER COLUMN id SET DEFAULT nextval('public.payment_instruction_items_id_seq'::regclass);


--
-- Name: payment_instruction_lists id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_instruction_lists ALTER COLUMN id SET DEFAULT nextval('public.payment_instruction_lists_id_seq'::regclass);


--
-- Name: push_subscriptions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.push_subscriptions ALTER COLUMN id SET DEFAULT nextval('public.push_subscriptions_id_seq'::regclass);


--
-- Name: quality_form_values id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_form_values ALTER COLUMN id SET DEFAULT nextval('public.quality_form_values_id_seq'::regclass);


--
-- Name: quality_forms id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_forms ALTER COLUMN id SET DEFAULT nextval('public.quality_forms_id_seq'::regclass);


--
-- Name: quality_template_assignees id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_template_assignees ALTER COLUMN id SET DEFAULT nextval('public.quality_template_assignees_id_seq'::regclass);


--
-- Name: quality_template_fields id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_template_fields ALTER COLUMN id SET DEFAULT nextval('public.quality_template_fields_id_seq'::regclass);


--
-- Name: quality_template_sections id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_template_sections ALTER COLUMN id SET DEFAULT nextval('public.quality_template_sections_id_seq'::regclass);


--
-- Name: quality_templates id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_templates ALTER COLUMN id SET DEFAULT nextval('public.quality_templates_id_seq'::regclass);


--
-- Name: reservation_uploads id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reservation_uploads ALTER COLUMN id SET DEFAULT nextval('public.reservation_uploads_id_seq'::regclass);


--
-- Name: reservations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reservations ALTER COLUMN id SET DEFAULT nextval('public.reservations_id_seq'::regclass);


--
-- Name: role_module_permissions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_module_permissions ALTER COLUMN id SET DEFAULT nextval('public.role_module_permissions_id_seq'::regclass);


--
-- Name: roles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles ALTER COLUMN id SET DEFAULT nextval('public.roles_id_seq'::regclass);


--
-- Name: room_types id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.room_types ALTER COLUMN id SET DEFAULT nextval('public.room_types_id_seq'::regclass);


--
-- Name: scheduled_definitions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_definitions ALTER COLUMN id SET DEFAULT nextval('public.scheduled_definitions_id_seq'::regclass);


--
-- Name: scheduled_entries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_entries ALTER COLUMN id SET DEFAULT nextval('public.scheduled_entries_id_seq'::regclass);


--
-- Name: transaction_categories id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transaction_categories ALTER COLUMN id SET DEFAULT nextval('public.transaction_categories_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: vendor_transactions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vendor_transactions ALTER COLUMN id SET DEFAULT nextval('public.vendor_transactions_id_seq'::regclass);


--
-- Name: vendor_uploads id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vendor_uploads ALTER COLUMN id SET DEFAULT nextval('public.vendor_uploads_id_seq'::regclass);


--
-- Name: vendors id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vendors ALTER COLUMN id SET DEFAULT nextval('public.vendors_id_seq'::regclass);


--
-- Name: advances advances_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.advances
    ADD CONSTRAINT advances_pkey PRIMARY KEY (id);


--
-- Name: agency_groups agency_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agency_groups
    ADD CONSTRAINT agency_groups_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: approval_request_logs approval_request_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_request_logs
    ADD CONSTRAINT approval_request_logs_pkey PRIMARY KEY (id);


--
-- Name: approval_requests approval_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT approval_requests_pkey PRIMARY KEY (id);


--
-- Name: approval_workflow_approver_roles approval_workflow_approver_roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflow_approver_roles
    ADD CONSTRAINT approval_workflow_approver_roles_pkey PRIMARY KEY (id);


--
-- Name: approval_workflow_requestor_roles approval_workflow_requestor_roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflow_requestor_roles
    ADD CONSTRAINT approval_workflow_requestor_roles_pkey PRIMARY KEY (id);


--
-- Name: approval_workflow_steps approval_workflow_steps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflow_steps
    ADD CONSTRAINT approval_workflow_steps_pkey PRIMARY KEY (id);


--
-- Name: approval_workflows approval_workflows_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflows
    ADD CONSTRAINT approval_workflows_pkey PRIMARY KEY (id);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: bank_accounts bank_accounts_iban_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bank_accounts
    ADD CONSTRAINT bank_accounts_iban_key UNIQUE (iban);


--
-- Name: bank_accounts bank_accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bank_accounts
    ADD CONSTRAINT bank_accounts_pkey PRIMARY KEY (id);


--
-- Name: bank_statements bank_statements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bank_statements
    ADD CONSTRAINT bank_statements_pkey PRIMARY KEY (id);


--
-- Name: bank_transactions bank_transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bank_transactions
    ADD CONSTRAINT bank_transactions_pkey PRIMARY KEY (id);


--
-- Name: budget_categories budget_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_categories
    ADD CONSTRAINT budget_categories_pkey PRIMARY KEY (id);


--
-- Name: budgets budgets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budgets
    ADD CONSTRAINT budgets_pkey PRIMARY KEY (id);


--
-- Name: cash_flows cash_flows_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_flows
    ADD CONSTRAINT cash_flows_pkey PRIMARY KEY (id);


--
-- Name: check_uploads check_uploads_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.check_uploads
    ADD CONSTRAINT check_uploads_pkey PRIMARY KEY (id);


--
-- Name: checks checks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.checks
    ADD CONSTRAINT checks_pkey PRIMARY KEY (id);


--
-- Name: conversation_members conversation_members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_members
    ADD CONSTRAINT conversation_members_pkey PRIMARY KEY (id);


--
-- Name: conversations conversations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversations
    ADD CONSTRAINT conversations_pkey PRIMARY KEY (id);


--
-- Name: credit_card_statements credit_card_statements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credit_card_statements
    ADD CONSTRAINT credit_card_statements_pkey PRIMARY KEY (id);


--
-- Name: credit_card_transactions credit_card_transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credit_card_transactions
    ADD CONSTRAINT credit_card_transactions_pkey PRIMARY KEY (id);


--
-- Name: credit_payments credit_payments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credit_payments
    ADD CONSTRAINT credit_payments_pkey PRIMARY KEY (id);


--
-- Name: credit_products credit_products_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credit_products
    ADD CONSTRAINT credit_products_pkey PRIMARY KEY (id);


--
-- Name: departments departments_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.departments
    ADD CONSTRAINT departments_name_key UNIQUE (name);


--
-- Name: departments departments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.departments
    ADD CONSTRAINT departments_pkey PRIMARY KEY (id);


--
-- Name: error_logs error_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.error_logs
    ADD CONSTRAINT error_logs_pkey PRIMARY KEY (id);


--
-- Name: exchange_rates exchange_rates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_rates
    ADD CONSTRAINT exchange_rates_pkey PRIMARY KEY (id);


--
-- Name: finance_events finance_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_events
    ADD CONSTRAINT finance_events_pkey PRIMARY KEY (id);


--
-- Name: messages messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_pkey PRIMARY KEY (id);


--
-- Name: modules modules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.modules
    ADD CONSTRAINT modules_pkey PRIMARY KEY (id);


--
-- Name: notifications notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);


--
-- Name: payment_instruction_items payment_instruction_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_instruction_items
    ADD CONSTRAINT payment_instruction_items_pkey PRIMARY KEY (id);


--
-- Name: payment_instruction_lists payment_instruction_lists_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_instruction_lists
    ADD CONSTRAINT payment_instruction_lists_pkey PRIMARY KEY (id);


--
-- Name: push_subscriptions push_subscriptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.push_subscriptions
    ADD CONSTRAINT push_subscriptions_pkey PRIMARY KEY (id);


--
-- Name: quality_form_values quality_form_values_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_form_values
    ADD CONSTRAINT quality_form_values_pkey PRIMARY KEY (id);


--
-- Name: quality_forms quality_forms_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_forms
    ADD CONSTRAINT quality_forms_pkey PRIMARY KEY (id);


--
-- Name: quality_template_assignees quality_template_assignees_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_template_assignees
    ADD CONSTRAINT quality_template_assignees_pkey PRIMARY KEY (id);


--
-- Name: quality_template_fields quality_template_fields_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_template_fields
    ADD CONSTRAINT quality_template_fields_pkey PRIMARY KEY (id);


--
-- Name: quality_template_sections quality_template_sections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_template_sections
    ADD CONSTRAINT quality_template_sections_pkey PRIMARY KEY (id);


--
-- Name: quality_templates quality_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_templates
    ADD CONSTRAINT quality_templates_pkey PRIMARY KEY (id);


--
-- Name: reservation_uploads reservation_uploads_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reservation_uploads
    ADD CONSTRAINT reservation_uploads_pkey PRIMARY KEY (id);


--
-- Name: reservations reservations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reservations
    ADD CONSTRAINT reservations_pkey PRIMARY KEY (id);


--
-- Name: role_module_permissions role_module_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_module_permissions
    ADD CONSTRAINT role_module_permissions_pkey PRIMARY KEY (id);


--
-- Name: roles roles_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_name_key UNIQUE (name);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);


--
-- Name: room_types room_types_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.room_types
    ADD CONSTRAINT room_types_pkey PRIMARY KEY (id);


--
-- Name: scheduled_definitions scheduled_definitions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_definitions
    ADD CONSTRAINT scheduled_definitions_pkey PRIMARY KEY (id);


--
-- Name: scheduled_entries scheduled_entries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_entries
    ADD CONSTRAINT scheduled_entries_pkey PRIMARY KEY (id);


--
-- Name: transaction_categories transaction_categories_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transaction_categories
    ADD CONSTRAINT transaction_categories_name_key UNIQUE (name);


--
-- Name: transaction_categories transaction_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transaction_categories
    ADD CONSTRAINT transaction_categories_pkey PRIMARY KEY (id);


--
-- Name: agency_groups uq_agency_groups_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agency_groups
    ADD CONSTRAINT uq_agency_groups_name UNIQUE (name);


--
-- Name: approval_workflow_approver_roles uq_awar_workflow_role; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflow_approver_roles
    ADD CONSTRAINT uq_awar_workflow_role UNIQUE (workflow_id, role_id);


--
-- Name: approval_workflow_requestor_roles uq_awrr_workflow_role; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflow_requestor_roles
    ADD CONSTRAINT uq_awrr_workflow_role UNIQUE (workflow_id, role_id);


--
-- Name: approval_workflow_steps uq_aws_workflow_step; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflow_steps
    ADD CONSTRAINT uq_aws_workflow_step UNIQUE (workflow_id, step_number);


--
-- Name: bank_transactions uq_bank_tx_account_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bank_transactions
    ADD CONSTRAINT uq_bank_tx_account_hash UNIQUE (account_id, tx_hash);


--
-- Name: budget_categories uq_budget_category_name_type; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_categories
    ADD CONSTRAINT uq_budget_category_name_type UNIQUE (name, type);


--
-- Name: budgets uq_budget_dept_cat_year_month; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budgets
    ADD CONSTRAINT uq_budget_dept_cat_year_month UNIQUE (department_id, category_id, year, month);


--
-- Name: checks uq_check_no_vendor_date; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.checks
    ADD CONSTRAINT uq_check_no_vendor_date UNIQUE (check_no, vendor_code, due_date);


--
-- Name: conversation_members uq_conversation_member; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_members
    ADD CONSTRAINT uq_conversation_member UNIQUE (conversation_id, user_id);


--
-- Name: exchange_rates uq_exchange_rate_date_currency; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_rates
    ADD CONSTRAINT uq_exchange_rate_date_currency UNIQUE (date, currency_code);


--
-- Name: finance_events uq_finance_events_source; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_events
    ADD CONSTRAINT uq_finance_events_source UNIQUE (source_type, source_id);


--
-- Name: quality_form_values uq_form_field; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_form_values
    ADD CONSTRAINT uq_form_field UNIQUE (form_id, field_id);


--
-- Name: conversations uq_private_conversation_users; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversations
    ADD CONSTRAINT uq_private_conversation_users UNIQUE (private_user_low, private_user_high);


--
-- Name: push_subscriptions uq_push_endpoint; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.push_subscriptions
    ADD CONSTRAINT uq_push_endpoint UNIQUE (endpoint);


--
-- Name: role_module_permissions uq_role_module; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_module_permissions
    ADD CONSTRAINT uq_role_module UNIQUE (role_id, module_id);


--
-- Name: room_types uq_room_types_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.room_types
    ADD CONSTRAINT uq_room_types_code UNIQUE (code);


--
-- Name: quality_forms uq_template_period; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_forms
    ADD CONSTRAINT uq_template_period UNIQUE (template_id, period_date);


--
-- Name: vendor_transactions uq_vendor_tx_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vendor_transactions
    ADD CONSTRAINT uq_vendor_tx_hash UNIQUE (vendor_id, tx_hash);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: vendor_transactions vendor_transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vendor_transactions
    ADD CONSTRAINT vendor_transactions_pkey PRIMARY KEY (id);


--
-- Name: vendor_uploads vendor_uploads_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vendor_uploads
    ADD CONSTRAINT vendor_uploads_pkey PRIMARY KEY (id);


--
-- Name: vendors vendors_hesap_kodu_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vendors
    ADD CONSTRAINT vendors_hesap_kodu_key UNIQUE (hesap_kodu);


--
-- Name: vendors vendors_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vendors
    ADD CONSTRAINT vendors_pkey PRIMARY KEY (id);


--
-- Name: idx_fe_bank_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fe_bank_account ON public.finance_events USING btree (bank_account_id);


--
-- Name: idx_fe_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fe_category ON public.finance_events USING btree (category_id);


--
-- Name: idx_fe_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fe_date ON public.finance_events USING btree (event_date);


--
-- Name: idx_fe_date_dir; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fe_date_dir ON public.finance_events USING btree (event_date, direction);


--
-- Name: idx_fe_date_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fe_date_id ON public.finance_events USING btree (event_date DESC, id DESC);


--
-- Name: idx_fe_matched; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fe_matched ON public.finance_events USING btree (is_matched);


--
-- Name: idx_fe_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fe_source ON public.finance_events USING btree (source_type, source_id);


--
-- Name: idx_fe_vendor; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fe_vendor ON public.finance_events USING btree (vendor_id);


--
-- Name: idx_vb_net_debt; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vb_net_debt ON public.vendor_balances USING btree (net_debt DESC);


--
-- Name: idx_vb_vendor_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_vb_vendor_id ON public.vendor_balances USING btree (vendor_id);


--
-- Name: ix_advances_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_advances_date ON public.advances USING btree (advance_date);


--
-- Name: ix_advances_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_advances_status ON public.advances USING btree (status);


--
-- Name: ix_agency_groups_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agency_groups_id ON public.agency_groups USING btree (id);


--
-- Name: ix_ar_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ar_entity ON public.approval_requests USING btree (entity_type, entity_id);


--
-- Name: ix_ar_requested_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ar_requested_by ON public.approval_requests USING btree (requested_by);


--
-- Name: ix_ar_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ar_status ON public.approval_requests USING btree (status);


--
-- Name: ix_ar_workflow; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_ar_workflow ON public.approval_requests USING btree (workflow_id);


--
-- Name: ix_arl_actor; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_arl_actor ON public.approval_request_logs USING btree (actor_id);


--
-- Name: ix_arl_request; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_arl_request ON public.approval_request_logs USING btree (request_id);


--
-- Name: ix_audit_logs_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_action ON public.audit_logs USING btree (action);


--
-- Name: ix_audit_logs_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_created_at ON public.audit_logs USING btree (created_at);


--
-- Name: ix_audit_logs_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_entity ON public.audit_logs USING btree (entity_type, entity_id);


--
-- Name: ix_audit_logs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_user_id ON public.audit_logs USING btree (user_id);


--
-- Name: ix_aw_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_aw_active ON public.approval_workflows USING btree (is_active);


--
-- Name: ix_aw_entity_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_aw_entity_type ON public.approval_workflows USING btree (entity_type);


--
-- Name: ix_aw_module; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_aw_module ON public.approval_workflows USING btree (module_id);


--
-- Name: ix_awar_workflow; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_awar_workflow ON public.approval_workflow_approver_roles USING btree (workflow_id);


--
-- Name: ix_awrr_workflow; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_awrr_workflow ON public.approval_workflow_requestor_roles USING btree (workflow_id);


--
-- Name: ix_aws_workflow; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_aws_workflow ON public.approval_workflow_steps USING btree (workflow_id);


--
-- Name: ix_bank_stmt_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_bank_stmt_account ON public.bank_statements USING btree (account_id);


--
-- Name: ix_bank_tx_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_bank_tx_account ON public.bank_transactions USING btree (account_id);


--
-- Name: ix_bank_tx_account_date_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_bank_tx_account_date_desc ON public.bank_transactions USING btree (account_id, date DESC, id DESC);


--
-- Name: ix_bank_tx_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_bank_tx_category ON public.bank_transactions USING btree (category_id);


--
-- Name: ix_bank_tx_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_bank_tx_date ON public.bank_transactions USING btree (date);


--
-- Name: ix_bank_tx_match; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_bank_tx_match ON public.bank_transactions USING btree (match_number);


--
-- Name: ix_bank_tx_match_number; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_bank_tx_match_number ON public.bank_transactions USING btree (match_number);


--
-- Name: ix_bank_tx_payment_method; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_bank_tx_payment_method ON public.bank_transactions USING btree (payment_method);


--
-- Name: ix_bank_tx_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_bank_tx_type ON public.bank_transactions USING btree (type);


--
-- Name: ix_bank_tx_vendor; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_bank_tx_vendor ON public.bank_transactions USING btree (vendor_id);


--
-- Name: ix_budget_categories_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_budget_categories_id ON public.budget_categories USING btree (id);


--
-- Name: ix_budgets_category_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_budgets_category_id ON public.budgets USING btree (category_id);


--
-- Name: ix_budgets_department_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_budgets_department_id ON public.budgets USING btree (department_id);


--
-- Name: ix_budgets_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_budgets_id ON public.budgets USING btree (id);


--
-- Name: ix_budgets_year_month; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_budgets_year_month ON public.budgets USING btree (year, month);


--
-- Name: ix_cash_flows_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cash_flows_created_by ON public.cash_flows USING btree (created_by);


--
-- Name: ix_cash_flows_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cash_flows_date ON public.cash_flows USING btree (date);


--
-- Name: ix_cash_flows_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cash_flows_type ON public.cash_flows USING btree (type);


--
-- Name: ix_cc_stmt_product; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cc_stmt_product ON public.credit_card_statements USING btree (credit_product_id);


--
-- Name: ix_cc_tx_stmt; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cc_tx_stmt ON public.credit_card_transactions USING btree (statement_id);


--
-- Name: ix_checks_bank_tx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_checks_bank_tx ON public.checks USING btree (bank_transaction_id);


--
-- Name: ix_checks_due_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_checks_due_date ON public.checks USING btree (due_date);


--
-- Name: ix_checks_vendor_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_checks_vendor_code ON public.checks USING btree (vendor_code);


--
-- Name: ix_conversation_members_conv_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_conversation_members_conv_user ON public.conversation_members USING btree (conversation_id, user_id);


--
-- Name: ix_conversation_members_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_conversation_members_user_id ON public.conversation_members USING btree (user_id);


--
-- Name: ix_conversations_updated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_conversations_updated_at ON public.conversations USING btree (updated_at);


--
-- Name: ix_credit_payments_due_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_credit_payments_due_date ON public.credit_payments USING btree (due_date);


--
-- Name: ix_credit_payments_product; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_credit_payments_product ON public.credit_payments USING btree (credit_product_id);


--
-- Name: ix_credit_products_linked_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_credit_products_linked_account ON public.credit_products USING btree (linked_account_id);


--
-- Name: ix_credit_products_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_credit_products_status ON public.credit_products USING btree (status);


--
-- Name: ix_credit_products_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_credit_products_type ON public.credit_products USING btree (type);


--
-- Name: ix_departments_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_departments_code ON public.departments USING btree (code);


--
-- Name: ix_departments_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_departments_id ON public.departments USING btree (id);


--
-- Name: ix_error_logs_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_error_logs_created_at ON public.error_logs USING btree (created_at);


--
-- Name: ix_error_logs_level; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_error_logs_level ON public.error_logs USING btree (level);


--
-- Name: ix_error_logs_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_error_logs_source ON public.error_logs USING btree (source);


--
-- Name: ix_exchange_rates_currency_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exchange_rates_currency_code ON public.exchange_rates USING btree (currency_code);


--
-- Name: ix_exchange_rates_currency_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exchange_rates_currency_date ON public.exchange_rates USING btree (currency_code, date DESC);


--
-- Name: ix_exchange_rates_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exchange_rates_date ON public.exchange_rates USING btree (date);


--
-- Name: ix_messages_conv_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_messages_conv_created ON public.messages USING btree (conversation_id, created_at);


--
-- Name: ix_messages_conv_deleted_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_messages_conv_deleted_created ON public.messages USING btree (conversation_id, is_deleted, created_at);


--
-- Name: ix_messages_conversation_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_messages_conversation_created ON public.messages USING btree (conversation_id, created_at);


--
-- Name: ix_messages_is_deleted; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_messages_is_deleted ON public.messages USING btree (is_deleted);


--
-- Name: ix_messages_message_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_messages_message_type ON public.messages USING btree (message_type);


--
-- Name: ix_messages_sender_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_messages_sender_id ON public.messages USING btree (sender_id);


--
-- Name: ix_modules_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_modules_code ON public.modules USING btree (code);


--
-- Name: ix_notifications_user_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notifications_user_created ON public.notifications USING btree (user_id, created_at);


--
-- Name: ix_notifications_user_unread; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notifications_user_unread ON public.notifications USING btree (user_id, is_read);


--
-- Name: ix_pi_items_list; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pi_items_list ON public.payment_instruction_items USING btree (list_id);


--
-- Name: ix_push_subscriptions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_push_subscriptions_user_id ON public.push_subscriptions USING btree (user_id);


--
-- Name: ix_quality_form_values_form_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_quality_form_values_form_id ON public.quality_form_values USING btree (form_id);


--
-- Name: ix_quality_forms_period_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_quality_forms_period_date ON public.quality_forms USING btree (period_date);


--
-- Name: ix_quality_forms_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_quality_forms_status ON public.quality_forms USING btree (status);


--
-- Name: ix_quality_forms_template_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_quality_forms_template_id ON public.quality_forms USING btree (template_id);


--
-- Name: ix_quality_template_assignees_template_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_quality_template_assignees_template_type ON public.quality_template_assignees USING btree (template_id, assignment_type);


--
-- Name: ix_quality_template_fields_section_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_quality_template_fields_section_id ON public.quality_template_fields USING btree (section_id);


--
-- Name: ix_quality_template_sections_template_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_quality_template_sections_template_id ON public.quality_template_sections USING btree (template_id);


--
-- Name: ix_quality_templates_frequency; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_quality_templates_frequency ON public.quality_templates USING btree (frequency);


--
-- Name: ix_quality_templates_is_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_quality_templates_is_active ON public.quality_templates USING btree (is_active);


--
-- Name: ix_reservations_agency; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reservations_agency ON public.reservations USING btree (agency);


--
-- Name: ix_reservations_checkin_agency; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reservations_checkin_agency ON public.reservations USING btree (checkin_date, agency);


--
-- Name: ix_reservations_checkin_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reservations_checkin_date ON public.reservations USING btree (checkin_date);


--
-- Name: ix_reservations_checkin_nation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reservations_checkin_nation ON public.reservations USING btree (checkin_date, nation);


--
-- Name: ix_reservations_nation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reservations_nation ON public.reservations USING btree (nation);


--
-- Name: ix_reservations_rec_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_reservations_rec_id ON public.reservations USING btree (rec_id);


--
-- Name: ix_reservations_record_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reservations_record_date ON public.reservations USING btree (record_date);


--
-- Name: ix_reservations_room_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reservations_room_type ON public.reservations USING btree (room_type);


--
-- Name: ix_room_types_is_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_room_types_is_active ON public.room_types USING btree (is_active);


--
-- Name: ix_room_types_sort_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_room_types_sort_order ON public.room_types USING btree (sort_order);


--
-- Name: ix_scheddef_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scheddef_active ON public.scheduled_definitions USING btree (is_active);


--
-- Name: ix_scheddef_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scheddef_type ON public.scheduled_definitions USING btree (source_type);


--
-- Name: ix_schedentry_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_schedentry_date ON public.scheduled_entries USING btree (entry_date);


--
-- Name: ix_schedentry_paid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_schedentry_paid ON public.scheduled_entries USING btree (is_paid);


--
-- Name: ix_schedentry_period; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_schedentry_period ON public.scheduled_entries USING btree (source_type, period_year, period_month);


--
-- Name: ix_schedentry_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_schedentry_source ON public.scheduled_entries USING btree (source_type, definition_id);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: ix_users_role_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_role_id ON public.users USING btree (role_id);


--
-- Name: ix_users_username; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_username ON public.users USING btree (username);


--
-- Name: ix_vendor_tx_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vendor_tx_date ON public.vendor_transactions USING btree (date);


--
-- Name: ix_vendor_tx_match; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vendor_tx_match ON public.vendor_transactions USING btree (match_number);


--
-- Name: ix_vendor_tx_payment_due; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vendor_tx_payment_due ON public.vendor_transactions USING btree (payment_due_date);


--
-- Name: ix_vendor_tx_upload; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vendor_tx_upload ON public.vendor_transactions USING btree (upload_id);


--
-- Name: ix_vendor_tx_vendor; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vendor_tx_vendor ON public.vendor_transactions USING btree (vendor_id);


--
-- Name: ix_vendors_hesap_kodu; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vendors_hesap_kodu ON public.vendors USING btree (hesap_kodu);


--
-- Name: ix_vtx_department; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vtx_department ON public.vendor_transactions USING btree (department_id);


--
-- Name: ix_vtx_dept_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vtx_dept_status ON public.vendor_transactions USING btree (dept_status);


--
-- Name: advances advances_bank_transaction_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.advances
    ADD CONSTRAINT advances_bank_transaction_id_fkey FOREIGN KEY (bank_transaction_id) REFERENCES public.bank_transactions(id) ON DELETE SET NULL;


--
-- Name: advances advances_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.advances
    ADD CONSTRAINT advances_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: approval_request_logs approval_request_logs_actor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_request_logs
    ADD CONSTRAINT approval_request_logs_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: approval_request_logs approval_request_logs_request_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_request_logs
    ADD CONSTRAINT approval_request_logs_request_id_fkey FOREIGN KEY (request_id) REFERENCES public.approval_requests(id) ON DELETE CASCADE;


--
-- Name: approval_requests approval_requests_completed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT approval_requests_completed_by_fkey FOREIGN KEY (completed_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: approval_requests approval_requests_requested_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT approval_requests_requested_by_fkey FOREIGN KEY (requested_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: approval_requests approval_requests_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT approval_requests_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.approval_workflows(id) ON DELETE SET NULL;


--
-- Name: approval_workflow_approver_roles approval_workflow_approver_roles_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflow_approver_roles
    ADD CONSTRAINT approval_workflow_approver_roles_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;


--
-- Name: approval_workflow_approver_roles approval_workflow_approver_roles_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflow_approver_roles
    ADD CONSTRAINT approval_workflow_approver_roles_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.approval_workflows(id) ON DELETE CASCADE;


--
-- Name: approval_workflow_requestor_roles approval_workflow_requestor_roles_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflow_requestor_roles
    ADD CONSTRAINT approval_workflow_requestor_roles_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;


--
-- Name: approval_workflow_requestor_roles approval_workflow_requestor_roles_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflow_requestor_roles
    ADD CONSTRAINT approval_workflow_requestor_roles_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.approval_workflows(id) ON DELETE CASCADE;


--
-- Name: approval_workflow_steps approval_workflow_steps_approver_dept_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflow_steps
    ADD CONSTRAINT approval_workflow_steps_approver_dept_id_fkey FOREIGN KEY (approver_dept_id) REFERENCES public.departments(id) ON DELETE SET NULL;


--
-- Name: approval_workflow_steps approval_workflow_steps_approver_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflow_steps
    ADD CONSTRAINT approval_workflow_steps_approver_role_id_fkey FOREIGN KEY (approver_role_id) REFERENCES public.roles(id) ON DELETE SET NULL;


--
-- Name: approval_workflow_steps approval_workflow_steps_approver_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflow_steps
    ADD CONSTRAINT approval_workflow_steps_approver_user_id_fkey FOREIGN KEY (approver_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: approval_workflow_steps approval_workflow_steps_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflow_steps
    ADD CONSTRAINT approval_workflow_steps_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.approval_workflows(id) ON DELETE CASCADE;


--
-- Name: approval_workflows approval_workflows_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflows
    ADD CONSTRAINT approval_workflows_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: audit_logs audit_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: bank_accounts bank_accounts_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bank_accounts
    ADD CONSTRAINT bank_accounts_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: bank_statements bank_statements_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bank_statements
    ADD CONSTRAINT bank_statements_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.bank_accounts(id) ON DELETE CASCADE;


--
-- Name: bank_statements bank_statements_uploaded_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bank_statements
    ADD CONSTRAINT bank_statements_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: bank_transactions bank_transactions_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bank_transactions
    ADD CONSTRAINT bank_transactions_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.bank_accounts(id) ON DELETE CASCADE;


--
-- Name: bank_transactions bank_transactions_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bank_transactions
    ADD CONSTRAINT bank_transactions_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.transaction_categories(id) ON DELETE SET NULL;


--
-- Name: bank_transactions bank_transactions_statement_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bank_transactions
    ADD CONSTRAINT bank_transactions_statement_id_fkey FOREIGN KEY (statement_id) REFERENCES public.bank_statements(id) ON DELETE SET NULL;


--
-- Name: bank_transactions bank_transactions_vendor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bank_transactions
    ADD CONSTRAINT bank_transactions_vendor_id_fkey FOREIGN KEY (vendor_id) REFERENCES public.vendors(id) ON DELETE SET NULL;


--
-- Name: budgets budgets_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budgets
    ADD CONSTRAINT budgets_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.budget_categories(id) ON DELETE CASCADE;


--
-- Name: budgets budgets_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budgets
    ADD CONSTRAINT budgets_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: budgets budgets_department_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budgets
    ADD CONSTRAINT budgets_department_id_fkey FOREIGN KEY (department_id) REFERENCES public.departments(id) ON DELETE CASCADE;


--
-- Name: cash_flows cash_flows_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_flows
    ADD CONSTRAINT cash_flows_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: check_uploads check_uploads_uploaded_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.check_uploads
    ADD CONSTRAINT check_uploads_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: checks checks_bank_transaction_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.checks
    ADD CONSTRAINT checks_bank_transaction_id_fkey FOREIGN KEY (bank_transaction_id) REFERENCES public.bank_transactions(id) ON DELETE SET NULL;


--
-- Name: checks checks_matched_vendor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.checks
    ADD CONSTRAINT checks_matched_vendor_id_fkey FOREIGN KEY (matched_vendor_id) REFERENCES public.vendors(id) ON DELETE SET NULL;


--
-- Name: checks checks_upload_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.checks
    ADD CONSTRAINT checks_upload_id_fkey FOREIGN KEY (upload_id) REFERENCES public.check_uploads(id) ON DELETE CASCADE;


--
-- Name: conversation_members conversation_members_conversation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_members
    ADD CONSTRAINT conversation_members_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversations(id) ON DELETE CASCADE;


--
-- Name: conversation_members conversation_members_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_members
    ADD CONSTRAINT conversation_members_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: credit_card_statements credit_card_statements_credit_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credit_card_statements
    ADD CONSTRAINT credit_card_statements_credit_product_id_fkey FOREIGN KEY (credit_product_id) REFERENCES public.credit_products(id) ON DELETE CASCADE;


--
-- Name: credit_card_transactions credit_card_transactions_statement_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credit_card_transactions
    ADD CONSTRAINT credit_card_transactions_statement_id_fkey FOREIGN KEY (statement_id) REFERENCES public.credit_card_statements(id) ON DELETE CASCADE;


--
-- Name: credit_payments credit_payments_bank_transaction_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credit_payments
    ADD CONSTRAINT credit_payments_bank_transaction_id_fkey FOREIGN KEY (bank_transaction_id) REFERENCES public.bank_transactions(id) ON DELETE SET NULL;


--
-- Name: credit_payments credit_payments_credit_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credit_payments
    ADD CONSTRAINT credit_payments_credit_product_id_fkey FOREIGN KEY (credit_product_id) REFERENCES public.credit_products(id) ON DELETE CASCADE;


--
-- Name: credit_products credit_products_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credit_products
    ADD CONSTRAINT credit_products_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: credit_products credit_products_linked_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credit_products
    ADD CONSTRAINT credit_products_linked_account_id_fkey FOREIGN KEY (linked_account_id) REFERENCES public.bank_accounts(id) ON DELETE SET NULL;


--
-- Name: departments departments_manager_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.departments
    ADD CONSTRAINT departments_manager_id_fkey FOREIGN KEY (manager_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: finance_events finance_events_bank_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_events
    ADD CONSTRAINT finance_events_bank_account_id_fkey FOREIGN KEY (bank_account_id) REFERENCES public.bank_accounts(id) ON DELETE SET NULL;


--
-- Name: finance_events finance_events_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_events
    ADD CONSTRAINT finance_events_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.transaction_categories(id) ON DELETE SET NULL;


--
-- Name: finance_events finance_events_matched_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_events
    ADD CONSTRAINT finance_events_matched_event_id_fkey FOREIGN KEY (matched_event_id) REFERENCES public.finance_events(id) ON DELETE SET NULL;


--
-- Name: finance_events finance_events_vendor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_events
    ADD CONSTRAINT finance_events_vendor_id_fkey FOREIGN KEY (vendor_id) REFERENCES public.vendors(id) ON DELETE SET NULL;


--
-- Name: approval_workflows fk_aw_module; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_workflows
    ADD CONSTRAINT fk_aw_module FOREIGN KEY (module_id) REFERENCES public.modules(id) ON DELETE SET NULL;


--
-- Name: conversations fk_conversations_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversations
    ADD CONSTRAINT fk_conversations_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: users fk_users_role_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT fk_users_role_id FOREIGN KEY (role_id) REFERENCES public.roles(id);


--
-- Name: vendor_transactions fk_vtx_budget_category; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vendor_transactions
    ADD CONSTRAINT fk_vtx_budget_category FOREIGN KEY (budget_category_id) REFERENCES public.budget_categories(id) ON DELETE SET NULL;


--
-- Name: vendor_transactions fk_vtx_department; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vendor_transactions
    ADD CONSTRAINT fk_vtx_department FOREIGN KEY (department_id) REFERENCES public.departments(id) ON DELETE SET NULL;


--
-- Name: vendor_transactions fk_vtx_dept_approved_by; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vendor_transactions
    ADD CONSTRAINT fk_vtx_dept_approved_by FOREIGN KEY (dept_approved_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: vendor_transactions fk_vtx_dept_assigned_by; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vendor_transactions
    ADD CONSTRAINT fk_vtx_dept_assigned_by FOREIGN KEY (dept_assigned_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: messages messages_conversation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversations(id) ON DELETE CASCADE;


--
-- Name: messages messages_sender_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_sender_id_fkey FOREIGN KEY (sender_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: modules modules_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.modules
    ADD CONSTRAINT modules_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.modules(id);


--
-- Name: notifications notifications_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: payment_instruction_items payment_instruction_items_list_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_instruction_items
    ADD CONSTRAINT payment_instruction_items_list_id_fkey FOREIGN KEY (list_id) REFERENCES public.payment_instruction_lists(id) ON DELETE CASCADE;


--
-- Name: payment_instruction_items payment_instruction_items_vendor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_instruction_items
    ADD CONSTRAINT payment_instruction_items_vendor_id_fkey FOREIGN KEY (vendor_id) REFERENCES public.vendors(id) ON DELETE SET NULL;


--
-- Name: payment_instruction_lists payment_instruction_lists_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payment_instruction_lists
    ADD CONSTRAINT payment_instruction_lists_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: push_subscriptions push_subscriptions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.push_subscriptions
    ADD CONSTRAINT push_subscriptions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: quality_form_values quality_form_values_field_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_form_values
    ADD CONSTRAINT quality_form_values_field_id_fkey FOREIGN KEY (field_id) REFERENCES public.quality_template_fields(id) ON DELETE CASCADE;


--
-- Name: quality_form_values quality_form_values_form_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_form_values
    ADD CONSTRAINT quality_form_values_form_id_fkey FOREIGN KEY (form_id) REFERENCES public.quality_forms(id) ON DELETE CASCADE;


--
-- Name: quality_forms quality_forms_filled_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_forms
    ADD CONSTRAINT quality_forms_filled_by_fkey FOREIGN KEY (filled_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: quality_forms quality_forms_reviewed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_forms
    ADD CONSTRAINT quality_forms_reviewed_by_fkey FOREIGN KEY (reviewed_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: quality_forms quality_forms_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_forms
    ADD CONSTRAINT quality_forms_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.quality_templates(id) ON DELETE RESTRICT;


--
-- Name: quality_template_assignees quality_template_assignees_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_template_assignees
    ADD CONSTRAINT quality_template_assignees_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;


--
-- Name: quality_template_assignees quality_template_assignees_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_template_assignees
    ADD CONSTRAINT quality_template_assignees_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.quality_templates(id) ON DELETE CASCADE;


--
-- Name: quality_template_assignees quality_template_assignees_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_template_assignees
    ADD CONSTRAINT quality_template_assignees_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: quality_template_fields quality_template_fields_section_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_template_fields
    ADD CONSTRAINT quality_template_fields_section_id_fkey FOREIGN KEY (section_id) REFERENCES public.quality_template_sections(id) ON DELETE CASCADE;


--
-- Name: quality_template_sections quality_template_sections_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_template_sections
    ADD CONSTRAINT quality_template_sections_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.quality_templates(id) ON DELETE CASCADE;


--
-- Name: quality_templates quality_templates_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quality_templates
    ADD CONSTRAINT quality_templates_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: reservation_uploads reservation_uploads_uploaded_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reservation_uploads
    ADD CONSTRAINT reservation_uploads_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: reservations reservations_upload_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reservations
    ADD CONSTRAINT reservations_upload_id_fkey FOREIGN KEY (upload_id) REFERENCES public.reservation_uploads(id) ON DELETE SET NULL;


--
-- Name: role_module_permissions role_module_permissions_module_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_module_permissions
    ADD CONSTRAINT role_module_permissions_module_id_fkey FOREIGN KEY (module_id) REFERENCES public.modules(id) ON DELETE CASCADE;


--
-- Name: role_module_permissions role_module_permissions_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_module_permissions
    ADD CONSTRAINT role_module_permissions_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;


--
-- Name: scheduled_definitions scheduled_definitions_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_definitions
    ADD CONSTRAINT scheduled_definitions_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: scheduled_entries scheduled_entries_definition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduled_entries
    ADD CONSTRAINT scheduled_entries_definition_id_fkey FOREIGN KEY (definition_id) REFERENCES public.scheduled_definitions(id) ON DELETE CASCADE;


--
-- Name: vendor_transactions vendor_transactions_upload_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vendor_transactions
    ADD CONSTRAINT vendor_transactions_upload_id_fkey FOREIGN KEY (upload_id) REFERENCES public.vendor_uploads(id) ON DELETE CASCADE;


--
-- Name: vendor_transactions vendor_transactions_vendor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vendor_transactions
    ADD CONSTRAINT vendor_transactions_vendor_id_fkey FOREIGN KEY (vendor_id) REFERENCES public.vendors(id) ON DELETE CASCADE;


--
-- Name: vendor_uploads vendor_uploads_uploaded_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vendor_uploads
    ADD CONSTRAINT vendor_uploads_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- PostgreSQL database dump complete
--

\unrestrict JCfJ9egWWkp4mORgUo9YnuytLbY9OrfoohlXFVSzkRVqIxlemVbphkeD2YW9LPu

