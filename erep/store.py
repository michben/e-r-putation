"""Emplacement des données et écritures sûres (0600, atomiques, verrouillées)."""
from __future__ import annotations

import contextlib
import datetime as _dt
import fcntl
import json
import os
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    d = Path(os.environ.get("EREP_DATA_DIR") or Path.home() / ".erep")
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def subject_dir(subject_id: str) -> Path:
    if not subject_id.startswith("s_") or not subject_id[2:].isalnum():
        raise ValueError(f"identifiant de personne invalide : {subject_id!r}")
    d = data_dir() / "subjects" / subject_id
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json(path: Path, obj) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def append_jsonl(path: Path, obj) -> None:
    path = Path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")


@contextlib.contextmanager
def locked(path: Path):
    """Verrou exclusif : une exécution planifiée et une manuelle ne s'écrasent pas."""
    fd = os.open(str(path) + ".lock", os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def utcnow() -> _dt.datetime:
    fixed = os.environ.get("EREP_NOW")  # pour les tests
    if fixed:
        return parse_ts(fixed)
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)


def ts(d: _dt.datetime) -> str:
    return d.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(s: str) -> _dt.datetime:
    if len(s) == 10:
        s += "T00:00:00Z"
    return _dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)


def add_months(d: _dt.datetime, months: int) -> _dt.datetime:
    """Ajoute des mois calendaires (le 31 janvier + 1 mois donne le 28 ou 29 février)."""
    m = d.month - 1 + months
    year, month = d.year + m // 12, m % 12 + 1
    nxt = _dt.date(year + (month == 12), month % 12 + 1, 1)
    last_day = (nxt - _dt.timedelta(days=1)).day
    return d.replace(year=year, month=month, day=min(d.day, last_day))
