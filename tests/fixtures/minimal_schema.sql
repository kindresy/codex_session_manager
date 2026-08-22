CREATE TABLE threads (
    id TEXT PRIMARY KEY,
    rollout_path TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    source TEXT NOT NULL,
    cwd TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    first_user_message TEXT NOT NULL DEFAULT ''
);

INSERT INTO threads VALUES (
    'cli-minimal',
    '/tmp/fixture/minimal.jsonl',
    1700000000,
    1700000200,
    'cli',
    '/tmp/fixture',
    0,
    'minimal question'
);
