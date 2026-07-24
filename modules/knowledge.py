"""Local file-backed Knowledge Base storage."""

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path


SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}
READABLE_EXTENSIONS = {"txt", "md"}
PREVIEW_LIMIT = 5000
BACKUP_VERSION = "1.0"


class KnowledgeStore:
    """Manage local knowledge files and metadata for keyword retrieval."""

    def __init__(self, base_path=None):
        root = Path(__file__).resolve().parent.parent
        self.base_path = Path(base_path) if base_path else root / "data" / "knowledge"
        self.files_path = self.base_path / "files"
        self.metadata_file = self.base_path / "metadata.json"
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.files_path.mkdir(parents=True, exist_ok=True)
        if not self.metadata_file.exists():
            self._write([])

    @staticmethod
    def _now():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _stamp():
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _read_metadata(self):
        try:
            with self.metadata_file.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, ValueError, json.JSONDecodeError):
            data = []
        return data if isinstance(data, list) else []

    def _write(self, records):
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.files_path.mkdir(parents=True, exist_ok=True)
        with self.metadata_file.open("w", encoding="utf-8") as file:
            json.dump(records, file, indent=4, ensure_ascii=False)

    def _record_status(self, file_type, stored_path, content, size):
        if file_type not in {"txt", "md", "pdf"}:
            return "Invalid Knowledge File"
        if not stored_path.exists():
            return "Missing File"
        if file_type in READABLE_EXTENSIONS and size > 0 and content == "":
            return "Read Error"
        return "OK"

    def _normalize(self, item):
        if not isinstance(item, dict):
            item = {}
        source_name = str(item.get("file_name") or item.get("name") or "Unknown")
        file_type = str(item.get("file_type") or Path(source_name).suffix.lower().lstrip(".") or "txt")
        record_id = str(item.get("id") or uuid.uuid4())
        stored_name = str(item.get("stored_name") or f"{record_id}.{file_type}")
        stored_path = self.files_path / stored_name
        size = item.get("file_size", 0)
        try:
            size = int(size)
        except (TypeError, ValueError):
            size = 0
        enabled = item.get("enabled", True)
        if isinstance(enabled, str):
            enabled = enabled.strip().casefold() not in {"false", "0", "no", "disabled"}
        content = str(item.get("content") or self._read_text(stored_path, file_type))
        status = self._record_status(file_type, stored_path, content, size)
        return {
            "id": record_id,
            "file_name": source_name,
            "file_type": file_type,
            "stored_name": stored_name,
            "file_size": size,
            "added_time": str(item.get("added_time") or self._now()),
            "updated_time": str(item.get("updated_time") or item.get("added_time") or self._now()),
            "enabled": bool(enabled),
            "character_count": len(content),
            "source_path": str(item.get("source_path") or ""),
            "stored_path": str(stored_path),
            "status": status,
            "content": content
        }

    def list_items(self):
        records = [self._normalize(item) for item in self._read_metadata()]
        self._write(records)
        return records

    def add_file(self, source_path):
        source = Path(source_path)
        extension = source.suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise ValueError("Unsupported knowledge file type.")
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(str(source))

        record_id = str(uuid.uuid4())
        stored_name = f"{record_id}{extension}"
        target = self.files_path / stored_name
        shutil.copy2(source, target)

        record = {
            "id": record_id,
            "file_name": source.name,
            "file_type": extension.lstrip("."),
            "stored_name": stored_name,
            "file_size": target.stat().st_size,
            "added_time": self._now(),
            "updated_time": self._now(),
            "enabled": True,
            "source_path": str(source),
            "stored_path": str(target),
            "status": "OK",
            "content": self._read_text(target, extension.lstrip("."))
        }
        record["character_count"] = len(record["content"])
        records = self.list_items()
        records.append(record)
        self._write(records)
        return record

    def delete(self, item_id):
        removed = None
        records = []
        for item in self.list_items():
            if item.get("id") == item_id:
                removed = item
                continue
            records.append(item)
        if removed is None:
            raise KeyError(item_id)
        stored_path = self.files_path / str(removed.get("stored_name", ""))
        if stored_path.exists():
            stored_path.unlink()
        self._write(records)
        return removed

    def set_enabled(self, item_id, enabled):
        records = self.list_items()
        changed = None
        for item in records:
            if item.get("id") == item_id:
                item["enabled"] = bool(enabled)
                item["updated_time"] = self._now()
                changed = item
                break
        if changed is None:
            raise KeyError(item_id)
        self._write(records)
        return changed

    def valid_for_retrieval(self, item):
        if not isinstance(item, dict):
            return False
        if not bool(item.get("enabled", True)):
            return False
        if item.get("status", "OK") != "OK":
            return False
        file_type = str(item.get("file_type", "")).lower().lstrip(".")
        return file_type in READABLE_EXTENSIONS and bool(str(item.get("content", "")).strip())

    def preview(self, item_id, limit=PREVIEW_LIMIT):
        record = next((item for item in self.list_items() if item.get("id") == item_id), None)
        if record is None:
            raise KeyError(item_id)

        file_type = str(record.get("file_type", "")).lower().lstrip(".")
        if file_type == "pdf":
            return "PDF preview not supported yet."
        if file_type not in READABLE_EXTENSIONS:
            return "Preview not supported for this file type."

        content = str(record.get("content") or "")
        if not content:
            content = self._read_text(self.files_path / str(record.get("stored_name", "")), file_type)
        try:
            preview_limit = max(0, int(limit))
        except (TypeError, ValueError):
            preview_limit = PREVIEW_LIMIT
        if len(content) > preview_limit:
            return content[:preview_limit] + "\n\n[Preview truncated]"
        return content

    def preview_details(self, item_id, limit=PREVIEW_LIMIT):
        record = next((item for item in self.list_items() if item.get("id") == item_id), None)
        if record is None:
            raise KeyError(item_id)

        file_type = str(record.get("file_type", "")).lower().lstrip(".")
        if file_type == "pdf":
            preview = "PDF preview not supported yet."
            truncated = False
            total_characters = 0
        elif file_type in READABLE_EXTENSIONS:
            content = str(record.get("content") or "")
            if not content:
                content = self._read_text(self.files_path / str(record.get("stored_name", "")), file_type)
            try:
                preview_limit = max(0, int(limit))
            except (TypeError, ValueError):
                preview_limit = PREVIEW_LIMIT
            total_characters = len(content)
            truncated = total_characters > preview_limit
            preview = content[:preview_limit]
        else:
            preview = "Preview not supported for this file type."
            truncated = False
            total_characters = 0

        return {
            "file_name": record.get("file_name", "Unknown"),
            "file_type": file_type,
            "character_count": total_characters,
            "preview_count": len(preview),
            "truncated": truncated,
            "content": preview
        }

    @staticmethod
    def search_preview(content, keyword):
        text = str(content or "")
        needle = str(keyword or "")
        if not needle:
            return []
        positions = []
        lowered = text.casefold()
        lowered_needle = needle.casefold()
        start = 0
        while True:
            index = lowered.find(lowered_needle, start)
            if index < 0:
                break
            positions.append(index)
            start = index + max(1, len(needle))
        return positions

    def stats(self, records=None):
        items = records if records is not None else self.list_items()
        counts = {
            "total": 0,
            "txt": 0,
            "md": 0,
            "pdf": 0,
            "retrievable": 0,
            "enabled": 0,
            "disabled": 0,
            "characters": 0,
            "missing": 0,
            "errors": 0
        }
        for item in items or []:
            file_type = str(item.get("file_type", "")).lower().lstrip(".")
            enabled = bool(item.get("enabled", True))
            characters = item.get("character_count", len(str(item.get("content", ""))))
            try:
                characters = int(characters)
            except (TypeError, ValueError):
                characters = 0
            counts["total"] += 1
            counts["enabled" if enabled else "disabled"] += 1
            status = str(item.get("status", "OK"))
            if status == "Missing File":
                counts["missing"] += 1
            elif status != "OK":
                counts["errors"] += 1
            if file_type in counts:
                counts[file_type] += 1
            if self.valid_for_retrieval(item):
                counts["retrievable"] += 1
                counts["characters"] += characters
        return counts

    def health(self):
        records = self.list_items()
        stats = self.stats(records)
        metadata_errors = 0
        for item in records:
            if not item.get("id") or not item.get("file_name"):
                metadata_errors += 1
            if item.get("status", "OK") != "OK":
                metadata_errors += 1
        stats["metadata_errors"] = metadata_errors
        return stats

    def health_with_backups(self, backup_dir=None):
        stats = self.health()
        backups = self.list_backups(backup_dir)
        stats["backup_count"] = len(backups)
        latest = backups[0] if backups else {}
        stats["last_backup_time"] = latest.get("created_time", "None")
        stats["latest_backup_version"] = latest.get("app_version", latest.get("backup_version", "None"))
        return stats

    def repair_metadata(self):
        repaired = []
        errors = []
        for raw_item in self._read_metadata():
            try:
                item = self._normalize(raw_item)
                file_type = str(item.get("file_type", "")).lower().lstrip(".")
                stored_path = Path(item.get("stored_path") or self.files_path / item.get("stored_name", ""))
                if file_type in READABLE_EXTENSIONS and stored_path.exists():
                    content = self._read_text(stored_path, file_type)
                    if content:
                        item["content"] = content
                item["character_count"] = len(str(item.get("content", "")))
                item["enabled"] = bool(item.get("enabled", True))
                item["updated_time"] = str(item.get("updated_time") or item.get("added_time") or self._now())
                item["stored_path"] = str(stored_path)
                item["status"] = self._record_status(
                    file_type,
                    stored_path,
                    str(item.get("content", "")),
                    int(item.get("file_size", 0) or 0)
                )
                repaired.append(item)
            except Exception as error:
                errors.append(str(error))
        self._write(repaired)
        return {"repaired": len(repaired), "errors": errors}

    def export_backup(self, target_path, config=None, app_version=""):
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": "Project Aurora Knowledge Backup",
            "backup_version": BACKUP_VERSION,
            "version": BACKUP_VERSION,
            "app_version": app_version,
            "exported_time": self._now(),
            "config": dict(config or {}),
            "metadata": self.list_items()
        }
        with target.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=4, ensure_ascii=False)
        return target

    def create_backup(self, backup_dir, config=None, app_version="", max_backup_count=10):
        directory = Path(backup_dir)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = self._stamp()
        target = directory / f"Aurora_Knowledge_Backup_{stamp}.json"
        counter = 1
        while target.exists():
            target = directory / f"Aurora_Knowledge_Backup_{stamp}_{counter:03d}.json"
            counter += 1
        created = self.export_backup(target, config=config, app_version=app_version)
        backups = self.list_backups(directory)
        try:
            limit = max(1, int(max_backup_count))
        except (TypeError, ValueError):
            limit = 10
        cleanup_required = len(backups) > limit
        return {
            "path": str(created),
            "backup_count": len(backups),
            "max_backup_count": limit,
            "cleanup_required": cleanup_required
        }

    def list_backups(self, backup_dir=None):
        directory = Path(backup_dir) if backup_dir else self.base_path / "backups"
        directory.mkdir(parents=True, exist_ok=True)
        records = []
        for path in directory.glob("*.json"):
            info = {
                "name": path.name,
                "path": str(path),
                "created_time": "",
                "file_size": path.stat().st_size if path.exists() else 0,
                "backup_version": "Unknown",
                "app_version": "Unknown",
                "status": "OK"
            }
            try:
                with path.open("r", encoding="utf-8") as file:
                    payload = json.load(file)
                if not isinstance(payload, dict) or payload.get("format") != "Project Aurora Knowledge Backup":
                    info["status"] = "Invalid backup format."
                else:
                    info["created_time"] = str(payload.get("exported_time") or "")
                    info["backup_version"] = str(payload.get("backup_version") or payload.get("version") or "Unknown")
                    info["app_version"] = str(payload.get("app_version") or "Unknown")
                    if not isinstance(payload.get("metadata"), list):
                        info["status"] = "Missing required fields."
            except (OSError, ValueError, json.JSONDecodeError):
                info["status"] = "Invalid backup format."
            records.append(info)
        records.sort(key=lambda item: item.get("created_time") or item.get("name", ""), reverse=True)
        return records

    def delete_backup(self, backup_path):
        path = Path(backup_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(str(path))
        path.unlink()
        return str(path)

    def import_backup(self, source_path, current_version=""):
        source = Path(source_path)
        try:
            with source.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("Invalid knowledge backup file.") from error

        if not isinstance(payload, dict):
            raise ValueError("Unsupported format.")
        if payload.get("format") != "Project Aurora Knowledge Backup":
            raise ValueError("Invalid backup format.")
        backup_version = str(payload.get("backup_version") or payload.get("version") or "")
        if backup_version and backup_version != BACKUP_VERSION:
            raise ValueError("Backup version unsupported.")
        metadata = payload.get("metadata")
        if not isinstance(metadata, list):
            raise ValueError("Missing required fields.")

        imported = []
        migrated = False
        for item in metadata:
            if not isinstance(item, dict):
                migrated = True
                item = {}
            if "enabled" not in item or "updated_time" not in item or "character_count" not in item:
                migrated = True
            record = self._normalize(item)
            file_type = str(record.get("file_type", "")).lower().lstrip(".")
            stored_path = self.files_path / str(record.get("stored_name") or f"{record['id']}.{file_type}")
            if file_type in READABLE_EXTENSIONS and record.get("content") and not stored_path.exists():
                stored_path.write_text(str(record.get("content", "")), encoding="utf-8")
                record["stored_path"] = str(stored_path)
                record["file_size"] = stored_path.stat().st_size
                record["status"] = "OK"
            else:
                record["status"] = self._record_status(
                    file_type,
                    stored_path,
                    str(record.get("content", "")),
                    int(record.get("file_size", 0) or 0)
                )
            imported.append(record)
        self._write(imported)
        app_version = str(payload.get("app_version") or "Unknown")
        migration_required = bool(current_version and app_version not in {"Unknown", current_version})
        return {
            "imported": len(imported),
            "config": payload.get("config", {}),
            "backup_version": backup_version or "Unknown",
            "app_version": app_version,
            "current_version": current_version,
            "migration_required": migration_required or migrated
        }

    @staticmethod
    def _read_text(path, file_type):
        if str(file_type).lower().lstrip(".") not in READABLE_EXTENSIONS:
            return ""
        try:
            return Path(path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return Path(path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""
