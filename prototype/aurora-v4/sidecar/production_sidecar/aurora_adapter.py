"""Development source adapter around the eager production Settings singleton.

Execute the actual Settings declaration, NOT its module-level Settings() call.
No fake sys.modules entries, copied defaults, production writes, or UI imports.
The narrowly audited declaration shape is checked and fails closed on drift.
This bridge is intentionally source-checkout-only, not a packaging solution.
"""
from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

from modules import app_paths
from modules.ollama_request_policy import resolve_ollama_request_policy


def settings_declaration(root: Path):
    source = root / "modules" / "settings.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    expected_imports = ast.parse(
        "import copy\nimport json\n"
        "from modules.app_paths import CONFIG_DIR, CONFIG_FILE, DEFAULT_SETTINGS_FILE\n"
    ).body
    if (len(tree.body) != 5
            or [ast.dump(n) for n in tree.body[:3]] != [ast.dump(n) for n in expected_imports]
            or not isinstance(tree.body[3], ast.ClassDef)
            or tree.body[3].name != "Settings"
            or tree.body[3].bases or tree.body[3].decorator_list
            or ast.dump(tree.body[4]) != ast.dump(ast.parse("settings = Settings()").body[0])):
        raise RuntimeError("SETTINGS_DECLARATION_CHANGED")
    declaration = tree.body[3]
    if not all(isinstance(n, ast.FunctionDef) for n in declaration.body):
        raise RuntimeError("SETTINGS_DECLARATION_CHANGED")
    namespace = {
        "__name__": __name__, "copy": copy, "json": json,
        "CONFIG_DIR": app_paths.CONFIG_DIR, "CONFIG_FILE": app_paths.CONFIG_FILE,
        "DEFAULT_SETTINGS_FILE": app_paths.DEFAULT_SETTINGS_FILE,
    }
    exec(compile(ast.Module(body=[declaration], type_ignores=[]), str(source), "exec"), namespace)
    return namespace["Settings"]


class ReadOnlySettings:
    """Reuse production load/migration methods with every write entry disabled."""

    def __init__(self, root: Path, config_file: Path | None = None):
        base = settings_declaration(root)
        owner = self

        class Snapshot(base):
            def load(self):
                self.config_file = config_file or app_paths.CONFIG_FILE
                self.config_dir = self.config_file.parent
                try:
                    self.data = json.loads(self.config_file.read_text(encoding="utf-8"))
                    if not isinstance(self.data, dict):
                        raise ValueError("settings must be an object")
                except FileNotFoundError:
                    owner.status = "missing_defaults"
                    self.data = copy.deepcopy(self.default_settings)
                    return
                except (OSError, UnicodeError, ValueError):
                    owner.status = "invalid_defaults"
                    self.data = copy.deepcopy(self.default_settings)
                    return
                owner.status = "loaded"
                # Same order as production Settings.load(), in memory only.
                self._migrate_first_run_settings()
                self._migrate_model_settings()
                self._merge_defaults(self.data, self.default_settings)
                self._migrate_language_settings()
                self._remove_legacy_remote_settings()
                self._remove_legacy_openwebui_settings()

            def save(self):
                raise RuntimeError("READ_ONLY_SETTINGS")

            def set(self, *args, **kwargs):
                raise RuntimeError("READ_ONLY_SETTINGS")

            def update_many(self, *args, **kwargs):
                raise RuntimeError("READ_ONLY_SETTINGS")

        self._snapshot = Snapshot()
        self.config_file = self._snapshot.config_file
        self.policy = resolve_ollama_request_policy(self)

    def get(self, key, default=None):
        return copy.deepcopy(self._snapshot.get(key, default))
