from __future__ import annotations
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import terminalrpg
from terminalrpg.validation import ConfigError, GameStateError

FIXTURES = Path(__file__).resolve().parent / "fixtures"
VALID = FIXTURES / "valid"
INVALID = FIXTURES / "invalid"
EXAMPLES = ROOT / "examples"


def load_fixture(game_path: Path, save_path: Path):
    old_data, old_save = terminalrpg.DATA_FILE, terminalrpg.SAVE_FILE
    terminalrpg.DATA_FILE = str(game_path)
    terminalrpg.SAVE_FILE = str(save_path)
    try:
        return terminalrpg.load_game_data(), terminalrpg.load_save_data()
    finally:
        terminalrpg.DATA_FILE, terminalrpg.SAVE_FILE = old_data, old_save


def run_with_inputs(game_data, save_data, inputs: list[str]) -> str:
    output = io.StringIO()
    queue = list(inputs)

    def fake_input(prompt: str = "") -> str:
        sys.stdout.write(prompt)
        if not queue:
            raise EOFError
        return queue.pop(0)

    with mock.patch("builtins.input", fake_input), contextlib.redirect_stdout(output):
        terminalrpg.run_game(game_data, save_data)
    return output.getvalue()


def assert_order(testcase: unittest.TestCase, text: str, *snippets: str) -> None:
    position = -1
    for snippet in snippets:
        next_position = text.find(snippet, position + 1)
        testcase.assertGreater(next_position, position, f"{snippet!r} missing or out of order in:\n{text}")
        position = next_position


class BadConfigTests(unittest.TestCase):
    """Configs that used to infinite-loop or jump to nonexistent nodes now fail readably."""

    def test_empty_answer_config_rejected_at_load(self):
        terminalrpg.DATA_FILE = str(INVALID / "empty_answer.json")
        with self.assertRaises(ConfigError) as ctx:
            terminalrpg.load_game_data()
        self.assertIn("no options", str(ctx.exception))
        self.assertIn("root", str(ctx.exception))

    def test_locked_routes_only_terminates_at_runtime(self):
        game_data, save_data = load_fixture(
            INVALID / "locked_routes_only.json", INVALID / "locked_routes_only.save.json"
        )
        with self.assertRaises(GameStateError) as ctx:
            run_with_inputs(game_data, save_data, [])
        message = str(ctx.exception)
        self.assertIn("locked", message)
        self.assertIn("Skeleton Key", message)

    def test_missing_answer_field_reports_path(self):
        terminalrpg.DATA_FILE = str(INVALID / "missing_answer.json")
        with self.assertRaises(ConfigError) as ctx:
            terminalrpg.load_game_data()
        message = str(ctx.exception)
        self.assertIn("answer", message)
        self.assertIn('"1"', message)

    def test_duplicate_dialogue_rejected(self):
        terminalrpg.DATA_FILE = str(INVALID / "duplicate_dialogue.json")
        with self.assertRaises(ConfigError) as ctx:
            terminalrpg.load_game_data()
        self.assertIn("Duplicate key", str(ctx.exception))

    def test_bad_answer_type_rejected(self):
        terminalrpg.DATA_FILE = str(INVALID / "bad_answer_type.json")
        with self.assertRaises(ConfigError) as ctx:
            terminalrpg.load_game_data()
        self.assertIn("answer", str(ctx.exception))

    def test_save_missing_field_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
            json.dump({"all": ["Title"]}, tmp)
            tmp_path = tmp.name
        terminalrpg.SAVE_FILE = tmp_path
        with self.assertRaises(ConfigError) as ctx:
            terminalrpg.load_save_data()
        self.assertIn("obtained", str(ctx.exception))

    def test_main_reports_config_error_and_exits(self):
        terminalrpg.DATA_FILE = str(INVALID / "empty_answer.json")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as ctx:
            terminalrpg.main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("Config Error", stderr.getvalue())

    def test_main_reports_game_state_error_and_still_saves(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
            json.dump({"all": ["Skeleton Key", "Gatecrasher"], "obtained": []}, tmp)
            tmp_path = tmp.name
        terminalrpg.DATA_FILE = str(INVALID / "locked_routes_only.json")
        terminalrpg.SAVE_FILE = tmp_path
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            terminalrpg.main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("Game Error", stderr.getvalue())
        with open(tmp_path) as file:
            self.assertEqual(json.load(file)["all"], ["Skeleton Key", "Gatecrasher"])


class ValidConfigTests(unittest.TestCase):
    """Legal configs keep their dialogue order and state changes unchanged."""

    def setUp(self):
        self.game_data, self.save_data = load_fixture(VALID / "mini_game.json", VALID / "mini_save.json")

    def test_dialogue_order_and_title_awarded(self):
        output = run_with_inputs(self.game_data, self.save_data, ["2", "1"])
        assert_order(self, output, "Start", "Where to?", "Forest", "A path splits.", "Left", "A river.", "You swim across.")
        self.assertEqual(self.save_data["obtained"], ["Swimmer"])

    def test_terminal_branch(self):
        output = run_with_inputs(self.game_data, self.save_data, ["1"])
        assert_order(self, output, "Start", "Cave", "It is dark.", "You find a torch.")
        self.assertEqual(self.save_data["obtained"], ["Torchbearer"])

    def test_wildcard_branch(self):
        run_with_inputs(self.game_data, self.save_data, ["2", "anything else"])
        self.assertEqual(self.save_data["obtained"], ["Lost"])

    def test_secret_branch(self):
        run_with_inputs(self.game_data, self.save_data, ["2", "map"])
        self.assertEqual(self.save_data["obtained"], ["Cartographer"])

    def test_unknown_option_reprompts_without_state_change(self):
        output = run_with_inputs(self.game_data, self.save_data, ["bogus", "1"])
        self.assertIn("Invalid Input!", output)
        self.assertEqual(output.count("Where to?"), 2)
        self.assertEqual(self.save_data["obtained"], ["Torchbearer"])

    def test_dotted_option_is_not_a_phantom_secret_jump(self):
        output = run_with_inputs(self.game_data, self.save_data, ["1.2", "v1.2"])
        self.assertIn("Invalid Input!", output)
        assert_order(self, output, "Invalid Input!", "Version Stone", "The engraving hums.")
        self.assertEqual(self.save_data["obtained"], ["Archaeologist"])

    def test_eof_terminates_cleanly(self):
        output = run_with_inputs(self.game_data, self.save_data, [])
        self.assertIn("Ending game.", output)
        self.assertEqual(self.save_data["obtained"], [])

    def test_debug_mode_raises_readable_error_on_unknown_option(self):
        terminalrpg.DEBUG = True
        try:
            with self.assertRaises(GameStateError) as ctx:
                run_with_inputs(self.game_data, self.save_data, ["bogus"])
            self.assertIn("bogus", str(ctx.exception))
        finally:
            terminalrpg.DEBUG = False


class ExampleConfigTests(unittest.TestCase):
    """The shipped example games must keep working exactly as before."""

    def test_terminal_game_loads_and_plays(self):
        game_data, save_data = load_fixture(
            EXAMPLES / "terminal_game" / "data.json", EXAMPLES / "terminal_game" / "save.json"
        )
        output = run_with_inputs(game_data, save_data, ["help", "about"])
        assert_order(self, output, "ROOT://", "Known commands", "A game about a game.", "Awarded Title: Read The Manual")
        self.assertEqual(save_data["obtained"], ["Read The Manual"])

    def test_terminal_game_dotted_host_option_still_works(self):
        game_data, save_data = load_fixture(
            EXAMPLES / "terminal_game" / "data.json", EXAMPLES / "terminal_game" / "save.json"
        )
        output = run_with_inputs(game_data, save_data, ["network", "192.168.1.1"])
        assert_order(self, output, "router", "Just a router. Boring.")
        self.assertEqual(save_data["obtained"], ["Port Scanner"])

    def test_birthday_game_loads_and_plays(self):
        game_data, save_data = load_fixture(
            EXAMPLES / "birthday_game" / "data.json", EXAMPLES / "birthday_game" / "save.json"
        )
        save_data["obtained"] = []
        output = run_with_inputs(game_data, save_data, ["2", "1", "1"])
        assert_order(self, output, "The Pencil Sharpener", "Steal it", "32", "Awarded Title: Hand Calculator")
        self.assertEqual(save_data["obtained"], ["Hand Calculator"])


if __name__ == "__main__":
    unittest.main()
