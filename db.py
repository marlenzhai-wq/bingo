"""
Bingo Bot — дерекқор қабаты (aiosqlite).
Барлық DB операциялары осы модульде орталықтандырылған.
"""
import json
import uuid
from datetime import datetime

import aiosqlite

from config import DB_PATH, MAIN_ADMIN_ID

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

CREATE_ADMINS = """
CREATE TABLE IF NOT EXISTS admins (
    user_id  INTEGER PRIMARY KEY,
    is_main  INTEGER NOT NULL DEFAULT 0
);
"""

CREATE_GAMES = """
CREATE TABLE IF NOT EXISTS games (
    id              TEXT    PRIMARY KEY,
    admin_id        INTEGER NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'waiting',
    players_msg_id  INTEGER,
    created_at      TEXT    NOT NULL
);
"""

CREATE_PLAYERS = """
CREATE TABLE IF NOT EXISTS players (
    game_id    TEXT    NOT NULL,
    user_id    INTEGER NOT NULL,
    username   TEXT,
    first_name TEXT,
    last_name  TEXT,
    card       TEXT    NOT NULL,
    marked     TEXT    NOT NULL,
    won        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (game_id, user_id)
);
"""

CREATE_CALLED = """
CREATE TABLE IF NOT EXISTS called_numbers (
    game_id  TEXT    NOT NULL,
    number   INTEGER NOT NULL,
    letter   TEXT    NOT NULL,
    PRIMARY KEY (game_id, number)
);
"""

# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

async def init_db():
    async with aiosqlite.connect(DB_PATH) as conn:
        # Кестелерді жасаймыз (бұрын жасалса — өзгертпейді)
        await conn.execute(CREATE_ADMINS)
        await conn.execute(CREATE_GAMES)
        await conn.execute(CREATE_PLAYERS)
        await conn.execute(CREATE_CALLED)

        # ── Автоматты миграция ──────────────────────────────────────────────
        # Ескі DB-де жаңа бағандар болмауы мүмкін — қауіпсіз қосамыз.
        migrations = [
            "ALTER TABLE games ADD COLUMN players_msg_id INTEGER",
            "ALTER TABLE games ADD COLUMN status TEXT NOT NULL DEFAULT 'waiting'",
            "ALTER TABLE admins ADD COLUMN is_main INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE players ADD COLUMN first_name TEXT",
            "ALTER TABLE players ADD COLUMN last_name TEXT",
        ]
        for sql in migrations:
            try:
                await conn.execute(sql)
            except Exception:
                pass  # Баған бұрыннан бар — елемейміз

        # Бастапқы басты админді бір рет қосамыз
        await conn.execute(
            "INSERT OR IGNORE INTO admins (user_id, is_main) VALUES (?, 1)",
            (MAIN_ADMIN_ID,),
        )
        await conn.commit()

# ---------------------------------------------------------------------------
# Админ функциялары
# ---------------------------------------------------------------------------

async def is_admin(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            "SELECT 1 FROM admins WHERE user_id = ?", (user_id,)
        )
        return await cur.fetchone() is not None


async def is_main_admin(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            "SELECT 1 FROM admins WHERE user_id = ? AND is_main = 1", (user_id,)
        )
        return await cur.fetchone() is not None


async def add_admin(user_id: int) -> bool:
    """True — жаңадан қосылды, False — бұрыннан бар."""
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            "SELECT 1 FROM admins WHERE user_id = ?", (user_id,)
        )
        if await cur.fetchone():
            return False
        await conn.execute(
            "INSERT INTO admins (user_id, is_main) VALUES (?, 0)", (user_id,)
        )
        await conn.commit()
        return True


async def remove_admin(user_id: int) -> bool:
    """True — өшірілді, False — бұрыннан жоқ немесе басты админ."""
    if await is_main_admin(user_id):
        return False
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            "DELETE FROM admins WHERE user_id = ? AND is_main = 0", (user_id,)
        )
        await conn.commit()
        return cur.rowcount > 0


async def get_all_admins() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT user_id, is_main FROM admins ORDER BY is_main DESC")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

# ---------------------------------------------------------------------------
# Ойын функциялары
# ---------------------------------------------------------------------------

def _new_game_id() -> str:
    return uuid.uuid4().hex[:8]


async def create_game(admin_id: int) -> str:
    game_id = _new_game_id()
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO games (id, admin_id, status, created_at) VALUES (?, ?, 'waiting', ?)",
            (game_id, admin_id, datetime.utcnow().isoformat()),
        )
        await conn.commit()
    return game_id


async def get_game(game_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT * FROM games WHERE id = ?", (game_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_nonfin_game_by_admin(admin_id: int) -> dict | None:
    """waiting немесе started (finished емес) соңғы ойынды қайтарады."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT * FROM games WHERE admin_id = ? AND status != 'finished' "
            "ORDER BY created_at DESC LIMIT 1",
            (admin_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def set_game_status(game_id: str, status: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "UPDATE games SET status = ? WHERE id = ?", (status, game_id)
        )
        await conn.commit()


async def save_players_msg_id(game_id: str, msg_id: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "UPDATE games SET players_msg_id = ? WHERE id = ?", (msg_id, game_id)
        )
        await conn.commit()

# ---------------------------------------------------------------------------
# Ойыншы функциялары
# ---------------------------------------------------------------------------

async def add_player(game_id: str, user_id: int, username: str,
                     first_name: str, last_name: str,
                     card: list, marked: list):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO players "
            "(game_id, user_id, username, first_name, last_name, card, marked, won) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            (game_id, user_id, username or "",
             first_name or "", last_name or "",
             json.dumps(card), json.dumps(marked)),
        )
        await conn.commit()


async def get_player(game_id: str, user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT * FROM players WHERE game_id = ? AND user_id = ?",
            (game_id, user_id),
        )
        row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["card"] = json.loads(d["card"])
        d["marked"] = json.loads(d["marked"])
        return d


async def get_player_active_game(user_id: int):
    """Ойыншының белсенді (finished емес) ойынын және оның картасын қайтарады."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT p.*, g.id AS game_id FROM players p "
            "JOIN games g ON g.id = p.game_id "
            "WHERE p.user_id = ? AND g.status != 'finished' "
            "ORDER BY g.created_at DESC LIMIT 1",
            (user_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["card"]   = json.loads(d["card"])
        d["marked"] = json.loads(d["marked"])
        return d["game_id"], d


async def get_players(game_id: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT * FROM players WHERE game_id = ?", (game_id,)
        )
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

# ---------------------------------------------------------------------------
# Шыққан сандар
# ---------------------------------------------------------------------------

async def add_called_number(game_id: str, number: int, letter: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO called_numbers (game_id, number, letter) "
            "VALUES (?, ?, ?)",
            (game_id, number, letter),
        )
        await conn.commit()


async def get_called_numbers(game_id: str) -> set[int]:
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
        return await cur.fetchone() is not None
