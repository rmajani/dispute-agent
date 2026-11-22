-- Northwind Bank (fictional) dispute agent schema.
-- Run by src/setup_db.py. WARNING: drops and recreates every table, so all data is lost.

-- ---------------------------------------------------------------
-- 1. Drop old tables. Children are dropped before parents, because a parent
--    can't be dropped while other tables still point at it.
--    CASCADE also removes anything else that depends on them.
-- ---------------------------------------------------------------
DROP TABLE IF EXISTS audit_log    CASCADE;
DROP TABLE IF EXISTS escalations  CASCADE;
DROP TABLE IF EXISTS credits      CASCADE;
DROP TABLE IF EXISTS disputes     CASCADE;
DROP TABLE IF EXISTS transactions CASCADE;
DROP TABLE IF EXISTS cards        CASCADE;
DROP TABLE IF EXISTS customers    CASCADE;

-- ---------------------------------------------------------------
-- 2. Core bank data (the "systems of record" the agent reads)
-- ---------------------------------------------------------------

CREATE TABLE customers (
    id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- auto-numbered 1, 2, 3...
    name   TEXT NOT NULL,
    dob    DATE NOT NULL,          -- used for identity check (P2)
    zip    TEXT NOT NULL,          -- billing ZIP, used for identity check (P2)
    email  TEXT NOT NULL
);

CREATE TABLE cards (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id  BIGINT NOT NULL REFERENCES customers(id),   -- foreign key: card belongs to a real customer
    last4        TEXT NOT NULL CHECK (last4 ~ '^[0-9]{4}$'), -- exactly 4 digits; we never store full numbers (P3)
    status       TEXT NOT NULL DEFAULT 'active'
                 CHECK (status IN ('active', 'frozen'))
);

CREATE TABLE transactions (
    id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    card_id   BIGINT NOT NULL REFERENCES cards(id),
    merchant  TEXT NOT NULL,
    amount    NUMERIC(10,2) NOT NULL CHECK (amount > 0),  -- NUMERIC, not float: exact cents for money
    txn_date  DATE NOT NULL,                              -- used for the 60-day window (P5)
    status    TEXT NOT NULL CHECK (status IN ('posted', 'pending'))  -- pending can't be disputed (P5)
);

-- ---------------------------------------------------------------
-- 3. Agent actions (what the agent writes)
-- ---------------------------------------------------------------

CREATE TABLE disputes (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- UNIQUE = the database itself refuses a second dispute on the same transaction (P8),
    -- even if the agent code has a bug.
    transaction_id  BIGINT NOT NULL UNIQUE REFERENCES transactions(id),
    customer_id     BIGINT NOT NULL REFERENCES customers(id),
    type            TEXT NOT NULL CHECK (type IN ('fraud', 'merchant')),
    reason          TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()   -- stored in UTC
);

CREATE TABLE credits (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- UNIQUE = at most one provisional credit per dispute: no double payouts (requirement 1).
    dispute_id  BIGINT NOT NULL UNIQUE REFERENCES disputes(id),
    -- Backstop: no single credit can exceed the highest policy limit ($500, P6).
    -- The exact per-type limit ($500 fraud / $250 merchant) is checked in Python.
    amount      NUMERIC(10,2) NOT NULL CHECK (amount > 0 AND amount <= 500),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE escalations (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- Nullable on purpose: a caller who fails identity checks (P2) gets escalated
    -- before we know which customer they are.
    customer_id  BIGINT REFERENCES customers(id),
    reason       TEXT NOT NULL,     -- short code/rule, e.g. 'P10: asked for human'
    summary      TEXT NOT NULL,     -- handoff notes so the human doesn't start from zero
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The audit log deliberately has NO foreign keys: it must be able to record anything,
-- including failed or refused actions that reference rows that don't exist.
CREATE TABLE audit_log (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    tool        TEXT NOT NULL,      -- which tool was called, e.g. 'freeze_card'
    inputs      JSONB NOT NULL,     -- the arguments the agent passed
    result      JSONB NOT NULL,     -- what happened (success, refusal, error)
    reason      TEXT NOT NULL       -- why, citing a policy rule ID (P11)
);

-- ---------------------------------------------------------------
-- 4. Row level security: lock out Supabase's public API.
--    With RLS on and NO policies, the API roles (anon / authenticated) see zero rows.
--    Our direct connection logs in as the table owner (postgres), which bypasses RLS.
-- ---------------------------------------------------------------
ALTER TABLE customers    ENABLE ROW LEVEL SECURITY;
ALTER TABLE cards        ENABLE ROW LEVEL SECURITY;
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE disputes     ENABLE ROW LEVEL SECURITY;
ALTER TABLE credits      ENABLE ROW LEVEL SECURITY;
ALTER TABLE escalations  ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log    ENABLE ROW LEVEL SECURITY;
