"""Phase 2 live comparison: runs texts A/B/C over real HTTP, prints REAL
outputs for the completion report. Does not assert outcomes."""
import json
import urllib.request

BASE = "http://127.0.0.1:5000"
TOPIC = "Effects of climate change on agriculture"
KWS = ["climate", "agriculture", "farmers", "crop", "temperature", "rainfall"]
TEXTS = {
    "A-direct": (
        "This essay will discuss climate change and agriculture. "
        "Climate change has serious effects on farmers. "
        "Extreme temperatures can reduce crop production, "
        "and irregular rainfall can affect planting schedules."
    ),
    "B-unrelated": (
        "Online video games allow players to communicate with friends across different countries. "
        "Competitive games also require teamwork and quick decision making."
    ),
    "C-related-wording": (
        "Farming communities increasingly face changing weather conditions. "
        "Growers may experience lower harvests when heat and unpredictable precipitation affect cultivation."
    ),
}


def post(text):
    req = urllib.request.Request(
        BASE + "/api/analyze",
        data=json.dumps({"text": text, "stage": "introduction", "topic": TOPIC, "teacher_keywords": KWS}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


for name, text in TEXTS.items():
    d = post(text)
    p2 = d["technical"]["phase2"]
    ta = p2["topic_analysis"]
    wn = p2["wordnet"]
    print(f"===== {name} ({d['analysis_id']}) =====")
    print("selected:", p2["keywords"]["selected"])
    print("matches:", [(t["original_term"], t["match_type"]) for t in wn["terms"] if t["match_type"] != "NO_MATCH"])
    print("no_match:", [t["original_term"] for t in wn["terms"] if t["match_type"] == "NO_MATCH"])
    print("vocab:", ta["tfidf"]["vocabulary_size"], "dims:", ta["tfidf"]["dimensions"])
    print("similarity:", round(ta["cosine"]["library_result"], 6), "| manual:", round(ta["cosine"]["manual_result"], 6),
          "| diff:", ta["cosine"]["difference"], "| match:", ta["cosine"]["match"])
    print("class:", ta["classification"]["classification"], "|", ta["classification"]["comparison"])
    print("timings: kw=%.2f wn=%.2f tfidf=%.2f cos=%.2f cls=%.2f total=%.1f" % (
        d["technical"]["timings"]["keyword_ms"], d["technical"]["timings"]["wordnet_ms"],
        d["technical"]["timings"]["tfidf_ms"], d["technical"]["timings"]["cosine_ms"],
        d["technical"]["timings"]["classification_ms"], d["summary"]["processing_ms"]))
    fb = [f for f in d["feedback"] if f["source"] == "TOPIC_CLASSIFIER"][0]
    print("feedback:", fb["title"], "| severity:", fb["severity"])
    print("reason:", fb["reason"][:220])
    if name == "A-direct":
        with open("e2e_phase2_A.json", "w") as fh:
            json.dump(d, fh, indent=1)
        ag = [t for t in wn["terms"] if t["original_term"] == "agriculture" and t["kind"] == "TEACHER_KEYWORD"][0]
        print("AGRICULTURE synsets:", ag["synset_count"], [s["name"] for s in ag["synsets"]][:6])
        print("AGRICULTURE retained:", ag["retained"][:12])
        print("AGRICULTURE rejected sample:", [(c["candidate_term"], c["rejection_reason"][:40]) for c in ag["rejected"][:4]])
print("DONE")
