#!/usr/bin/env python3
"""
Import the generated BDR workflows into n8n via the public API.
- Creates/updates each workflow (stable IDs across re-imports)
- Resolves __WFID:<NAME>__ placeholders in master.json against ids.json
- Activates sub-workflows and the master (webhook)
Usage: python3 import_workflows.py
"""
import json
import os
import sys
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# load .env
env = {}
p = os.path.join(ROOT, ".env")
if os.path.exists(p):
    for line in open(p):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
APIKEY = env.get("N8N_API_KEY", "")
if not APIKEY:
    sys.exit("N8N_API_KEY missing in .env")

BASE = "http://127.0.0.1:5678/api/v1"
IDS_PATH = os.path.join(HERE, "ids.json")


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"X-N8N-API-KEY": APIKEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode() or "{}")
        except Exception:
            err = {"message": str(e)}
        return {"__error__": e.code, **err}


def load_ids():
    if os.path.exists(IDS_PATH):
        return json.load(open(IDS_PATH))
    return {}


def save_ids(d):
    json.dump(d, open(IDS_PATH, "w"), indent=1)


def list_workflows():
    out, cursor = [], None
    while True:
        path = "/workflows?limit=100" + (("&cursor=" + cursor) if cursor else "")
        r = api("GET", path)
        out.extend(r.get("data", []))
        cursor = r.get("nextCursor")
        if not cursor:
            break
    return out


def clean(wf):
    wf = dict(wf)
    wf.pop("active", None)
    wf.pop("description", None)
    return wf


def main():
    ids = load_ids()
    existing = {w["name"]: w for w in list_workflows()}
    # logical id -> file
    order = [
        ("TOOLS_SEARCH", "tools_search.json"),
        ("TOOLS_FETCH", "tools_fetch.json"),
        ("TOOLS_LLM", "tools_llm.json"),
        ("A1_ICP", "a1_icp.json"),
        ("A2_DISCOVERY", "a2_discovery.json"),
        ("A3_VERIFICATION", "a3_verification.json"),
        ("A4_CONTACTS", "a4_contact_discovery.json"),
        ("A5_CONTACT_VERIFY", "a5_contact_verification.json"),
        ("A6_RESEARCH", "a6_research.json"),
        ("A7_EMAILS", "a7_personalization.json"),
        ("A8_FACT_CHECK", "a8_fact_checker.json"),
    ]
    def resolve(wf):
        s = json.dumps(wf)
        for k, v in ids.items():
            s = s.replace(f"__WFID:{k}__", v)
        return json.loads(s)

    for logical, fname in order:
        wf = resolve(clean(json.load(open(os.path.join(HERE, fname)))))
        r = api("PUT", "/workflows/" + ids[logical], wf) if logical in ids else api("POST", "/workflows", wf)
        if "__error__" in r or "message" in r and "id" not in r:
            sys.exit(f"FAILED to upsert {fname}: {r}")
        ids[logical] = r["id"]
        save_ids(ids)
        print(f"  {fname} -> {r['id']} ({'updated' if logical in [x for x in []] else 'ok'})")

    # master: resolve placeholders
    master = json.load(open(os.path.join(HERE, "master.json")))
    s = json.dumps(master)
    for logical, _ in order:
        s = s.replace(f"__WFID:{logical}__", ids[logical])
    master = clean(json.loads(s))
    mkey = "MASTER"
    r = api("PUT", f"/workflows/{ids[mkey]}", master) if mkey in ids else api("POST", "/workflows", master)
    if "__error__" in r or ("message" in r and "id" not in r):
        sys.exit(f"FAILED to upsert master.json: {r}")
    ids["MASTER"] = r["id"]
    save_ids(ids)
    print(f"  master.json -> {r['id']}")

    # activate all (subs first, then master)
    for logical in [x for x, _ in order] + ["MASTER"]:
        r = api("POST", f"/workflows/{ids[logical]}/activate")
        status = "active" if r.get("active") else (r.get("message", "?")[:80])
        print(f"  activate {logical}: {status}")
    print("IMPORT COMPLETE")


if __name__ == "__main__":
    main()
