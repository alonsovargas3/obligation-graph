PRAGMA foreign_keys = ON;
-- Schema v2 (wave 2). Derived data: an older graph.db is rebuilt, not migrated (ADR-008).

CREATE TABLE IF NOT EXISTS source (
  id TEXT PRIMARY KEY, url TEXT NOT NULL, filer TEXT, filing_date TEXT, form TEXT,
  exhibit TEXT, local_path TEXT NOT NULL, sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS party (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS agreement (
  id TEXT PRIMARY KEY, title TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('lease','colocation','hosting','guarantee','recognition','amendment','other')),
  effective_date TEXT CHECK (effective_date IS NULL OR date(effective_date) IS effective_date),
  source_id TEXT NOT NULL REFERENCES source(id),
  base_agreement_id TEXT REFERENCES agreement(id),
  is_form INTEGER NOT NULL DEFAULT 0 CHECK (is_form IN (0,1))
);
CREATE TABLE IF NOT EXISTS agreement_party (
  agreement_id TEXT NOT NULL REFERENCES agreement(id),
  party_id INTEGER NOT NULL REFERENCES party(id),
  role TEXT NOT NULL CHECK (role IN ('landlord','tenant','guarantor','provider','customer','lender','other')),
  clause_ref_id INTEGER NOT NULL REFERENCES clause_ref(id),
  PRIMARY KEY (agreement_id, party_id, role)
);
CREATE TABLE IF NOT EXISTS site (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, location TEXT, capacity_mw REAL
);
CREATE TABLE IF NOT EXISTS clause_ref (
  id INTEGER PRIMARY KEY,
  obligation_id INTEGER REFERENCES obligation(id),
  agreement_id TEXT NOT NULL REFERENCES agreement(id),
  section TEXT, page INTEGER,
  char_start INTEGER NOT NULL CHECK (char_start >= 0),
  char_end INTEGER NOT NULL,
  span_text TEXT NOT NULL CHECK (span_text <> ''),
  grounded INTEGER NOT NULL CHECK (grounded IN (0,1)),
  CHECK (char_end > char_start),
  CHECK (length(span_text) = char_end - char_start)
);
CREATE TABLE IF NOT EXISTS event (
  id INTEGER PRIMARY KEY,
  agreement_id TEXT NOT NULL REFERENCES agreement(id),
  name TEXT NOT NULL,
  date TEXT CHECK (date IS NULL OR date(date) IS date),
  clause_ref_id INTEGER REFERENCES clause_ref(id)
);
CREATE TABLE IF NOT EXISTS defined_term (
  id INTEGER PRIMARY KEY,
  agreement_id TEXT NOT NULL REFERENCES agreement(id),
  term TEXT NOT NULL,
  clause_ref_id INTEGER NOT NULL REFERENCES clause_ref(id),
  UNIQUE (agreement_id, term)
);
CREATE TABLE IF NOT EXISTS extraction_run (
  id INTEGER PRIMARY KEY,
  run_id TEXT NOT NULL UNIQUE,
  source_id TEXT NOT NULL REFERENCES source(id),
  prompt_version TEXT NOT NULL,
  model TEXT NOT NULL,
  textdoc_sha256 TEXT NOT NULL,
  model_attempts_json TEXT NOT NULL DEFAULT '[]',
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  completed_at TEXT,
  UNIQUE (source_id, prompt_version)
);
CREATE TABLE IF NOT EXISTS obligation (
  id INTEGER PRIMARY KEY,
  agreement_id TEXT NOT NULL REFERENCES agreement(id),
  site_id INTEGER REFERENCES site(id),
  type TEXT NOT NULL CHECK (type IN ('payment','delivery','sla','penalty','termination_right','guarantee','notice','insurance','other')),
  owed_by INTEGER REFERENCES party(id),
  owed_to INTEGER REFERENCES party(id),
  description TEXT NOT NULL,
  amount REAL, currency TEXT,
  due_date TEXT CHECK (due_date IS NULL OR date(due_date) IS due_date),
  anchor_event_id INTEGER REFERENCES event(id),
  offset_days INTEGER CHECK (offset_days IS NULL OR typeof(offset_days) = 'integer'),
  "trigger" TEXT,
  status TEXT NOT NULL CHECK (status IN ('active','superseded','redacted','blank')),
  extraction_run_id INTEGER REFERENCES extraction_run(id),
  CHECK ((anchor_event_id IS NULL) = (offset_days IS NULL)),
  CHECK (NOT (due_date IS NOT NULL AND anchor_event_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS supersedes (
  obligation_id INTEGER NOT NULL REFERENCES obligation(id),
  superseded_obligation_id INTEGER NOT NULL REFERENCES obligation(id),
  change_order_id TEXT NOT NULL REFERENCES agreement(id),
  clause_ref_id INTEGER NOT NULL REFERENCES clause_ref(id),
  PRIMARY KEY (obligation_id, superseded_obligation_id)
);
CREATE TABLE IF NOT EXISTS guarantees (
  guarantee_obligation_id INTEGER NOT NULL REFERENCES obligation(id),
  guaranteed_obligation_id INTEGER NOT NULL REFERENCES obligation(id),
  clause_ref_id INTEGER NOT NULL REFERENCES clause_ref(id),
  PRIMARY KEY (guarantee_obligation_id, guaranteed_obligation_id)
);
CREATE TABLE IF NOT EXISTS triggers (
  obligation_id INTEGER NOT NULL REFERENCES obligation(id),
  triggered_by_obligation_id INTEGER NOT NULL REFERENCES obligation(id),
  kind TEXT NOT NULL CHECK (kind IN ('default','cross_default','step_in','condition')),
  clause_ref_id INTEGER NOT NULL REFERENCES clause_ref(id),
  PRIMARY KEY (obligation_id, triggered_by_obligation_id, kind)
);
CREATE TABLE IF NOT EXISTS gate_decision (
  id INTEGER PRIMARY KEY,
  change_order_id TEXT NOT NULL, question TEXT NOT NULL, backend TEXT NOT NULL,
  answer INTEGER CHECK (answer IN (0,1)), confidence REAL, latency_ms INTEGER,
  input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL, error TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TRIGGER IF NOT EXISTS clause_ref_agreement_ins BEFORE INSERT ON clause_ref
WHEN NEW.obligation_id IS NOT NULL
 AND NEW.agreement_id IS NOT (SELECT agreement_id FROM obligation WHERE id = NEW.obligation_id)
BEGIN SELECT RAISE(ABORT, 'clause_ref agreement differs from obligation agreement'); END;

CREATE TRIGGER IF NOT EXISTS clause_ref_agreement_upd BEFORE UPDATE OF obligation_id, agreement_id ON clause_ref
WHEN NEW.obligation_id IS NOT NULL
 AND NEW.agreement_id IS NOT (SELECT agreement_id FROM obligation WHERE id = NEW.obligation_id)
BEGIN SELECT RAISE(ABORT, 'clause_ref agreement differs from obligation agreement'); END;

CREATE TRIGGER IF NOT EXISTS event_citation_ins BEFORE INSERT ON event
WHEN NEW.clause_ref_id IS NOT NULL
 AND NEW.agreement_id IS NOT (SELECT agreement_id FROM clause_ref WHERE id = NEW.clause_ref_id)
BEGIN SELECT RAISE(ABORT, 'event citation from another agreement'); END;

CREATE TRIGGER IF NOT EXISTS event_citation_upd BEFORE UPDATE OF clause_ref_id, agreement_id ON event
WHEN NEW.clause_ref_id IS NOT NULL
 AND NEW.agreement_id IS NOT (SELECT agreement_id FROM clause_ref WHERE id = NEW.clause_ref_id)
BEGIN SELECT RAISE(ABORT, 'event citation from another agreement'); END;

CREATE TRIGGER IF NOT EXISTS defined_term_citation_ins BEFORE INSERT ON defined_term
WHEN NEW.agreement_id IS NOT (SELECT agreement_id FROM clause_ref WHERE id = NEW.clause_ref_id)
BEGIN SELECT RAISE(ABORT, 'defined term citation from another agreement'); END;

CREATE TRIGGER IF NOT EXISTS defined_term_citation_upd BEFORE UPDATE OF clause_ref_id, agreement_id ON defined_term
WHEN NEW.agreement_id IS NOT (SELECT agreement_id FROM clause_ref WHERE id = NEW.clause_ref_id)
BEGIN SELECT RAISE(ABORT, 'defined term citation from another agreement'); END;

DROP VIEW IF EXISTS visible_agreement_party;
DROP VIEW IF EXISTS visible_defined_term;
DROP VIEW IF EXISTS visible_triggers;
DROP VIEW IF EXISTS visible_guarantees;
DROP VIEW IF EXISTS visible_supersedes;
DROP VIEW IF EXISTS visible_obligation;

CREATE VIEW visible_obligation AS
WITH anchored AS (
  SELECT o.id AS obligation_id,
    CASE WHEN e.date IS NOT NULL
      AND EXISTS (SELECT 1 FROM clause_ref c
                  WHERE c.id = e.clause_ref_id AND c.grounded = 1 AND c.agreement_id = e.agreement_id)
      AND (e.agreement_id = o.agreement_id
           OR e.agreement_id = (SELECT a.base_agreement_id FROM agreement a WHERE a.id = o.agreement_id))
    THEN date(e.date, printf('%+d days', o.offset_days)) END AS anchored_due
  FROM obligation o LEFT JOIN event e ON e.id = o.anchor_event_id
)
SELECT o.*,
  COALESCE(o.due_date, an.anchored_due) AS effective_due,
  CASE WHEN o.status = 'superseded' THEN 'superseded'
       WHEN COALESCE(o.due_date, an.anchored_due) IS NULL THEN 'pending'
       ELSE 'scheduled' END AS lifecycle
FROM obligation o JOIN anchored an ON an.obligation_id = o.id
WHERE EXISTS (SELECT 1 FROM clause_ref c
              WHERE c.obligation_id = o.id AND c.grounded = 1 AND c.agreement_id = o.agreement_id);

CREATE VIEW visible_supersedes AS
SELECT s.* FROM supersedes s JOIN clause_ref c ON c.id = s.clause_ref_id AND c.grounded = 1
WHERE c.agreement_id = s.change_order_id
  AND s.obligation_id IN (SELECT id FROM visible_obligation)
  AND s.superseded_obligation_id IN (SELECT id FROM visible_obligation);

CREATE VIEW visible_guarantees AS
SELECT g.* FROM guarantees g JOIN clause_ref c ON c.id = g.clause_ref_id AND c.grounded = 1
WHERE c.agreement_id = (SELECT agreement_id FROM obligation WHERE id = g.guarantee_obligation_id)
  AND g.guarantee_obligation_id IN (SELECT id FROM visible_obligation)
  AND g.guaranteed_obligation_id IN (SELECT id FROM visible_obligation);

CREATE VIEW visible_triggers AS
SELECT t.* FROM triggers t JOIN clause_ref c ON c.id = t.clause_ref_id AND c.grounded = 1
WHERE c.agreement_id IN (SELECT agreement_id FROM obligation
                        WHERE id IN (t.obligation_id, t.triggered_by_obligation_id))
  AND t.obligation_id IN (SELECT id FROM visible_obligation)
  AND t.triggered_by_obligation_id IN (SELECT id FROM visible_obligation);

CREATE VIEW visible_defined_term AS
SELECT d.* FROM defined_term d
JOIN clause_ref c ON c.id = d.clause_ref_id AND c.grounded = 1 AND c.agreement_id = d.agreement_id;

CREATE VIEW IF NOT EXISTS visible_agreement_party AS
SELECT ap.* FROM agreement_party ap
JOIN clause_ref c ON c.id = ap.clause_ref_id AND c.grounded = 1 AND c.agreement_id = ap.agreement_id;
