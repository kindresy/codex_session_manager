CREATE TABLE threads (
    id TEXT PRIMARY KEY,
    rollout_path TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    source TEXT NOT NULL,
    cwd TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    first_user_message TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER,
    recency_at_ms INTEGER,
    recency_at INTEGER NOT NULL DEFAULT 0
);

INSERT INTO threads VALUES
    ('cli-current', '/tmp/fixture/current.jsonl', 1, 2, 'cli', '/tmp/fixture', 0,
     'current question', 1700000000000, 1700000300000, 0),
    ('cli-archived', '/tmp/fixture/archived.jsonl', 1, 2, 'cli', '/tmp/fixture', 1,
     'archived question', 1700000100000, 1700000400000, 0),
    ('vscode-current', '/tmp/fixture/vscode.jsonl', 1, 2, 'vscode', '/tmp/fixture', 0,
     'editor question', 1700000200000, 1700000500000, 0),
    ('subagent-current', '/tmp/fixture/subagent.jsonl', 1, 2,
     '{"subagent":{"thread_spawn":{}}}', '/tmp/fixture', 0,
     'worker question', 1700000300000, 1700000600000, 0);
