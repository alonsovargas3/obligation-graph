"""Build tests/fixtures/graph/real_v4.db: the real wave-3 integration graph in schema v4 plus the four site pins."""
import sqlite3, sys, yaml, json
from pathlib import Path
sys.path.insert(0, "src")
from og.store.db import connect
from og.textdoc import TextDoc
src, out, text_dir = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
out.unlink(missing_ok=True)
con = connect(out)
con.execute("PRAGMA foreign_keys = OFF")
con.execute("ATTACH ? AS v3", (src,))
tables = ["source","party","agreement","site","extraction_run","obligation","clause_ref","agreement_party","event","defined_term",
          "change_run","change_run_chain","change_finding","supersedes","guarantees","triggers","gate_decision"]
con.execute("BEGIN")
for t in tables:
    cols = [r[1] for r in con.execute(f"PRAGMA v3.table_info({t})")]
    cl = ",".join(f'"{c}"' for c in cols)
    con.execute(f'INSERT INTO main."{t}"({cl}) SELECT {cl} FROM v3."{t}"')
docs = yaml.safe_load(open("data/sources.yaml"))["documents"]
for e in docs:
    pin = e.get("site")
    if not pin: continue
    doc = TextDoc.load(text_dir / f"{e['id']}.json")
    seg = doc.segment(pin["segment_id"]); st = doc.text[seg.char_start:seg.char_end]
    i = st.index(pin["quote"]); a = seg.char_start + i; b = a + len(pin["quote"])
    assert doc.text[a:b] == pin["quote"]
    sec = doc.section_for(a)
    ref = con.execute("INSERT INTO clause_ref(obligation_id,agreement_id,section,page,char_start,char_end,span_text,grounded) VALUES(NULL,?,?,?,?,?,?,1)",
                      (e["id"], sec.number if sec else None, doc.page_for(a), a, b, pin["quote"])).lastrowid
    con.execute("INSERT OR IGNORE INTO site(name, location) VALUES(?,?)", (pin["name"], pin["location"]))
    sid = con.execute("SELECT id FROM site WHERE name=? AND location=?", (pin["name"], pin["location"])).fetchone()[0]
    con.execute("INSERT INTO agreement_site(agreement_id, site_id, clause_ref_id) VALUES(?,?,?)", (e["id"], sid, ref))
con.execute("COMMIT")
con.execute("DETACH v3")
con.execute("PRAGMA foreign_keys = ON")
print("fk violations", con.execute("PRAGMA foreign_key_check").fetchall()[:3])
q = lambda s: con.execute(s).fetchone()[0]
print("visible", q("select count(*) from visible_obligation"), "due", q("select count(*) from visible_obligation where effective_due is not null"),
      "owed_to", q("select count(*) from visible_obligation where owed_to is not null"),
      "sites", q("select count(*) from visible_site_binding"), "parties", q("select count(*) from visible_party_binding"),
      "fresh runs", q("select count(*) from fresh_change_run"), "finding refs", q("select count(*) from visible_change_finding_ref"))
con.execute("VACUUM"); con.close()
