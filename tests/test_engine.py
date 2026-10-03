from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import terminalrpg
from terminalrpg import (
    ConfigError,
    GameStateError,
    parse_game_data,
    run_game,
    validate_game_data,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def make_save(all_titles: list[str] | None = None) -> dict:
    return {"all": all_titles or [], "obtained": []}


def load_fresh_save(example: str) -> dict:
    """Load An Example Save With Progress Reset For Deterministic Runs."""
    save = json.loads((EXAMPLES / example / "save.json").read_text())
    save["obtained"] = []
    return save


def run_with_inputs(game_data, save_data, inputs: list[str]) -> str:
    """Run The Engine With Scripted Input, Return Captured Stdout."""
    output = io.StringIO()
    with mock.patch("builtins.input", side_effect=inputs):
        with contextlib.redirect_stdout(output):
            run_game(game_data, save_data)
    return output.getvalue()


def assert_in_order(test_case: unittest.TestCase, output: str, expected: list[str]) -> None:
    position = -1
    for fragment in expected:
        next_position = output.find(fragment, position + 1)
        test_case.assertGreater(next_position, position, f"{fragment!r} missing or out of order in:\n{output}")
        position = next_position


class InfiniteLoopAndBadNodeTests(unittest.TestCase):
    """Configs That Used To Crash Or Spin Forever Must Now Fail Readably."""

    def test_empty_answer_object_rejected(self):
        # A Node With No Options Loops "Invalid Input!" Forever In The Old Engine.
        with self.assertRaises(ConfigError) as ctx:
            parse_game_data('{"prompt": "p", "question": "q", "answer": {}}')
        self.assertIn("empty", str(ctx.exception))
        self.assertIn("root", str(ctx.exception))

    def test_cyclic_jump_rejected_at_validation(self):
        node = {"prompt": "p", "question": "q", "answer": {}}
        node["answer"]["again"] = node  # Self-Referencing Jump
        with self.assertRaises(ConfigError) as ctx:
            validate_game_data(node)
        self.assertIn("Cyclic", str(ctx.exception))

    def test_cyclic_jump_stopped_at_runtime(self):
        # Backstop: Even If Validation Is Bypassed, The State Machine Terminates.
        node = {"prompt": "p", "question": "q", "answer": {}}
        node["answer"]["again"] = node
        with mock.patch.object(terminalrpg, "MAX_STEPS", 5):
            with self.assertRaises(GameStateError) as ctx:
                run_with_inputs(node, make_save(), ["again"] * 10)
        self.assertIn("step limit", str(ctx.exception))

    def test_all_options_locked_deadlock_stopped(self):
        # Every Option Is A Locked Route: Old Engine Reprompts Forever.
        config = '{"prompt": "p", "question": "q", "answer": {"Secret Title": "The End"}}'
        game_data = parse_game_data(config)
        save = make_save(all_titles=["Secret Title"])
        with self.assertRaises(GameStateError) as ctx:
            run_with_inputs(game_data, save, ["anything"] * 3)
        self.assertIn("deadlocked", str(ctx.exception))

    def test_missing_answer_field_rejected(self):
        with self.assertRaises(ConfigError) as ctx:
            parse_game_data('{"prompt": "p", "question": "q"}')
        self.assertIn("'answer'", str(ctx.exception))

    def test_missing_prompt_field_rejected(self):
        with self.assertRaises(ConfigError) as ctx:
            parse_game_data('{"question": "q", "answer": "end"}')
        self.assertIn("'prompt'", str(ctx.exception))

    def test_invalid_answer_type_rejected(self):
        for bad_answer in ("42", "[\"x\"]", "null"):
            with self.assertRaises(ConfigError, msg=bad_answer):
                parse_game_data(f'{{"prompt": "p", "question": "q", "answer": {bad_answer}}}')

    def test_invalid_option_value_rejected(self):
        with self.assertRaises(ConfigError) as ctx:
            parse_game_data('{"prompt": "p", "question": "q", "answer": {"go": 42}}')
        self.assertIn("'go'", str(ctx.exception))

    def test_unknown_field_rejected(self):
        with self.assertRaises(ConfigError) as ctx:
            parse_game_data('{"prompt": "p", "question": "q", "answer": "end", "goto": "nowhere"}')
        self.assertIn("Unknown field", str(ctx.exception))

    def test_duplicate_dialogue_option_rejected(self):
        # JSON Parsers Silently Keep The Last Duplicate Key; The Engine Must Not.
        with self.assertRaises(ConfigError) as ctx:
            parse_game_data('{"prompt": "p", "question": "q", "answer": {"a": "one", "a": "two"}}')
        self.assertIn("Duplicate", str(ctx.exception))

    def test_unknown_option_reprompts_instead_of_crashing(self):
        game_data = parse_game_data(
            '{"prompt": "p", "question": "pick", "answer": {"1": "done"}}'
        )
        save = make_save()
        output = run_with_inputs(game_data, save, ["bogus", "1"])
        assert_in_order(self, output, ["pick", "Invalid Input!", "done"])

    def test_eof_on_input_ends_game_cleanly(self):
        game_data = parse_game_data(
            '{"prompt": "p", "question": "q", "answer": {"1": "done"}}'
        )
        output = io.StringIO()
        with mock.patch("builtins.input", side_effect=EOFError):
            with contextlib.redirect_stdout(output):
                run_game(game_data, make_save())  # Must Return, Not Raise
        self.assertIn("Input stream closed", output.getvalue())

    def test_invalid_json_rejected(self):
        with self.assertRaises(ConfigError) as ctx:
            parse_game_data('{"prompt": "p",')
        self.assertIn("Invalid JSON", str(ctx.exception))


class LegalConfigRegressionTests(unittest.TestCase):
    """Valid Configs Must Keep Their Exact Dialogue Order And State Changes."""

    def test_example_configs_pass_validation(self):
        for data_file in EXAMPLES.glob("*/data.json"):
            with self.subTest(config=data_file):
                parse_game_data(data_file.read_text())

    def test_birthday_game_simple_route(self):
        game_data = parse_game_data((EXAMPLES / "birthday_game" / "data.json").read_text())
        save = load_fresh_save("birthday_game")
        output = run_with_inputs(game_data, save, ["2", "2"])
        assert_in_order(self, output, [
            "Where do you want to go?",
            "Oh, a perfectly good pencil just sitting there.",
            "I'm sure my brother needs the pencil anyways",
            "Awarded Title: Did Nothing",
        ])
        self.assertEqual(save["obtained"], ["Did Nothing"])

    def test_birthday_game_secret_option_route(self):
        game_data = parse_game_data((EXAMPLES / "birthday_game" / "data.json").read_text())
        save = load_fresh_save("birthday_game")
        output = run_with_inputs(game_data, save, ["2", "1", "2^5"])
        assert_in_order(self, output, [
            "Where do you want to go?",
            "What is 2 to the power of 5?",
            "Awarded Title: Genius",
        ])
        self.assertEqual(save["obtained"], ["Genius"])

    def test_terminal_game_route_and_wildcard(self):
        game_data = parse_game_data((EXAMPLES / "terminal_game" / "data.json").read_text())
        save = load_fresh_save("terminal_game")
        output = run_with_inputs(game_data, save, ["help", "about"])
        assert_in_order(self, output, [
            "SYSTEM BOOT COMPLETE",
            "Known commands",
            "A game about a game.",
            "Awarded Title: Read The Manual",
        ])
        self.assertEqual(save["obtained"], ["Read The Manual"])

    def test_titles_are_not_duplicated_in_save(self):
        game_data = parse_game_data(
            '{"prompt": "p", "question": "q", "answer": {"1": "Awarded Title: Repeat"}}'
        )
        save = make_save()
        run_with_inputs(game_data, save, ["1"])
        run_with_inputs(game_data, save, ["1"])
        self.assertEqual(save["obtained"], ["Repeat"])


if __name__ == "__main__":
    unittest.main()
