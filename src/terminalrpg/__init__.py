from __future__ import annotations
from collections import Counter
from typing import TypedDict, Any
import json
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ModuleNotFoundError:
    pass

from .validation import (
    ConfigError,
    GameStateError,
    load_json_strict,
    validate_game_data,
    validate_save_data,
)

DATA_FILE: str | None = os.getenv("DATA")
SAVE_FILE: str | None = os.getenv("SAVE")
DEBUG: bool = os.getenv("ENV") == "DEBUG"

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

def load_game_data() -> GameData:
    if DATA_FILE is None:
        raise ConfigError('Environment variable "DATA" is not set; point it at a game data JSON file.')
    data = load_json_strict(DATA_FILE)
    validate_game_data(data)
    return process_json_data(data)

def load_save_data() -> SaveData:
    if SAVE_FILE is None:
        raise ConfigError('Environment variable "SAVE" is not set; point it at a save JSON file.')
    data = load_json_strict(SAVE_FILE)
    validate_save_data(data)
    return SaveData(data)

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
    while True:
        print("-------------")
        print(game_data["prompt"]) if game_data["prompt"] else None
        print(game_data["question"]) if game_data["question"] else None

        if end_game_if_end(game_data, save_data):
            print(game_data["answer"])
            return
        assert isinstance(game_data["answer"], dict) # Answer Is Guarantee To Be Dict Cuz Otherwise End Game. Assert For Type Checkers

        locked_options = [option for option in game_data["answer"] if is_not_unlocked_route(option, save_data)]
        if len(locked_options) == len(game_data["answer"]):
            raise GameStateError(
                "No available options: every route from this node is locked, so the game cannot continue.\n"
                f"Node prompt: {game_data['prompt']!r}\n"
                f"Locked option(s): {', '.join(repr(option) for option in locked_options)}\n"
                'Unlock the required title(s) or add a reachable option (e.g. a "*" wildcard) to this node.'
            )

        option_str: str = "\n".join([
            f"{option}) {data["prompt"]}" 
            for option, data in game_data["answer"].items() 
            if not is_hidden_option(option, save_data)
        ])

        try:
            response: str = input(option_str + "\n")
        except EOFError:
            print("\nInput stream closed. Ending game.")
            return

        if is_not_unlocked_route(response, save_data):
            print("Invalid Input?")
            continue

        if (data := game_data["answer"].get(response)) is not None:
            game_data = data
            continue

        secret_options = {key[1:].strip(): key for key in game_data["answer"].keys() if key.startswith(".")}
        if response in secret_options:
            game_data = game_data["answer"][secret_options[response]]
            continue

        if "*" in game_data["answer"].keys():
            game_data = game_data["answer"]["*"]
            continue

        if DEBUG:
            raise GameStateError(f"Failed to read input.\nInput: {response}\nGame Data: {game_data}")
        print("Invalid Input!")

def main():
    try:
        game_data: GameData = load_game_data()
        save_data: SaveData = load_save_data()
    except ConfigError as exc:
        print(f"Config Error: {exc}", file=sys.stderr)
        raise SystemExit(1)

    if is_game_complete(save_data):
        print("Game Completed!")
        return

    try:
        run_game(game_data, save_data)
    except GameStateError as exc:
        print(f"Game Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    finally:
        save_data_to_file(save_data)
