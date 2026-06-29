import json
import uuid
from datetime import datetime

import aiosqlite

from config import DB_PATH

CREATE_GAMES = """
CREATE TABLE IF NOT EXISTS games (
    id TEXT PRIMARY KEY,
    admin_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL
);
"""

CREATE_PLAYERS = """
CREATE TABLE IF NOT EXISTS players (
    game_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT,
    card TEXT NOT NULL,
    marked TEXT NOT NULL,
    won INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (game_id, user_id)
);
"""

CREATE_CALLED = """
CREATE TABLE IF NOT EXISTS called_numbers (
    game_id TEXT NOT NULL,
    number INTEGER NOT NULL,
    letter TEXT NOT NULL,
    PRIMARY KEY (game_id, number)
);
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(CREATE_GAMES)
        await conn.execute(CREATE_PLAYERS)
        await conn.execute(CREATE_CALLED)
        await conn.commit()


def new_game_id() -> str:
    return uuid.uuid4().hex[:8]


async def create_game(admin_id: int) -> str:
    game_id = new_game_id()
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO games (id, admin_id, status, created_at) VALUES (?, ?, 'active', ?)",
            (game_id, admin_id, datetime.utcnow().isoformat()),
        )
        await conn.commit()
    return game_id


async def get_game(game_id: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_active_game_by_admin(admin_id: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT * FROM games WHERE admin_id = ? AND status = 'active' "
            "ORDER BY created_at DESC LIMIT 1",
            (admin_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def set_game_status(game_id: str, status: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("UPDATE games SET status = ? WHERE id = ?", (status, game_id))
        await conn.commit()


async def add_player(game_id: str, user_id: int, username: str, card: list, marked: list):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO players (game_id, user_id, username, card, marked, won) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            (game_id, user_id, username or "", json.dumps(card), json.dumps(marked)),
        )
        await conn.commit()


async def get_player(game_id: str, user_id: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT * FROM players WHERE game_id = ? AND user_id = ?", (game_id, user_id)
        )
        row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["card"] = json.loads(d["card"])
        d["marked"] = json.loads(d["marked"])
        return d


async def get_players(game_id: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT * FROM players WHERE game_id = ?", (game_id,))
        rows = await cur.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["card"] = json.loads(d["card"])
            d["marked"] = json.loads(d["marked"])
            result.append(d)
        return result


async def update_player_marked(game_id: str, user_id: int, marked: list):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "UPDATE players SET marked = ? WHERE game_id = ? AND user_id = ?",
            (json.dumps(marked), game_id, user_id),
        )
        await conn.commit()


async def set_player_won(game_id: str, user_id: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "UPDATE players SET won = 1 WHERE game_id = ? AND user_id = ?",
            (game_id, user_id),
        )
        await conn.commit()


async def add_called_number(game_id: str, number: int, letter: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO called_numbers (game_id, number, letter) VALUES (?, ?, ?)",
            (game_id, number, letter),
        )
        await conn.commit()


async def get_called_numbers(game_id: str) -> set:
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            "SELECT number FROM called_numbers WHERE game_id = ?", (game_id,)
        )
        rows = await cur.fetchall()
        return {r[0] for r in rows}


async def is_number_called(game_id: str, number: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            "SELECT 1 FROM called_numbers WHERE game_id = ? AND number = ?",
            (game_id, number),
        )
        row = await cur.fetchone()
        return row is not None
