from __future__ import annotations
from typing import Any
import json

class ConfigError(Exception):
    """Raised when a JSON config violates the TerminalRPG schema (docs/SCHEMA.md)."""

class GameStateError(Exception):
    """Raised when the state machine cannot safely continue and must terminate."""

NODE_FIELDS = {"prompt", "question", "answer"}

def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise ConfigError(
                f'Duplicate key "{key}" in JSON object. '
                "Repeated dialogue options must be renamed or removed."
            )
        obj[key] = value
    return obj

def load_json_strict(path: str) -> Any:
    try:
        with open(path, "r") as file:
            return json.load(file, object_pairs_hook=_reject_duplicate_keys)
    except FileNotFoundError:
        raise ConfigError(f'Config file not found: "{path}".') from None
    except json.JSONDecodeError as exc:
        raise ConfigError(f'Invalid JSON in "{path}": {exc}.') from None

def validate_game_data(data: Any) -> None:
    _validate_node(data, path="root")

def _validate_node(node: Any, path: str) -> None:
    if not isinstance(node, dict):
        raise ConfigError(f"{path}: node must be a JSON object, got {type(node).__name__}.")

    missing = NODE_FIELDS - node.keys()
    if missing:
        raise ConfigError(f"{path}: node is missing required field(s): {', '.join(sorted(missing))}.")

    extra = node.keys() - NODE_FIELDS
    if extra:
        raise ConfigError(f"{path}: node has unknown field(s): {', '.join(sorted(extra))}.")

    for field in ("prompt", "question"):
        if not isinstance(node[field], str):
            raise ConfigError(f'{path}: field "{field}" must be a string.')

    answer = node["answer"]
    if isinstance(answer, str):
        return
    if not isinstance(answer, dict):
        raise ConfigError(f'{path}: field "answer" must be a string or an object of options.')
    if not answer:
        raise ConfigError(
            f'{path}: node has no options; the game could never leave this node. '
            'Add at least one option (or a "*" wildcard).'
        )

    for option, target in answer.items():
        if option.startswith(".") and not option[1:].strip():
            raise ConfigError(f'{path}: secret option "{option}" has no name; secret options must look like ".name".')
        if isinstance(target, str):
            continue
        _validate_node(target, f'{path} -> "{option}"')

def validate_save_data(data: Any) -> None:
    if not isinstance(data, dict):
        raise ConfigError("save: root must be a JSON object.")
    for field in ("all", "obtained"):
        if field not in data:
            raise ConfigError(f'save: missing required field "{field}".')
        if not isinstance(data[field], list) or not all(isinstance(title, str) for title in data[field]):
            raise ConfigError(f'save: field "{field}" must be a list of strings.')
