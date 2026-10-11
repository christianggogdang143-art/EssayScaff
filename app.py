"""EssayScaff Phase 1 — Flask entry point (live feedback engine)."""

from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, render_template  # noqa: E402

from routes.analysis_routes import api_bp  # noqa: E402
from routes.validation_routes import validation_bp  # noqa: E402
from services.db import init_db  # noqa: E402


# Global request-body cap (engineering/security limit, not a research
# threshold). Sized from existing per-field limits: the largest legitimate
# payload is a max-size Stage-3 outline (6 points x 21 texts x 20000 chars
# ~= 2.6 MB JSON), so 5 MB leaves ~2x headroom while blocking unbounded
# bodies. Deliberately kept OUT of config.py's frozen classifier
# configuration so VR-2 snapshot hashes can never be affected by it.
MAX_CONTENT_LENGTH = 5 * 1024 * 1024


def create_app(prewarm: bool = True) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
    app.register_blueprint(api_bp)
    app.register_blueprint(validation_bp)
    try:
        init_db()
    except Exception:  # noqa: BLE001 - app must boot even if DB init fails
        logging.getLogger(__name__).exception("Database init failed; continuing without persistence")

    if prewarm:
        try:
            from services.grammar_service import prewarm as lt_prewarm

            # Daemon thread: warms the shared LanguageTool server in the
            # background. Boot never blocks and never fails when LT is down.
            lt_prewarm()
        except Exception:  # noqa: BLE001 - prewarm must never break boot
            logging.getLogger(__name__).exception("LanguageTool prewarm failed; grammar checks will degrade")

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/research/validation")
    def validation_workspace():
        """Researcher-only validation workspace (not a student stage)."""
        return render_template("validation.html")

    return app


app = create_app()

if __name__ == "__main__":
    # debug=False: the reloader spawns a child process that breaks clean
    # shutdown and double-boots the NLP backends. Use flask --debug for dev.
    app.run(host="127.0.0.1", port=5000, debug=False)
