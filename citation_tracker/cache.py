"""Persistent disk caching for Scopus and Scholar queries."""

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path(".cache/citation_tracker")


class DiskCache:
    """Simple JSON-based disk cache with namespaces."""

    def __init__(self, cache_dir: Path = DEFAULT_CACHE_DIR, enabled: bool = True):
        self.cache_dir = cache_dir
        self.enabled = enabled
        if self.enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, namespace: str, key: str) -> Path:
        safe_key = "".join(c if c.isalnum() or c in "._-" else "_" for c in key)
        # Limit filename length
        if len(safe_key) > 150:
            import hashlib
            hash_str = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
            safe_key = f"{safe_key[:100]}_{hash_str}"
        ns_dir = self.cache_dir / namespace
        ns_dir.mkdir(parents=True, exist_ok=True)
        return ns_dir / f"{safe_key}.json"

    def get(self, namespace: str, key: str) -> Optional[Any]:
        if not self.enabled:
            return None
        file_path = self._file_path(namespace, key)
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.debug(f"Failed to read cache file {file_path}: {e}")
                return None
        return None

    def set(self, namespace: str, key: str, value: Any) -> None:
        if not self.enabled:
            return
        file_path = self._file_path(namespace, key)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(value, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug(f"Failed to write cache file {file_path}: {e}")

    def clear(self) -> None:
        """Clear all cached files."""
        if self.cache_dir.exists():
            import shutil
            shutil.rmtree(self.cache_dir, ignore_errors=True)
            self.cache_dir.mkdir(parents=True, exist_ok=True)

