PRAGMA foreign_keys = ON;
-- Schema v5 (wave 5). Derived data: an older graph.db is rebuilt, not migrated (ADR-008).

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
CREATE TABLE IF NOT EXISTS agreement_site (
  agreement_id TEXT NOT NULL REFERENCES agreement(id),
  site_id INTEGER NOT NULL REFERENCES site(id),
  clause_ref_id INTEGER NOT NULL REFERENCES clause_ref(id),
  PRIMARY KEY (agreement_id, site_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS site_identity ON site(name, location);
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
CREATE TABLE IF NOT EXISTS obligation_timing (
  obligation_id INTEGER PRIMARY KEY REFERENCES obligation(id),
  kind TEXT NOT NULL CHECK (kind IN ('scheduled','contingent','unresolved','untimed')),
  trigger_kind TEXT CHECK (trigger_kind IS NULL OR trigger_kind IN
    ('invoice','notice','demand','default','completion','term_end','defined_event','other_event')),
  trigger_clause_ref_id INTEGER REFERENCES clause_ref(id),
  relation TEXT CHECK (relation IS NULL OR relation IN ('lt','lte','eq','gte','gt')),
  offset_days INTEGER CHECK (offset_days IS NULL OR typeof(offset_days) = 'integer'),
  offset_unit TEXT CHECK (offset_unit IS NULL OR offset_unit IN ('calendar','business','hours','months')),
  anchor_event_id INTEGER REFERENCES event(id),
  bound_date TEXT CHECK (bound_date IS NULL OR date(bound_date) IS bound_date),
  reason TEXT CHECK (reason IS NULL OR reason IN
    ('business_days','anchor_without_date','anchor_not_found','relative_to_other_obligation',
     'conditional_or_compound','unsupported_unit','cross_reference','redacted_offset',
     'recurring_schedule','month_granularity','conflicting_dates')),
  CHECK (kind <> 'scheduled' OR (bound_date IS NOT NULL AND relation IS NOT NULL
         AND anchor_event_id IS NOT NULL AND (offset_unit IS NULL OR offset_unit = 'calendar'))),
  CHECK (kind <> 'contingent' OR trigger_clause_ref_id IS NOT NULL),
  CHECK ((kind = 'unresolved') = (reason IS NOT NULL)),
  CHECK (kind <> 'untimed' OR (trigger_clause_ref_id IS NULL AND bound_date IS NULL
         AND anchor_event_id IS NULL AND relation IS NULL AND trigger_kind IS NULL
         AND offset_days IS NULL AND reason IS NULL))
);
CREATE TABLE IF NOT EXISTS supersedes (
  obligation_id INTEGER NOT NULL REFERENCES obligation(id),
  superseded_obligation_id INTEGER NOT NULL REFERENCES obligation(id),
  change_order_id TEXT NOT NULL REFERENCES agreement(id),
  clause_ref_id INTEGER NOT NULL REFERENCES clause_ref(id),
  change_run_id INTEGER NOT NULL REFERENCES change_run(id),
  PRIMARY KEY (obligation_id, superseded_obligation_id),
  CHECK (obligation_id <> superseded_obligation_id)
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
CREATE TABLE IF NOT EXISTS change_run (
  id INTEGER PRIMARY KEY,
  run_id TEXT NOT NULL UNIQUE,
  pair_id TEXT NOT NULL,
  change_order_id TEXT NOT NULL REFERENCES agreement(id),
  mode TEXT NOT NULL CHECK (mode IN ('ungated','gated')),
  prompt_version TEXT NOT NULL,
  question_set_sha256 TEXT NOT NULL,
  model TEXT NOT NULL,
  fingerprints_json TEXT NOT NULL DEFAULT '{}',
  baseline_run_id TEXT,
  chain_size INTEGER NOT NULL CHECK (chain_size >= 2),
  cost_usd REAL, incremental_cost_usd REAL, latency_ms INTEGER,
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  completed_at TEXT,
  UNIQUE (change_order_id, mode),
  CHECK ((mode = 'gated') = (baseline_run_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS change_run_chain (
  change_run_id INTEGER NOT NULL REFERENCES change_run(id),
  position INTEGER NOT NULL CHECK (position >= 0),
  agreement_id TEXT NOT NULL REFERENCES agreement(id),
  role TEXT NOT NULL CHECK (role IN ('base','prior_amendment','change_order')),
  textdoc_sha256 TEXT NOT NULL,
  extraction_run_id TEXT NOT NULL,
  PRIMARY KEY (change_run_id, agreement_id),
  UNIQUE (change_run_id, position)
);
CREATE TABLE IF NOT EXISTS change_finding (
  id INTEGER PRIMARY KEY,
  change_run_id INTEGER NOT NULL REFERENCES change_run(id),
  kind TEXT NOT NULL CHECK (kind IN ('supersedes','shifted_date','price_change','potential_conflict')),
  category TEXT NOT NULL CHECK (category IN ('price','dates','termination','guarantee','sla','parties_or_sites')),
  new_clause_ref_id INTEGER NOT NULL REFERENCES clause_ref(id),
  old_clause_ref_id INTEGER REFERENCES clause_ref(id),
  context_clause_ref_id INTEGER REFERENCES clause_ref(id),
  old_origin TEXT NOT NULL CHECK (old_origin IN ('chain','self','unresolved')),
  target_label TEXT,
  target_resolution TEXT CHECK (target_resolution IS NULL OR target_resolution IN ('section','range','document','unresolved')),
  old_value TEXT, new_value TEXT, delta TEXT, currency TEXT,
  CHECK ((old_origin = 'unresolved') = (old_clause_ref_id IS NULL))
);
CREATE TABLE IF NOT EXISTS gate_decision (
  id INTEGER PRIMARY KEY,
  change_run_id INTEGER REFERENCES change_run(id),
  change_order_id TEXT NOT NULL, question TEXT NOT NULL, backend TEXT NOT NULL,
  tier TEXT CHECK (tier IS NULL OR tier IN ('rules','classifier','none')),
  answer INTEGER CHECK (answer IN (0,1)), confidence REAL,
  samples_json TEXT NOT NULL DEFAULT '[]', evidence_json TEXT NOT NULL DEFAULT '[]',
  run_check INTEGER CHECK (run_check IN (0,1)),
  latency_ms INTEGER, input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL, error TEXT,
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

DROP VIEW IF EXISTS visible_change_finding_ref;
DROP VIEW IF EXISTS visible_site_binding;
DROP VIEW IF EXISTS visible_event_binding;
DROP VIEW IF EXISTS visible_party_binding;
DROP VIEW IF EXISTS visible_obligation_clause;
DROP VIEW IF EXISTS visible_change_finding;
DROP VIEW IF EXISTS visible_agreement_party;
DROP VIEW IF EXISTS visible_defined_term;
DROP VIEW IF EXISTS visible_triggers;
DROP VIEW IF EXISTS visible_guarantees;
DROP VIEW IF EXISTS visible_supersedes;
DROP VIEW IF EXISTS visible_obligation;
DROP VIEW IF EXISTS visible_obligation_timing;
DROP VIEW IF EXISTS grounded_obligation;
DROP VIEW IF EXISTS eligible_supersedes;
DROP VIEW IF EXISTS fresh_change_run;

-- A change run is fresh when it completed and its full chain vector equals the
-- current extraction snapshot of every chain member (rev 2 R4: complete membership).
CREATE VIEW fresh_change_run AS
SELECT r.* FROM change_run r
WHERE r.completed_at IS NOT NULL
  AND (SELECT count(*) FROM change_run_chain k WHERE k.change_run_id = r.id) = r.chain_size
  AND EXISTS (SELECT 1 FROM change_run_chain k WHERE k.change_run_id = r.id
              AND k.agreement_id = r.change_order_id AND k.role = 'change_order'
              AND k.position = r.chain_size - 1)
  AND NOT EXISTS (
    SELECT 1 FROM change_run_chain k
    WHERE k.change_run_id = r.id
      AND NOT EXISTS (SELECT 1 FROM agreement a JOIN extraction_run e ON e.source_id = a.source_id
                      WHERE a.id = k.agreement_id AND e.run_id = k.extraction_run_id
                        AND e.textdoc_sha256 = k.textdoc_sha256));

-- Edge eligibility (rev 2 R2), shared by visible_supersedes and the lifecycle:
-- ungated fresh run, grounded citation in the change order, distinct endpoints,
-- superseding obligation in the change order, superseded one strictly earlier in
-- the run's chain, both endpoints with a grounded same-agreement ClauseRef.
CREATE VIEW eligible_supersedes AS
SELECT s.* FROM supersedes s
JOIN fresh_change_run r ON r.id = s.change_run_id AND r.mode = 'ungated'
                       AND r.change_order_id = s.change_order_id
JOIN clause_ref c ON c.id = s.clause_ref_id AND c.grounded = 1 AND c.agreement_id = s.change_order_id
JOIN obligation n ON n.id = s.obligation_id AND n.agreement_id = s.change_order_id
JOIN obligation o ON o.id = s.superseded_obligation_id
JOIN change_run_chain kn ON kn.change_run_id = r.id AND kn.agreement_id = n.agreement_id
JOIN change_run_chain ko ON ko.change_run_id = r.id AND ko.agreement_id = o.agreement_id
WHERE s.obligation_id <> s.superseded_obligation_id
  AND ko.position < kn.position
  AND EXISTS (SELECT 1 FROM clause_ref x WHERE x.obligation_id = n.id AND x.grounded = 1
              AND x.agreement_id = n.agreement_id)
  AND EXISTS (SELECT 1 FROM clause_ref x WHERE x.obligation_id = o.id AND x.grounded = 1
              AND x.agreement_id = o.agreement_id);

-- Wave 5 rev 2.1 R2-1: acyclic order. grounded_obligation (internal, not for readers)
-- -> visible_obligation_timing -> visible_obligation. The timing view never reads
-- visible_obligation.
CREATE VIEW grounded_obligation AS
SELECT o.* FROM obligation o
WHERE EXISTS (SELECT 1 FROM clause_ref c
              WHERE c.obligation_id = o.id AND c.grounded = 1 AND c.agreement_id = o.agreement_id);

-- A timing row is visible only when its trigger (if any) is a grounded ref in the
-- obligation's agreement contained in one of the obligation's own grounded extraction
-- citations, its anchor (if any) is a visible dated event in the obligation's agreement
-- or its recorded base, and a scheduled row's stored bound equals the bound recomputed
-- from that cited anchor date and the calendar offset.
CREATE VIEW visible_obligation_timing AS
SELECT t.obligation_id, o.agreement_id, t.kind, t.trigger_kind, t.relation,
  t.offset_days, t.offset_unit, t.reason,
  tr.id AS trigger_clause_ref_id, tr.section AS trigger_section, tr.page AS trigger_page,
  tr.char_start AS trigger_char_start, tr.char_end AS trigger_char_end,
  tr.span_text AS trigger_span_text,
  eb.event_id AS anchor_event_id, eb.agreement_id AS anchor_agreement_id,
  eb.name AS anchor_name, eb.date AS anchor_date, eb.clause_ref_id AS anchor_clause_ref_id,
  eb.section AS anchor_section, eb.page AS anchor_page, eb.char_start AS anchor_char_start,
  eb.char_end AS anchor_char_end, eb.span_text AS anchor_span_text,
  CASE WHEN t.kind = 'scheduled' THEN t.bound_date END AS bound_date
FROM obligation_timing t
JOIN grounded_obligation o ON o.id = t.obligation_id
LEFT JOIN clause_ref tr ON tr.id = t.trigger_clause_ref_id
LEFT JOIN visible_event_binding eb ON eb.event_id = t.anchor_event_id
WHERE (t.trigger_clause_ref_id IS NULL
       OR (tr.grounded = 1 AND tr.agreement_id = o.agreement_id
           AND EXISTS (SELECT 1 FROM clause_ref c
                       WHERE c.obligation_id = o.id AND c.grounded = 1
                         AND c.agreement_id = o.agreement_id
                         AND c.char_start <= tr.char_start AND tr.char_end <= c.char_end)))
  AND (t.anchor_event_id IS NULL
       OR (eb.event_id IS NOT NULL
           AND (eb.agreement_id = o.agreement_id
                OR eb.agreement_id = (SELECT a.base_agreement_id FROM agreement a
                                      WHERE a.id = o.agreement_id))))
  AND (t.kind <> 'scheduled'
       OR (eb.date IS NOT NULL
           AND t.bound_date = date(eb.date, printf('%+d days', COALESCE(t.offset_days, 0)))));

CREATE VIEW visible_obligation AS
WITH anchored AS (
  SELECT o.id AS obligation_id,
    CASE WHEN e.date IS NOT NULL
      AND EXISTS (SELECT 1 FROM clause_ref c
                  WHERE c.id = e.clause_ref_id AND c.grounded = 1 AND c.agreement_id = e.agreement_id)
      AND (e.agreement_id = o.agreement_id
           OR e.agreement_id = (SELECT a.base_agreement_id FROM agreement a WHERE a.id = o.agreement_id))
    THEN date(e.date, printf('%+d days', o.offset_days)) END AS anchored_due
  FROM grounded_obligation o LEFT JOIN event e ON e.id = o.anchor_event_id
)
SELECT o.*,
  COALESCE(o.due_date, an.anchored_due,
           CASE WHEN vt.kind = 'scheduled' AND vt.relation IN ('lte','eq') THEN vt.bound_date END)
    AS effective_due,
  CASE WHEN o.status = 'superseded'
         OR EXISTS (SELECT 1 FROM eligible_supersedes es WHERE es.superseded_obligation_id = o.id)
       THEN 'superseded'
       WHEN COALESCE(o.due_date, an.anchored_due) IS NOT NULL OR vt.kind = 'scheduled'
       THEN 'scheduled'
       ELSE 'pending' END AS lifecycle
FROM grounded_obligation o
JOIN anchored an ON an.obligation_id = o.id
LEFT JOIN visible_obligation_timing vt ON vt.obligation_id = o.id;

CREATE VIEW visible_supersedes AS
SELECT s.* FROM eligible_supersedes s
WHERE s.obligation_id IN (SELECT id FROM visible_obligation)
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

CREATE VIEW visible_change_finding AS
SELECT f.*, r.change_order_id, r.mode, r.run_id, r.pair_id FROM change_finding f
JOIN fresh_change_run r ON r.id = f.change_run_id
JOIN clause_ref n ON n.id = f.new_clause_ref_id AND n.grounded = 1 AND n.agreement_id = r.change_order_id
WHERE (f.old_clause_ref_id IS NULL
       OR EXISTS (SELECT 1 FROM clause_ref o
                  JOIN change_run_chain k ON k.change_run_id = r.id AND k.agreement_id = o.agreement_id
                  WHERE o.id = f.old_clause_ref_id AND o.grounded = 1
                    AND (f.old_origin = 'self') = (o.agreement_id = r.change_order_id)))
  AND (f.context_clause_ref_id IS NULL
       OR EXISTS (SELECT 1 FROM clause_ref x WHERE x.id = f.context_clause_ref_id
                  AND x.grounded = 1 AND x.agreement_id = r.change_order_id));

-- Citation-bearing projections (wave 4 rev 2.1 R2-1). Readers (og.query, the change
-- report, the scorers) take every citation from these; none joins clause_ref directly.
-- Each row is one (owner, grounded same-agreement ref) pair.
CREATE VIEW visible_obligation_clause AS
SELECT o.id AS obligation_id, o.agreement_id, c.id AS clause_ref_id,
       c.section, c.page, c.char_start, c.char_end, c.span_text
FROM visible_obligation o
JOIN clause_ref c ON c.obligation_id = o.id AND c.grounded = 1 AND c.agreement_id = o.agreement_id;

CREATE VIEW visible_party_binding AS
SELECT ap.agreement_id, ap.party_id, p.name, ap.role, c.id AS clause_ref_id,
       c.section, c.page, c.char_start, c.char_end, c.span_text
FROM visible_agreement_party ap
JOIN party p ON p.id = ap.party_id
JOIN clause_ref c ON c.id = ap.clause_ref_id AND c.grounded = 1 AND c.agreement_id = ap.agreement_id;

CREATE VIEW visible_event_binding AS
SELECT e.id AS event_id, e.agreement_id, e.name, e.date, c.id AS clause_ref_id,
       c.section, c.page, c.char_start, c.char_end, c.span_text
FROM event e
JOIN clause_ref c ON c.id = e.clause_ref_id AND c.grounded = 1 AND c.agreement_id = e.agreement_id;

CREATE VIEW visible_site_binding AS
SELECT a.agreement_id, a.site_id, s.name, s.location, c.id AS clause_ref_id,
       c.section, c.page, c.char_start, c.char_end, c.span_text
FROM agreement_site a
JOIN site s ON s.id = a.site_id
JOIN clause_ref c ON c.id = a.clause_ref_id AND c.grounded = 1 AND c.agreement_id = a.agreement_id;

CREATE VIEW visible_change_finding_ref AS
SELECT f.id AS finding_id, 'new' AS side, c.agreement_id, c.id AS clause_ref_id,
       c.section, c.page, c.char_start, c.char_end, c.span_text
FROM visible_change_finding f
JOIN clause_ref c ON c.id = f.new_clause_ref_id AND c.grounded = 1 AND c.agreement_id = f.change_order_id
UNION ALL
SELECT f.id, 'old', c.agreement_id, c.id, c.section, c.page, c.char_start, c.char_end, c.span_text
FROM visible_change_finding f
JOIN clause_ref c ON c.id = f.old_clause_ref_id AND c.grounded = 1
JOIN change_run_chain k ON k.change_run_id = f.change_run_id AND k.agreement_id = c.agreement_id
WHERE (f.old_origin = 'self') = (c.agreement_id = f.change_order_id)
UNION ALL
SELECT f.id, 'context', c.agreement_id, c.id, c.section, c.page, c.char_start, c.char_end, c.span_text
FROM visible_change_finding f
JOIN clause_ref c ON c.id = f.context_clause_ref_id AND c.grounded = 1 AND c.agreement_id = f.change_order_id;
