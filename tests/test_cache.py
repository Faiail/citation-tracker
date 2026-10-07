"""Tests for disk cache."""

import tempfile
from pathlib import Path
from citation_tracker.cache import DiskCache


def test_disk_cache():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = DiskCache(cache_dir=Path(tmpdir), enabled=True)

        assert cache.get("ns", "key1") is None

        cache.set("ns", "key1", {"value": 42})
        assert cache.get("ns", "key1") == {"value": 42}

        # Clear cache
        cache.clear()
        assert cache.get("ns", "key1") is None


def test_disabled_cache():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = DiskCache(cache_dir=Path(tmpdir), enabled=False)
        cache.set("ns", "key1", {"value": 42})
        assert cache.get("ns", "key1") is None

