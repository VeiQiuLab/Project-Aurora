"""Local Persona configuration for Aurora chat behavior."""

import json
from datetime import datetime
from pathlib import Path


DEFAULT_PERSONA = {
    "name": "Aurora",
    "description": "\u672c\u5730 AI \u52a9\u624b",
    "style": "\u6e29\u67d4\u3001\u7406\u6027\u3001\u7b80\u6d01",
    "rules": [
        "\u4f18\u5148\u7ed9\u51fa\u660e\u786e\u65b9\u6848",
        "\u907f\u514d\u65e0\u610f\u4e49\u91cd\u590d",
        "\u4fdd\u6301\u4e0a\u4e0b\u6587\u8fde\u7eed"
    ]
}


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class PersonaStore:
    """Load, save, update, and reset the local Persona configuration."""

    def __init__(self, file_path=None):
        root = Path(__file__).resolve().parent.parent
        if file_path:
            self.file_path = Path(file_path)
            self.directory = self.file_path.parent
        else:
            self.directory = root / "data" / "persona"
            self.file_path = self.directory / "persona.json"
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self.reset()

    def _normalize(self, data):
        if not isinstance(data, dict):
            data = {}
        normalized = dict(DEFAULT_PERSONA)
        normalized.update({key: data.get(key, DEFAULT_PERSONA[key]) for key in DEFAULT_PERSONA})
        normalized["last_loaded_time"] = str(data.get("last_loaded_time") or "Never loaded.")
        normalized["last_updated_time"] = str(data.get("last_updated_time") or _now())
        if not isinstance(normalized.get("rules"), list):
            normalized["rules"] = [str(normalized.get("rules", ""))]
        normalized["rules"] = [
            str(rule).strip()
            for rule in normalized.get("rules", [])
            if str(rule).strip()
        ] or list(DEFAULT_PERSONA["rules"])
        return normalized

    def validate(self, persona):
        if not isinstance(persona, dict):
            raise ValueError("Invalid Persona format.")
        name = str(persona.get("name", "")).strip()
        if not name:
            raise ValueError("Invalid Persona format.")
        rules = persona.get("rules", [])
        if isinstance(rules, str):
            rules = [line.strip() for line in rules.splitlines() if line.strip()]
        if not isinstance(rules, list):
            raise ValueError("Invalid Persona format.")
        return True

    def load(self, update_timestamp=True):
        try:
            with self.file_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, ValueError, json.JSONDecodeError):
            data = {}
        persona = self._normalize(data)
        if update_timestamp:
            persona["last_loaded_time"] = _now()
        self.save(persona, update_timestamp=False)
        return persona

    def save(self, persona, update_timestamp=True):
        if isinstance(persona, dict) and "last_loaded_time" not in persona and self.file_path.exists():
            try:
                with self.file_path.open("r", encoding="utf-8") as file:
                    current = json.load(file)
                if isinstance(current, dict) and current.get("last_loaded_time"):
                    persona = dict(persona)
                    persona["last_loaded_time"] = current.get("last_loaded_time")
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        persona = self._normalize(persona)
        if update_timestamp:
            persona["last_updated_time"] = _now()
        self.validate(persona)
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.file_path.open("w", encoding="utf-8") as file:
            json.dump(persona, file, indent=4, ensure_ascii=False)
        return persona

    def update(self, name, description, style, rules):
        if isinstance(rules, str):
            rule_list = [line.strip() for line in rules.splitlines() if line.strip()]
        else:
            rule_list = [str(rule).strip() for rule in rules or [] if str(rule).strip()]
        return self.save({
            "name": name,
            "description": description,
            "style": style,
            "rules": rule_list,
            "last_loaded_time": self.load(update_timestamp=False).get("last_loaded_time", "Never loaded.")
        })

    def reset(self):
        return self.save(DEFAULT_PERSONA)

    def build_context(self, persona=None):
        persona = self._normalize(persona or self.load())
        lines = [
            "Persona:",
            f"Name: {persona.get('name', '')}",
            f"Description: {persona.get('description', '')}",
            f"Style: {persona.get('style', '')}",
            "Rules:"
        ]
        lines.extend(f"- {rule}" for rule in persona.get("rules", []))
        return "\n".join(lines)

    def preview_prompt(self, persona=None):
        persona = self._normalize(persona or self.load())
        lines = [
            "Current Persona:",
            "",
            "Name:",
            persona.get("name", ""),
            "",
            "Description:",
            persona.get("description", ""),
            "",
            "Style:",
            persona.get("style", ""),
            "",
            "Rules:"
        ]
        for index, rule in enumerate(persona.get("rules", []), start=1):
            lines.append(f"{index}. {rule}")
        lines.extend(["", "Final System Prompt:", self.build_context(persona)])
        return "\n".join(lines)

    def test_prompt(self, prompt, persona=None):
        persona = self._normalize(persona or self.load())
        return "\n".join([
            "Input:",
            str(prompt or ""),
            "",
            "Persona Context:",
            self.build_context(persona)
        ])

    def status(self, enabled=True, persona=None):
        persona = self._normalize(persona or self.load())
        return {
            "enabled": bool(enabled),
            "name": persona.get("name", ""),
            "rules_count": len(persona.get("rules", [])),
            "characters": len(self.build_context(persona)),
            "last_loaded_time": persona.get("last_loaded_time") or "Never loaded.",
            "last_updated_time": persona.get("last_updated_time") or "Never loaded."
        }

    def context_status(self, enabled=True, persona=None):
        context = self.build_context(persona) if enabled else ""
        return {
            "name": "Persona",
            "enabled": bool(enabled and context),
            "characters": len(context)
        }
