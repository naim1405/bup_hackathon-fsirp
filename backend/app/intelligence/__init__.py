"""Intelligence engine for FSIRP.

Everything related to intelligence lives in this package and nowhere else:
training, forecasting, detection, projection, allocation planning, the
operator approval/execution workflow, and the HTTP API wiring.

Public entry points:
    * :class:`app.intelligence.service.IntelligenceEngine` — orchestrator.
    * :data:`app.intelligence.config.POLICY` — operator-tunable policy.
    * :data:`app.intelligence.routes.router` — FastAPI routes.
"""

from app.intelligence.config import POLICY, PolicyConfig

__all__ = ["POLICY", "PolicyConfig"]
