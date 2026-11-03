"""Installing, updating and removing plugins from a plugin index.

An index is a JSON file listing plugins, their versions, the Inkmill versions
they support and a SHA-256 hash for every file. The Inkmill repository
publishes one at ``plugins/index.json`` (built by
``scripts/build_plugin_index.py``). The same index works from two kinds of
source:

* online: the index URL, with plugin files fetched relative to it, and
* local: a folder, usually a clone of the Inkmill repository, for machines
  without network access.

Installed plugins live in ``<config dir>/plugins/<id>/``. The previous
version of an updated plugin is kept in ``plugins/.previous/<id>/`` so an
update that breaks can be rolled back.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from . import __version__
from .plugins import MANIFEST, Manifest, is_compatible, parse_version, plugins_dir

DEFAULT_INDEX_URL = "https://raw.githubusercontent.com/aarondodd/inkmill/main/plugins/index.json"
INDEX_SCHEMA = 1
INSTALL_RECORD = ".inkmill-install.json"
PREVIOUS_DIR = ".previous"
TIMEOUT = 20


class PluginSourceError(Exception):
    """The source could not be read, or what it returned is not usable."""


@dataclass
class IndexEntry:
    manifest: Manifest
    files: dict[str, str]
    path: str

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def compatible(self) -> bool:
        return is_compatible(self.manifest.requires_inkmill)


@dataclass
class Source:
    kind: str  # "online" or "local"
    location: str

    @classmethod
    def from_settings(cls, table: dict[str, Any]) -> "Source":
        kind = str(table.get("source", "online"))
        if kind == "local":
            return cls("local", str(table.get("local_path", "")))
        return cls("online", str(table.get("index_url") or DEFAULT_INDEX_URL))

    @property
    def label(self) -> str:
        return f"online: {self.location}" if self.kind == "online" else f"local: {self.location}"

    def index_file(self) -> Path:
        """For a local source, the index.json to read."""
        base = Path(self.location).expanduser()
        for candidate in (base / "plugins" / "index.json", base / "index.json", base):
            if candidate.is_file():
                return candidate
        raise PluginSourceError(f"no plugins/index.json under {base}")

    def _url(self, relative: str) -> str:
        base = self.location.rsplit("/", 1)[0]
        return f"{base}/{relative}"

    def read(self, relative: str | None = None) -> bytes:
        """Read the index (``relative`` None) or a file relative to it."""
        if self.kind == "local":
            if not self.location:
                raise PluginSourceError("no local folder set; choose one with 7 (Source)")
            index = self.index_file()
            target = index if relative is None else index.parent / relative
            try:
                return target.read_bytes()
            except OSError as exc:
                raise PluginSourceError(f"cannot read {target}: {exc.strerror or exc}") from exc
        url = self.location if relative is None else self._url(relative)
        request = urllib.request.Request(url, headers={"User-Agent": f"Inkmill/{__version__}"})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise PluginSourceError(f"{url}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise PluginSourceError(f"cannot reach {url}: {reason}") from exc


def parse_index(data: bytes) -> list[IndexEntry]:
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PluginSourceError(f"the index is not valid JSON: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("plugins"), list):
        raise PluginSourceError("the index has no plugin list")
    if int(doc.get("schema", 0)) > INDEX_SCHEMA:
        raise PluginSourceError("the index is newer than this Inkmill understands; update Inkmill")
    entries = []
    for item in doc["plugins"]:
        if not isinstance(item, dict) or "id" not in item or not isinstance(item.get("files"), dict):
            continue
        manifest = Manifest.from_dict(item)
        entries.append(IndexEntry(manifest, {str(k): str(v) for k, v in item["files"].items()}, str(item.get("path", manifest.id))))
    return entries


def fetch_index(source: Source) -> list[IndexEntry]:
    return parse_index(source.read())


def _safe_relative(name: str) -> PurePosixPath:
    rel = PurePosixPath(name)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts or ":" in rel.parts[0]:
        raise PluginSourceError(f"refusing unsafe file name in index: {name}")
    return rel


@dataclass
class Installed:
    id: str
    path: Path
    manifest: Manifest | None
    managed: bool
    record: dict[str, Any] = field(default_factory=dict)

    @property
    def version(self) -> str:
        return self.manifest.version if self.manifest else ""


def installed_plugins(directory: Path | None = None) -> dict[str, Installed]:
    directory = directory or plugins_dir()
    found: dict[str, Installed] = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.iterdir(), key=lambda p: p.name):
        if path.name.startswith((".", "_")):
            continue
        if path.is_dir() and (path / MANIFEST).is_file():
            try:
                manifest = Manifest.load(path / MANIFEST)
            except Exception:
                manifest = None
            record: dict[str, Any] = {}
            record_path = path / INSTALL_RECORD
            if record_path.is_file():
                try:
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    record = {}
            pid = manifest.id if manifest else path.name
            found[pid] = Installed(pid, path, manifest, bool(record), record)
        elif path.is_file() and path.suffix == ".py":
            found[path.stem] = Installed(path.stem, path, None, False)
    return found


def install(entry: IndexEntry, source: Source, directory: Path | None = None) -> Path:
    """Download, verify and install ``entry``. Returns the plugin folder.

    Nothing in the plugins folder changes unless every file arrives intact.
    """
    if not entry.compatible:
        raise PluginSourceError(f"{entry.manifest.name} needs Inkmill {entry.manifest.requires_inkmill}")
    directory = directory or plugins_dir()
    directory.mkdir(parents=True, exist_ok=True)
    staging = directory / f".staging-{entry.id}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    try:
        for name, digest in sorted(entry.files.items()):
            rel = _safe_relative(name)
            data = source.read(f"{entry.path}/{rel.as_posix()}")
            actual = hashlib.sha256(data).hexdigest()
            if actual != digest:
                raise PluginSourceError(
                    f"{entry.path}/{name} does not match the index (expected {digest[:12]}, got {actual[:12]})"
                )
            target = staging.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        if not (staging / MANIFEST).is_file():
            raise PluginSourceError(f"{entry.id} has no {MANIFEST}")
        record = {
            "id": entry.id,
            "version": entry.manifest.version,
            "source": source.label,
            "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "files": entry.files,
        }
        (staging / INSTALL_RECORD).write_text(json.dumps(record, indent=2), encoding="utf-8")
        final = directory / entry.id
        if final.exists():
            previous_root = directory / PREVIOUS_DIR
            previous_root.mkdir(exist_ok=True)
            previous = previous_root / entry.id
            shutil.rmtree(previous, ignore_errors=True)
            final.rename(previous)
        staging.rename(final)
        return final
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def remove(plugin_id: str, directory: Path | None = None) -> None:
    directory = directory or plugins_dir()
    target = directory / plugin_id
    if target.is_dir():
        shutil.rmtree(target)
    elif (directory / f"{plugin_id}.py").is_file():
        (directory / f"{plugin_id}.py").unlink()
    shutil.rmtree(directory / PREVIOUS_DIR / plugin_id, ignore_errors=True)


def previous_version(plugin_id: str, directory: Path | None = None) -> str | None:
    directory = directory or plugins_dir()
    manifest = directory / PREVIOUS_DIR / plugin_id / MANIFEST
    if not manifest.is_file():
        return None
    try:
        return Manifest.load(manifest).version
    except Exception:
        return "?"


def rollback(plugin_id: str, directory: Path | None = None) -> None:
    """Put the version replaced by the last update back."""
    directory = directory or plugins_dir()
    previous = directory / PREVIOUS_DIR / plugin_id
    if not previous.is_dir():
        raise PluginSourceError(f"no previous version of {plugin_id} is kept")
    current = directory / plugin_id
    shutil.rmtree(current, ignore_errors=True)
    previous.rename(current)


# -- the rows the manager screen shows ---------------------------------------

STATUS_TEXT = {
    "installed": "installed",
    "update": "update available",
    "available": "not installed",
    "incompatible": "needs newer Inkmill",
    "unmanaged": "local, unmanaged",
    "disabled": "disabled",
    "error": "failed to load",
    "skipped": "not loaded",
}


@dataclass
class Row:
    id: str
    name: str
    summary: str
    installed: Installed | None = None
    entry: IndexEntry | None = None
    disabled: bool = False
    load_error: str | None = None
    load_skipped: str | None = None
    previous: str | None = None

    @property
    def installed_version(self) -> str:
        return self.installed.version if self.installed else ""

    @property
    def available_version(self) -> str:
        return self.entry.manifest.version if self.entry else ""

    @property
    def has_update(self) -> bool:
        if not (self.installed and self.entry and self.entry.compatible):
            return False
        if self.installed and not self.installed.managed and self.installed.path.suffix == ".py":
            return False
        new = parse_version(self.available_version)
        old = parse_version(self.installed_version)
        if new is None or old is None:
            return self.available_version != self.installed_version
        return new > old

    @property
    def status(self) -> str:
        if self.installed is not None:
            if self.disabled:
                return "disabled"
            if self.load_error:
                return "error"
            if self.has_update:
                return "update"
            if self.load_skipped:
                return "skipped"
            if not self.installed.managed:
                return "unmanaged"
            return "installed"
        if self.entry is not None and not self.entry.compatible:
            return "incompatible"
        return "available"


def build_rows(
    index: list[IndexEntry],
    installed: dict[str, Installed],
    *,
    disabled: set[str] | None = None,
    load_info: dict[str, Any] | None = None,
    directory: Path | None = None,
) -> list[Row]:
    disabled = disabled or set()
    load_info = load_info or {}
    by_id = {e.id: e for e in index}
    rows: list[Row] = []
    for pid in sorted(set(by_id) | set(installed), key=str.lower):
        inst = installed.get(pid)
        entry = by_id.get(pid)
        manifest = (entry.manifest if entry else None) or (inst.manifest if inst else None)
        info = load_info.get(pid)
        rows.append(
            Row(
                id=pid,
                name=manifest.name if manifest else pid,
                summary=manifest.summary if manifest else "",
                installed=inst,
                entry=entry,
                disabled=pid in disabled,
                load_error=getattr(info, "error", None),
                load_skipped=getattr(info, "skipped", None) if getattr(info, "skipped", None) != "disabled" else None,
                previous=previous_version(pid, directory) if inst else None,
            )
        )
    return rows
