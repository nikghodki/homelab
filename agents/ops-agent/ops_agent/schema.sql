-- Ops agent database (CNPG cluster ops, database app). Idempotent; applied by `ops-agent migrate`.
CREATE TABLE IF NOT EXISTS settings (
  key        text PRIMARY KEY,
  value      jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by text NOT NULL DEFAULT 'system'
);
INSERT INTO settings (key, value) VALUES ('mode', '"shadow"') ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS incidents (
  id            bigserial PRIMARY KEY,
  key           text NOT NULL,                 -- correlation key (one open incident per key)
  title         text NOT NULL,
  severity      text NOT NULL DEFAULT 'warning',  -- critical | warning | info
  klass         text NOT NULL DEFAULT 'generic',  -- playbook class
  status        text NOT NULL DEFAULT 'open',     -- open | investigating | rca_ready | resolved | closed
  family_impact boolean NOT NULL DEFAULT false,
  during_change text,                          -- change that likely caused it (merge, sync), if any
  tags          text[] NOT NULL DEFAULT '{}',
  source        text NOT NULL,
  labels        jsonb NOT NULL DEFAULT '{}',
  opened_at     timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  resolved_at   timestamptz,
  replay_run    bigint,                        -- set for replayed (A0) incidents
  workflow_id   text,
  snoozed_until timestamptz,
  dismissed     boolean NOT NULL DEFAULT false
);
CREATE UNIQUE INDEX IF NOT EXISTS incidents_open_key ON incidents (key)
  WHERE status IN ('open', 'investigating', 'rca_ready') AND replay_run IS NULL;
CREATE INDEX IF NOT EXISTS incidents_opened ON incidents (opened_at DESC);

CREATE TABLE IF NOT EXISTS events (
  id           bigserial PRIMARY KEY,
  received_at  timestamptz NOT NULL DEFAULT now(),
  occurred_at  timestamptz NOT NULL,
  source       text NOT NULL,                  -- alertmanager | k8s | github | gatus | loki | manual | replay
  fingerprint  text NOT NULL,
  status       text NOT NULL,                  -- firing | resolved | warning
  summary      text NOT NULL,
  labels       jsonb NOT NULL DEFAULT '{}',
  payload_sha  text NOT NULL,
  payload      jsonb NOT NULL DEFAULT '{}',    -- redacted
  incident_id  bigint REFERENCES incidents(id)
);
CREATE INDEX IF NOT EXISTS events_fp ON events (fingerprint, received_at DESC);
CREATE INDEX IF NOT EXISTS events_received ON events (received_at DESC);

CREATE TABLE IF NOT EXISTS evidence (
  id          bigserial PRIMARY KEY,
  incident_id bigint NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
  ref         text NOT NULL,                   -- E1, E2, ... (per incident)
  phase       text NOT NULL,                   -- first_look | investigate | recall
  tool        text NOT NULL,
  args        jsonb NOT NULL,
  time_from   timestamptz,
  time_to     timestamptz,
  result_sha  text NOT NULL,
  result      text NOT NULL,                   -- redacted, capped
  link        text,
  ok          boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (incident_id, ref)
);

CREATE TABLE IF NOT EXISTS rcas (
  id           bigserial PRIMARY KEY,
  incident_id  bigint NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
  engine       text NOT NULL,                  -- own-loop | holmesgpt | deterministic
  model        text,
  confidence   text,                           -- high | medium | low | none
  summary      text NOT NULL,
  body         jsonb NOT NULL,                 -- structured RCA (design §5.2)
  markdown     text NOT NULL,
  tokens       integer NOT NULL DEFAULT 0,
  tool_calls   integer NOT NULL DEFAULT 0,
  seconds      real NOT NULL DEFAULT 0,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS postmortems (       -- decision 0013 Q11: in shadow mode, postmortems live here
  id          bigserial PRIMARY KEY,
  incident_id bigint NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
  markdown    text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS notifications (
  id          bigserial PRIMARY KEY,
  incident_id bigint REFERENCES incidents(id) ON DELETE SET NULL,
  kind        text NOT NULL,
  priority    text NOT NULL,
  title       text NOT NULL,
  body        text NOT NULL,
  state       text NOT NULL,                   -- sent | held | suppressed | failed
  reason      text,
  action_token text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  sent_at     timestamptz
);

CREATE TABLE IF NOT EXISTS changes (           -- merges to main, Argo CD syncs: for "during-change" correlation
  id         bigserial PRIMARY KEY,
  at         timestamptz NOT NULL,
  kind       text NOT NULL,                    -- merge | argocd-sync
  ref        text NOT NULL,                    -- commit sha / app@revision
  summary    text NOT NULL,
  paths      text[] NOT NULL DEFAULT '{}',
  components text[] NOT NULL DEFAULT '{}',
  UNIQUE (kind, ref)
);
CREATE INDEX IF NOT EXISTS changes_at ON changes (at DESC);

CREATE TABLE IF NOT EXISTS docs_chunks (
  id        bigserial PRIMARY KEY,
  commit    text NOT NULL,
  path      text NOT NULL,
  line_from integer NOT NULL,
  line_to   integer NOT NULL,
  heading   text NOT NULL,
  body      text NOT NULL,
  tsv       tsvector GENERATED ALWAYS AS (to_tsvector('english', heading || ' ' || body)) STORED
);
CREATE INDEX IF NOT EXISTS docs_chunks_tsv ON docs_chunks USING gin (tsv);

CREATE TABLE IF NOT EXISTS llm_usage (
  day        date NOT NULL,
  engine     text NOT NULL,
  model      text NOT NULL,
  calls      integer NOT NULL DEFAULT 0,
  prompt_tokens integer NOT NULL DEFAULT 0,
  completion_tokens integer NOT NULL DEFAULT 0,
  PRIMARY KEY (day, engine, model)
);

CREATE TABLE IF NOT EXISTS audit (             -- append-only, hash-chained
  id         bigserial PRIMARY KEY,
  at         timestamptz NOT NULL DEFAULT now(),
  actor      text NOT NULL,
  action     text NOT NULL,
  detail     jsonb NOT NULL DEFAULT '{}',
  prev_hash  text NOT NULL,
  hash       text NOT NULL
);

CREATE TABLE IF NOT EXISTS replay_runs (
  id         bigserial PRIMARY KEY,
  started_at timestamptz NOT NULL DEFAULT now(),
  engine     text NOT NULL,
  model      text NOT NULL,
  note       text
);
CREATE TABLE IF NOT EXISTS replay_results (
  id           bigserial PRIMARY KEY,
  run_id       bigint NOT NULL REFERENCES replay_runs(id) ON DELETE CASCADE,
  gold_id      text NOT NULL,                  -- G1..G7
  incident_id  bigint REFERENCES incidents(id) ON DELETE SET NULL,
  root_cause   text,                           -- yes | partly | no
  precision    real,                           -- correct claims / claims made
  claims_total integer,
  claims_correct integer,
  unsafe       integer NOT NULL DEFAULT 0,
  secret_leak  boolean NOT NULL DEFAULT false,
  tokens       integer,
  tool_calls   integer,
  seconds      real,
  notes        text,
  UNIQUE (run_id, gold_id)
);
