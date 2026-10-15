from __future__ import annotations

from pathlib import Path

# Файлы в корне папки Telegram Desktop tdata (opentele читает key_<keyFile>, по умолчанию key_datas)
_TDATA_KEY_FILES = frozenset({"key_datas", "key_data"})


def looks_like_tdata_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    for name in _TDATA_KEY_FILES:
        if (path / name).is_file():
            return True
    try:
        for entry in path.iterdir():
            if entry.is_file() and entry.name.startswith("key_"):
                return True
    except OSError:
        return False
    return False


def normalize_extract_root(base: Path) -> Path:
    """Если в архиве одна обёртка-папка — зайти внутрь (частый случай при zip)."""
    current = base.resolve()
    while True:
        if looks_like_tdata_dir(current) or (current / "tdata").is_dir():
            return current
        skip_names = {"__MACOSX"}
        entries = [
            p
            for p in current.iterdir()
            if p.name not in skip_names and not p.name.startswith(".")
        ]
        if len(entries) == 1 and entries[0].is_dir():
            current = entries[0]
            continue
        return current


def _summarize_tree(base: Path, *, max_entries: int = 12) -> str:
    lines: list[str] = []
    try:
        for p in sorted(base.iterdir())[:max_entries]:
            kind = "dir" if p.is_dir() else "file"
            lines.append(f"  • {p.name}/" if kind == "dir" else f"  • {p.name}")
        extra = len(list(base.iterdir())) - max_entries
        if extra > 0:
            lines.append(f"  … и ещё {extra} элемент(ов)")
    except OSError as exc:
        lines.append(f"  (не удалось прочитать каталог: {exc})")
    return "\n".join(lines) if lines else "  (пусто)"


def find_tdata_root(base: Path) -> Path:
    base = normalize_extract_root(base)
    candidates: list[Path] = []

    def add(path: Path) -> None:
        path = path.resolve()
        if path not in candidates:
            candidates.append(path)

    if looks_like_tdata_dir(base):
        add(base)
    if base.name.lower() == "tdata" and base.is_dir():
        add(base)
    nested = base / "tdata"
    if nested.is_dir():
        add(nested)
    for path in base.rglob("*"):
        if not path.is_dir():
            continue
        if path.name.lower() == "tdata" or looks_like_tdata_dir(path):
            add(path)

    candidates.sort(key=lambda p: (len(p.parts), str(p)))

    for path in candidates:
        if looks_like_tdata_dir(path):
            return path
        if path.name.lower() == "tdata" and any(path.iterdir()):
            return path

    hint = _summarize_tree(base)
    raise FileNotFoundError(
        "Папка tdata не найдена в архиве.\n"
        "Нужен ZIP с папкой tdata из Telegram Desktop "
        "(внутри должны быть файлы key_datas и папки вроде D877F783…).\n"
        "Путь: %s\n"
        "Содержимое верхнего уровня:\n%s"
        % (base, hint)
    )
