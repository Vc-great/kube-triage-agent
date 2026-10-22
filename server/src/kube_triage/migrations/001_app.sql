-- Only business tables. Never alter Aegra's checkpointer/runtime tables.
CREATE TABLE IF NOT EXISTS app_conversations (
    thread_id TEXT PRIMARY KEY,
    graph_id TEXT,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    checkpoint_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS app_conversation_messages (
    id UUID PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES app_conversations(thread_id),
    source_message_id TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('human', 'assistant')),
    content JSONB NOT NULL,
    sequence BIGSERIAL UNIQUE,
    position INTEGER NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true,
    run_id TEXT,
    status TEXT NOT NULL,
    checkpoint_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(thread_id, source_message_id, content_sha256)
);
CREATE INDEX IF NOT EXISTS app_messages_current
    ON app_conversation_messages(thread_id, active, position);
CREATE TABLE IF NOT EXISTS app_evidence (
    id UUID PRIMARY KEY,
    thread_id TEXT,
    graph_id TEXT,
    run_id TEXT,
    tool_call_id TEXT,
    tool_name TEXT NOT NULL,
    namespace TEXT NOT NULL,
    resource_name TEXT,
    arguments JSONB NOT NULL,
    status TEXT NOT NULL,
    error_type TEXT,
    payload JSONB NOT NULL,
    is_truncated BOOLEAN NOT NULL,
    sha256 TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS app_evidence_thread ON app_evidence(thread_id, observed_at);
