"""Recherche dans le corpus de comptabilité nationale (SEC 2010, MGDD 2022) et le journal des cas.

    python3 cn.py search "contrôle administration publique" [-d SEC] [-n 10]
    python3 cn.py get SEC 20.29 [20.30-20.35] [-c 1]      # paragraphes (± contexte)
    python3 cn.py get MGDD 1.2.3 29                       # MGDD : section puis ¶ (la numérotation repart par chapitre)
    python3 cn.py section MGDD 1.2.3 | section SEC "test marchand"
    python3 cn.py toc SEC [20] [--depth 3]
    python3 cn.py cite SEC 20.29                          # passages (MGDD, cas) qui renvoient à ce paragraphe
    python3 cn.py refs MGDD 3.2.2                         # paragraphes du SEC cités dans une section
    python3 cn.py cas                                     # liste du journal des cas

Index : data/corpus.json (versionné) + cas/*.md (privé) → data/corpus.sqlite, reconstruit automatiquement
quand l'un d'eux change. Recherche plein texte SQLite FTS5 (BM25), insensible aux accents ; syntaxe FTS5
acceptée : OR, NOT, "expression exacte", préfixe*, NEAR(a b, 5). Les termes avec tiret ou point
(intra-government, D.42) sont mis entre guillemets automatiquement.
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent
CORPUS = ROOT / "data" / "corpus.json"
DB = ROOT / "data" / "corpus.sqlite"
CASES = ROOT / "cas"


# ---------------------------------------------------------------- index

def signature():
    files = [CORPUS] + sorted(CASES.glob("*.md"))
    return json.dumps([(f.name, f.stat().st_mtime_ns) for f in files if f.exists()])


def case_chunks():
    for f in sorted(CASES.glob("*.md")):
        text = f.read_text()
        title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), f.stem)
        yield {"id": f"CAS-{f.stem}", "doc": "CAS", "sec": None, "para": None, "ref": f"cas/{f.name}",
               "page": None, "page_end": None, "text": text, "path": title}


def build_db():
    corpus = json.loads(CORPUS.read_text())
    tmp = DB.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript("""
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE sources(id TEXT PRIMARY KEY, title TEXT, cite TEXT, lang TEXT, url TEXT, file TEXT, pages INT);
        CREATE TABLE sections(id TEXT PRIMARY KEY, ord INT, doc TEXT, level INT, num TEXT, ref_num TEXT,
                              title TEXT, page INT, parent TEXT, path TEXT);
        CREATE TABLE chunks(rowid INTEGER PRIMARY KEY, id TEXT UNIQUE, doc TEXT, sec TEXT, para TEXT, ref TEXT,
                            page INT, page_end INT, path TEXT, text TEXT);
        CREATE VIRTUAL TABLE fts USING fts5(ref, path, text, content='chunks', content_rowid='rowid',
                                            tokenize='unicode61 remove_diacritics 2');
    """)
    for s in corpus["sources"]:
        db.execute("INSERT INTO sources VALUES (?,?,?,?,?,?,?)",
                   [s[k] for k in ("id", "title", "cite", "lang", "url", "file", "pages")])
    secs = {}
    for i, s in enumerate(corpus["sections"]):
        secs[s["id"]] = s
        db.execute("INSERT INTO sections VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (s["id"], i, s["doc"], s["level"], s["num"], s["ref_num"], s["title"], s["page"],
                    s["parent"], " > ".join(s["path"])))
    rows = [dict(c, path=" > ".join(secs[c["sec"]]["path"])) for c in corpus["chunks"]] + list(case_chunks())
    db.executemany("INSERT INTO chunks(id, doc, sec, para, ref, page, page_end, path, text) "
                   "VALUES (:id,:doc,:sec,:para,:ref,:page,:page_end,:path,:text)", rows)
    db.execute("INSERT INTO fts(fts) VALUES ('rebuild')")
    db.execute("INSERT INTO meta VALUES ('signature', ?)", (signature(),))
    db.commit()
    db.close()
    tmp.replace(DB)


def connect():
    if not CORPUS.exists():
        sys.exit("data/corpus.json absent : lancer d'abord python3 build.py")
    try:
        db = sqlite3.connect(DB)
        ok = db.execute("SELECT value FROM meta WHERE key='signature'").fetchone() == (signature(),)
    except sqlite3.DatabaseError:
        ok = False
    if not ok:
        print("(index reconstruit)", file=sys.stderr)
        build_db()
        db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db


# ---------------------------------------------------------------- affichage

def where(c):
    pages = "" if c["page"] is None else f"p. {c['page']}" + (f"-{c['page_end']}" if c["page_end"] != c["page"] else "")
    return f"{c['ref']}  [{pages}]" if pages else c["ref"]


_last_path = None


def show(c):
    """Passage complet ; le fil d'Ariane n'est répété que s'il change d'un passage au suivant."""
    global _last_path
    print(f"## {where(c)}")
    if c["path"] != _last_path:
        print(f"   {c['path']}")
        _last_path = c["path"]
    print(c["text"])
    print()


def doc_id(db, name):
    ids = [r[0] for r in db.execute("SELECT id FROM sources")] + ["CAS"]
    for i in ids:
        if i.lower() == name.lower():
            return i
    sys.exit(f"document inconnu : {name} (disponibles : {', '.join(ids)})")


# ---------------------------------------------------------------- commandes

FTS_TOKEN = re.compile(r'"[^"]*"\*?|NEAR\([^)]*\)|[()]|[^\s()]+')


def fts_query(q):
    """Termes avec ponctuation (intra-government, D.42, start-up) → "chaînes exactes" ; le reste tel quel."""
    out = []
    for t in FTS_TOKEN.findall(q):
        if t.startswith('"') or t.startswith("NEAR(") or t in ("(", ")", "OR", "AND", "NOT") \
                or re.fullmatch(r"\w+\*?", t):
            out.append(t)
        else:
            star = "*" if t.endswith("*") else ""
            out.append('"' + t.rstrip("*").replace('"', "") + '"' + star)
    return " ".join(out)


def cmd_search(db, a):
    q = fts_query(" ".join(a.query))
    sql = """SELECT c.*, snippet(fts, 2, '«', '»', ' … ', 40) AS snip FROM fts JOIN chunks c ON c.rowid = fts.rowid
             WHERE fts MATCH ? {} ORDER BY bm25(fts, 4.0, 2.0, 1.0) LIMIT ?"""
    filt, params = "", []
    if a.doc:
        filt, params = "AND c.doc = ?", [doc_id(db, a.doc)]
    try:
        rows = db.execute(sql.format(filt), [q, *params, a.n]).fetchall()
    except sqlite3.OperationalError as e:
        # syntaxe FTS5 invalide : on le dit, puis chaque mot devient une chaîne exacte (tous requis)
        safe = " ".join('"' + w.replace('"', "") + '"' for w in re.findall(r"[\w.'’-]+", q) if w not in ("OR", "AND", "NOT"))
        print(f"(syntaxe de recherche invalide : {e} ; recherche refaite avec : {safe})", file=sys.stderr)
        rows = db.execute(sql.format(filt), [safe, *params, a.n]).fetchall()
    if not rows:
        print("aucun résultat (essayer OR, un préfixe mot*, ou l'autre langue : SEC en français, MGDD en anglais)")
        sys.exit(1)
    for r in rows:
        print(f"## {where(r)}\n   {r['path']}\n   {r['snip'].replace(chr(10), ' ')}\n")


def para_key(p):
    """'20.29' → (20, 29), pour les plages 20.29-20.35 ; None pour les numéros d'annexe (B5.1.1)."""
    parts = p.split(".")
    return tuple(int(x) for x in parts) if all(x.isdigit() for x in parts) else None


def resolve(db, doc, args):
    """Arguments d'un get → liste de rowid. SEC : '20.29' ou '20.29-20.35'. MGDD : '<section> <¶>' ou '<section> ¶29-31'."""
    rows = []
    if doc == "CAS":
        for a in args:
            rows += [r["rowid"] for r in db.execute("SELECT rowid FROM chunks WHERE doc='CAS' AND ref LIKE ?",
                                                     (f"%{a}%",))]
        return rows
    scoped = db.execute("SELECT 1 FROM chunks WHERE doc=? AND para IS NOT NULL AND ref LIKE '%¶%' LIMIT 1",
                        (doc,)).fetchone()
    if scoped:  # numérotation par section : <section> <¶ ou plage>
        args = [x.replace("¶", "") for x in args if x.replace("¶", "")]
        if len(args) != 2:
            sys.exit(f"{doc} : préciser la section puis le paragraphe, ex. get {doc} 1.2.3 29")
        sec, wanted = args
        lo, _, hi = wanted.partition("-")
        cands = db.execute("""SELECT c.rowid, c.para, s.ref_num FROM chunks c JOIN sections s ON s.id = c.sec
                              WHERE c.doc=? AND c.para IS NOT NULL AND (s.ref_num = ? OR s.ref_num LIKE ?)
                              ORDER BY c.rowid""", (doc, sec, sec + ".%")).fetchall()
        return [r["rowid"] for r in cands if int(lo) <= int(r["para"]) <= int(hi or lo)]
    for a in args:
        lo, _, hi = a.partition("-")
        allp = db.execute("SELECT rowid, para FROM chunks WHERE doc=? AND para IS NOT NULL ORDER BY rowid",
                          (doc,)).fetchall()
        if hi:
            klo, khi = para_key(lo), para_key(hi)
            if not klo or not khi:
                sys.exit(f"plage invalide : {a}")
            rows += [r["rowid"] for r in allp if (k := para_key(r["para"])) and len(k) == len(klo) and klo <= k <= khi]
        else:
            rows += [r["rowid"] for r in allp if r["para"] == lo]
    return rows


def cmd_get(db, a):
    doc = doc_id(db, a.doc)
    ids = resolve(db, doc, a.refs)
    if not ids:
        sys.exit("paragraphe introuvable (voir cn.py toc pour la structure, ou cn.py search)")
    if a.context:
        ids = sorted({i + d for i in ids for d in range(-a.context, a.context + 1)})
    for i in ids:
        r = db.execute("SELECT * FROM chunks WHERE rowid=? AND doc=?", (i, doc)).fetchone()
        if r:
            show(r)


def find_section(db, doc, key):
    r = db.execute("SELECT * FROM sections WHERE doc=? AND num=? ORDER BY ord LIMIT 1", (doc, key)).fetchone()
    if r:
        return r
    rows = db.execute("SELECT * FROM sections WHERE doc=? AND title LIKE ? ORDER BY level, ord",
                      (doc, f"%{key}%")).fetchall()
    if len(rows) > 1:
        print(f"{len(rows)} sections correspondent, première retenue :", file=sys.stderr)
        for x in rows[:10]:
            print(f"   [{x['page']}] {x['path']}", file=sys.stderr)
    return rows[0] if rows else None


def descendants(db, sec):
    """Sections du sous-arbre : de `sec` jusqu'à la prochaine section de niveau ≤ (ordre des signets)."""
    nxt = db.execute("SELECT ord FROM sections WHERE doc=? AND ord>? AND level<=? ORDER BY ord LIMIT 1",
                     (sec["doc"], sec["ord"], sec["level"])).fetchone()
    end = nxt[0] if nxt else 10 ** 9
    return db.execute("SELECT * FROM sections WHERE doc=? AND ord>=? AND ord<? ORDER BY ord",
                      (sec["doc"], sec["ord"], end)).fetchall()


def cmd_section(db, a):
    doc = doc_id(db, a.doc)
    sec = find_section(db, doc, " ".join(a.key))
    if not sec:
        sys.exit("section introuvable (voir cn.py toc)")
    subs = descendants(db, sec)
    ids = [s["id"] for s in subs]
    rows = db.execute(f"SELECT * FROM chunks WHERE sec IN ({','.join('?' * len(ids))}) ORDER BY rowid", ids).fetchall()
    words = sum(len(r["text"].split()) for r in rows)
    print(f"# {sec['path']}  [p. {sec['page']}] — {len(subs)} sections, {len(rows)} passages, {words} mots\n")
    if a.max_words and words > a.max_words:
        print(f"(trop long : plan seul ; relancer avec --max-words 0 pour tout afficher)\n")
        for s in subs:
            print(f"{'  ' * (s['level'] - sec['level'])}[{s['page']}] {s['title']}")
        return
    for r in rows:
        show(r)


def cmd_toc(db, a):
    doc = doc_id(db, a.doc)
    if a.key:
        sec = find_section(db, doc, " ".join(a.key))
        if not sec:
            sys.exit("section introuvable")
        subs, base = descendants(db, sec), sec["level"]
    else:
        subs, base = db.execute("SELECT * FROM sections WHERE doc=? ORDER BY ord", (doc,)).fetchall(), 1
    for s in subs:
        if s["level"] - base < a.depth:
            print(f"{'  ' * (s['level'] - base)}[{s['page']}] {s['title']}")


def cmd_cite(db, a):
    """Passages des autres documents qui citent un paragraphe (ex. MGDD : « ESA 2010 paragraph 20.29 »)."""
    doc = doc_id(db, a.doc)
    num = a.para
    pat = re.compile(r"(?<![\d.])" + re.escape(num) + r"(?![\d])")
    rows = db.execute("SELECT * FROM chunks WHERE doc != ? AND text LIKE ? ORDER BY rowid", (doc, f"%{num}%")).fetchall()
    hits = [r for r in rows if pat.search(r["text"])]
    if doc == "SEC":  # ne garder que les mentions qui renvoient bien au SEC / ESA
        between = r"(?:[^.;]|\.(?=\d)){0,80}?"   # un point n'arrête la phrase que s'il n'est pas dans un numéro
        ctx = re.compile(r"(ESA|SEC)" + between + re.escape(num) + r"|" + re.escape(num) + r"[^.;]{0,20}?(ESA|SEC)", re.I)
        hits = [r for r in hits if ctx.search(r["text"])] or hits
    print(f"{len(hits)} passage(s) citent {num}\n")
    for r in hits:
        i = pat.search(r["text"]).start()
        print(f"## {where(r)}\n   {r['path']}\n   … {r['text'][max(0, i - 200):i + 150].replace(chr(10), ' ')} …\n")


def cmd_refs(db, a):
    """Paragraphes du SEC cités dans une section (« ESA 2010 paragraph 20.29 », « points 20.19 à 20.28 »)."""
    doc = doc_id(db, a.doc)
    sec = find_section(db, doc, " ".join(a.key))
    if not sec:
        sys.exit("section introuvable (voir cn.py toc)")
    ids = [s["id"] for s in descendants(db, sec)]
    rows = db.execute(f"SELECT * FROM chunks WHERE sec IN ({','.join('?' * len(ids))}) ORDER BY rowid", ids).fetchall()
    known = {r[0]: r for r in db.execute("SELECT para, ref, page, substr(text, 1, 110) FROM chunks WHERE doc='SEC' AND para IS NOT NULL")}
    cited = {}
    for r in rows:
        # dans le SEC, tout numéro de paragraphe ; ailleurs, seulement à proximité de « ESA » / « SEC »
        spans = [r["text"]] if doc == "SEC" else [m.group(0) for m in re.finditer(r"(ESA|SEC)\s*2010(?:[^.;]|\.(?=\d)){0,100}", r["text"])]
        for span in spans:
            for n in re.findall(r"(?<![\d.])(\d{1,2}\.\d{2,3})(?![\d])", span):
                if n in known and r["para"] != n:
                    cited.setdefault(n, []).append(r["ref"])
    print(f"# {sec['path']} : {len(cited)} paragraphe(s) du SEC cité(s)\n")
    for n in sorted(cited, key=para_key):
        _, ref, page, start = known[n]
        froms = sorted(set(cited[n]), key=cited[n].index)
        print(f"{ref} [p. {page}] — {start.replace(chr(10), ' ')}…\n   cité par : {', '.join(froms[:6])}{' …' if len(froms) > 6 else ''}")


def cmd_cas(db, a):
    rows = db.execute("SELECT * FROM chunks WHERE doc='CAS' ORDER BY ref DESC").fetchall()
    if not rows:
        print("journal vide (cas/*.md)")
    for r in rows:
        print(f"{r['ref']} — {r['path']}")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="recherche plein texte")
    s.add_argument("query", nargs="+")
    s.add_argument("-d", "--doc")
    s.add_argument("-n", type=int, default=10)
    s = sub.add_parser("get", help="paragraphe(s) par numéro")
    s.add_argument("doc")
    s.add_argument("refs", nargs="+")
    s.add_argument("-c", "--context", type=int, default=0, help="paragraphes voisins à inclure")
    s = sub.add_parser("section", help="texte d'une section (numéro ou partie du titre)")
    s.add_argument("doc")
    s.add_argument("key", nargs="+")
    s.add_argument("--max-words", type=int, default=15000, help="au-delà, plan seul ; 0 = sans limite")
    s = sub.add_parser("toc", help="plan")
    s.add_argument("doc")
    s.add_argument("key", nargs="*")
    s.add_argument("--depth", type=int, default=2)
    s = sub.add_parser("cite", help="qui cite ce paragraphe ?")
    s.add_argument("doc")
    s.add_argument("para")
    s = sub.add_parser("refs", help="paragraphes du SEC cités dans une section")
    s.add_argument("doc")
    s.add_argument("key", nargs="+")
    sub.add_parser("cas", help="journal des cas")
    a = p.parse_args()
    db = connect()
    globals()[f"cmd_{a.cmd}"](db, a)


if __name__ == "__main__":
    main()
