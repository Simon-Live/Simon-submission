"""Security response headers: CSP, frame-ancestors, nosniff, Referrer-Policy, Permissions-Policy, COOP, HSTS
(docs/specs/prod-hardening.md "Headers", APP-M1, HOST-M5).

Built from what `web/` loads, not guessed: inline `<script>` bodies and inline event handler attributes of the served
HTML files are allowed by hash, so no `'unsafe-inline'` for scripts. `THIRD_PARTY` is empty: Inter and MediaPipe are
self-hosted under `web/vendor/` (LIC-H5). `'wasm-unsafe-eval'` stays: MediaPipe compiles its WebAssembly.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
import re
import threading

from part7.prod_mode import is_prod

# What web/ loads from outside the origin: nothing. Inter and MediaPipe (code, wasm, pose model) are served from
# web/vendor/ (lane ph-policy, LIC-H5, LEG-H2); a new third party is added here with the file that loads it.
THIRD_PARTY: dict[str, tuple[str, ...]] = {"script": (), "connect": (), "style": (), "font": ()}
PERMISSIONS_POLICY = ("camera=(self), microphone=(self), geolocation=(), payment=(), usb=(), serial=(), bluetooth=(), "
                      "midi=(), magnetometer=(), gyroscope=(), accelerometer=(), interest-cohort=()")
HSTS = "max-age=31536000"
_INLINE_SCRIPT = re.compile(rb"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>", re.S | re.I)
_HANDLER = re.compile(rb"\son[a-z]+=\"(?P<code>[^\"]*)\"", re.I)
_cache: dict[tuple, str] = {}
_lock = threading.Lock()


def csp_mode() -> str:
    """`enforce`, `report-only` or `off` (`SIMON7_CSP_MODE`). Default: enforce in prod, report-only elsewhere."""
    value = os.environ.get("SIMON7_CSP_MODE", "").strip().lower()
    return value if value in ("enforce", "report-only", "off") else ("enforce" if is_prod() else "report-only")


def _hash(raw: bytes) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(raw).digest()).decode() + "'"


def inline_hashes(web_dir: Path) -> tuple[list[str], list[str]]:
    """(inline script hashes, inline event handler hashes) of the top-level `*.html` files in `web_dir`."""
    scripts: set[str] = set()
    handlers: set[str] = set()
    for page in sorted(Path(web_dir).glob("*.html")):
        try:
            data = page.read_bytes()
        except OSError:
            continue
        for found in _INLINE_SCRIPT.finditer(data):
            if b"src=" not in found["attrs"].lower() and found["body"].strip():
                scripts.add(_hash(found["body"]))
        handlers.update(_hash(found["code"]) for found in _HANDLER.finditer(data))
    return sorted(scripts), sorted(handlers)


def _stamp(web_dir: Path) -> tuple:
    try:
        return tuple((p.name, p.stat().st_mtime_ns) for p in sorted(Path(web_dir).glob("*.html")))
    except OSError:
        return ()


def _directive(head: str, origins: tuple[str, ...]) -> str:
    return " ".join((head, *origins))


def build_csp(web_dir: Path, *, framed_by_self: bool = False) -> str:
    """The policy for pages served from `web_dir`. `framed_by_self`: the Part 6 catalog page that Watch frames, or the whitepaper."""
    scripts, handlers = inline_hashes(web_dir)
    script_src = ["'self'", "'wasm-unsafe-eval'", *THIRD_PARTY["script"], *scripts]
    if handlers:
        script_src += ["'unsafe-hashes'", *handlers]
    parts = [
        "default-src 'self'",
        "script-src " + " ".join(script_src),
        _directive("style-src 'self' 'unsafe-inline'", THIRD_PARTY["style"]),  # element style attributes are set in markup
        _directive("font-src 'self' data:", THIRD_PARTY["font"]),
        "img-src 'self' data: blob:",
        "media-src 'self' blob:",
        _directive("connect-src 'self' blob: data:", THIRD_PARTY["connect"]),
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors " + ("'self'" if framed_by_self else "'none'"),
    ]
    return "; ".join(parts)


def csp_for(web_dir: Path, *, framed_by_self: bool = False) -> str:
    key = (str(web_dir), framed_by_self, _stamp(web_dir))
    with _lock:
        if key not in _cache:
            _cache.clear()
            _cache[key] = build_csp(web_dir, framed_by_self=framed_by_self)
        return _cache[key]


def headers(web_dir: Path, *, same_origin_frame: bool = False, https: bool | None = None) -> dict[str, str]:
    """The headers every response carries. `same_origin_frame`: a page the app frames from its own origin (a Part 6
    catalog page, or the whitepaper).

    HSTS only in prod (`https` overrides, for tests). Referrer-Policy is added by `_Handler._send`.
    """
    out = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN" if same_origin_frame else "DENY",
        "Permissions-Policy": PERMISSIONS_POLICY,
        "Cross-Origin-Opener-Policy": "same-origin",
    }
    mode = csp_mode()
    if mode != "off":
        name = "Content-Security-Policy" if mode == "enforce" else "Content-Security-Policy-Report-Only"
        out[name] = csp_for(web_dir, framed_by_self=same_origin_frame)
    if is_prod() if https is None else https:
        out["Strict-Transport-Security"] = HSTS
    return out
