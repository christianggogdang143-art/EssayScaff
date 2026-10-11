"""E2E verification: boots the real Flask server over HTTP, POSTs the manual
test text, checks the live page + static JS, prints the REAL response for
the completion report. Run: python e2e_verify.py (deletes itself after use
is optional; kept out of tests/ so pytest stays fast)."""

import json
import subprocess
import sys
import time
import urllib.request

SAMPLE = (
    "This essay will discuss climate change and agriculture. "
    "Climate change have serious effects on farmers. "
    "Farmers experience lower crop production because extreme temperatures affect crops. "
    "Farmers also experience problems because rainfall patterns continue to change."
)

log = open("e2e_server.log", "w")
proc = subprocess.Popen(
    [sys.executable, "app.py"],
    stdout=log,
    stderr=subprocess.STDOUT,
    text=True,
)
try:
    # Wait for boot.
    ok = False
    for _ in range(60):
        time.sleep(1)
        try:
            with urllib.request.urlopen("http://127.0.0.1:5000/api/health", timeout=5) as r:
                print("HEALTH:", r.read().decode()[:200])
                ok = True
                break
        except Exception:
            pass
    assert ok, "server did not boot"

    def post(path, payload):
        req = urllib.request.Request(
            "http://127.0.0.1:5000" + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode())

    status, data = post("/api/analyze", {"text": SAMPLE, "stage": "introduction"})
    print("POST /api/analyze ->", status)
    print("ANALYSIS_ID:", data["analysis_id"])
    print("SUMMARY:", json.dumps(data["summary"]))
    print("FEEDBACK:")
    for f in data["feedback"]:
        print(f"  [{f['feedback_id']}] {f['category']}/{f['title']} S{f['sentence_number']} src={f['source']}")
        print(f"    text={f['text']!r}")
    print("SENTENCES:", [(s["number"], s["start"], s["end"]) for s in data["technical"]["sentences"]])
    print("N_TOKENS:", len(data["technical"]["tokens"]))
    print("FIRST_TOKEN:", json.dumps(data["technical"]["tokens"][0]))
    lt = data["technical"]["language_tool_results"]
    print("LT:", lt["status"], "issues=", len(lt["issues"]), "err=", lt.get("error"))
    print("TIMINGS:", json.dumps(data["technical"]["timings"], indent=None))
    with open("e2e_output.json", "w") as fh:
        json.dump(data, fh, indent=2)
    print("saved e2e_output.json")

    with urllib.request.urlopen("http://127.0.0.1:5000/", timeout=10) as r:
        html = r.read().decode()
    assert "live_feedback.js" in html and 'id="editor"' in html
    print("GET / -> page ok,", len(html), "chars")
    with urllib.request.urlopen("http://127.0.0.1:5000/static/js/live_feedback.js", timeout=10) as r:
        js = r.read().decode()
    assert "DEBOUNCE_MS" in js
    print("GET static JS -> ok,", len(js), "chars")
    print("E2E PASS")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except Exception:
        proc.kill()
        proc.wait(timeout=15)
    log.close()
