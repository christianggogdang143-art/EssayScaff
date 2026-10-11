"""SAFE source-code viewer for Transparency Mode.

Security design:
- Explicit whitelist: only the listed research-implementation files can ever
  be served. There is no filesystem browsing and no path joining of user
  input.
- The `file` parameter must EXACTLY equal a whitelist key. Anything else
  (absolute paths, `..`, backslashes, `.env`, database files, unknown names)
  is rejected before any file access.
- The `function` parameter must name an attribute that actually exists in the
  whitelisted module; its source is extracted with `inspect` from the LIVE
  imported module, so the displayed code is guaranteed to be the code that
  executed (same process). For historical runs the API flags that the shown
  code is the CURRENT implementation.
- Never reads environment variables, secrets, or anything outside the
  whitelisted project modules.
"""

from __future__ import annotations

import importlib
import inspect

# file key -> importable module name. Keys are the only accepted `file` values.
WHITELIST: dict[str, str] = {
    "config.py": "config",
    "app.py": "app",
    "routes/analysis_routes.py": "routes.analysis_routes",
    "services/nlp_service.py": "services.nlp_service",
    "services/grammar_service.py": "services.grammar_service",
    "services/feedback_service.py": "services.feedback_service",
    "services/analysis_service.py": "services.analysis_service",
    "services/db.py": "services.db",
    "services/transparency.py": "services.transparency",
    "services/source_view.py": "services.source_view",
    "services/keywords.py": "services.keywords",
    "services/wordnet_service.py": "services.wordnet_service",
    "services/similarity.py": "services.similarity",
    "services/prewriting.py": "services.prewriting",
    "services/stage1.py": "services.stage1",
    "services/thesis.py": "services.thesis",
    "services/stage2.py": "services.stage2",
    "services/outline.py": "services.outline",
    "services/stage3.py": "services.stage3",
    "services/reflection.py": "services.reflection",
    "services/stage4.py": "services.stage4",
    "services/knowledge_base/interface.py": "services.knowledge_base.interface",
    "services/rhetorical_moves.py": "services.rhetorical_moves",
    "rules/rule_engine.py": "rules.rule_engine",
    "rules/thesis_rules.py": "rules.thesis_rules",
    "rules/meta_rules.py": "rules.meta_rules",
    "rules/style_rules.py": "rules.style_rules",
    "rules/mechanics_rules.py": "rules.mechanics_rules",
}

MAX_LINES = 2000


def _reject(reason: str) -> dict:
    return {"allowed": False, "error": reason}


def get_source(file: str, function: str | None = None) -> dict:
    """Return whitelisted source code (read-only data, never executes it).

    Returns {allowed: True, file, function, start_line, end_line,
    total_lines, source} or {allowed: False, error}.
    """
    if not isinstance(file, str):
        return _reject("Invalid file parameter.")
    # Block traversal / absolute / separator tricks BEFORE whitelist lookup.
    # (Exact-match lookup alone would already reject these, this is
    # defense-in-depth with explicit error messages.)
    if (
        ".." in file
        or file.startswith(("/", "\\"))
        or "\\" in file
        or (len(file) > 1 and file[1] == ":")
        or file.startswith("~")
    ):
        return _reject("Path traversal / absolute paths are not allowed.")
    module_name = WHITELIST.get(file)
    if module_name is None:
        return _reject(f"File '{file}' is not an approved research module.")
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001
        return _reject(f"Module '{module_name}' could not be loaded: {exc}")

    if not function:
        try:
            lines, start = inspect.getsourcelines(module)
        except Exception as exc:  # noqa: BLE001
            return _reject(f"Source unavailable: {exc}")
        end = start + len(lines) - 1
        return {
            "allowed": True,
            "file": file,
            "function": None,
            "start_line": start,
            "end_line": min(end, start + MAX_LINES - 1),
            "total_lines": len(lines),
            "source": "".join(lines[:MAX_LINES]),
        }

    if not isinstance(function, str) or not function.replace("_", "").isalnum():
        return _reject("Invalid function name.")
    obj = getattr(module, function, None)
    if obj is None or not (inspect.isfunction(obj) or inspect.isclass(obj)):
        return _reject(f"Function '{function}' not found in '{file}'.")
    try:
        lines, start = inspect.getsourcelines(obj)
    except Exception as exc:  # noqa: BLE001
        return _reject(f"Source unavailable: {exc}")
    return {
        "allowed": True,
        "file": file,
        "function": function,
        "start_line": start,
        "end_line": start + len(lines) - 1,
        "total_lines": len(lines),
        "source": "".join(lines),
    }
