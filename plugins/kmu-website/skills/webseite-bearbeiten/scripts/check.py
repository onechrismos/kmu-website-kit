# -*- coding: utf-8 -*-
"""Prüft eine KMU-Webseite vor dem Veröffentlichen. Läuft lokal (Skill) und in der GitHub Action.

  python check.py              Vorschau bauen + prüfen
  python check.py --live       Veröffentlichungs-Version bauen + prüfen. Steht in .kmu/site.json
                               "stufe": "vorschau" (Testziel), wird stattdessen die Vorschau geprüft.
  python check.py --accept     NUR Betreuer (KMU_OWNER=1): aktuellen Stand als "gut" festschreiben
                               (Struktur der Seiten + geschützte Dateien -> .kmu/lock.json)

Exit 0 = alles gut, 1 = Fehler (nicht veröffentlichen). Meldungen sind für Laien verständlich.
"""
import sys, os, json, re, subprocess, pathlib, shlex, datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit, unquote

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import kmulib

LIVE = "--live" in sys.argv
ACCEPT = "--accept" in sys.argv
CI = "--ci" in sys.argv or os.environ.get("GITHUB_ACTIONS") == "true"

errors, warnings = [], []
def err(m): errors.append(m)
def warn(m): warnings.append(m)


# ---------------------------------------------------------------- Struktur einer Seite
TEXT_ATTRS = {"alt", "title", "aria-label", "placeholder", "content"}

class Structure(HTMLParser):
    """Zerlegt HTML in eine Liste von Bausteinen OHNE den sichtbaren Text.
    Text darf sich ändern, Tags/Klassen/Links/Skripte nicht."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tokens = []; self.raw = None; self.line = []
    def handle_starttag(self, tag, attrs):
        a = " ".join(f'{k}="{v}"' if k not in TEXT_ATTRS else k for k, v in sorted(attrs, key=lambda x: x[0]))
        self.tokens.append((self.getpos()[0], f"<{tag} {a}>".replace(" >", ">")))
        if tag in ("script", "style"): self.raw = tag
    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
    def handle_endtag(self, tag):
        self.tokens.append((self.getpos()[0], f"</{tag}>")); self.raw = None
    def handle_data(self, data):
        if self.raw:
            self.tokens.append((self.getpos()[0], f"[{self.raw}:{re.sub(r'\s+', ' ', data.strip())}]"))
        for ph in re.findall(r"\{\{[A-Z0-9_]+\}\}", data):
            self.tokens.append((self.getpos()[0], ph))
    def handle_comment(self, data):
        pass


def page_structure(text):
    """Seitenquelle -> (Liste (zeile, baustein)). Erste Zeile = JSON-Metadaten:
    title/desc/og dürfen sich ändern, alles andere (preload, nav …) nicht."""
    first, _, body = text.partition("\n")
    toks = []
    try:
        meta = json.loads(first)
        fixed = {k: v for k, v in meta.items() if k not in ("title", "desc", "og")}
        toks.append((1, "META " + json.dumps(fixed, sort_keys=True, ensure_ascii=False)))
    except json.JSONDecodeError:
        toks.append((1, "META kaputt"))
    p = Structure(); p.feed(body); p.close()
    toks += [(ln + 1, t) for ln, t in p.tokens]
    return toks


def structure_hash(toks):
    import hashlib
    return hashlib.sha256("\n".join(t for _, t in toks).encode("utf-8")).hexdigest()


def git_show(root, rev, rel):
    try:
        return subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=root, capture_output=True, check=True).stdout.decode("utf-8")
    except Exception:
        return None


def explain_diff(root, rel, cur):
    """Erste Stelle zeigen, an der die Struktur vom letzten gespeicherten Stand abweicht."""
    old = git_show(root, "HEAD", rel)
    if old is None: return ""
    a, b = page_structure(old), cur
    for i in range(max(len(a), len(b))):
        x = a[i] if i < len(a) else (None, "(nichts)")
        y = b[i] if i < len(b) else (None, "(nichts)")
        if x[1] != y[1]:
            return f" Erste Abweichung ungefähr in Zeile {y[0] or x[0]}: vorher {x[1][:90]!r}, jetzt {y[1][:90]!r}."
    return ""


# ---------------------------------------------------------------- Prüfungen
def check_lock(root, cfg):
    lock_p = root / ".kmu" / "lock.json"
    if not lock_p.exists():
        err("Es gibt noch keinen festgeschriebenen Stand (.kmu/lock.json). Der Betreuer muss einmal 'check.py --accept' ausführen.")
        return
    lock = json.loads(lock_p.read_text(encoding="utf-8"))
    for rel, h in lock.get("protected", {}).items():
        p = root / rel
        if not p.exists():
            err(f"Geschützte Datei fehlt: {rel}. Bitte rückgängig machen oder den Betreuer fragen.")
        elif kmulib.sha256(p) != h:
            err(f"Geschützte Datei wurde verändert: {rel}. Solche Änderungen macht nur der Betreuer.")
    for rel in kmulib.files_matching(root, cfg["protected"]):
        if rel not in lock.get("protected", {}) and rel != ".kmu/lock.json":
            err(f"Neue Datei in einem geschützten Bereich: {rel}. Solche Änderungen macht nur der Betreuer.")
    for rel, h in lock.get("structure", {}).items():
        p = root / rel
        if not p.exists():
            err(f"Seite fehlt: {rel}. Seiten löschen macht nur der Betreuer."); continue
        toks = page_structure(p.read_text(encoding="utf-8"))
        if structure_hash(toks) != h:
            err(f"Der Aufbau von {rel} wurde verändert (nicht nur Text). Erlaubt ist nur Text zwischen den Tags zu ändern."
                + explain_diff(root, rel, toks))
    for rel in kmulib.files_matching(root, cfg["structure_locked"]):
        if rel not in lock.get("structure", {}):
            err(f"Neue Seite {rel}: Neue Seiten legt nur der Betreuer an.")


def check_firma(root):
    p = root / "content" / "firma.json"
    if not p.exists(): return
    try:
        F = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        err(f"content/firma.json ist beschädigt (Zeile {e.lineno}): {e.msg}. Meist fehlt ein Komma oder ein Anführungszeichen."); return
    for k in ("name", "strasse", "plz", "ort", "telefon", "email"):
        if not str(F.get(k, "")).strip(): err(f"content/firma.json: '{k}' fehlt oder ist leer.")
    if F.get("email") and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", F["email"], re.I):
        err(f"content/firma.json: E-Mail sieht falsch aus: {F['email']}")
    for k in ("telefon", "telefon2"):
        v = F.get(k)
        if v and len(re.sub(r"\D", "", v)) not in (10, 11, 12):
            err(f"content/firma.json: Telefonnummer '{v}' sieht falsch aus (erwartet z. B. 056 245 10 70).")
    if F.get("plz") and not re.fullmatch(r"\d{4}", str(F["plz"])):
        err("content/firma.json: PLZ muss 4 Ziffern haben.")
    seen = set()
    for o in F.get("oeffnungszeiten", []):
        t = o.get("tage", "?")
        for d in o.get("wochentage", []):
            if d not in range(7): err(f"Öffnungszeiten '{t}': Wochentag {d} gibt es nicht (0=So, 1=Mo … 6=Sa).")
            if d in seen: err(f"Öffnungszeiten: Wochentag {d} kommt doppelt vor.")
            seen.add(d)
        last = -1
        for z in o.get("zeiten", []):
            if len(z) != 2 or not all(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", x) for x in z):
                err(f"Öffnungszeiten '{t}': Zeit {z} muss im Format [\"07:00\", \"12:00\"] sein."); continue
            a, b = (int(x[:2]) * 60 + int(x[3:]) for x in z)
            if a >= b or a < last: err(f"Öffnungszeiten '{t}': {z[0]}–{z[1]} ist unlogisch (Ende vor Beginn oder Überschneidung).")
            last = b
    n = F.get("hinweis") or {}
    if n.get("bis"):
        try:
            if datetime.date.fromisoformat(n["bis"]) < datetime.date.today() and n.get("text"):
                warn("Der Hinweis-Balken ist abgelaufen und wird nicht mehr angezeigt. Text kann geleert werden.")
        except ValueError:
            err("content/firma.json: hinweis.bis muss JJJJ-MM-TT sein, z. B. 2026-12-31.")


class Out(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.h1 = 0; self.refs = []; self.title = ""; self._t = False; self.robots = None; self.desc = None
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "h1": self.h1 += 1
        if tag == "title": self._t = True
        if tag == "meta" and a.get("name") == "robots": self.robots = a.get("content", "")
        if tag == "meta" and a.get("name") == "description": self.desc = a.get("content", "")
        for k in ("href", "src", "poster"):
            if a.get(k): self.refs.append(a[k])
        for k in ("srcset", "imagesrcset"):
            if a.get(k): self.refs += [s.strip().split(" ")[0] for s in a[k].split(",") if s.strip()]
    def handle_endtag(self, tag):
        if tag == "title": self._t = False
    def handle_data(self, d):
        if self._t: self.title += d


def check_output(root, cfg):
    out = root / cfg["out"]
    pages = sorted(out.glob("*.html"))
    if not pages: err(f"Im Ordner {cfg['out']}/ wurden keine Seiten erzeugt."); return
    for f in pages:
        t = f.read_text(encoding="utf-8"); p = Out(); p.feed(t)
        n = f.name
        if p.h1 != 1: err(f"{n}: Es muss genau eine Hauptüberschrift (H1) geben, gefunden: {p.h1}.")
        if not p.title.strip(): err(f"{n}: Seitentitel fehlt.")
        elif len(p.title) > 70: warn(f"{n}: Seitentitel ist lang ({len(p.title)} Zeichen, ideal ≤ 60) – Google kürzt ihn.")
        if not (p.desc or "").strip(): err(f"{n}: Beschreibung für Google (meta description) fehlt.")
        elif len(p.desc) > 165: warn(f"{n}: Google-Beschreibung ist lang ({len(p.desc)} Zeichen, ideal ≤ 155).")
        if "{{" in t: err(f"{n}: Ein Platzhalter {{{{…}}}} wurde nicht ersetzt.")
        for l in re.findall(r'<script type="application/ld\+json">(.*?)</script>', t, re.S):
            try: json.loads(l)
            except json.JSONDecodeError as e: err(f"{n}: Google-Daten (JSON-LD) ungültig: {e.msg}.")
        if LIVE:
            if not p.robots or "noindex" in p.robots: err(f"{n}: Live-Version darf nicht 'noindex' sein.")
            if re.search(r'<body[^>]*class="[^"]*staging', t): err(f"{n}: Live-Version ist noch als Vorschau (staging) markiert.")
            if re.search(r'class="[^"]*\btodo\b|data-todo=', t): err(f"{n}: Enthält noch gelbe Platzhalter (todo).")
        else:
            if not p.robots or "noindex" not in p.robots: err(f"{n}: Vorschau muss 'noindex' sein (sonst findet Google die Testseite).")
        for r in p.refs:
            u = urlsplit(r)
            if u.scheme or r.startswith(("#", "//", "mailto:", "tel:", "javascript:")) or not u.path: continue
            target = (out / unquote(u.path)).resolve()
            if u.path.endswith("/"): target = target / "index.html"
            if not target.exists(): err(f"{n}: Verweis auf fehlende Datei '{u.path}'.")
    big = [(p, p.stat().st_size) for p in out.rglob("*") if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif")]
    for p, s in big:
        if s > 1_500_000: err(f"Bild zu gross: {p.relative_to(out).as_posix()} ({s // 1024} KB, max. 1500 KB). Macht die Seite langsam.")
        elif s > 600_000: warn(f"Bild gross: {p.relative_to(out).as_posix()} ({s // 1024} KB).")


def run_build(root, cfg):
    b = cfg.get("build", {})
    cmd = b.get("live" if LIVE else "vorschau") or ("python build.py --prod" if LIVE else "python build.py")
    args = shlex.split(cmd)
    if args[0] in ("python", "python3"): args[0] = sys.executable
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    r = subprocess.run(args, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    if r.returncode != 0:
        msg = (r.stderr.strip() or r.stdout.strip()).splitlines()
        err("Die Webseite liess sich nicht erzeugen: " + " | ".join(msg[-6:]))
        return False
    return True


def accept(root, cfg):
    if os.environ.get("KMU_OWNER") != "1":
        sys.exit("Nur der Betreuer darf einen Stand festschreiben (KMU_OWNER=1).")
    lock = {"_info": "Automatisch erzeugt von check.py --accept. Nicht von Hand ändern.",
            "protected": {rel: kmulib.sha256(root / rel) for rel in kmulib.files_matching(root, cfg["protected"]) if rel != ".kmu/lock.json"},
            "structure": {rel: structure_hash(page_structure((root / rel).read_text(encoding="utf-8")))
                          for rel in kmulib.files_matching(root, cfg["structure_locked"])}}
    (root / ".kmu" / "lock.json").write_text(json.dumps(lock, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Festgeschrieben: {len(lock['protected'])} geschützte Dateien, {len(lock['structure'])} Seiten.")


def main():
    root = kmulib.find_root()
    if not root: sys.exit("Kein Webseiten-Projekt gefunden (.kmu/site.json fehlt).")
    cfg = kmulib.load_site(root)
    if ACCEPT:
        accept(root, cfg); return
    global LIVE
    if LIVE and cfg.get("stufe") == "vorschau":
        LIVE = False
        print("Hinweis: Diese Webseite ist noch in der Vorschau-Stufe (Testadresse, nicht bei Google).")
    check_firma(root)
    check_lock(root, cfg)
    if run_build(root, cfg):
        check_output(root, cfg)
    mode = "LIVE" if LIVE else "Vorschau"
    for w in warnings: print("Hinweis:", w)
    if errors:
        print(f"\n✗ {len(errors)} Problem(e) – NICHT veröffentlichen ({mode}):")
        for e in errors: print("  -", e)
        sys.exit(1)
    print(f"✓ Alles in Ordnung ({mode}). Erzeugt in {cfg['out']}/")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
