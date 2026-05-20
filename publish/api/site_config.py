"""publication/site_config.py — deploy-environment configuration.

Separated from `meta.py` (which is the analytical-pin source of truth)
because the URL prefix is a deploy-environment property, not a
methodology pin. Moving from project-page to custom-domain hosting
should not bump the pin.

`SITE_BASE` is the URL prefix the deployed site is served under. For
the default GitHub Pages project deploy at
https://hwesto.github.io/epistemic-lens/ the prefix is
`/epistemic-lens`. Override via the EPISTEMIC_LENS_BASE env var
(e.g. `""` for org-page or custom-domain deploys at the root).

Used by `publication/page_renderers.py`, `card_renderers.py`, and
`build_index.py` to prefix every absolute path in the rendered HTML
and stamped JSON, so links resolve against the actual served subpath
instead of the org root.
"""
from __future__ import annotations

import os

SITE_BASE: str = os.environ.get("EPISTEMIC_LENS_BASE", "/epistemic-lens").rstrip("/")
