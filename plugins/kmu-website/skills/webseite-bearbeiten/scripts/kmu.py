# -*- coding: utf-8 -*-
"""Sichere Git-Abläufe für Kunden. Claude ruft NUR diese Befehle auf, nie git push/reset direkt.

  python kmu.py start                      neuesten Stand holen, Status zeigen
  python kmu.py status                     was ist geändert, aber noch nicht veröffentlicht?
  python kmu.py veroeffentlichen "Text"    prüfen (live) -> speichern -> hochladen (geht dann automatisch online)
  python kmu.py verwerfen                  noch nicht veröffentlichte Änderungen verwerfen
  python kmu.py verlauf                    letzte 15 Versionen anzeigen
  python kmu.py rueckgaengig [VERSION]     eine veröffentlichte Version rückgängig machen (Standard: die letzte)
"""
import sys, subprocess, pathlib, re

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import kmulib

HERE = pathlib.Path(__file__).parent


def git(*args, check=True, root=None):
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip())
    return r.stdout.rstrip()  # nicht strip(): 'git status --porcelain' beginnt mit Leerzeichen


def has_remote(root):
    return bool(git("remote", root=root, check=False))


def editable_specs(cfg):
    return [f":(glob){p}" for p in cfg["editable"]]


def changed_files(root):
    out = git("status", "--porcelain", "--untracked-files=all", root=root)
    return [l[3:].strip().strip('"') for l in out.splitlines() if l.strip()]


def run_check(root, live=True):
    args = [sys.executable, str(HERE / "check.py")] + (["--live"] if live else [])
    r = subprocess.run(args, cwd=root)
    return r.returncode == 0


def cmd_start(root, cfg):
    if has_remote(root):
        try:
            git("pull", "--ff-only", root=root)
            print("✓ Neuester Stand geholt.")
        except RuntimeError as e:
            print("✗ Konnte den neuesten Stand nicht holen:", e)
            print("  → Nichts ändern und den Betreuer informieren.")
            sys.exit(1)
    else:
        print("(Kein Online-Speicher verbunden – nur lokal.)")
    cmd_status(root, cfg)


def cmd_status(root, cfg):
    ch = changed_files(root)
    if not ch:
        print("Keine offenen Änderungen."); return
    print("Noch nicht veröffentlichte Änderungen:")
    for f in ch:
        mark = "" if kmulib.is_editable(cfg, f) else "   ← GESCHÜTZT, darf nicht geändert werden"
        print("  -", f + mark)


def cmd_publish(root, cfg, msg):
    if not msg.strip():
        sys.exit("Bitte eine kurze Beschreibung der Änderung angeben, z. B. \"Öffnungszeiten Samstag angepasst\".")
    ch = changed_files(root)
    bad = [f for f in ch if not kmulib.is_editable(cfg, f) and not f.startswith(cfg["out"] + "/")]
    if bad:
        print("✗ Es sind Dateien geändert, die nicht geändert werden dürfen:")
        for f in bad: print("  -", f)
        sys.exit("  → Nicht veröffentlicht. 'python kmu.py verwerfen' oder Betreuer fragen.")
    if not [f for f in ch if kmulib.is_editable(cfg, f)]:
        sys.exit("Es gibt nichts zu veröffentlichen.")
    if has_remote(root):
        try:
            git("pull", "--ff-only", root=root)
        except RuntimeError:
            pass  # lokale Änderungen sind noch nicht gespeichert; Abgleich unten nach dem Commit
    print("Prüfe die Live-Version …")
    if not run_check(root, live=True):
        sys.exit("✗ Prüfung fehlgeschlagen – NICHT veröffentlicht. Bitte die Meldungen oben beheben.")
    git("add", "--", *editable_specs(cfg), root=root)
    git("commit", "-m", msg.strip(), root=root)
    sha = git("rev-parse", "--short", "HEAD", root=root)
    if not has_remote(root):
        print(f"✓ Lokal gespeichert als Version {sha} (kein Online-Speicher verbunden, daher nicht online)."); return
    r = subprocess.run(["git", "push"], cwd=root, capture_output=True, text=True)
    if r.returncode != 0:
        # Jemand anderes hat inzwischen veröffentlicht: zusammenführen, nochmals prüfen, nochmals senden
        m = subprocess.run(["git", "pull", "--no-rebase", "--no-edit"], cwd=root, capture_output=True, text=True)
        if m.returncode != 0:
            subprocess.run(["git", "merge", "--abort"], cwd=root, capture_output=True)
            sys.exit("✗ Ihre Änderung überschneidet sich mit einer anderen. Lokal gespeichert, aber NICHT online. Bitte Betreuer informieren.")
        if not run_check(root, live=True):
            sys.exit("✗ Nach dem Zusammenführen schlägt die Prüfung fehl. NICHT online. Bitte Betreuer informieren.")
        git("push", root=root)
        sha = git("rev-parse", "--short", "HEAD", root=root)
    dom = cfg.get("domain", "")
    print(f"✓ Veröffentlicht (Version {sha}). In ca. 1–2 Minuten online" + (f": https://{dom}/" if dom else "."))
    print("  Falls etwas nicht stimmt: 'mach das rückgängig' sagen.")


def cmd_discard(root, cfg):
    ch = [f for f in changed_files(root) if not f.startswith(cfg["out"] + "/")]
    if not ch:
        print("Nichts zu verwerfen."); return
    git("restore", "--staged", "--worktree", "--", ".", root=root, check=False)
    git("clean", "-fdq", "--", *editable_specs(cfg), root=root, check=False)  # nur neue Dateien in erlaubten Bereichen
    print("✓ Offene Änderungen verworfen:", ", ".join(ch))


def cmd_log(root, cfg):
    print(git("log", "-15", "--date=format:%d.%m.%Y %H:%M", "--pretty=format:%h  %ad  %an  –  %s", root=root))


def cmd_undo(root, cfg, rev="HEAD"):
    if not re.fullmatch(r"[0-9a-fA-F]{6,40}|HEAD", rev):
        sys.exit("Version bitte als Kürzel aus 'verlauf' angeben, z. B. a1b2c3d.")
    if [f for f in changed_files(root) if not f.startswith(cfg["out"] + "/")]:
        sys.exit("Es gibt noch offene Änderungen. Zuerst veröffentlichen oder verwerfen.")
    subj = git("log", "-1", "--pretty=%s", rev, root=root)
    if len(git("rev-list", "--parents", "-n", "1", rev, root=root).split()) > 2:
        r = subprocess.run(["git", "revert", "--no-edit", "-m", "1", rev], cwd=root, capture_output=True, text=True)
    else:
        r = subprocess.run(["git", "revert", "--no-edit", rev], cwd=root, capture_output=True, text=True)
    if r.returncode != 0:
        subprocess.run(["git", "revert", "--abort"], cwd=root, capture_output=True)
        sys.exit("✗ Diese Version lässt sich nicht automatisch rückgängig machen (spätere Änderungen bauen darauf auf). Bitte Betreuer informieren.")
    if not run_check(root, live=True):
        git("reset", "--hard", "HEAD~1", root=root)  # nur den eben erzeugten, noch nicht gesendeten Revert-Commit entfernen
        sys.exit("✗ Nach dem Rückgängigmachen schlägt die Prüfung fehl. Nichts geändert. Bitte Betreuer informieren.")
    if has_remote(root):
        git("push", root=root)
        print(f"✓ Rückgängig gemacht: «{subj}». In ca. 1–2 Minuten online.")
    else:
        print(f"✓ Lokal rückgängig gemacht: «{subj}».")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    root = kmulib.find_root()
    if not root:
        sys.exit("Kein Webseiten-Projekt gefunden (.kmu/site.json fehlt).")
    cfg = kmulib.load_site(root)
    a = sys.argv[1:] or ["status"]
    c = a[0]
    try:
        if c == "start": cmd_start(root, cfg)
        elif c == "status": cmd_status(root, cfg)
        elif c in ("veroeffentlichen", "publish"): cmd_publish(root, cfg, " ".join(a[1:]))
        elif c == "verwerfen": cmd_discard(root, cfg)
        elif c == "verlauf": cmd_log(root, cfg)
        elif c in ("rueckgaengig", "undo"): cmd_undo(root, cfg, a[1] if len(a) > 1 else "HEAD")
        else: sys.exit(__doc__)
    except RuntimeError as e:
        sys.exit(f"✗ Fehler: {e}\n  → Bitte Betreuer informieren.")


if __name__ == "__main__":
    main()
