"""Phase 6 E2E: cases A-F through the real API. Prints REAL outputs.
No assertions on pedagogical outcomes — structure verified by tests."""
import json
import urllib.request

BASE = "http://127.0.0.1:5000"
TOPIC = "Effects of climate change on agriculture"
KWS = ["climate", "agriculture", "farmers", "crop", "temperature", "rainfall"]
THESIS = ("Extreme temperatures and irregular rainfall reduce crop production "
          "and create significant challenges for farmers.")
B1 = {"text": "Extreme temperatures reduce crop production.",
      "details": ["High heat can interfere with crop growth.",
                  "Temperature stress can affect harvest outcomes."]}
B2 = {"text": "Irregular rainfall disrupts farming schedules.",
      "details": ["Unpredictable rainfall can affect planting timing."]}
B3 = {"text": "Farmers face production challenges from changing weather conditions.",
      "details": ["Weather uncertainty can complicate farm planning."]}


def post(path, payload):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.status, json.loads(r.read().decode())


def stage1(text):
    s, d = post("/api/stage1/analyze", {"text": text, "topic": TOPIC, "teacher_keywords": KWS})
    return d["session_id"]


def stage2(text, s1=None):
    p = {"text": text, "topic": TOPIC, "teacher_keywords": KWS}
    if s1:
        p["stage1_session_id"] = s1
    s, d = post("/api/stage2/analyze", p)
    return d["session_id"], d


def stage3(thesis, outline, s2=None):
    p = {"thesis": thesis, "outline": outline}
    if s2:
        p["stage2_session_id"] = s2
    s, d = post("/api/stage3/analyze", p)
    return d["session_id"], d


def reflect(s1=None, s2=None, s3=None, session=None, note=None):
    p = {}
    if session:
        p["session_id"] = session
    if s1:
        p["stage1_session_id"] = s1
    if s2:
        p["stage2_session_id"] = s2
    if s3:
        p["stage3_session_id"] = s3
    if note:
        p["student_note"] = note
    return post("/api/stage4/reflect", p)[1]


def show(name, d):
    sc = d["scaffold"]
    print(f"===== {name} =====")
    print(f"level: {sc['level']} ({sc['label']}) | decision: {d['readiness']['decision']}")
    print(f"reason: {sc['reason']}")
    print("fired reflect:", [r for r in d.get("unresolved_rules", [])])
    print("prompts:", [(p["prompt_id"], p["detail_level"]) for p in d["prompts"]["prompts"]])
    print("checklist shown:", d["readiness"]["decision"] in ("READY_FOR_INDEPENDENT_REVIEW", "COMPLETE"))
    t = d["timings"]
    print("timings ms:", {k: round(v, 1) for k, v in t.items() if k != "total_ms"})


# ---- Case A: many unresolved issues ----
# (stage3 gate needs a READY chain, so a READY outline is linked while messy
# stage1/2 histories supply actives: off-topic idea + meta thesis)
s1a = stage1("Video games are fun to play with friends online every day.")
s2a, _ = stage2("This essay will discuss farming and climate issues affecting farmers everywhere.", s1a)
s2a2, _ = stage2(THESIS, s1a)
s3a, s3d = stage3(THESIS, [B1, B2, B3], s2a2)
print("A stage3 readiness:", s3d["readiness"]["decision"], "| stage4_allowed:",
      s3d["readiness"].get("stage4_allowed"))
dA = reflect(s1a, s2a, s3a)
show("A — many unresolved issues", dA)

# ---- Case B: meta + dup resolved, one alignment issue remains ----
s1b = stage1("Climate change harms farmers. Crop yields fall because rainfall is unpredictable.")
s2b, _ = stage2("This essay will discuss farming.", s1b)          # meta active R1
s2b2_data = post("/api/stage2/analyze", {"text": THESIS, "topic": TOPIC,
                                         "teacher_keywords": KWS,
                                         "stage1_session_id": s1b,
                                         "session_id": s2b})[1]  # R2 meta resolved
s3b, _ = stage3(THESIS, [B1, B2, B3], s2b)
dB = reflect(s1b, s2b, s3b)
show("B — partial improvement", dB)

# ---- Case F: clean + stable (3+ revisions with resolution) ----
s1f = stage1("Climate change affects agriculture.")                 # R1 issue
s1f2 = post("/api/stage1/analyze", {"text": "Climate change reduces farm output because rainfall patterns shift each season, hurting growers.", "topic": TOPIC, "teacher_keywords": KWS, "session_id": s1f})[1]
s1f3 = post("/api/stage1/analyze", {"text": "Shifting rainfall patterns reduce farm output and hurt growers across regions.", "topic": TOPIC, "teacher_keywords": KWS, "session_id": s1f})[1]
s2f, _ = stage2(THESIS, s1f)
s3f, _ = stage3(THESIS, [B1, B2, B3], s2f)
dF = reflect(s1f, s2f, s3f)
show("F — stable clean history", dF)

# ---- Case D: real regression (broad R1 -> focused R2 -> broad R3) ----
s1d = stage1("Climate change affects agriculture and farming everywhere.")
s1d = post("/api/stage1/analyze", {"text": "Climate change reduces farm output because rainfall patterns shift each season.", "topic": TOPIC, "teacher_keywords": KWS, "session_id": s1d})[1]["session_id"]
post("/api/stage1/analyze", {"text": "Farming and agriculture change a lot with the climate in many ways.", "topic": TOPIC, "teacher_keywords": KWS, "session_id": s1d})
s2d, _ = stage2(THESIS, s1d)
s3d, _ = stage3(THESIS, [B1, B2, B3], s2d)
dD = reflect(s1d, s2d, s3d, note="Went back to my broader wording.")
show("D — regression (resolved, then reappeared)", dD)
dD2 = reflect(s1d, s2d, s3d, session=dD.get("session_id"))
show("D2 — second reflection same session (history accumulates)", dD2)

# ---- Case E: no history ----
dE = reflect()
show("E — insufficient history", dE)
print("DONE")
