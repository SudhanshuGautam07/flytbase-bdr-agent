# BDR Intelligence Agent
**FlytBase Outbound Hackathon Submission**

> A working, evidence-first multi-agent system that takes a campaign brief and autonomously produces ICP-qualified accounts, verified contacts, research briefs, and fact-checked personalized outreach emails — with a live trace of every agent decision and every failure.

---

## 1. What it does (the loop)

```
┌────────────────────────────────────────────────────────────────────────────┐
│  CAMPAIGN BRIEF                                                            │
│  "Large-scale lithium/copper/iron-ore mining, Latin America,              │
│   anchor: SQM, personas: Head of Ops / VP HSE / Site Directors"           │
└──────────────────────────────────┬─────────────────────────────────────────┘
                                   ▼
   A1  ICP INTEL          fingerprint the anchor (SQM) from live Wikipedia + news
   A2  ACCOUNT DISCOVERY  BDR seed pool + live web search → candidate companies
   A3  ACCOUNT VERIFY     per account: fetch site + news + search → ICP-fit verdict
                          with cited evidence (claim / source / URL / extract / confidence)
   A4  CONTACT DISCOVERY  per account: people search + appointments news + /about page
   A5  CONTACT VERIFY     per contact: is this a real person, current, right role?
   A6  DEEP RESEARCH      per account: profile / recent events / ops / tech / safety
                          signals / opportunities (facts vs inferences, clearly marked)
   A7  PERSONALIZATION    per contact: human-sounding email grounded ONLY in A6 research
   A8  FACT CHECKER       extract every claim → judge each against the evidence bundle
                          → rewrite any email with unsupported claims
                                   ▼
        OUTPUT: accounts + contacts + research briefs + final emails (CSV exportable)
        plus a full agent trace and a record of every failure + fix
```

## 2. Live system

| Component | Where | What |
|---|---|---|
| **Dashboard** | `http://localhost:8000` (deployed link: TBD) | Run a campaign, watch the live agent trace, browse accounts/contacts/emails/research, export CSV |
| **n8n (agent brain)** | `http://localhost:5678` | 12 workflows: 3 tools + 8 agents + master orchestrator |
| **FastAPI + JSON store** | `:8000` + `data/store.json` | Single source of truth; n8n ingests every artifact here |
| **Trigger** | `POST /webhook/master` | `{vertical, geography, reference_account, target_roles, solution, max_accounts}` |

**Run it:** `bash bootstrap.sh` (installs n8n if missing, starts both services, imports the 12 workflows).

## 3. Architecture mind-map

```
                          ┌──────────────────────────────┐
                          │   MASTER ORCHESTRATOR        │
                          │   webhook /webhook/master    │
                          │   per-stage: start-log →     │
                          │   input → exec agent →       │
                          │   end-log → carry context    │
                          └──────────────┬───────────────┘
        ┌───────────┬──────────┬─────────┼─────────┬──────────┬──────────┬──────────┐
        ▼           ▼          ▼         ▼         ▼          ▼          ▼          ▼
      A1 ICP    A2 Discover A3 Verify A4 Contacts A5 Verify  A6 Research A7 Email  A8 Fact-
                          ┌──┴───────────────────────┴──┐              Checker
                          ▼          ▼                   ▼
                     TOOLS_search  TOOLS_llm       TOOLS_fetch
        (Brave/Serper/Tavily/     (OpenAI/Gemini/  (page → clean text)
         Google-News-RSS fallback) Anthropic, fail-safe)
        │
        └──► every search batch, every artifact is ingested into the
             FastAPI evidence store (data/store.json) → dashboard + CSV
```

**Why n8n = the brain:** visual, auditable, per-node failure outputs, webhook-triggered — and every agent is an independent sub-workflow with a strict input/output contract, so each stage can be tested, replayed, and swapped.

**Why FastAPI owns state (not n8n):** n8n Code nodes have no filesystem access and per-node context is not shared — so all durable state lives in one locked JSON store that agents *push* to (POST /api/ingest) and *pull* from (GET /api/accounts, /api/evidence_bundle, …). The store is the single source of truth; n8n is stateless compute.

## 4. Research quality — evidence-first by construction

1. **No fabricated data.** Every agent prompt carries a hard rule: *only use what is in the provided evidence; never invent names, companies, roles, emails, numbers, or dates.* The contact agent must return `[]` rather than guess.
2. **Structured evidence schema.** Account verification and contact verification must output: `{claim, source, url, published, extract (verbatim quote), confidence}`. A qualified account needs ≥4 ICP criteria matched *with* evidence.
3. **Live research, logged.** Every search batch (query, provider, results) is ingested and shown in the dashboard — the "evidence collected" count is real and inspectable.
4. **Facts vs inferences.** The research brief marks every item `is_inference`; the email writer must hedge inferences ("it looks like") and may only cite research facts.
5. **Claim-level fact-check (A8).** After emails are written, every factual claim is extracted and judged against the evidence bundle: `supported / partial / unsupported`. Any `unsupported` claim triggers a rewrite pass. The final email ships with its verdict report visible in the dashboard.
6. **Keyless-safe.** With no search API key the system degrades to Google News RSS + Wikipedia API + company site fetches — it still researches, it just less deeply.

## 5. Thought process — design decisions & state

- **Sequential pipeline, parallel nothing-by-accident.** Stages run in order (each needs the previous stage's output); within a stage, per-entity loops use n8n SplitInBatches with throttling (1.5s between search calls — respectful of rate limits and providers).
- **Every sub-agent returns exactly one result item** — real result, `failed` (with reason), or `skipped` (with reason, e.g. "no qualified accounts upstream"). The master logs each as an `agent_run` record; the dashboard's agent trace is built directly from these. A stage can never silently vanish.
- **Failure policy:** a stage failure is recorded, downstream stages skip gracefully, and the campaign ends `completed_with_failures` with the exact failing stage and error visible — never a silent success, never a hard crash.
- **Context passing:** the master carries `{campaign, kb, icp, candidates, qualified_accounts, contacts, verified_contacts, research, emails}` between stages; each sub also re-fetches ground truth from the store (store > memory).

## 6. Failures we hit (and fixed) — the honest log

| # | Failure | Symptom | Root cause | Fix |
|---|---|---|---|---|
| 1 | n8n 2.8.4 blocks `$env` by default | LLM/search calls failed with "access to env vars denied" | env access requires `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` explicitly | set in `start_n8n.sh` / `bootstrap.sh` |
| 2 | API keys sent literally | OpenAI: "Incorrect API key: `{{ $env.OPENAI_API_KEY }}`" | strings inside a fixedCollection are only evaluated when the *whole* value starts with `=` | headers rewritten as full expressions `={{ 'Bearer ' + $env.OPENAI_API_KEY }}` |
| 3 | `onError` ignored | HTTP failures killed sub-workflows instead of routing to fail-nodes | in n8n 2.x `onError` is a **node-level** field, not a parameter | moved to node root in generator |
| 4 | Switch fallback silently dropped items | discovery LLM never called; run ended early as "success" | `fallbackOutput` must live under `parameters.options` (v3) | fixed generator; verified against node source |
| 5 | Cross-node reference returned nothing | RSS parsed to 0 results | `$node[name]` unreliable in Code sandbox | switched to documented `$('Node').first()` + direct `$json` for parents |
| 6 | 0-item chains stall | with 0 candidates the loop body never ran, so the done-branch never fired and the sub returned nothing | n8n nodes don't execute with 0 input items | every Prep now emits a `__skipped` sentinel + a Has-Items switch routes straight to Return |
| 7 | Wikipedia 404 for anchor | no context for ICP agent | slugs without diacritics 404; HTML scrape brittle | MediaWiki API: opensearch → extracts (redirects=1) |
| 8 | Google News RSS empty on long queries | 0 results per search | RSS ranking degrades on long multi-term queries | fallback queries split into short, high-signal terms |
| 9 | "staticData as shared loop state" | designed to accumulate across nodes | `this.context.staticData` is **per-node**, not shared | abandoned; FastAPI store is the only shared state |

*Each of these is visible in the git history of `workflows/` and in the execution history of the running n8n instance — judges can watch the before/after on the live system.*

## 7. Output quality

- **Accounts:** name, country, commodities, ICP score 0–100, human-written fit reason, `why_it_fits` points with source URLs, raw evidence extracts.
- **Contacts:** name, role, seniority, LinkedIn URL (only if found in evidence), email (only if found, with verification status — never pattern-generated), verification summary + evidence.
- **Research briefs:** 5 buckets (profile / recent events / operational / technology / safety) + FlytBase opportunities, each fact vs inference, each with source URL.
- **Emails:** 150–220 words, open with a verifiable site-specific observation, one concrete FlytBase angle, proof refs (Shell / Anglo American / CSX only where they genuinely fit), low-friction CTA, and a per-claim fact-check report attached.
- **CSV export** for the full pipeline in one click.

## 8. Walkthrough (5-min video script)

1. (30s) Open dashboard → brief is pre-filled from the hackathon prompt.
2. (15s) Click **RUN AGENT** — trace panel lights up stage by stage.
3. (60s) A1: show the SQM Wikipedia extract + news feeding the ICP fingerprint. A2: show live search results flowing in (provider logged).
4. (60s) A3: open a qualified account → evidence extracts with URLs. A4/A5: show a verified contact with the evidence that verified them.
5. (60s) A6: research brief — note the inference badges. A7: the email, reading like a human BDR wrote it.
6. (45s) A8: open the fact-check report → show one claim judged `partial` and the rewritten sentence.
7. (15s) CSV export + "this exact run is reproducible with one button."

## 9. Repo map

```
flytbase-bdr-agent/
├── bootstrap.sh               # one-command run
├── start_n8n.sh               # n8n start with required env flags
├── .env                       # API keys (never committed)
├── flytbase_kb.json           # FlytBase knowledge base (positioning, angle, referenceable customers)
├── seed_data/candidate_pool.json   # BDR-seeded real company pool (input, not output)
├── workflows/
│   ├── gen_workflows.py       # generates the 12 workflow JSONs (parts 1–3)
│   ├── import_workflows.py    # idempotent import + placeholder resolution + activation
│   ├── ids.json               # logical → n8n id map
│   └── *.json                 # tools_search/fetch/llm, a1…a8, master
├── app/
│   ├── server.py              # FastAPI: ingest store, read APIs, run trigger, CSV
│   └── static/index.html      # dashboard (single file, no external assets)
├── data/                      # JSON evidence store (created at runtime)
└── docs/Submission.md         # this document
```
