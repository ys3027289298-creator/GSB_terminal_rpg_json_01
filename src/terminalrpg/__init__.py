from __future__ import annotations
from collections import Counter
from typing import TypedDict, Any
import json
import os
import sys

try:
    from dotenv import load_dotenv
except ModuleNotFoundError: # dotenv Is Optional, Engine Must Still Boot Without It
    def load_dotenv(*args: Any, **kwargs: Any) -> bool:
        return False

load_dotenv()

DATA_FILE: str = os.getenv("DATA", "")
SAVE_FILE: str = os.getenv("SAVE", "")
DEBUG: bool = os.getenv("ENV") == "DEBUG"

# Hard Cap On Dialogue Steps Per Run. A Legit Game Never Comes Close,
# So Hitting It Means The Config Loops Back On Itself.
MAX_STEPS: int = 10_000

NODE_FIELDS: frozenset[str] = frozenset({"prompt", "question", "answer"})

class GameError(Exception):
    """Readable Engine Error, Safe To Show To Players/Authors."""

class ConfigError(GameError):
    """Raised When The JSON Config Breaks The Schema Or Jump Rules."""

class GameStateError(GameError):
    """Raised When A Valid-Looking Config Deadlocks At Runtime."""

class GameData(TypedDict):
    """
    Prompt Is What Appears Next To The Option
    When You Choose The Option, The Question Appears(Context For The Next Option)
    Answers Can Either Be: 
        - String: Only One Option
        - Dict: Multiple Options
            - GameData: New Game State As Result Of The Option
            - String: No New Game State, End Game(Will Be Converted Into Blank Game Data State)
    """
    prompt: str
    question: str
    answer: str | dict[str, GameData]

class SaveData(TypedDict):
    all: list[str]
    obtained: list[str]

def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """json object_pairs_hook That Rejects Duplicate Dialogue Options."""
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise ConfigError(f"Duplicate dialogue option '{key}' in the same node. Each option must be defined once.")
        obj[key] = value
    return obj

def validate_game_data(node: Any, path: str = "root", _ancestors: set[int] | None = None) -> None:
    """
    Schema And Jump-Safety Rules For The JSON Config (Format Unchanged):
      1. Every Node Is An Object With Exactly prompt/question/answer.
      2. prompt And question Must Be Strings.
      3. answer Is Either A String (Ending) Or A Non-Empty Object Of Options.
      4. Option Keys Are Strings; Values Are Strings (Ending) Or Nodes.
      5. No Duplicate Option Keys Inside One Node (Checked At Parse Time).
      6. No Cyclic Jumps: A Node May Never Reference Itself Or An Ancestor.
    """
    if _ancestors is None:
        _ancestors = set()

    if not isinstance(node, dict):
        raise ConfigError(f"{path}: Node must be a JSON object, got {type(node).__name__}.")

    if id(node) in _ancestors:
        raise ConfigError(f"{path}: Cyclic jump detected. A node cannot lead back to itself or an ancestor.")

    unknown_fields = set(node) - NODE_FIELDS
    if unknown_fields:
        raise ConfigError(f"{path}: Unknown field(s) {sorted(unknown_fields)}. Only {sorted(NODE_FIELDS)} are allowed.")

    for field in ("prompt", "question", "answer"):
        if field not in node:
            raise ConfigError(f"{path}: Missing required field '{field}'.")

    for field in ("prompt", "question"):
        if not isinstance(node[field], str):
            raise ConfigError(f"{path}: Field '{field}' must be a string, got {type(node[field]).__name__}.")

    answer = node["answer"]
    if isinstance(answer, str):
        return

    if not isinstance(answer, dict):
        raise ConfigError(f"{path}: Field 'answer' must be a string (ending) or an object of options, got {type(answer).__name__}.")

    if not answer:
        raise ConfigError(f"{path}: 'answer' is an empty object. The dialogue would have no options and loop forever.")

    _ancestors.add(id(node))
    for option, child in answer.items():
        if not isinstance(option, str):
            raise ConfigError(f"{path}: Option keys must be strings, got {type(option).__name__}.")
        if not isinstance(child, (str, dict)):
            raise ConfigError(f"{path} -> '{option}': Option must be a string (ending) or an object (next node), got {type(child).__name__}.")
        if isinstance(child, dict):
            validate_game_data(child, f"{path} -> '{option}'", _ancestors)
    _ancestors.discard(id(node))

def parse_game_data(text: str) -> GameData:
    """Parse JSON Text Into GameData, Enforcing Schema And Jump Rules."""
    try:
        raw = json.loads(text, object_pairs_hook=_unique_object)
    except json.JSONDecodeError as error:
        raise ConfigError(f"Invalid JSON: {error}") from error
    validate_game_data(raw)
    return process_json_data(raw)

def load_game_data() -> GameData:
    if not DATA_FILE:
        raise ConfigError("DATA environment variable is not set. Point it at a game data JSON file.")
    try:
        with open(DATA_FILE, "r") as file:
            return parse_game_data(file.read())
    except OSError as error:
        raise ConfigError(f"Cannot read DATA file '{DATA_FILE}': {error.strerror or error}") from error

def load_save_data() -> SaveData:
    if not SAVE_FILE:
        raise ConfigError("SAVE environment variable is not set. Point it at a save JSON file.")
    try:
        with open(SAVE_FILE, "r") as file:
            return SaveData(json.load(file))
    except OSError as error:
        raise ConfigError(f"Cannot read SAVE file '{SAVE_FILE}': {error.strerror or error}") from error
    except json.JSONDecodeError as error:
        raise ConfigError(f"Invalid JSON in SAVE file '{SAVE_FILE}': {error}") from error

def save_data_to_file(save_data: SaveData) -> None:
    with open(SAVE_FILE, "w") as file:
        json.dump(save_data, file, indent=4)

def string_to_game_data(answer_string: str) -> GameData:
    return GameData(prompt="", question="", answer=answer_string)

def process_json_data(data: dict[str, Any]) -> GameData:
    if isinstance(data["answer"], str):
        return GameData(**data)

    for option, answer in data["answer"].items():
        data["answer"][option] = string_to_game_data(answer) \
            if isinstance(answer, str) \
            else process_json_data(answer)
    return GameData(**data)

def is_game_complete(save_data: SaveData) -> bool:
    return Counter(save_data["all"]) == Counter(save_data["obtained"])

def award_title(title: str, save_data: SaveData) -> None:
    title = title.strip()
    if title not in save_data["obtained"]:
        save_data["obtained"].append(title)

def end_game_if_end(game_data: GameData, save_data: SaveData) -> bool:
    if isinstance(game_data["answer"], dict):
        return False

    if "Awarded Title" in game_data["answer"]:
        award_title(game_data["answer"].rsplit(":", 1)[1], save_data)
    return True

def is_not_unlocked_route(option: str, save_data: SaveData) -> bool:
    return option in save_data["all"] and option not in save_data["obtained"]

def is_hidden_option(option: str, save_data: SaveData) -> bool:
    """
    - Not Blank(Enter)
    - Not *(Wildcard Any)
    - Not .(Secret)
    """
    return option == "" or "*" in option or "." in option or is_not_unlocked_route(option, save_data)

def run_game(game_data: GameData, save_data: SaveData) -> None:
    for _step in range(MAX_STEPS):
        print("-------------")
        print(game_data["prompt"]) if game_data["prompt"] else None
        print(game_data["question"]) if game_data["question"] else None

        if end_game_if_end(game_data, save_data):
            print(game_data["answer"])
            return
        assert isinstance(game_data["answer"], dict) # Answer Is Guarantee To Be Dict Cuz Otherwise End Game. Assert For Type Checkers

        reachable = [option for option in game_data["answer"] if not is_not_unlocked_route(option, save_data)]
        if not reachable:
            raise GameStateError(
                "Dialogue deadlocked: every option at this node is locked "
                f"(question: {game_data['question']!r}). The game would loop forever, so it was stopped."
            )

        option_str: str = "\n".join([
            f"{option}) {data["prompt"]}" 
            for option, data in game_data["answer"].items() 
            if not is_hidden_option(option, save_data)
        ])

        try:
            response: str = input(option_str + "\n")
        except EOFError:
            print("Input stream closed. Ending game.")
            return

        if is_not_unlocked_route(response, save_data):
            print("Invalid Input?")
            continue

        if (data := game_data["answer"].get(response)) is not None:
            game_data = data
            continue

        secret_options = [key.split(".", 1)[1].strip() for key in game_data["answer"].keys() if "." in key]
        if response in secret_options:
            game_data = game_data["answer"][f".{response}"]
            continue

        if "*" in game_data["answer"].keys():
            game_data = game_data["answer"]["*"]
            continue

        if DEBUG:
            raise Exception(f"Failed to read input.\nInput: {response}\nGame Data: {game_data}")
        print("Invalid Input!")
    raise GameStateError(f"Dialogue exceeded the {MAX_STEPS} step limit. The config likely jumps in a cycle, so the game was stopped.")

def main():
    try:
        game_data: GameData = load_game_data()
        save_data: SaveData = load_save_data()
    except GameError as error:
        print(f"Config Error: {error}", file=sys.stderr)
        raise SystemExit(1)

    if is_game_complete(save_data):
        print("Game Completed!")
        return

    try:
        run_game(game_data, save_data)
    except GameError as error:
        print(f"Game Stopped: {error}", file=sys.stderr)
    finally:
        save_data_to_file(save_data)
