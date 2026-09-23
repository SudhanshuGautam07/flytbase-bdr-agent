#!/usr/bin/env python3
"""Activate the fixed-ID imported workflows in n8n's SQLite DB before server start."""
import glob
import os
import sqlite3
import sys

IDS = [
    "TSRCH00000000001", "TFETCH0000000002", "TLLM000000000003",
    "A1ICP00000000001", "A2DISC0000000001", "A3VERI0000000001",
    "A4CONT0000000001", "A5CVER0000000001", "A6RSCH0000000001",
    "A7MAIL0000000001", "A8FACT0000000001", "MASTER0000000001",
]
base = os.environ.get("N8N_USER_FOLDER", "/var/data/n8n")
candidates = [
    os.path.join(base, ".n8n", "database.sqlite"),
    os.path.join(base, "database.sqlite"),
] + glob.glob(os.path.join(base, "**", "database.sqlite"), recursive=True)
db = next((p for p in candidates if os.path.isfile(p)), None)
if not db:
    raise SystemExit(f"n8n database.sqlite not found under {base}; checked {candidates}")

con = sqlite3.connect(db, timeout=60)
try:
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    table = "workflow_entity" if "workflow_entity" in tables else "workflow_entity"
    if table not in tables:
        raise RuntimeError(f"workflow table missing; found {sorted(tables)}")
    cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    if "active" not in cols:
        raise RuntimeError(f"active column missing from {table}: {sorted(cols)}")
    marks = ",".join("?" for _ in IDS)
    con.execute(f"UPDATE {table} SET active=1 WHERE id IN ({marks})", IDS)
    con.commit()
    rows = list(con.execute(f"SELECT id, name, active FROM {table} WHERE id IN ({marks}) ORDER BY name", IDS))
    if len(rows) != len(IDS) or not all(r[2] for r in rows):
        raise RuntimeError(f"activation incomplete: {rows}")
    print(f"Activated {len(rows)} workflows in {db}")
    for wid, name, active in rows:
        print(f"  active={active} id={wid} name={name}")
finally:
    con.close()
