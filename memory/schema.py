"""
Database schema for Sigil memory engine.
Single SQLite file with FTS5 + sqlite-vec for hybrid retrieval.
"""

SCHEMA_VERSION = 4

# ── Migrations ──────────────────────────────────────────────────────
# Each migration upgrades from version N to N+1.
# Applied in order when the DB is behind SCHEMA_VERSION.
MIGRATIONS = {
    # v3 -> v4: Add working_fts, working memory triggers
    4: [
        """CREATE VIRTUAL TABLE IF NOT EXISTS working_fts USING fts5(
               content, content='working', content_rowid='rowid')""",
        """CREATE TRIGGER IF NOT EXISTS working_ai AFTER INSERT ON working BEGIN
               INSERT INTO working_fts(rowid, content) VALUES (new.rowid, new.content);
           END""",
        """CREATE TRIGGER IF NOT EXISTS working_ad AFTER DELETE ON working BEGIN
               INSERT INTO working_fts(working_fts, rowid, content)
               VALUES ('delete', old.rowid, old.content);
           END""",
        """CREATE TRIGGER IF NOT EXISTS working_au AFTER UPDATE ON working BEGIN
               INSERT INTO working_fts(working_fts, rowid, content)
               VALUES ('delete', old.rowid, old.content);
               INSERT INTO working_fts(rowid, content) VALUES (new.rowid, new.content);
           END""",
    ],
}


def migrate(conn, current_version: int) -> int:
    """Apply pending migrations. Returns new version number."""
    for target_version in sorted(MIGRATIONS.keys()):
        if current_version < target_version:
            for sql in MIGRATIONS[target_version]:
                try:
                    conn.execute(sql)
                except Exception:
                    pass  # IF NOT EXISTS handles most cases
            current_version = target_version
    conn.commit()
    return current_version

SCHEMA_SQL = """
-- Sigil schema v3

-- Semantic memory: facts, preferences, knowledge
CREATE TABLE IF NOT EXISTS semantic (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    importance REAL DEFAULT 0.5,
    source TEXT DEFAULT 'user',
    agent_id TEXT DEFAULT 'default',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    access_count INTEGER DEFAULT 0,
    last_accessed TEXT,
    decay_class TEXT DEFAULT 'standard',
    metadata TEXT DEFAULT '{}'
);

-- Episodic memory: events, decisions, outcomes
CREATE TABLE IF NOT EXISTS episodic (
    id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    detail TEXT,
    outcome TEXT,
    emotion TEXT,
    importance REAL DEFAULT 0.5,
    source TEXT DEFAULT 'conversation',
    agent_id TEXT DEFAULT 'default',
    session_id TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    tags TEXT DEFAULT '[]',
    metadata TEXT DEFAULT '{}'
);

-- Procedural memory: workflows that self-improve
CREATE TABLE IF NOT EXISTS procedural (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    steps TEXT NOT NULL,  -- JSON array of steps
    version INTEGER DEFAULT 1,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    last_outcome TEXT,
    last_failure_context TEXT,
    agent_id TEXT DEFAULT 'default',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    metadata TEXT DEFAULT '{}'
);

-- Working memory: hot context, TTL-evicted
CREATE TABLE IF NOT EXISTS working (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    importance REAL DEFAULT 0.5,
    session_id TEXT,
    agent_id TEXT DEFAULT 'default',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    expires_at TEXT,
    metadata TEXT DEFAULT '{}'
);

-- Vector embeddings (used by sqlite-vec or manual cosine sim)
CREATE TABLE IF NOT EXISTS vectors (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    memory_table TEXT NOT NULL,  -- 'semantic', 'episodic', 'procedural'
    embedding BLOB NOT NULL,
    model TEXT DEFAULT 'bge-small-en-v1.5',
    dimensions INTEGER DEFAULT 384,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);

-- Knowledge graph: temporal triples
CREATE TABLE IF NOT EXISTS triples (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    source TEXT DEFAULT 'extraction',
    agent_id TEXT DEFAULT 'default',
    valid_from TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    valid_until TEXT,  -- NULL = still valid
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    metadata TEXT DEFAULT '{}'
);

-- Event bus for multi-agent sync
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    memory_id TEXT,
    memory_table TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    synced_by TEXT DEFAULT '[]'  -- JSON array of agent_ids that have consumed this
);

-- Projects and tasks
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'active',
    milestone TEXT,
    deadline TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'pending',
    priority TEXT DEFAULT 'medium',
    assignee TEXT,
    depends_on TEXT DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    completed_at TEXT,
    metadata TEXT DEFAULT '{}',
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS sigil_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- FTS5 indexes for fast text search
CREATE VIRTUAL TABLE IF NOT EXISTS semantic_fts USING fts5(
    content, category, source,
    content='semantic', content_rowid='rowid'
);

CREATE VIRTUAL TABLE IF NOT EXISTS episodic_fts USING fts5(
    summary, detail, outcome, tags,
    content='episodic', content_rowid='rowid'
);

CREATE VIRTUAL TABLE IF NOT EXISTS procedural_fts USING fts5(
    name, steps,
    content='procedural', content_rowid='rowid'
);

CREATE VIRTUAL TABLE IF NOT EXISTS triples_fts USING fts5(
    subject, predicate, object,
    content='triples', content_rowid='rowid'
);

-- FTS5 for working memory
CREATE VIRTUAL TABLE IF NOT EXISTS working_fts USING fts5(
    content,
    content='working', content_rowid='rowid'
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_semantic_category ON semantic(category);
CREATE INDEX IF NOT EXISTS idx_semantic_agent ON semantic(agent_id);
CREATE INDEX IF NOT EXISTS idx_semantic_importance ON semantic(importance DESC);
CREATE INDEX IF NOT EXISTS idx_episodic_agent ON episodic(agent_id);
CREATE INDEX IF NOT EXISTS idx_episodic_created ON episodic(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_working_session ON working(session_id);
CREATE INDEX IF NOT EXISTS idx_working_expires ON working(expires_at);
CREATE INDEX IF NOT EXISTS idx_vectors_memory ON vectors(memory_id, memory_table);
CREATE INDEX IF NOT EXISTS idx_triples_subject ON triples(subject);
CREATE INDEX IF NOT EXISTS idx_triples_object ON triples(object);
CREATE INDEX IF NOT EXISTS idx_triples_valid ON triples(valid_from, valid_until);
CREATE INDEX IF NOT EXISTS idx_events_agent ON events(agent_id);
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee);

-- FTS triggers for working memory
CREATE TRIGGER IF NOT EXISTS working_ai AFTER INSERT ON working BEGIN
    INSERT INTO working_fts(rowid, content)
    VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS working_ad AFTER DELETE ON working BEGIN
    INSERT INTO working_fts(working_fts, rowid, content)
    VALUES ('delete', old.rowid, old.content);
END;

CREATE TRIGGER IF NOT EXISTS working_au AFTER UPDATE ON working BEGIN
    INSERT INTO working_fts(working_fts, rowid, content)
    VALUES ('delete', old.rowid, old.content);
    INSERT INTO working_fts(rowid, content)
    VALUES (new.rowid, new.content);
END;

-- FTS triggers to keep indexes in sync
CREATE TRIGGER IF NOT EXISTS semantic_ai AFTER INSERT ON semantic BEGIN
    INSERT INTO semantic_fts(rowid, content, category, source)
    VALUES (new.rowid, new.content, new.category, new.source);
END;

CREATE TRIGGER IF NOT EXISTS semantic_ad AFTER DELETE ON semantic BEGIN
    INSERT INTO semantic_fts(semantic_fts, rowid, content, category, source)
    VALUES ('delete', old.rowid, old.content, old.category, old.source);
END;

CREATE TRIGGER IF NOT EXISTS semantic_au AFTER UPDATE ON semantic BEGIN
    INSERT INTO semantic_fts(semantic_fts, rowid, content, category, source)
    VALUES ('delete', old.rowid, old.content, old.category, old.source);
    INSERT INTO semantic_fts(rowid, content, category, source)
    VALUES (new.rowid, new.content, new.category, new.source);
END;

CREATE TRIGGER IF NOT EXISTS episodic_ai AFTER INSERT ON episodic BEGIN
    INSERT INTO episodic_fts(rowid, summary, detail, outcome, tags)
    VALUES (new.rowid, new.summary, new.detail, new.outcome, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS episodic_ad AFTER DELETE ON episodic BEGIN
    INSERT INTO episodic_fts(episodic_fts, rowid, summary, detail, outcome, tags)
    VALUES ('delete', old.rowid, old.summary, old.detail, old.outcome, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS episodic_au AFTER UPDATE ON episodic BEGIN
    INSERT INTO episodic_fts(episodic_fts, rowid, summary, detail, outcome, tags)
    VALUES ('delete', old.rowid, old.summary, old.detail, old.outcome, old.tags);
    INSERT INTO episodic_fts(rowid, summary, detail, outcome, tags)
    VALUES (new.rowid, new.summary, new.detail, new.outcome, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS procedural_ai AFTER INSERT ON procedural BEGIN
    INSERT INTO procedural_fts(rowid, name, steps)
    VALUES (new.rowid, new.name, new.steps);
END;

CREATE TRIGGER IF NOT EXISTS procedural_ad AFTER DELETE ON procedural BEGIN
    INSERT INTO procedural_fts(procedural_fts, rowid, name, steps)
    VALUES ('delete', old.rowid, old.name, old.steps);
END;

CREATE TRIGGER IF NOT EXISTS triples_ai AFTER INSERT ON triples BEGIN
    INSERT INTO triples_fts(rowid, subject, predicate, object)
    VALUES (new.rowid, new.subject, new.predicate, new.object);
END;

CREATE TRIGGER IF NOT EXISTS triples_ad AFTER DELETE ON triples BEGIN
    INSERT INTO triples_fts(triples_fts, rowid, subject, predicate, object)
    VALUES ('delete', old.rowid, old.subject, old.predicate, old.object);
END;
"""

# FTS5 triggers for update on procedural and triples
SCHEMA_SQL_EXTRA = """
CREATE TRIGGER IF NOT EXISTS procedural_au AFTER UPDATE ON procedural BEGIN
    INSERT INTO procedural_fts(procedural_fts, rowid, name, steps)
    VALUES ('delete', old.rowid, old.name, old.steps);
    INSERT INTO procedural_fts(rowid, name, steps)
    VALUES (new.rowid, new.name, new.steps);
END;

CREATE TRIGGER IF NOT EXISTS triples_au AFTER UPDATE ON triples BEGIN
    INSERT INTO triples_fts(triples_fts, rowid, subject, predicate, object)
    VALUES ('delete', old.rowid, old.subject, old.predicate, old.object);
    INSERT INTO triples_fts(rowid, subject, predicate, object)
    VALUES (new.rowid, new.subject, new.predicate, new.object);
END;
"""
