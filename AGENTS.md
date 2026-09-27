# oma-voice agent instructions

## Tests: Behave BDD only

All automated tests **must** be BDD scenarios run with [behave](https://behave.readthedocs.io/).

- Write new coverage as Gherkin in `features/*.feature` plus step defs in `features/steps/`.
- Run the suite with: `PYTHONPATH=src behave`
- Do **not** add `unittest`, `pytest`, `nose`, or ad-hoc `test_*.py` files.
- Do **not** treat `python -m unittest` or `pytest` as the project test runner.
- A change is not tested until a feature scenario covers it and `behave` is green.

If you need a helper, put it under `features/steps/` (or `features/environment.py`). Helpers are not a second test framework.

### Layout

```
features/
  environment.py          # sys.path, behave config
  *.feature               # Given / When / Then
  steps/*.py              # step implementations
```

### Rules for new scenarios

- One behaviour per scenario. Names say what the user or system does, not the Python function.
- Prefer the allowlist, config, tool loop, chat HUD, and MCP as the surfaces under test.
- Mock subprocesses and llama-server; do not call Grok or other remote models.
- Live Voxtype / Hyprland / GPU checks are manual, not Behave jobs, unless tagged `@manual` and skipped by default.

### Forbidden

```python
# tests/test_foo.py
import unittest
class Foo(unittest.TestCase):
    ...
```

```python
# pytest style in this repo
def test_foo():
    assert True
```
