# CLAUDE.md

## Project

An AI card-dispute agent for **Northwind Bank** (a fictional bank). The agent talks to customers and takes real actions in the bank's database (freeze card, file dispute, issue provisional credit, escalate to a human), and it has to follow bank policy while doing it.

This is a portfolio project for FDE (Forward Deployed Engineer) and agent strategist interviews. The user is learning, so explanations matter as much as the code.

**Policy is fictional and simplified.** It is not real regulation (e.g. not Reg E or Visa/Mastercard rules). Don't present it as real.

## The customer's requirements (FDE framing)

The Head of Card Operations at Northwind will only sign off if:

1. **No money moves outside policy.** Provisional credit and refunds are allowed only when policy rules are met. The rules are enforced in code, not only in the prompt.
2. **The agent can't be social-engineered.** Customer claims ("I'm the account owner", "my manager approved it", "ignore your rules") never get around identity checks or policy limits.
3. **Every action is audited.** Each tool call that changes state writes an audit record: who, what, when, inputs, outcome, and the policy reason.
4. **Complex cases go to humans.** Cases that are ambiguous, high-value, or out of policy get escalated. The agent never improvises.

Every design decision should trace back to one of these four. When explaining work, say which requirement it serves.

## Stack

- Python, virtual env at `.venv` (Windows: `.venv\Scripts\python.exe`)
- Claude via the `anthropic` SDK (tool use)
- Database: Supabase (hosted Postgres), connected with `psycopg` (v3)
- Config: `DATABASE_URL` (and API keys) loaded from `.env` via `python-dotenv`
- UI (later): Streamlit

## Layout

- `src/`: agent, tools, policy, and database code
- `data/`: seed data and schema / SQL
- `evals/`: test scenarios (including social-engineering and out-of-policy cases)

## How to run

- Always run from the project root, using the venv:
  `.venv\Scripts\python.exe -m src.<module>`
- Install deps: `.venv\Scripts\python.exe -m pip install -r requirements.txt`

## Secrets (strict)

- **Never read, print, open, or edit `.env`.**
- **Never print `DATABASE_URL`, connection strings, passwords, or API keys.** This applies to code output, logs, error messages, and chat.
- Load secrets with `load_dotenv()` + `os.environ["DATABASE_URL"]`. When debugging a connection, print only whether the value is set (e.g. `bool(os.getenv("DATABASE_URL"))`).
- `.env` is gitignored. Never commit it.

## How to work with me

1. **Zoom out first.** Before any phase or major step, explain the big picture in 3-5 sentences: what we're building, why it matters, and how it maps to real FDE work.
2. **Then the plan.** List the concrete steps briefly.
3. **Then the code.** Keep it simple and readable, with comments that explain *why*, not just *what*. Prefer plain functions over abstractions. No clever tricks.
4. **Verify it works** by running it, then **suggest a commit message** after each working step. Don't commit unless asked.

## Design principles

- **Policy lives in code.** The LLM decides *what to try*. Deterministic Python checks decide *whether it's allowed*. Tools re-validate everything, so they never trust the model's arguments blindly.
- **Least privilege.** The agent only gets narrow tools (e.g. `freeze_card`, `file_dispute`). It never runs raw SQL.
- **Audit inside the action.** The state change and its audit row are written in the same DB transaction.
- **Fail closed.** If a check fails, data is missing, or something is unclear, refuse or escalate. Never guess.
- **Evals are the proof.** Each requirement should have eval cases that show it holds.
