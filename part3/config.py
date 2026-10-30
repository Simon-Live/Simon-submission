"""The optional `part3.toml` file (spec integration-contract.md "Body profiles").

Lookup: an explicit path (`--config`, API `config=<path>`), else the `PART3_CONFIG` environment
variable, else `./part3.toml` when it exists. `config=False` never reads a file. The tables read are
`[body]` with `profile` (a string) and `stature` (a number), and `[keyframes]` with `densify` (`every:<n>` or
`off`, checked only when a part4 keyframes run uses it); other keys are ignored.
"""

import dataclasses
import os
import pathlib
import tomllib

from part3.schema import ContractError, is_number

DEFAULT_NAME = "part3.toml"
ENV_NAME = "PART3_CONFIG"


@dataclasses.dataclass(frozen=True)
class Config:
    """A parsed config file: `label` names it in messages, `dir` anchors relative `file:` paths."""

    path: pathlib.Path
    label: str
    dir: pathlib.Path
    profile: object = None
    stature: object = None
    densify: object = None


def _read(path, label, channel):
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise ContractError(channel, f"{path}: cannot read ({error.strerror or error})") from error
    except UnicodeDecodeError as error:
        raise ContractError(label, f"not valid TOML ({error})") from error
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ContractError(label, f"not valid TOML ({error})") from error


def _body_table(data, label):
    body = data.get("body", {})
    if not isinstance(body, dict):
        raise ContractError(label, "body: expected a table")
    if "profile" in body and not isinstance(body["profile"], str):
        raise ContractError(label, "body.profile: expected a string")
    if "stature" in body and not is_number(body["stature"]):
        raise ContractError(label, "body.stature: expected a number")
    return body


def _densify_value(data, label):
    table = data.get("keyframes", {})
    if not isinstance(table, dict):
        raise ContractError(label, "keyframes: expected a table")
    return table.get("densify")


def _load_file(path, label, channel):
    data = _read(path, label, channel)
    body = _body_table(data, label)
    resolved = pathlib.Path(path).resolve()
    return Config(resolved, label, resolved.parent, body.get("profile"), body.get("stature"),
                  _densify_value(data, label))


def load(config=None, env=None):
    """The `Config` for the lookup above, or None when no file applies.

    `config`: None discovers, False never reads, a str or Path names the file (a missing file is an
    error). `env` is a mapping; None means `os.environ`. Raises ContractError for an unreadable or
    invalid file, naming the file and the key.
    """
    if config is False:
        return None
    env = os.environ if env is None else env
    if config is not None:
        return _load_file(config, str(config), "--config")
    named = env.get(ENV_NAME)
    if named:
        return _load_file(named, named, ENV_NAME)
    if pathlib.Path(DEFAULT_NAME).is_file():
        return _load_file(DEFAULT_NAME, DEFAULT_NAME, DEFAULT_NAME)
    return None
