# Build Log: Northwind Bank Dispute Agent

A running record of what was built, why, and what went wrong. Newest phase at the bottom.

---

## Phase 1: Policy, database, seed data

**Completed:** 2026-11-21 · **Commits:** `45bfae6`, `a74c27f`, `4191019`

### What we built

| Piece | File | Purpose |
|---|---|---|
| Project rules | `CLAUDE.md` | Customer requirements, stack, secrets rules, way of working |
| DB connection | `src/db.py` | The single place that knows how to reach Supabase |
| Policy | `data/policy.md` | 12 rules with stable IDs (P1–P12), enforcement map, open questions |
| Schema | `data/schema.sql` + `src/setup_db.py` | 7 tables with foreign keys, safety constraints, RLS |
| Seed data | `src/seed.py` | 30 customers, 44 cards, 675 transactions, 10 edge-case customers |
| Reset | `src/reset_db.py` | Wipe and re-seed in about 2s, run before every eval |
| Demo cheat sheet | `data/demo_customers.json` | Verification details and transaction IDs for each edge case |

### Key decisions and why

**1. A fictional, simplified policy (with rule IDs).**
Real dispute rules (Reg E, card-network rules) are long and legally specific. Getting them wrong
in a portfolio project would be worse than not using them. A fictional policy keeps the focus
on the real skill: turning a customer's written rules into enforceable, testable behavior.
Each rule has an ID (P1–P12) so code, audit log reasons and evals can all cite the same rule.
- **Enforcement map:** each rule is labeled as enforced in **code** (money, identity, dates and
  limits, which the LLM can't talk around) or in the **prompt + evals** (judgment calls like
  spotting a non-cardholder or a customer backing off a fraud claim).
- **Open questions:** six ambiguities found in the policy (e.g. for a $700 fraud claim, is $500
  credited automatically or the whole amount escalated?), each with a documented interpretation.
  The default is to choose the option that moves no money without a person approving it.

**2. Supabase (hosted Postgres) instead of SQLite.**
- It's closer to production: a networked database with credentials, roles and connection pooling,
  which is what an agent at a real bank would talk to.
- Postgres features the design depends on: `NUMERIC` for exact money, `TIMESTAMPTZ` for UTC
  audit times, `JSONB` for audit log inputs and results, `CHECK`/`UNIQUE` constraints, and
  transactional DDL (the schema applies all-or-nothing).
- It forced handling secrets properly from day one (`.env`, never printed).
- Trade-off: every query is a network round trip. Seeding about 700 rows one at a time would take
  around a minute, so inserts are batched with psycopg pipeline mode (`executemany(...,
  returning=True)`) and a full reset takes about 2s.

**3. RLS lockdown on every table.**
Supabase automatically exposes tables through a public REST API. For bank data that's an open door.
Row level security is on for all 7 tables with **no policies**, so the API roles see nothing.
Our Python connection logs in as the table owner, which bypasses RLS, so the agent's own tools
are the only way in.

**4. The database itself enforces the policy where it can (defense in depth).**
Even if the agent code has a bug:
- `disputes.transaction_id UNIQUE`: no duplicate disputes (P8)
- `credits.dispute_id UNIQUE`: no paying out twice on one dispute
- `credits.amount <= 500`: no credit above the highest policy limit
- `last4` must be exactly 4 digits: there's nowhere to store a full card number (P3)
- `audit_log` has no foreign keys, so it can record refused or failed actions too

**5. Deterministic seed data with a fixed "today" (2026-11-20).**
Fixed random seed + fixed date + `TRUNCATE ... RESTART IDENTITY` = the same customers, card numbers
and transaction IDs on every reset (checked: two runs produce byte-identical
`demo_customers.json`). Evals can refer to specific IDs, and a pass means the same thing every day.
Last4 is unique across all cards, so last4 + DOB + ZIP always identifies exactly one card.

**6. The edge cases chosen: one per policy boundary, one per customer.**
Each tests a place where the agent could plausibly get it wrong:

| Edge case | Tests | Why it's tricky |
|---|---|---|
| $480 fraud, 10d ago | P6 auto credit | Happy path, just under the $500 limit |
| $700 fraud, 5d ago | P6 escalation | Must file the dispute but **not** credit it |
| $120 non-delivery | P7 auto credit | Merchant path, must ask "did you contact the merchant?" |
| $300 merchant issue | P7 escalation | Over the $250 merchant limit |
| $60 charged twice | P7 duplicate charge | Which of two identical transactions to dispute |
| 59d / 61d old | P5 window | Boundary on both sides of 60 days |
| Pending txn | P5 status | Looks disputable but isn't yet |
| Already disputed | P8 duplicates | Customer may not remember they already filed |
| 3 disputes in 90d | P8 limit | Fourth one must escalate, not file |
| Card already frozen | P6 freeze | Freezing must be safe to repeat; the dispute must still be filed |

Background spending is kept under $250, so random data can never accidentally trigger an edge case.

### Problems hit and how we fixed them

**1. The `.env` connection string wasn't real (three separate problems).**
- *Symptom 1:* `FATAL: tenant/user postgres.xxxx not found`, then the same error with
  `postgres.abcdefghijk`. Both were placeholder project references, so Supabase's shared pooler
  couldn't find which project to route to.
- *Symptom 2:* `RuntimeError: DATABASE_URL is not set`, even though `.env` existed.
- *Diagnosis without reading the secret:* a small script that printed only the file's encoding,
  line count and **key names** (never values). It showed line 2 had no `=`: the connection string
  had been pasted without `DATABASE_URL=` in front of it.
- *Fix:* copy the exact **Session pooler** string from Supabase (Connect → Session pooler) and put
  `DATABASE_URL=` in front of it.
- *Lesson:* an earlier "connected" message was accepted at face value even though it didn't match
  the script's actual output. Verify with the real output, not a summary of it.

**2. Git Bash ate the backslashes.**
`! .venv\Scripts\python.exe` became `.venvScriptspython.exe: command not found`, because the
Claude Code `!` prefix runs in Git Bash, where `\` is an escape character.
*Fix:* use forward slashes (`.venv/Scripts/python.exe`) in Bash. Backslashes are fine in PowerShell.

**3. The anon permission test failed in an unexpected way.**
The test inserted a row, switched to Supabase's public `anon` role and counted rows. Expected:
`0 rows` (RLS hiding them). Actual: `permission denied for table customers`.
*Why:* this Supabase project doesn't grant `anon` access to newly created tables, so the API was
blocked by table permissions before RLS was even checked. It wasn't a bug but a second layer of
protection. RLS stays on so the data is still protected if someone later grants `anon` access.
The test ran in a transaction that was rolled back, so no test data was left behind.

### What I'd say in an interview

> "Before writing any agent code, I turned the bank's policy into rules with IDs, found six
> ambiguities and resolved them in favor of no money moving without a human, and made the database
> itself refuse duplicate disputes, double payouts and over-limit credits, so the AI can't break
> those rules even if the prompt fails."

---
