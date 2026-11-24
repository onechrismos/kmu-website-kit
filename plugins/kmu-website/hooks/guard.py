# -*- coding: utf-8 -*-
"""Sperr-Hook (PreToolUse): verhindert, dass Claude in einem Kunden-Webseiten-Projekt
geschützte Dateien ändert oder gefährliche Befehle ausführt.

- Greift NUR in Ordnern mit .kmu/site.json. Überall sonst: keine Wirkung.
- Betreuer-Modus: Umgebungsvariable KMU_OWNER=1 (in den eigenen Claude-Einstellungen) -> keine Sperre.
- Bei einem internen Fehler wird gesperrt (fail closed), nicht durchgelassen.
"""
import sys, json, os, re, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "skills" / "webseite-bearbeiten" / "scripts"))

CONTACT = "Diese Änderung macht der Webseiten-Betreuer. Bitte eine Anfrage an ihn formulieren."


def decide(decision, reason=""):
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision}}
    if reason:
        out["hookSpecificOutput"]["permissionDecisionReason"] = reason
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0)


DANGEROUS = [
    (r"\bgit\s+push\b[^|;&]*(\s-f\b|--force|--force-with-lease|--delete|\s-d\b|\s\+\S|\s:\S)", "Erzwungenes Hochladen/Löschen ist gesperrt."),
    (r"\bgit\s+push\b", "Bitte nur über 'kmu.py veroeffentlichen' hochladen (dort wird vorher geprüft)."),
    (r"\bgit\s+(reset|rebase|clean|filter-branch|filter-repo|replace|update-ref|reflog\s+expire|gc\b|prune)", "Dieser Git-Befehl kann Verlauf löschen und ist gesperrt. Rückgängig nur über 'kmu.py rueckgaengig'."),
    (r"\bgit\s+commit\b[^|;&]*--amend", "Nachträgliches Ändern gespeicherter Versionen ist gesperrt."),
    (r"\bgit\s+(remote|config|branch\s+-[dDmM]|tag\s+-d|checkout\s+-[bB]|switch\s+-c|worktree|submodule)\b", "Dieser Git-Befehl ist gesperrt."),
    (r"\bgit\s+(checkout|restore)\b[^|;&]*(\s--\s*\.|\s\.\s*$|--source)", "Bitte 'kmu.py verwerfen' verwenden."),
    (r"\b(ssh|scp|sftp|rsync|ftp|lftp|winscp)\b", "Direktes Hochladen auf den Server ist gesperrt – Veröffentlichen läuft automatisch über 'kmu.py veroeffentlichen'."),
    (r"\bcurl\b[^|;&]*(\s-T\b|--upload-file|\s-F\b|--data|\s-d\b|-X\s*(PUT|POST|DELETE))", "Hochladen per curl ist gesperrt."),
    (r"\brm\s+(-[a-zA-Z]*r|-[a-zA-Z]*f|--recursive)|\brmdir\b|\bdel\s+/[sq]|\brd\s+/s|Remove-Item\b[^|;&]*-Recurse", "Rekursives Löschen ist gesperrt."),
    (r"KMU_OWNER", "Der Betreuer-Modus kann hier nicht eingeschaltet werden."),
    (r"check\.py[^|;&]*--accept", "Festschreiben darf nur der Betreuer."),
    (r"\b(chmod|chown|icacls|attrib|takeown)\b", "Rechte ändern ist gesperrt."),
    (r"\b(pip|npm|pnpm|yarn|winget|choco|brew)\s+(install|i|add|uninstall)\b", "Software installieren ist gesperrt."),
]

WRITE_HINT = re.compile(
    r"(>{1,2}|\btee\b|\bsed\s+[^|;&]*-i|\bperl\s+[^|;&]*-i|\b(mv|cp|rm|truncate|touch|ln|install|dd)\b|"
    r"Set-Content|Add-Content|Out-File|Clear-Content|Remove-Item|Move-Item|Copy-Item|Rename-Item|New-Item|"
    r"\[IO\.File\]|WriteAll|open\([^)]*['\"][wax+]|write_text|write_bytes|shutil\.|os\.(remove|unlink|rename|replace))",
    re.I)


def check_command(cmd, root, cfg, kmulib):
    for pat, why in DANGEROUS:
        if re.search(pat, cmd, re.I | re.M):
            # Die eigenen sicheren Abläufe sind erlaubt
            if re.match(r"""^\s*(python3?|py)\s+["']?[^"'\n;&|]*kmu\.py["']?\s""", cmd + " ") and not re.search(r"[;&|`]|\$\(", cmd):
                return None
            return why
    cmd = re.sub(r"\d?>&\d|[12]?>\s*/dev/null|[12]?>\s*\$null|\bNUL\b", " ", cmd)  # harmlose Umleitungen
    if WRITE_HINT.search(cmd):
        # Schreibt der Befehl evtl. in einen geschützten Bereich? Dann sperren.
        prot_roots = set()
        for pat in cfg["protected"]:
            base = pat.split("*")[0].rstrip("/")
            if base: prot_roots.add(base)
        only_redirect = not WRITE_HINT.search(re.sub(r">{1,2}\s*[^\s|&;]+", " ", cmd))
        if only_redirect:  # nur Umleitung: nur das Ziel der Umleitung zählt
            tokens = re.findall(r">{1,2}\s*([^\s|&;]+)", cmd)
        else:
            tokens = re.findall(r"[\w./\\-]+", cmd)
        for t in tokens:
            t2 = t.replace("\\", "/").lstrip("./")
            rel = kmulib.rel_posix(root, t) or t2
            for pr in prot_roots:
                if rel == pr or rel.startswith(pr + "/") or t2 == pr or t2.startswith(pr + "/"):
                    return f"Der Befehl würde einen geschützten Bereich ändern ({pr}). {CONTACT}"
        # Schreiben per Shell in erlaubte Dateien ist unnötig -> Edit-Werkzeug verwenden
        if re.search(r"(>{1,2}\s*[\w./\\-]*(content|pages)/|Set-Content|Out-File|sed\s+[^|;&]*-i)", cmd, re.I):
            return "Bitte Dateien nur mit dem Bearbeiten-Werkzeug ändern, nicht per Befehl."
    return None


def main():
    data = json.load(sys.stdin)
    if os.environ.get("KMU_OWNER") == "1":
        sys.exit(0)
    import kmulib
    root = kmulib.find_root(data.get("cwd") or None)
    if not root:
        sys.exit(0)  # kein Kunden-Projekt -> keine Wirkung
    cfg = kmulib.load_site(root)
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}

    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        path = ti.get("file_path") or ti.get("notebook_path") or ""
        rel = kmulib.rel_posix(root, path)
        if rel is None:
            sys.exit(0)  # ausserhalb des Projekts (z. B. Notizordner)
        if kmulib.is_editable(cfg, rel):
            sys.exit(0)
        if rel.startswith(cfg["out"] + "/"):
            decide("deny", f"{rel} wird automatisch erzeugt. Bitte die Quelle in content/ oder pages/ ändern.")
        decide("deny", f"{rel} ist geschützt (Design, Technik oder Einstellungen). Erlaubt sind nur: "
                       f"{', '.join(cfg['editable'])}. {CONTACT}")

    if tool in ("Bash", "PowerShell"):
        why = check_command(ti.get("command", ""), root, cfg, kmulib)
        if why:
            decide("deny", why)
    sys.exit(0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        decide("deny", f"Die Sicherheitsprüfung hat einen Fehler ({type(e).__name__}: {e}). Zur Sicherheit gesperrt – bitte Betreuer informieren.")
