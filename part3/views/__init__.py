"""Output views (spec integration-contract.md "Views"): pure functions of the native skeleton.

`REGISTRY` maps a view name to its module, which has `NAME`, `DESCRIPTION`, `SCHEMA` (the file in
`contracts/` that describes its output) and `render(skeleton, **opts) -> dict`. The built-in modules
are imported on first use. A new view is one module plus its name in `NAMES` (or a call to `register`).
"""

import importlib

from part3.schema import ContractError

NAMES = ("native", "part4", "part5")
_loaded = None


def _load():
    return {name: importlib.import_module(f"part3.views.{name}") for name in NAMES}


def _registry():
    global _loaded
    if _loaded is None:
        _loaded = _load()
    return _loaded


def __getattr__(name):
    if name == "REGISTRY":
        return _registry()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def register(module):
    """Add a view module (it needs `NAME`, `DESCRIPTION`, `SCHEMA` and `render`)."""
    _registry()[module.NAME] = module


def names():
    """The view names `--view` accepts: the built-in names, then any others registered."""
    return list(NAMES) + [name for name in _registry() if name not in NAMES]


LIMITS = ("max_frames", "keyframes_densify", "densify_flag", "env", "config")  # limits and ignorable channels, never refused


def reject_options(opts, view):
    """Raise ContractError for an option that is set but only another view uses (`--keyframes` with `native`)."""
    for key, value in opts.items():
        if value is not None and key not in LIMITS:
            raise ContractError("--" + key.replace("_", "-"), f"only applies to --view part4 (the view is {view})")


def render(skeleton, view="native", **opts):
    """The `view` document for a native `skeleton`; `opts` (keyframes, keyframes_person, max_frames, keyframes_densify, env, config) go to the view as given.

    `max_frames` (None: the cap, `resample.MAX_FRAMES`) bounds the part4 timeline; the other views have
    none and ignore it. Raises ContractError("--view", ...) for a view that is not registered.
    """
    module = _registry().get(view) if isinstance(view, str) else None
    if module is None:
        raise ContractError("--view", f"must be one of {', '.join(names())}")
    return module.render(skeleton, **opts)


def keyframes_doc(rendered):
    """The `simon.keyframes.v1` companion of a part4 render, or None for a render without a `timeline`."""
    if not isinstance(rendered, dict) or "timeline" not in rendered:
        return None
    return _registry()["part4"].keyframes_doc(rendered)
