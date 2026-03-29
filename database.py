#=======database.py============ 

import aiosqlite
import os
import asyncio

DB_PATH = os.getenv("DB_PATH", "forwarder.db")

# -------------------- CONNECTION --------------------

async def connect_db():
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL;")
    await conn.execute("PRAGMA foreign_keys=ON;")
    return conn

# -------------------- INIT --------------------------

async def init_db():
    async with aiosqlite.connect(DB_PATH) as conn:
        # meta
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
            );
        """)

        # WORKSPACES
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS workspaces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                owner_id INTEGER NOT NULL,
                target_channel TEXT,
                paused INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # SOURCES
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL,
                source_identifier TEXT NOT NULL
            )
        """)

        await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS ux_sources
                ON sources (workspace_id, source_identifier );
        """)

        # keywords
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL,
                keyword TEXT NOT NULL
            )
        """)

        # USERS
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # PROCESSED MESSAGES
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS processed (
                chat_id INTEGER,
                msg_id INTEGER,
                workspace_id INTEGER,
                PRIMARY KEY (chat_id, msg_id, workspace_id)
            )
        """)
        
        # 🔐 unique keyword per workspace
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_keywords
            ON keywords (workspace_id, keyword)
        """)

        await conn.commit()

#version 

async def get_db_version():
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT value FROM meta WHERE key = 'db_version'") as cursor:
            row = await cursor.fetchone()
            return int(row["value"]) if row else 0

# -------------------- USERS -------------------------

async def user_exists(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)) as cursor:
            r = await cursor.fetchone()
            return r is not None

async def create_user(user_id: int, username: str, first_name: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
            (user_id, username, first_name)
        )
        await conn.commit()

# -------------------- WORKSPACES --------------------

async def create_workspace(name: str, owner_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            "INSERT INTO workspaces (name, owner_id, target_channel) VALUES (?, ?, ?)",
            (name, owner_id, "")
        )
        wid = cursor.lastrowid
        await conn.commit()
        return wid

async def get_user_workspaces(user_id: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT id, name FROM workspaces WHERE owner_id = ? ORDER BY id DESC",
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return rows

MAX_WORKSPACES_PER_USER = 3

async def can_create_workspace(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM workspaces WHERE owner_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            count = row[0]
            return count < MAX_WORKSPACES_PER_USER

async def get_workspace(wid: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT id, name, owner_id, target_channel, paused FROM workspaces WHERE id = ?",
            (wid,)
        ) as cursor:
            row = await cursor.fetchone()
            return row

async def set_workspace_paused(wid: int, paused: bool):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "UPDATE workspaces SET paused = ? WHERE id = ?",
            (1 if paused else 0, wid)
        )
        await conn.commit()

async def delete_workspace(wid: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("DELETE FROM sources WHERE workspace_id = ?", (wid,))
        await conn.execute("DELETE FROM keywords WHERE workspace_id = ?", (wid,))
        await conn.execute("DELETE FROM workspaces WHERE id = ?", (wid,))

        await conn.execute("DELETE FROM processed WHERE workspace_id = ?", (wid,))
        
        await conn.commit()

# -------------------- SOURCES ----------------------

async def add_source(wid: int, source: str) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(
                "INSERT INTO sources (workspace_id, source_identifier) VALUES (?, ?)",
                (wid, source)
            )
            await conn.commit()
            return True
    except aiosqlite.IntegrityError:
        return False

async def get_sources(wid: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT source_identifier FROM sources WHERE workspace_id = ?",
            (wid,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [r["source_identifier"] for r in rows]

MAX_SOURCES_PER_WORKSPACE = 10

async def can_add_source(wid: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM sources WHERE workspace_id = ?",
            (wid,)
        ) as cursor:
            row = await cursor.fetchone()
            count = row[0]
            return count < MAX_SOURCES_PER_WORKSPACE

async def remove_source(wid: int, source: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "DELETE FROM sources WHERE workspace_id = ? AND source_identifier = ?",
            (wid, source)
        )
        await conn.commit()

# -------------------- KEYWORDS ---------------------

async def add_keyword(wid: int, keyword: str) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(
                "INSERT INTO keywords (workspace_id, keyword) VALUES (?, ?)",
                (wid, keyword)
            )
            await conn.commit()
            return True
    except aiosqlite.IntegrityError:
        return False

async def get_keywords(wid: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT keyword FROM keywords WHERE workspace_id = ?",
            (wid,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [r["keyword"].lower() for r in rows]

MAX_KEYWORDS_PER_WORKSPACE = 20

async def can_add_keyword(wid: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM keywords WHERE workspace_id = ?",
            (wid,)
        ) as cursor:
            row = await cursor.fetchone()
            count = row[0]
            return count < MAX_KEYWORDS_PER_WORKSPACE

async def remove_keyword(wid: int, keyword: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "DELETE FROM keywords WHERE workspace_id = ? AND keyword = ?",
            (wid, keyword)
        )
        await conn.commit()

# -------------------- FORWARDER --------------------

async def is_processed(chat_id: int, msg_id: int, wid: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT 1 FROM processed WHERE chat_id = ? AND msg_id = ? AND workspace_id = ?",
            (chat_id, msg_id, wid)
        ) as cursor:
            r = await cursor.fetchone()
            return r is not None

async def mark_processed(chat_id: int, msg_id: int, wid: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO processed (chat_id, msg_id, workspace_id) VALUES (?, ?, ?)",
            (chat_id, msg_id, wid)
        )
        await conn.commit()

async def get_workspaces_by_source(source_identifier: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("""
            SELECT w.id, w.name, w.target_channel, w.paused
            FROM workspaces w
            JOIN sources s ON w.id = s.workspace_id
            WHERE s.source_identifier = ?
        """, (source_identifier,)) as cursor:
            rows = await cursor.fetchall()
            return rows

async def set_target_channel(wid: int, target: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "UPDATE workspaces SET target_channel = ? WHERE id = ?",
            (target, wid)
        )
        await conn.commit()

async def remove_target(wid: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "UPDATE workspaces SET target_channel = NULL WHERE id = ?",
            (wid,)
        )
        await conn.commit()
