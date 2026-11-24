# -*- coding: utf-8 -*-
"""Gemeinsame Hilfsfunktionen für check.py, kmu.py und den Sperr-Hook.
Liest die Kunden-Konfiguration .kmu/site.json und beantwortet: Darf diese Datei geändert werden?"""
import json, pathlib, fnmatch, hashlib, os

DEFAULT_EDITABLE = ["content/**", "pages/*.html"]
DEFAULT_PROTECTED = [".kmu/**", ".github/**", ".claude/**", "CLAUDE.md", "build.py", "static/**"]


def find_root(start=None):
    """Projektordner mit .kmu/site.json suchen (vom Startordner aufwärts). None, wenn keiner."""
    p = pathlib.Path(start or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    for d in [p, *p.parents]:
        if (d / ".kmu" / "site.json").is_file():
            return d
    return None


def load_site(root):
    cfg = json.loads((root / ".kmu" / "site.json").read_text(encoding="utf-8"))
    cfg.setdefault("editable", DEFAULT_EDITABLE)
    cfg.setdefault("protected", DEFAULT_PROTECTED)
    cfg.setdefault("structure_locked", ["pages/*.html"])
    cfg.setdefault("out", "dist")
    return cfg


def _match(rel, patterns):
    for pat in patterns:
        # "*" passt nur innerhalb eines Ordners, "**" auch über Unterordner
        if fnmatch.fnmatchcase(rel, pat) and ("**" in pat or rel.count("/") == pat.count("/")):
            return True
        if pat.endswith("/**") and (rel == pat[:-3] or rel.startswith(pat[:-2])):
            return True
    return False


def rel_posix(root, path):
    """Pfad relativ zum Projekt (mit /), oder None wenn ausserhalb."""
    try:
        p = pathlib.Path(path)
        if not p.is_absolute():
            p = pathlib.Path(os.getcwd()) / p
        return p.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return None


def is_editable(cfg, rel):
    return _match(rel, cfg["editable"]) and not _match(rel, cfg["protected"])


def is_protected(cfg, rel):
    return _match(rel, cfg["protected"])


def files_matching(root, patterns, exclude_dirs=(".git", "node_modules")):
    out = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel.split("/")[0] in exclude_dirs:
            continue
        if _match(rel, patterns):
            out.append(rel)
    return sorted(out)


def sha256(path):
    """Prüfsumme; bei Textdateien unabhängig von Windows/Mac/Linux-Zeilenenden."""
    data = pathlib.Path(path).read_bytes()
    if b"\0" not in data[:8000]:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()
