# JSON Schema & Jump Safety Rules

TerminalRPG configs keep their existing format. These rules define what the
engine accepts, when it rejects a config, and how the state machine guarantees
it can always terminate. Anything that violates these rules produces a
readable `ConfigError` (at load time) or `GameStateError` (at runtime) instead
of a crash or an infinite loop.

## 1. Node Schema

A game config is a single root node. Every node is a JSON object with exactly
three fields:

```json
{
    "prompt": "shown next to the option that leads here",
    "question": "shown when the node is entered",
    "answer": "terminal string OR an object of options"
}
```

- `prompt` and `question` must be strings (they may be empty).
- `answer` as a **string** makes the node terminal: the string is printed and
  the game ends. If it contains `Awarded Title: <name>`, the title is awarded.
- `answer` as an **object** maps option keys to either a terminal string or
  another node (recursive).
- Missing fields, unknown extra fields, and wrong types are rejected at load
  time with the JSON path of the offending node.

### Option Keys

| Key shape      | Meaning                                                        |
| -------------- | -------------------------------------------------------------- |
| `"talk"`       | Normal visible option.                                         |
| `""`           | Blank option, triggered by pressing Enter. Hidden from list.   |
| `"*"`          | Wildcard fallback for any unmatched input. Hidden from list.   |
| `".secret"`    | Secret option, typed without the dot. Hidden from list.        |
| `"Some Title"` | Locked route: hidden until the title is in `save.obtained`.    |

Rules for keys:

- An option object must declare **at least one** key. An empty option object
  is a node the player can never leave, so it is rejected at load time.
- Secret keys must start with `.` and have a non-empty name after the dot.
  Keys that merely *contain* a dot (e.g. `"192.168.1.1"`) are normal options
  and are never treated as secrets.
- Duplicate keys in the same JSON object are rejected. Previously the parser
  silently kept only the last duplicate branch, dropping dialogue.

### Save File

```json
{ "all": ["Title A"], "obtained": ["Title A"] }
```

Both fields are required and must be lists of strings.

## 2. Jump Safety Rules

- **R1 (static):** Every non-terminal node declares at least one option.
- **R2 (static):** Every jump target exists by construction. Transitions only
  follow keys of the current node's own option object, and secret input is
  resolved through an exact map of `.`-prefixed keys — the engine can never
  jump to a node that is not in the config.
- **R3 (runtime):** Before each prompt, at least one option must be
  selectable (i.e. not a locked route). If every route is locked, the engine
  raises `GameStateError` naming the node and the locked options, and
  terminates instead of looping forever.
- **R4 (runtime):** Unknown input never mutates state. In `PROD` the engine
  prints `Invalid Input!` and re-prompts; in `DEBUG` it raises
  `GameStateError` with the offending input and node.
- **R5 (runtime):** `EOF` on stdin ends the game cleanly; `main` still writes
  the save file on the way out.
- **R6:** Config errors are reported at load time with the JSON path of the
  offending node. The engine never starts a run with an invalid config.
