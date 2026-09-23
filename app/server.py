#!/usr/bin/env python3
"""
BDR Intelligence Agent - FastAPI app.
- Owns the JSON data store (ingested from the n8n agent workflows)
- Serves the dashboard UI
- Triggers the n8n master webhook on campaign run
- Exposes read APIs + CSV export
"""
import json
import os
import threading
import time
import urllib.request
import urllib.parse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(ROOT, "data"))
STORE_PATH = os.path.join(DATA_DIR, "store.json")
SEED_PATH = os.path.join(ROOT, "seed_data", "candidate_pool.json")
KB_PATH = os.path.join(ROOT, "flytbase_kb.json")
N8N_WEBHOOK = os.environ.get("N8N_WEBHOOK", "http://127.0.0.1:5678/webhook/master")

os.makedirs(DATA_DIR, exist_ok=True)

_lock = threading.Lock()
_counter = {"id": 0}


def _default_store():
    return {
        "campaigns": {}, "icp": {}, "accounts": [], "contacts": [],
        "research": [], "emails": [], "agent_runs": [], "searches": [],
    }


def load_store():
    if os.path.exists(STORE_PATH):
        try:
            return json.load(open(STORE_PATH))
        except Exception:
            pass
    return _default_store()


def save_store(s):
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f)
    os.replace(tmp, STORE_PATH)


def next_id():
    _counter["id"] += 1
    return _counter["id"]


def _find(lst, preds):
    for it in lst:
        if all(it.get(k) == v for k, v in preds.items()):
            return it
    return None


def ingest(campaign_id, kind, payload):
    with _lock:
        s = load_store()
        if kind == "campaign":
            c = dict(payload or {})
            c["id"] = c.get("id") or campaign_id
            s["campaigns"][c["id"]] = c
        elif kind == "campaign_update":
            c = s["campaigns"].get(payload.get("match", {}).get("id"))
            if c:
                c.update(payload.get("patch") or {})
        elif kind == "icp":
            s["icp"][campaign_id] = payload or {}
        elif kind == "account":
            a = dict(payload or {})
            a["id"] = next_id()
            a["campaign_id"] = campaign_id
            if not _find(s["accounts"], {"campaign_id": campaign_id, "name": a.get("name")}):
                s["accounts"].append(a)
            else:
                for ex in s["accounts"]:
                    if ex.get("campaign_id") == campaign_id and ex.get("name") == a.get("name"):
                        ex.update({k: v for k, v in a.items() if v not in (None, "", [])})
        elif kind == "contact":
            c = dict(payload or {})
            c["id"] = next_id()
            c["campaign_id"] = campaign_id
            if not _find(s["contacts"], {"campaign_id": campaign_id, "account_name": c.get("account_name"), "name": c.get("name")}):
                s["contacts"].append(c)
        elif kind == "contact_update":
            m = payload.get("match") or {}
            c = _find(s["contacts"], {"campaign_id": campaign_id, **m})
            if c:
                c.update(payload.get("patch") or {})
        elif kind == "research":
            r = dict(payload or {})
            r["id"] = next_id()
            r["campaign_id"] = campaign_id
            if not _find(s["research"], {"campaign_id": campaign_id, "account_name": r.get("account_name")}):
                s["research"].append(r)
        elif kind == "email":
            e = dict(payload or {})
            e["id"] = next_id()
            e["campaign_id"] = campaign_id
            if not _find(s["emails"], {"campaign_id": campaign_id, "contact_name": e.get("contact_name")}):
                s["emails"].append(e)
        elif kind == "email_update":
            m = payload.get("match") or {}
            e = _find(s["emails"], {"campaign_id": campaign_id, **m})
            if e:
                e.update(payload.get("patch") or {})
        elif kind == "agent_run":
            s["agent_runs"].append({
                "id": next_id(), "campaign_id": campaign_id,
                "agent": (payload or {}).get("agent"), "label": (payload or {}).get("label"),
                "status": (payload or {}).get("status", "running"),
                "started_at": (payload or {}).get("started_at"),
                "finished_at": None, "detail": None, "error": None,
            })
        elif kind == "agent_run_end":
            agent = (payload or {}).get("agent")
            target = None
            for run in reversed(s["agent_runs"]):
                if run.get("campaign_id") == campaign_id and run.get("agent") == agent and run.get("status") == "running":
                    target = run
                    break
            if target:
                target.update(payload or {})
            else:
                s["agent_runs"].append({"id": next_id(), "campaign_id": campaign_id,
                                        "status": (payload or {}).get("status"), **(payload or {})})
        elif kind == "search":
            p = dict(payload or {})
            p["id"] = next_id()
            p["campaign_id"] = campaign_id
            p["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            s["searches"].append(p)
        else:
            return {"ok": False, "error": f"unknown type {kind}"}
        save_store(s)
    return {"ok": True}


app = FastAPI(title="BDR Intelligence Agent")


@app.post("/api/ingest")
async def api_ingest(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "invalid json")
    return ingest(body.get("campaign_id"), body.get("type"), body.get("payload"))


def _q(request: Request):
    return dict(request.query_params)


@app.get("/api/seed")
async def api_seed():
    return json.load(open(SEED_PATH))


@app.get("/api/kb")
async def api_kb():
    return json.load(open(KB_PATH))


@app.get("/api/campaigns")
async def api_campaigns():
    with _lock:
        s = load_store()
    out = sorted(s["campaigns"].values(), key=lambda c: c.get("created_at") or "", reverse=True)
    return out


@app.get("/api/agent_runs")
async def api_agent_runs(request: Request):
    q = _q(request)
    with _lock:
        s = load_store()
    runs = [r for r in s["agent_runs"] if not q.get("campaign_id") or r.get("campaign_id") == q["campaign_id"]]
    return runs


@app.get("/api/searches")
async def api_searches(request: Request):
    q = _q(request)
    with _lock:
        s = load_store()
    out = [r for r in s["searches"] if not q.get("campaign_id") or r.get("campaign_id") == q["campaign_id"]]
    return out


@app.get("/api/accounts")
async def api_accounts(request: Request):
    q = _q(request)
    with _lock:
        s = load_store()
    out = [a for a in s["accounts"]
           if (not q.get("campaign_id") or a.get("campaign_id") == q["campaign_id"])
           and (not q.get("status") or a.get("status") == q["status"])]
    return out


@app.get("/api/contacts")
async def api_contacts(request: Request):
    q = _q(request)
    with _lock:
        s = load_store()
    out = [c for c in s["contacts"]
           if (not q.get("campaign_id") or c.get("campaign_id") == q["campaign_id"])
           and (not q.get("status") or c.get("status") == q["status"])]
    return out


@app.get("/api/research")
async def api_research(request: Request):
    q = _q(request)
    with _lock:
        s = load_store()
    out = [r for r in s["research"] if not q.get("campaign_id") or r.get("campaign_id") == q["campaign_id"]]
    return out


@app.get("/api/emails")
async def api_emails(request: Request):
    q = _q(request)
    with _lock:
        s = load_store()
    out = [e for e in s["emails"]
           if (not q.get("campaign_id") or e.get("campaign_id") == q["campaign_id"])
           and (not q.get("status") or e.get("status") == q["status"])]
    return out


@app.get("/api/evidence_bundle")
async def api_evidence_bundle(request: Request):
    q = _q(request)
    cid = q.get("campaign_id")
    with _lock:
        s = load_store()
    bundle = {
        "research": [r for r in s["research"] if r.get("campaign_id") == cid and not r.get("status")],
        "account_evidence": [{
            "name": a.get("name"), "fit_reason": a.get("fit_reason"),
            "why_it_fits": a.get("why_it_fits"), "evidence": a.get("evidence"),
            "icp_score": a.get("icp_score"),
        } for a in s["accounts"] if a.get("campaign_id") == cid and a.get("status") == "qualified"],
        "contact_verification": [{
            "name": c.get("name"), "company": c.get("account_name"), "role": c.get("current_role") or c.get("role"),
            "summary": c.get("verification_summary"), "evidence": c.get("evidence"),
        } for c in s["contacts"] if c.get("campaign_id") == cid and c.get("status") == "verified"],
    }
    return bundle


@app.get("/api/summary")
async def api_summary(request: Request):
    q = _q(request)
    cid = q.get("campaign_id")
    with _lock:
        s = load_store()
    accounts = [a for a in s["accounts"] if a.get("campaign_id") == cid]
    contacts = [c for c in s["contacts"] if c.get("campaign_id") == cid]
    research = [r for r in s["research"] if r.get("campaign_id") == cid and not r.get("status")]
    emails = [e for e in s["emails"] if e.get("campaign_id") == cid]
    runs = [r for r in s["agent_runs"] if r.get("campaign_id") == cid]
    searches = [x for x in s["searches"] if x.get("campaign_id") == cid]
    failed = [r for r in runs if r.get("status") == "failed"]
    return {
        "campaign_id": cid,
        "campaign": s["campaigns"].get(cid),
        "icp": s["icp"].get(cid),
        "counts": {
            "candidates": len([a for a in accounts if a.get("status") == "candidate"]) + len([a for a in accounts if a.get("status") in ("qualified", "rejected")]),
            "qualified_accounts": len([a for a in accounts if a.get("status") == "qualified"]),
            "rejected_accounts": len([a for a in accounts if a.get("status") == "rejected"]),
            "contacts_candidate": len([c for c in contacts if c.get("status") == "candidate"]),
            "contacts_verified": len([c for c in contacts if c.get("status") == "verified"]),
            "contacts_rejected": len([c for c in contacts if c.get("status") == "rejected"]),
            "research_briefs": len(research),
            "emails_draft": len([e for e in emails if e.get("status") == "draft"]),
            "emails_final": len([e for e in emails if e.get("status") == "final"]),
            "searches": len(searches),
        },
        "failed_agents": [{"agent": r.get("agent"), "error": r.get("error")} for r in failed],
        "running": any(r.get("status") == "running" for r in runs),
    }


@app.get("/api/run/{cid}")
async def api_run_detail(cid: str):
    with _lock:
        s = load_store()
    if cid not in s["campaigns"]:
        raise HTTPException(404, "campaign not found")
    accs = [a for a in s["accounts"] if a.get("campaign_id") == cid]
    by_acc = {}
    for c in s["contacts"]:
        if c.get("campaign_id") == cid:
            by_acc.setdefault(c.get("account_name"), []).append(c)
    for e in s["emails"]:
        if e.get("campaign_id") == cid:
            key = (e.get("account_name"),)
            by_acc.setdefault(e.get("account_name"), [])
    emails = [e for e in s["emails"] if e.get("campaign_id") == cid]
    research = [r for r in s["research"] if r.get("campaign_id") == cid]
    runs = [r for r in s["agent_runs"] if r.get("campaign_id") == cid]
    searches = [x for x in s["searches"] if x.get("campaign_id") == cid]
    return {
        "campaign": s["campaigns"][cid],
        "icp": s["icp"].get(cid),
        "accounts": accs,
        "contacts_by_account": by_acc,
        "emails": emails,
        "research": research,
        "agent_runs": runs,
        "searches": searches,
    }


@app.post("/api/run")
async def api_run(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    req = urllib.request.Request(
        N8N_WEBHOOK,
        data=json.dumps(body or {}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return {"ok": True, "status": r.status, "note": "pipeline started in background; poll /api/agent_runs"}
    except Exception as e:
        raise HTTPException(502, f"failed to trigger n8n webhook: {e}")


@app.get("/api/export.csv")
async def api_export_csv(request: Request):
    q = _q(request)
    cid = q.get("campaign_id")
    with _lock:
        s = load_store()
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["account", "country", "commodities", "icp_score", "status", "fit_reason",
                "contact", "role", "seniority", "contact_status", "linkedin", "email", "email_status",
                "email_subject", "email_body", "proof_refs", "fact_check_unsupported", "fact_check_rewritten"])
    accounts = [a for a in s["accounts"] if (not cid or a.get("campaign_id") == cid) and a.get("status") == "qualified"]
    for a in accounts:
        acc_contacts = [c for c in s["contacts"] if c.get("account_name") == a.get("name") and (not cid or c.get("campaign_id") == cid)]
        acc_emails = [e for e in s["emails"] if e.get("account_name") == a.get("name") and (not cid or e.get("campaign_id") == cid) and e.get("status") == "final"]
        if not acc_contacts:
            w.writerow([a.get("name"), a.get("country"), ",".join(a.get("commodities") or []), a.get("icp_score"), a.get("status"), (a.get("fit_reason") or "")[:300], "", "", "", "", "", "", "", "", "", "", "", ""])
            continue
        for c in acc_contacts:
            e = next((x for x in acc_emails if x.get("contact_name") == c.get("name")), None)
            fc = (e or {}).get("fact_check") or {}
            w.writerow([
                a.get("name"), a.get("country"), ",".join(a.get("commodities") or []), a.get("icp_score"), a.get("status"),
                (a.get("fit_reason") or "")[:300],
                c.get("name"), c.get("current_role") or c.get("role"), c.get("seniority"), c.get("status"),
                c.get("linkedin") or "", c.get("email") or "", c.get("email_status") or "",
                (e or {}).get("subject") or "", (e or {}).get("body") or "",
                ";".join((e or {}).get("proof_refs") or []), fc.get("unsupported", ""), fc.get("rewritten", ""),
            ])
    return PlainTextResponse(buf.getvalue(), headers={"Content-Disposition": "attachment; filename=bdr_outreach.csv"})


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html")
    return HTMLResponse(open(html_path).read())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
