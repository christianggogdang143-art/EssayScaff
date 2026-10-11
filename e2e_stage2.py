"""Phase 4 Stage 2 live verification: cases A-E over real HTTP with a
linked Stage 1 session, plus page + security checks."""
import json
import urllib.request

BASE = "http://127.0.0.1:5000"
TOPIC = "Effects of climate change on agriculture"
KWS = ["climate", "agriculture", "farmers", "crop", "temperature", "rainfall"]
IDEA = ("Climate change affects crop production because extreme temperatures "
        "and irregular rainfall create difficulties for farmers.")
THESES = {
    "A-meta": "This essay will discuss climate change and agriculture.",
    "B-broad": "Climate change affects the world.",
    "C-developed": ("Extreme temperatures and irregular rainfall reduce crop production "
                    "and create significant challenges for farmers."),
    "D-overloaded": ("Climate change affects farmers, reduces crops, damages roads, changes "
                     "economies, increases disease, causes migration, and creates many "
                     "environmental problems."),
    "E-drift": "Competitive online games improve teamwork among students.",
}


def post(path, payload):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status, json.loads(r.read().decode())


def get_raw(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return r.status, r.read().decode()


status, s1 = post("/api/stage1/analyze", {"text": IDEA, "topic": TOPIC, "teacher_keywords": KWS})
S1 = s1["session_id"]
print("Stage1 session:", S1, "->", s1["readiness"]["decision"])

sess = None
for name, th in THESES.items():
    payload = {"text": th, "topic": TOPIC, "teacher_keywords": KWS, "stage1_session_id": S1}
    if sess:
        payload["session_id"] = sess
    status, d = post("/api/stage2/analyze", payload)
    sess = sess or d["session_id"]
    print(f"===== {name} R{d['revision_number']} HTTP {status} =====")
    c = d["components"]
    print("components: subject=%r verb=%r complete=%s concepts=%d" % (
        c["detected_subject"], c["main_verb"], c["complete_structure"], c["concept_count"]))
    print("fired:", [r["rule_id"] for r in d["thesis_rules"] if r["status"] in ("TRIGGERED", "ISSUE")])
    print("prompts:", [(p["prompt_id"], p["priority"]) for p in d["prompts"]["prompts"]])
    print("readiness:", d["readiness"]["decision"], "| align:", d["alignment"]["classification"])
    print("compare:", [m["text"][:90] for m in d["comparison"]["messages"]])
    print("timings:", {k: round(v, 2) for k, v in d["timings"].items() if k != "total_ms"})

status, s = get_raw(f"/api/stage2/session/{sess}")
s = json.loads(s)
print("HISTORY:", status, "revisions:", s["revision_count"],
      [(r["revision_number"], r["readiness"]["decision"]) for r in s["revisions"]])
print("R1 preserved:", s["revisions"][0]["thesis_text"] == THESES["A-meta"])

status, page = get_raw("/")
print("PAGE:", status, "| stage2 UI:", all(x in page for x in ["thesisEditor", "thesisPrompts", "thesisHistory", "stage3Btn", "tab-stage2"]))
try:
    get_raw("/api/source?file=services%2Fdb.py")
    print("SECURITY db.py: NOT BLOCKED (unexpected!)")
except Exception as e:
    print("SECURITY db.py blocked:", "403" in str(e))
print("DONE")
