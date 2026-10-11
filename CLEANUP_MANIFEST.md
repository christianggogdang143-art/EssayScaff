# EssayScaff — Cleanup Manifest (2026-10-11)

No git history exists (zero commits), so nothing deleted here is recoverable
from version control. Classification is conservative: when in doubt, KEEP.

## SAFE_DELETE (deleted; byte-identical regeneration verified)

| Path | Size | Reason | References | Reproducible | Risk |
|---|---|---|---|---|---|
| `__pycache__/` (root, routes, services incl. subpackages, rules, tests — 77 `.pyc`) | ~1.7 MB | CPython bytecode caches | None (interpreter-owned) | Yes — recreated on import/pytest | None |
| `.pytest_cache/` (`lastfailed={}`, 359-entry `nodeids`, tags) | ~25 KB | pytest run cache; `nodeids` already stale vs 400 tests | None | Yes — recreated on next run | None |

Total recovered: ~1.7 MB. No source, data, or test files touched.

## LIKELY_OBSOLETE — KEPT (no recovery path, human decision required)

Unreferenced one-off scripts (0 hits in tests/docs/routes; print-only, assert nothing):
`e2e_verify.py`, `e2e_phase2.py`, `e2e_stage1.py`, `e2e_stage2.py`, `e2e_stage4.py`
(~16 KB code) and their outputs `e2e_output.json` (35 KB), `e2e_phase2_A.json` (202 KB).
Kept because: no git recovery exists, and outputs may serve as historical evidence.
Human call: delete only after confirming no thesis-evidence value.

## KEEP (intentionally preserved suspicious-looking items)

- `essayscaff.db` (~33 MB): live dev/pilot history (257 runs, 591 revisions, 854 events).
  Never delete without an explicit backup + human sign-off.
- `services/db.py` legacy migration helpers: required for existing DBs.
- `services/transparency.py:token_detail`: dead in production but asserted by
  `tests/test_transparency.py` — removing it breaks the suite; keep.
- `config.py:STAGE1_MIN_SENTENCES`: unread by logic but VR-2-frozen; keep.
- `templates/index.html#reflectionChecklist`, `#overview[hidden]`: dead markup kept
  (removal is cosmetic churn with nonzero regression risk).
- `essayscaff.labChain` (write-only sessionStorage): forward-compatible trace; keep.
- `requirements.txt` `requests` pin: transitive via language-tool-python; keep (env stability).
- `professor-handout.html`: instructor doc; test-count line corrected 394→400 during audit.

## HUMAN_REVIEW (not deleted, needs a person)

1. `e2e_*` scripts/outputs above — obsolete or evidence?
2. `essayscaff.db` — which sessions (if any) count as pilot/research data? Nothing is labeled.
3. Validation datasets (`VDS-20261006-B63DBF`, `VDS-20261006-6A7420`, both DRAFT, 0 samples) —
   keep; decide whether to populate or remove before pilot.
4. Dead JS helpers (`highlight.js:fbId`, `validation.js:anVal`, `walkthrough.js:fmtNum`,
   `analytics.js:markActivityBlip`, `rules/style_rules.py:_punct_only`, unused CSS
   `.trace-q`/`.wt-flow`, duplicated `code` rule) — all verified caller-free, but removal
   is elegance-only churn; batch into a future refactor with test cover, not this cleanup.
5. Missing root `.gitignore` — added (covers `__pycache__/`, `*.pyc`, `.pytest_cache/`).
6. `CURRENT_ARCHITECTURE.md` predates the dashboard/highlight/copy-button work — left untouched
   (tests pin phrases inside it); decide canonical doc during next docs pass.
