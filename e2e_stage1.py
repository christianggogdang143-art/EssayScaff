"""Phase 3 Stage 1 live verification: cases A-D over real HTTP in one
session (revision history), plus page + security checks."""
import json
import urllib.request

BASE = "http://127.0.0.1:5000"
TOPIC = "Effects of climate change on agriculture"
KWS = ["climate", "agriculture", "farmers", "crop", "temperature", "rainfall"]
IDEAS = {
    "A-broad": "Climate change affects agriculture.",
    "B-developed": ("Climate change affects crop production because extreme temperatures "
                    "and irregular rainfall create difficulties for farmers."),
    "C-unrelated": "Online video games help players communicate with friends and improve teamwork.",
    "D-short": "Climate.",
}


def post(path, payload):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status, json.loads(r.read().decode())


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return r.status, json.loads(r.read().decode()) if "json" in r.headers.get("Content-Type", "") else r.read().decode()


session = None
for name, idea in IDEAS.items():
    payload = {"text": idea, "topic": TOPIC, "teacher_keywords": KWS}
    if session:
        payload["session_id"] = session
    status, d = post("/api/stage1/analyze", payload)
    session = session or d["session_id"]
    print(f"===== {name} R{d['revision_number']} ({d['session_id']}) HTTP {status} =====")
    print("concepts:", d["evidence"]["selected_keywords"])
    print("fired:", [r["rule_id"] for r in d["rules"] if r["status"] == "TRIGGERED"])
    print("prompts:", [(p["prompt_id"], p["priority"]) for p in d["prompts"]["prompts"]])
    print("readiness:", d["readiness"]["decision"])
    print("compare:", [m["text"][:100] for m in d["comparison"]["messages"]])
    print("timings:", {k: round(v, 2) for k, v in d["timings"].items()})

status, s = get(f"/api/stage1/session/{session}")
print("HISTORY:", status, "revisions:", s["revision_count"],
      [(r["revision_number"], r["readiness"]["decision"]) for r in s["revisions"]])
print("R1 preserved:", s["revisions"][0]["idea_text"] == IDEAS["A-broad"])

status, page = get("/")
print("PAGE:", status, "| stage1 UI:", all(x in page for x in ["ideaEditor", "guidedPrompts", "revisionHistory", "stage2Btn", "tab-stage1"]))
status, denied = get("/api/source?file=.env")
print("SECURITY .env:", status, denied.get("error", "")[:50])
print("DONE")
