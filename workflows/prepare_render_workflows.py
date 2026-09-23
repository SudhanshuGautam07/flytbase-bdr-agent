#!/usr/bin/env python3
"""Build fixed-ID workflow JSONs for unattended n8n CLI import on Render."""
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "render_workflows")

FILES = {
    "TOOLS_SEARCH": ("tools_search.json", "TSRCH00000000001"),
    "TOOLS_FETCH": ("tools_fetch.json", "TFETCH0000000002"),
    "TOOLS_LLM": ("tools_llm.json", "TLLM000000000003"),
    "A1_ICP": ("a1_icp.json", "A1ICP00000000001"),
    "A2_DISCOVERY": ("a2_discovery.json", "A2DISC0000000001"),
    "A3_VERIFICATION": ("a3_verification.json", "A3VERI0000000001"),
    "A4_CONTACTS": ("a4_contact_discovery.json", "A4CONT0000000001"),
    "A5_CONTACT_VERIFY": ("a5_contact_verification.json", "A5CVER0000000001"),
    "A6_RESEARCH": ("a6_research.json", "A6RSCH0000000001"),
    "A7_EMAILS": ("a7_personalization.json", "A7MAIL0000000001"),
    "A8_FACT_CHECK": ("a8_fact_checker.json", "A8FACT0000000001"),
    "MASTER": ("master.json", "MASTER0000000001"),
}


def main():
    for _, (_, wid) in FILES.items():
        assert len(wid) == 16, (wid, len(wid))
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)
    id_map = {k: wid for k, (_, wid) in FILES.items()}
    for logical, (filename, wid) in FILES.items():
        src = os.path.join(HERE, filename)
        wf = json.load(open(src))
        raw = json.dumps(wf)
        for key, target in id_map.items():
            raw = raw.replace(f"__WFID:{key}__", target)
        wf = json.loads(raw)
        wf["id"] = wid
        # Preserve active state for unattended CLI import; publish command creates the current version.
        wf["active"] = True
        # CLI import accepts exported workflow fields; description is harmless.
        with open(os.path.join(OUT, filename), "w") as f:
            json.dump(wf, f)
    print(f"Prepared {len(FILES)} Render workflows in {OUT}")


if __name__ == "__main__":
    main()
