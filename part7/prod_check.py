"""The prod start-up check and the prod values the other modules read (docs/specs/prod-hardening.md).

`verify_start()` is the one place that decides whether the app may start in prod (`prod_mode.is_prod()`); it lists
every problem by name and never prints a value. Outside prod it does nothing.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Mapping
from urllib.parse import urlsplit

from part7.prod_mode import ProdModeError, is_prod

SECRETS_ENV = "PROD_SECRETS_DIR"
ORIGIN_ENVS = ("PROD_PUBLIC_URL", "PROD_ORIGIN")  # CONTRACT.md names PROD_PUBLIC_URL; PROD_ORIGIN is the register's name
HOSTS_ENV = "SIMON7_PROD_HOSTS"  # extra comma separated hostnames (the registry's non-canonical domains)
MAIL_SECRETS = ("SIMON7_SMTP_URL", "SIMON7_MAIL_FROM")  # ADR-0025
# Environment names that switch on a stub, a test transport, a mock provider or a debug route.
STUB_ENV_PREFIXES = ("SIMON7_STAGING", "STAGING_", "SIMON7_FAKE", "SIMON7_STUB", "SIMON7_MOCK", "SIMON7_TEST", "SIMON7_DEBUG")
# A key in the environment is an operator key: prod reads secrets from PROD_SECRETS_DIR files only.
KEY_ENV_NAMES = ("MODEL_API_KEY", "HF_TOKEN", "BASETEN_API_KEY", "MUSE_SPARK_API_KEY", "MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET",
                 "MODAL_CONFIG_PATH", "SIMON7_SMTP_URL", "SIMON7_SMTP_HOST", "SIMON7_SMTP_USER", "SIMON7_SMTP_PASSWORD",
                 "SIMON7_MAIL_API_KEY", "SIMON7_AUTH_PEPPER")
# Path fragments that mark an operator key location (the firm's operator keys, Simon's own key folder, Modal's token file).
OPERATOR_PATH_PARTS = ("operator-keys", "/.config/" + "firm", "/.config/simon", ".modal.toml")
BYOK_TTL_MAX_S = 86400
# Variables that make prod run something on this host it must not (security audit B1, R1).
REFUSED_ENV = {
    "SIMON7_PRIVATE": "private mode runs a local LLM on the host GPU, never in prod",
    "SIMON7_PART2_GPU_VENV": "prod runs Part 2 on Modal only, never in a host GPU venv",
    # prod verify nofallback D2: each starts a resident Part 2 model on this host (p2_pose turns them off too)
    "SIMON7_P2_WARM_WORKERS": "the warm 3D worker holds a Part 2 model on this host, never in prod",
    "SIMON7_P2_TRACK_WORKER": "the warm track worker holds a Part 2 model on this host, never in prod",
}
# Policy switches that would run a model on this host when on (nofallback D2): only unset or off starts. Face copy is not one:
# in prod it runs on the Modal app simon-image3d (SIMON7_SERVERLESS_IMAGE3D=1), never on this host.
REFUSED_ON = {
    "SIMON7_POLICY_MMS_TTS": "MMS speech installs and runs a TTS model on this host",
}
STATE_ENV, APP_STATE_ENV = "PROD_STATE_DIR", "SIMON7_STATE_DIR"
_WARNED: list[str] = []


def secrets_dir(env: Mapping[str, str] | None = None) -> Path | None:
    raw = (env if env is not None else os.environ).get(SECRETS_ENV, "").strip()
    return Path(raw).expanduser().resolve() if raw else None


def origin(env: Mapping[str, str] | None = None) -> str | None:
    """The public origin (`https://host`, no path) the contract hands the app, or None."""
    source = env if env is not None else os.environ
    for name in ORIGIN_ENVS:
        value = source.get(name, "").strip().rstrip("/")
        parts = urlsplit(value)
        if value and parts.scheme == "https" and parts.hostname and not parts.path and not parts.query:
            return f"https://{parts.netloc.lower()}"
    return None


def allowed_hosts(env: Mapping[str, str] | None = None) -> frozenset[str]:
    """Hostnames (no port) a prod request may name in `Host`: the public origin's plus `SIMON7_PROD_HOSTS`."""
    source = env if env is not None else os.environ
    names = {h.strip().lower() for h in source.get(HOSTS_ENV, "").split(",") if h.strip()}
    found = origin(source)
    if found:
        names.add(urlsplit(found).hostname or "")
    names.discard("")
    return frozenset(names)


def byok_ttl_problem(env: Mapping[str, str]) -> str | None:
    """The credential store's TTL (`modal_creds.IDLE_TTL_S`) is the only one; a variable naming another would make the
    health line and the store disagree, so it is refused (one source, set at integration)."""
    from part7 import modal_creds  # here: prod_check is imported by config, which most modules import

    raw = env.get("SIMON7_BYOK_IDLE_TTL_S", "").strip()
    if raw and raw != str(modal_creds.IDLE_TTL_S):
        return (f"SIMON7_BYOK_IDLE_TTL_S is not used: the credential store deletes a token after "
                f"{modal_creds.IDLE_TTL_S} s unused; unset it")
    return None


def _mail_problems(env: Mapping[str, str], secrets: Path | None) -> list[str]:
    out: list[str] = []
    forced = env.get("SIMON7_MAIL_TRANSPORT", "").strip().lower()
    if forced and forced != "smtp":
        out.append("SIMON7_MAIL_TRANSPORT names a stub or test mail transport; prod sends through SMTP only")
    if secrets is None:
        return out
    for name in MAIL_SECRETS:
        path = secrets / name
        if not path.is_file() or not path.read_text(encoding="utf-8", errors="replace").strip():
            out.append(f"the secret file {name} is missing or empty in {SECRETS_ENV} (ADR-0025)")
    url_file = secrets / "SIMON7_SMTP_URL"
    if url_file.is_file():
        scheme = urlsplit(url_file.read_text(encoding="utf-8", errors="replace").strip()).scheme
        if scheme not in ("smtp", "smtps"):  # smtp is STARTTLS (mail._smtp_send never sends in the clear), smtps implicit TLS
            out.append("SIMON7_SMTP_URL must start with smtps:// (implicit TLS) or smtp:// (STARTTLS required)")
    return out


def _key_file_problems(secrets: Path | None, muse_on: bool = False) -> list[str]:
    """Operator key files in the secrets dir: refused (keys.PROD_REFUSED_KEYS, R1), but for the Muse keys while that switch is on."""
    if secrets is None:
        return []
    from part7 import keys  # here: keys imports config, which imports this module

    allowed = keys.MUSE_KEYS if muse_on else ()
    return [f"the key file {name} is in {SECRETS_ENV}; prod spends no operator key (only {', '.join(keys.PROD_KEYS)})"
            for name in keys.PROD_REFUSED_KEYS if name not in allowed and (secrets / name).exists()]


def _muse_problems(source: Mapping[str, str], secrets: Path | None) -> list[str]:
    """With the Muse switch on: its key files and caps above 0 (docs/specs/muse-prod.md). Prod never starts half open."""
    from part7 import keys

    out = [f"SIMON7_POLICY_MUSE is on but the key file {name} is not in {SECRETS_ENV}" for name in keys.MUSE_KEYS
           if secrets is None or not (secrets / name).is_file()]
    return out


def _inside(path: Path, folder: Path) -> bool:
    return folder in path.parents


def prod_state(env: Mapping[str, str]) -> Path | None:
    """The prod state dir: PROD_STATE_DIR (prod/up.sh passes it), else the parent of SIMON7_STATE_DIR (`$STATE/app`)."""
    raw = env.get(STATE_ENV, "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    app = env.get(APP_STATE_ENV, "").strip()
    return Path(app).expanduser().resolve().parent if app else None


def _host_problems(env: Mapping[str, str]) -> list[str]:
    """nofallback D2 and D3: HOME and the Part 2 host venv live in the prod state dir, never in a person's home, so
    no file of the host (a GPU venv, a model cache, a Modal profile) is found by its default path."""
    import pwd  # here: unused outside prod

    state = prod_state(env)
    if state is None:
        return [f"{APP_STATE_ENV} is not set; prod keeps its state, and its HOME, in the prod state dir"]
    out = []
    home = Path(env.get("HOME") or pwd.getpwuid(os.getuid()).pw_dir).expanduser().resolve()
    if not _inside(home, state) or home == Path(pwd.getpwuid(os.getuid()).pw_dir).resolve():
        out.append(f"HOME is outside the prod state dir; prod/up.sh sets it to {STATE_ENV}/home")
    app = env.get(APP_STATE_ENV, "").strip()
    if app and not _inside(Path(app).expanduser().resolve(), state) and Path(app).expanduser().resolve() != state:
        out.append(f"{APP_STATE_ENV} is outside {STATE_ENV}")
    host_py = env.get("SIMON7_P2_HOST_PYTHON", "").strip()
    if host_py and not _inside(Path(host_py).expanduser().absolute(), state):
        out.append("SIMON7_P2_HOST_PYTHON is outside the prod state dir; prod/up.sh prepares it there")
    return out


def _byok_key_problem(env: Mapping[str, str]) -> str | None:
    """lifecycle R1: the credential key was made for this state and its file is gone."""
    from part7 import byok_crypto  # here: byok_crypto imports prod_mode only, but keep start-up imports light

    app = env.get(APP_STATE_ENV, "").strip()
    return byok_crypto.missing_problem(Path(app).expanduser(), env) if app else None


def _pepper_problem(env: Mapping[str, str]) -> str | None:
    """byok R7: a pepper an earlier start wrote into the state dir rides in every backup; prod keeps it in the secrets dir."""
    app = env.get(APP_STATE_ENV, "").strip()
    found = Path(app).expanduser() / "identity" / "SIMON7_AUTH_PEPPER" if app else None
    if found is not None and (found.is_symlink() or found.exists()):
        return f"SIMON7_AUTH_PEPPER is in the state dir (identity/); move it to {SECRETS_ENV} so no backup holds it"
    return None


def _compute_problems(env: Mapping[str, str], secrets: Path | None) -> list[str]:
    """docs/specs/serverless-compute.md AC-SC13. Token files are checked by stat only: this process never opens them."""
    from part7 import keys  # here: keys imports config, which imports this module

    compute = env.get("PROD_COMPUTE", "").strip()
    mode = env.get("SIMON7_COMPUTE", "").strip().lower()
    if compute == "byok":
        out = [] if env.get("SIMON7_BYOK", "").strip().lower() == "on" else [
            "PROD_COMPUTE is byok and SIMON7_BYOK is not on; bring-your-own compute is paused"]
        if mode:
            out.append("SIMON7_COMPUTE is set under PROD_COMPUTE=byok")
        out += [f"the key file {name} is in {SECRETS_ENV}; under byok prod holds no Modal token of its own"
                for name in keys.MODAL_TOKEN_FILES if secrets is not None and (secrets / name).exists()]
        return out
    if compute != "serverless":
        return ["PROD_COMPUTE is not serverless or byok; prod never runs a model on this host"]
    out = [] if mode == "serverless" else ["SIMON7_COMPUTE is not serverless under PROD_COMPUTE=serverless"]
    for name in keys.MODAL_TOKEN_FILES:
        out += _token_file_problems(secrets, name)
    value = env.get("SIMON7_SERVERLESS_MAX_CONCURRENT", "").strip()
    if value and (not value.isdigit() or int(value) < 1):
        out.append("SIMON7_SERVERLESS_MAX_CONCURRENT is not a whole number above 0")
    return out


def _token_file_problems(secrets: Path | None, name: str) -> list[str]:
    import stat

    if secrets is None:
        return []
    try:
        info = (secrets / name).lstat()
    except OSError:
        return [f"the secret file {name} is missing in {SECRETS_ENV}"]
    if not stat.S_ISREG(info.st_mode) or info.st_size == 0:
        return [f"the secret file {name} is not a regular file with content"]
    if stat.S_IMODE(info.st_mode) & 0o077:
        return [f"the secret file {name} is readable by others; it must be 0600"]
    return []


def _model_switch_problems(source: Mapping[str, str]) -> list[str]:
    out = [f"{name} is set; {why}" for name, why in REFUSED_ENV.items() if source.get(name, "").strip()]
    out += [f"{name} is not off; {why}, never in prod" for name, why in REFUSED_ON.items()
            if source.get(name, "").strip().lower() not in ("", "off")]
    return out


def problems(env: Mapping[str, str] | None = None) -> list[str]:
    """Every reason the app must not start in prod; empty when the configuration is good. Never holds a value."""
    source = env if env is not None else os.environ
    out: list[str] = []
    secrets = secrets_dir(source)
    if secrets is None or not secrets.is_dir():
        out.append(f"{SECRETS_ENV} is not set to an existing directory")
        secrets = None
    keys = source.get("SIMON7_KEYS_DIR", "").strip()
    if keys and (secrets is None or Path(keys).expanduser().resolve() != secrets):
        out.append(f"SIMON7_KEYS_DIR is set and is not {SECRETS_ENV}; prod reads secrets from {SECRETS_ENV} only")
    found = origin(source)
    if found is None:
        out.append("the public origin is missing or not a plain https://host (PROD_PUBLIC_URL or PROD_ORIGIN)")
    pinned = source.get("SIMON7_PUBLIC_ORIGIN", "").strip().rstrip("/")
    if pinned and pinned != found:
        out.append("SIMON7_PUBLIC_ORIGIN differs from the prod origin")
    out += _compute_problems(source, secrets)
    ttl = byok_ttl_problem(source)
    if ttl:
        out.append(ttl)
    out += _mail_problems(source, secrets)
    out += [f"{name} switches on a stub, test or debug mode" for name in sorted(source)
            if name.startswith(STUB_ENV_PREFIXES) and source[name].strip() not in ("", "0")]
    out += [f"{name} puts a key in the environment; prod reads keys from {SECRETS_ENV} files" for name in KEY_ENV_NAMES
            if source.get(name, "").strip()]
    out += [f"{name} names an operator key path" for name, value in sorted(source.items())
            if name not in ("PATH", "PWD", "OLDPWD") and any(part in value for part in OPERATOR_PATH_PARTS)]
    out += _model_switch_problems(source)
    out += _host_problems(source)
    key_missing = _byok_key_problem(source)
    if key_missing:
        out.append(key_missing)
    pepper = _pepper_problem(source)
    if pepper:
        out.append(pepper)
    mode = source.get("SIMON7_CSP_MODE", "").strip().lower()
    if mode and mode != "enforce":
        out.append("SIMON7_CSP_MODE is not enforce; prod enforces its Content-Security-Policy")
    byok_key = source.get("SIMON7_BYOK_KEY_FILE", "").strip()
    if byok_key and (secrets is None or secrets not in Path(byok_key).expanduser().resolve().parents):
        out.append(f"SIMON7_BYOK_KEY_FILE is outside {SECRETS_ENV}; the credential key lives with the other secrets")
    muse_on = source.get("SIMON7_POLICY_MUSE", "").strip().lower() == "on"
    out += _key_file_problems(secrets, muse_on)
    if muse_on:
        out += _muse_problems(source, secrets)
    if source.get("SIMON7_DISK_GUARD", "on").strip().lower() == "off":
        out.append("SIMON7_DISK_GUARD=off; the free-disk floor is always on in prod")
    from part7 import legal_drafts  # here: legal_pages imports config, which imports this module
    from part7.parts import p6_catalog  # here: p6_catalog imports config, which imports this module

    out += legal_drafts.problems(source)
    p6_port = p6_catalog.port_problem({**source, "FIRM_ENV": "prod"})  # contract C2: Part 6 on the declared port
    if p6_port:
        out.append(p6_port)
    return out


def verify_start(env: Mapping[str, str] | None = None) -> None:
    """Raise `ProdModeError` naming every problem when prod is misconfigured. A no-op outside prod."""
    active = is_prod() if env is None else env.get("FIRM_ENV", "") == "prod"
    if not active:
        return
    found = problems(env)
    if found:
        raise ProdModeError("prod start refused:\n- " + "\n- ".join(found))
    from part7 import legal_drafts

    note = legal_drafts.warning(env if env is not None else os.environ)
    if note and not _WARNED:  # every start under the override says so, once per process (a11y B10)
        _WARNED.append(note)
        print(f"serve: {note}", file=sys.stderr, flush=True)


def keys_dir_for_prod() -> Path:
    """The only secrets directory prod reads (`config.keys_dir` returns it in prod)."""
    secrets = secrets_dir()
    if secrets is None:
        raise ProdModeError(f"{SECRETS_ENV} is not set")
    return secrets
