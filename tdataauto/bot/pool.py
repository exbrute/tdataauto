from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def user_pool_root(data_dir: Path, user_id: int) -> Path:
    return data_dir / "pools" / str(user_id)


def load_pool(data_dir: Path, user_id: int) -> list[dict]:
    meta = user_pool_root(data_dir, user_id) / "pool.json"
    if not meta.is_file():
        return []
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def save_pool(data_dir: Path, user_id: int, items: list[dict]) -> None:
    root = user_pool_root(data_dir, user_id)
    root.mkdir(parents=True, exist_ok=True)
    meta = root / "pool.json"
    meta.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def allocate_entry_dir(data_dir: Path, user_id: int) -> tuple[str, Path]:
    entry_id = uuid4().hex[:12]
    path = user_pool_root(data_dir, user_id) / entry_id
    path.mkdir(parents=True, exist_ok=True)
    return entry_id, path


def append_entry(data_dir: Path, user_id: int, entry: dict) -> list[dict]:
    items = load_pool(data_dir, user_id)
    items.append(entry)
    save_pool(data_dir, user_id, items)
    return items


def clear_pool(data_dir: Path, user_id: int) -> None:
    root = user_pool_root(data_dir, user_id)
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)


def entry_extracted_dir(data_dir: Path, user_id: int, entry_id: str) -> Path:
    return user_pool_root(data_dir, user_id) / entry_id / "extracted"


def new_pool_entry(
    *,
    entry_id: str,
    file_name: str,
    profile: dict | None,
    scan_error: str | None,
) -> dict:
    return {
        "entry_id": entry_id,
        "file_name": file_name,
        "profile": profile,
        "scan_error": scan_error,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
