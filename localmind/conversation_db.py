"""Small transactional journal for chat text and deliberately uploaded context.

Short connections use DELETE journaling: a relocated data tree never depends on
an open WAL sidecar. The caller serializes access and coordinates storage moves.
There are no paths, commands, permissions or model-generated SQL in this format.
"""
from contextlib import contextmanager
import sqlite3

from . import paths


SCHEMA_VERSION = 1


class ConversationDatabase:
    def __init__(self, path=None):
        self.path = paths.ordinary_tree(path) if path is not None else None
        self._memory = None

    @contextmanager
    def transaction(self, *, write=False):
        if self.path is not None:
            paths.ordinary_tree(self.path)
            paths.ordinary_tree(self.path.with_name(self.path.name + '-journal'))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=10)
        else:
            if self._memory is None:
                self._memory = sqlite3.connect(':memory:', timeout=10, check_same_thread=False)
            connection = self._memory
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA synchronous=FULL')
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ValueError('История создана более новой версией LocalMind. Обновите приложение.')
            connection.execute('BEGIN IMMEDIATE' if write or version == 0 else 'BEGIN')
            # Another process may have initialized the schema while BEGIN
            # waited for its writer. Inspect again under the transaction lock.
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ValueError('История создана более новой версией LocalMind. Обновите приложение.')
            if version == 0:
                connection.execute('''CREATE TABLE conversations (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT,
                    updated_at TEXT, draft TEXT NOT NULL DEFAULT '',
                    context TEXT NOT NULL DEFAULT '{}', attachments TEXT NOT NULL DEFAULT '[]',
                    topic TEXT NOT NULL DEFAULT '')''')
                connection.execute('''CREATE TABLE messages (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL
                        REFERENCES conversations(id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL, role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                    content TEXT NOT NULL, created_at TEXT,
                    UNIQUE(conversation_id, sequence))''')
                connection.execute('CREATE INDEX message_conversation ON messages(conversation_id,sequence)')
                connection.execute('''CREATE TABLE imports (
                    digest TEXT PRIMARY KEY, conversation_ids TEXT NOT NULL,
                    payload_hash TEXT NOT NULL)''')
                connection.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            if self.path is not None:
                connection.close()
