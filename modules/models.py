import subprocess


def _hidden_window_flags():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


MODEL_FIELDS = ("name", "model_id", "size", "modified")


def get_model_records():
    """Return Ollama models as records ready for UI display."""

    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
            creationflags=_hidden_window_flags()
        )

        if result.returncode != 0:
            return []

        lines = [
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip()
        ]

        if len(lines) <= 1:
            return []

        records = []

        for line in lines[1:]:
            values = line.split()

            if len(values) < 2:
                continue

            name = values[0]
            model_id = values[1]
            size_end = 3

            if len(values) > 3 and values[3].upper() in {
                "B", "KB", "MB", "GB", "TB"
            }:
                size_end = 4

            record = {
                "name": name,
                "model_id": model_id,
                "size": " ".join(values[2:size_end]),
                "modified": " ".join(values[size_end:])
            }
            records.append(record)

        return records

    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return []


def get_models():
    """Return Ollama models as the original plain-text representation."""

    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
            creationflags=_hidden_window_flags()
        )

        if result.returncode == 0:
            return result.stdout.strip()

        return "Unable to retrieve model list"

    except (FileNotFoundError, subprocess.SubprocessError, OSError) as error:
        return "Error: " + str(error)
