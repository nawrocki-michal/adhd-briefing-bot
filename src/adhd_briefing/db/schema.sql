-- ADHD Briefing — znormalizowany schemat SQLite
-- Pokrywa Fazę C (Capture) oraz przyszłe fazy R (Retrieval) i A (Action).
-- Idempotentny: bezpieczny do wielokrotnego uruchomienia (IF NOT EXISTS).

-- Użytkownicy
CREATE TABLE IF NOT EXISTS users (
    chat_id       TEXT PRIMARY KEY,
    topics        TEXT,                       -- JSON list
    sources       TEXT,                       -- JSON list
    briefing_time TEXT,                       -- "07:30"
    timezone      TEXT,                       -- "Europe/Warsaw"
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Historia briefingów (faza R — kalendarz)
CREATE TABLE IF NOT EXISTS briefings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    TEXT REFERENCES users(chat_id),
    date       DATE NOT NULL,
    status     TEXT DEFAULT 'sent',           -- sent | read | skipped
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Artykuły (faza R — retrieval, faza A — akcje)
CREATE TABLE IF NOT EXISTS articles (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    briefing_id       INTEGER REFERENCES briefings(id),
    url               TEXT NOT NULL,
    title             TEXT,
    summary           TEXT,                    -- TL;DR bullets
    main_outcome      TEXT,                    -- główny komunikat
    action_suggestion TEXT,                    -- co możesz z tym zrobić
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Widziane artykuły (deduplication per użytkownik)
CREATE TABLE IF NOT EXISTS seen_articles (
    chat_id TEXT REFERENCES users(chat_id),
    url     TEXT NOT NULL,
    seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, url)
);

-- Inbox jednorazowy — artykuły wklejone przez użytkownika, do dostarczenia
-- w najbliższym briefingu (one-shot: czyszczone po dostawie). Model „streść mi to".
CREATE TABLE IF NOT EXISTS pending_articles (
    chat_id  TEXT REFERENCES users(chat_id),
    url      TEXT NOT NULL,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, url)
);

-- Akcje użytkownika (faza A — gamifikacja)
CREATE TABLE IF NOT EXISTS actions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id   INTEGER REFERENCES articles(id),
    chat_id      TEXT REFERENCES users(chat_id),
    completed    BOOLEAN DEFAULT FALSE,
    completed_at DATETIME
);

-- Idempotencja schedulera — jeden briefing per użytkownik per dzień
CREATE TABLE IF NOT EXISTS briefing_runs (
    chat_id  TEXT REFERENCES users(chat_id),
    run_date DATE NOT NULL,
    status   TEXT,                             -- running | completed | failed
    PRIMARY KEY (chat_id, run_date)
);
