"""Local file-backed Knowledge Base storage."""

import hashlib
import json
import math
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from modules.embedding import EmbeddingError, get_embedding_provider


SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}
READABLE_EXTENSIONS = {"txt", "md"}
PREVIEW_LIMIT = 5000
BACKUP_VERSION = "1.0"
EMBEDDING_TEXT_LIMIT = 8000
VECTOR_INDEX_VERSION = "1.0"
VECTOR_INDEX_FORMAT = "Project Aurora Knowledge Vector Index"


class KnowledgeStore:
    """Manage local knowledge files and metadata for keyword retrieval."""

    def __init__(self, base_path=None):
        root = Path(__file__).resolve().parent.parent
        self.base_path = Path(base_path) if base_path else root / "data" / "knowledge"
        self.files_path = self.base_path / "files"
        self.metadata_file = self.base_path / "metadata.json"
        self.vector_index_file = self.base_path / "vector_index.json"
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

    def _read_vector_index(self):
        try:
            with self.vector_index_file.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, ValueError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        items = data.get("items", [])
        if not isinstance(items, list):
            items = []
        return {
            "format": data.get("format") or VECTOR_INDEX_FORMAT,
            "version": data.get("version") or VECTOR_INDEX_VERSION,
            "updated_time": str(data.get("updated_time") or ""),
            "items": [item for item in items if isinstance(item, dict)]
        }

    def _write_vector_index(self, index):
        self.base_path.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": VECTOR_INDEX_FORMAT,
            "version": VECTOR_INDEX_VERSION,
            "updated_time": self._now(),
            "items": list(index.get("items", [])) if isinstance(index, dict) else []
        }
        with self.vector_index_file.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=4, ensure_ascii=False)
        return payload

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
        try:
            embedding_dimensions = int(item.get("embedding_dimensions") or 0)
        except (TypeError, ValueError):
            embedding_dimensions = 0
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
            "embedding_status": str(item.get("embedding_status") or "Not Indexed"),
            "embedding_model": str(item.get("embedding_model") or ""),
            "embedding_updated_time": str(item.get("embedding_updated_time") or ""),
            "embedding_dimensions": embedding_dimensions,
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
        record["embedding_status"] = "Not Indexed"
        record["embedding_model"] = ""
        record["embedding_updated_time"] = ""
        record["embedding_dimensions"] = 0
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
        self.remove_vector(item_id)
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

    def embedding_payload(self, item_id, provider=None, text_limit=EMBEDDING_TEXT_LIMIT):
        record = next((item for item in self.list_items() if item.get("id") == item_id), None)
        if record is None:
            raise KeyError(item_id)
        if not self.valid_for_retrieval(record):
            raise ValueError("Knowledge item is not readable for embedding.")

        content = str(record.get("content") or "")
        try:
            limit = max(500, int(text_limit))
        except (TypeError, ValueError):
            limit = EMBEDDING_TEXT_LIMIT
        embedding_provider = provider or get_embedding_provider()
        vector = embedding_provider.embed_text(content[:limit])
        return {
            "id": record.get("id"),
            "file_name": record.get("file_name"),
            "model": getattr(embedding_provider, "model", record.get("embedding_model", "")),
            "dimensions": len(vector),
            "embedding": vector
        }

    def update_embedding_metadata(self, item_id, model, dimensions, status="Indexed"):
        records = self.list_items()
        changed = None
        for item in records:
            if item.get("id") == item_id:
                item["embedding_status"] = str(status or "Indexed")
                item["embedding_model"] = str(model or "")
                try:
                    item["embedding_dimensions"] = max(0, int(dimensions or 0))
                except (TypeError, ValueError):
                    item["embedding_dimensions"] = 0
                item["embedding_updated_time"] = self._now()
                item["updated_time"] = self._now()
                changed = item
                break
        if changed is None:
            raise KeyError(item_id)
        self._write(records)
        return changed

    def generate_embedding(self, item_id, provider=None, text_limit=EMBEDDING_TEXT_LIMIT, update_metadata=True):
        try:
            payload = self.embedding_payload(item_id, provider=provider, text_limit=text_limit)
        except EmbeddingError:
            raise
        if update_metadata:
            self.update_embedding_metadata(
                item_id,
                payload.get("model", ""),
                payload.get("dimensions", 0),
                status="Indexed"
            )
        return payload

    @staticmethod
    def _normalize_vector(vector):
        if not isinstance(vector, list):
            return []
        values = []
        for value in vector:
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                return []
        return values

    @staticmethod
    def _cosine_similarity(left, right):
        if not left or not right or len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if left_norm <= 0 or right_norm <= 0:
            return 0.0
        return dot / (left_norm * right_norm)

    @staticmethod
    def _content_hash(content):
        return hashlib.sha256(str(content or "").encode("utf-8")).hexdigest()

    def save_vector(self, item_id, embedding, model="", metadata=None):
        vector = self._normalize_vector(embedding)
        if not vector:
            raise ValueError("Embedding vector is empty or invalid.")

        records = self.list_items()
        record = next((item for item in records if item.get("id") == item_id), None)
        if record is None:
            raise KeyError(item_id)

        index = self._read_vector_index()
        items = [item for item in index.get("items", []) if item.get("id") != item_id]
        entry = {
            "id": item_id,
            "file_name": record.get("file_name", ""),
            "stored_name": record.get("stored_name", ""),
            "model": str(model or record.get("embedding_model") or ""),
            "dimensions": len(vector),
            "content_hash": self._content_hash(record.get("content", "")),
            "updated_time": self._now(),
            "embedding": vector
        }
        if isinstance(metadata, dict):
            entry["metadata"] = metadata
        items.append(entry)
        index["items"] = items
        self._write_vector_index(index)
        self.update_embedding_metadata(item_id, entry["model"], len(vector), status="Indexed")
        return entry

    def remove_vector(self, item_id):
        index = self._read_vector_index()
        original_count = len(index.get("items", []))
        index["items"] = [item for item in index.get("items", []) if item.get("id") != item_id]
        if len(index["items"]) != original_count:
            self._write_vector_index(index)
        return original_count - len(index["items"])

    def index_item(self, item_id, provider=None, text_limit=EMBEDDING_TEXT_LIMIT):
        payload = self.generate_embedding(
            item_id,
            provider=provider,
            text_limit=text_limit,
            update_metadata=False
        )
        return self.save_vector(
            item_id,
            payload.get("embedding", []),
            model=payload.get("model", ""),
            metadata={
                "source": "knowledge",
                "text_limit": text_limit
            }
        )

    def build_vector_index(self, provider=None, item_ids=None, text_limit=EMBEDDING_TEXT_LIMIT):
        allowed_ids = {str(item_id) for item_id in item_ids} if item_ids else None
        indexed = []
        errors = []
        for item in self.list_items():
            item_id = str(item.get("id") or "")
            if allowed_ids is not None and item_id not in allowed_ids:
                continue
            if not self.valid_for_retrieval(item):
                continue
            try:
                indexed.append(self.index_item(item_id, provider=provider, text_limit=text_limit))
            except Exception as error:
                errors.append({
                    "id": item_id,
                    "file_name": item.get("file_name", ""),
                    "error": str(error)
                })
        return {
            "indexed": len(indexed),
            "errors": errors,
            "index_file": str(self.vector_index_file)
        }

    def vector_search_by_embedding(self, embedding, top_k=3, min_similarity=0.0, enabled_only=True, enriched=False):
        query_vector = self._normalize_vector(embedding)
        if not query_vector:
            return []
        try:
            limit = max(1, int(top_k))
        except (TypeError, ValueError):
            limit = 3
        try:
            threshold = float(min_similarity)
        except (TypeError, ValueError):
            threshold = 0.0

        records = {item.get("id"): item for item in self.list_items()}
        results = []
        for entry in self._read_vector_index().get("items", []):
            item_id = entry.get("id")
            record = records.get(item_id)
            if record is None:
                continue
            if enabled_only and not bool(record.get("enabled", True)):
                continue
            if record.get("status", "OK") != "OK":
                continue
            vector = self._normalize_vector(entry.get("embedding", []))
            score = self._cosine_similarity(query_vector, vector)
            if score < threshold:
                continue
            content = str(record.get("content", ""))
            result = {
                "id": item_id,
                "file_name": record.get("file_name", ""),
                "file_type": record.get("file_type", ""),
                "score": score,
                "similarity": score,
                "model": entry.get("model", ""),
                "embedding_updated_time": entry.get("updated_time", ""),
                "snippet": content[:500],
                "record": record
            }
            if enriched:
                result["score_details"] = {
                    "vector": score,
                    "keyword": None,
                    "matched_terms": [],
                    "importance": None,
                    "confidence": None,
                }
                result["retrieval_method"] = "vector"
            results.append(result)
        results.sort(key=lambda item: item.get("score", 0), reverse=True)
        return results[:limit]

    def vector_search(self, query, provider=None, top_k=3, min_similarity=0.0, enabled_only=True, enriched=False):
        text = str(query or "").strip()
        if not text:
            return []
        embedding_provider = provider or get_embedding_provider()
        query_vector = embedding_provider.embed_text(text)
        return self.vector_search_by_embedding(
            query_vector,
            top_k=top_k,
            min_similarity=min_similarity,
            enabled_only=enabled_only,
            enriched=enriched,
        )

    def retrieve(self, prompt, max_results=3, enabled_only=True, prefer_vector=True, enriched=False):
        """Retrieve Knowledge records with vector search and keyword fallback."""

        text = str(prompt or "").strip()
        if not text:
            return []
        try:
            limit = max(0, int(max_results))
        except (TypeError, ValueError):
            limit = 3
        if limit <= 0:
            return []

        if prefer_vector:
            try:
                if not self._read_vector_index().get("items"):
                    raise ValueError("Vector index is empty.")
                vector_results = self.vector_search(
                    text,
                    top_k=limit,
                    enabled_only=enabled_only,
                    enriched=enriched,
                )
                records = []
                for result in vector_results:
                    if not isinstance(result, dict) or not isinstance(result.get("record"), dict):
                        continue
                    record = dict(result["record"])
                    if enriched:
                        record["score_details"] = dict(result.get("score_details", {}))
                        record["retrieval_method"] = result.get("retrieval_method", "vector")
                        record["score"] = result.get("score", record.get("score", 0.0))
                    records.append(record)
                if records:
                    return records
            except Exception:
                pass

        from modules.retrieval import search_knowledge
        return search_knowledge(
            text,
            self.list_items(),
            max_results=limit,
            enabled_only=enabled_only,
            enriched=enriched,
        )

    def _vector_entries_by_id(self):
        entries = {}
        for entry in self._read_vector_index().get("items", []):
            item_id = str(entry.get("id") or "")
            if item_id:
                entries[item_id] = entry
        return entries

    def embedding_state(self, item, vector_entry=None):
        if not isinstance(item, dict):
            return {
                "status": "Invalid",
                "has_embedding": False,
                "stale": False,
                "needs_reindex": True,
                "reason": "Invalid knowledge record."
            }
        if not self.valid_for_retrieval(item):
            return {
                "status": "Unavailable",
                "has_embedding": False,
                "stale": False,
                "needs_reindex": False,
                "reason": "Knowledge item is not readable for embedding."
            }

        entry = vector_entry
        if entry is None:
            entry = self._vector_entries_by_id().get(str(item.get("id") or ""))
        if not isinstance(entry, dict):
            return {
                "status": "Not Indexed",
                "has_embedding": False,
                "stale": False,
                "needs_reindex": True,
                "reason": "No vector index entry."
            }

        vector = self._normalize_vector(entry.get("embedding", []))
        dimensions = int(entry.get("dimensions") or 0)
        if not vector or dimensions != len(vector):
            return {
                "status": "Invalid",
                "has_embedding": bool(vector),
                "stale": False,
                "needs_reindex": True,
                "reason": "Vector dimensions are invalid."
            }

        current_hash = self._content_hash(item.get("content", ""))
        indexed_hash = str(entry.get("content_hash") or "")
        if indexed_hash and indexed_hash != current_hash:
            return {
                "status": "Stale",
                "has_embedding": True,
                "stale": True,
                "needs_reindex": True,
                "reason": "Knowledge content changed after indexing."
            }

        return {
            "status": "Indexed",
            "has_embedding": True,
            "stale": False,
            "needs_reindex": False,
            "reason": ""
        }

    def refresh_embedding_status(self, records=None):
        items = records if records is not None else self.list_items()
        entries = self._vector_entries_by_id()
        changed = False
        summary = {
            "indexed": 0,
            "not_indexed": 0,
            "stale": 0,
            "invalid": 0,
            "unavailable": 0,
            "needs_reindex": 0
        }
        for item in items:
            state = self.embedding_state(item, entries.get(str(item.get("id") or "")))
            status = state.get("status", "Not Indexed")
            if status == "Indexed":
                summary["indexed"] += 1
            elif status == "Stale":
                summary["stale"] += 1
            elif status == "Invalid":
                summary["invalid"] += 1
            elif status == "Unavailable":
                summary["unavailable"] += 1
            else:
                summary["not_indexed"] += 1
            if state.get("needs_reindex"):
                summary["needs_reindex"] += 1
            if item.get("embedding_status") != status:
                item["embedding_status"] = status
                item["updated_time"] = self._now()
                changed = True
        if changed:
            self._write(items)
        summary["updated"] = changed
        return summary

    def vector_index_health(self, records=None):
        items = records if records is not None else self.list_items()
        records_by_id = {str(item.get("id") or ""): item for item in items}
        index = self._read_vector_index()
        entries = index.get("items", [])
        orphaned = []
        invalid = []
        stale = []
        indexed = 0
        for entry in entries:
            item_id = str(entry.get("id") or "")
            record = records_by_id.get(item_id)
            if record is None:
                orphaned.append(item_id)
                continue
            state = self.embedding_state(record, entry)
            if state.get("status") == "Indexed":
                indexed += 1
            elif state.get("status") == "Stale":
                stale.append(item_id)
            elif state.get("status") == "Invalid":
                invalid.append(item_id)

        indexed_ids = {
            str(entry.get("id") or "")
            for entry in entries
            if str(entry.get("id") or "")
        }
        missing = [
            item_id
            for item_id, item in records_by_id.items()
            if item_id and self.valid_for_retrieval(item) and item_id not in indexed_ids
        ]
        return {
            "exists": self.vector_index_file.exists(),
            "path": str(self.vector_index_file),
            "format": index.get("format", ""),
            "version": index.get("version", ""),
            "updated_time": index.get("updated_time", ""),
            "entries": len(entries),
            "indexed": indexed,
            "missing": len(missing),
            "stale": len(stale),
            "invalid": len(invalid),
            "orphaned": len(orphaned),
            "needs_reindex": len(missing) + len(stale) + len(invalid),
            "orphaned_ids": orphaned,
            "stale_ids": stale,
            "invalid_ids": invalid
        }

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
        embedding_summary = self.refresh_embedding_status(records)
        if embedding_summary.get("updated"):
            records = self.list_items()
        stats = self.stats(records)
        metadata_errors = 0
        for item in records:
            if not item.get("id") or not item.get("file_name"):
                metadata_errors += 1
            if item.get("status", "OK") != "OK":
                metadata_errors += 1
        stats["metadata_errors"] = metadata_errors
        stats["embedding_indexed"] = embedding_summary.get("indexed", 0)
        stats["embedding_not_indexed"] = embedding_summary.get("not_indexed", 0)
        stats["embedding_stale"] = embedding_summary.get("stale", 0)
        stats["embedding_invalid"] = embedding_summary.get("invalid", 0)
        stats["embedding_needs_reindex"] = embedding_summary.get("needs_reindex", 0)
        stats["vector_index"] = self.vector_index_health(records)
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
