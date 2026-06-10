"""SQLite persistence for completed hand reviews."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "poker_workbench.db"


def _connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS hand_reviews (
            hand_id TEXT PRIMARY KEY,
            completed_at TEXT NOT NULL,
            hero_seat INTEGER NOT NULL,
            hero_cards TEXT NOT NULL,
            player_count INTEGER NOT NULL,
            street TEXT NOT NULL,
            pot INTEGER NOT NULL,
            hero_result INTEGER NOT NULL,
            action_count INTEGER NOT NULL,
            data_json TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def save_review(hand_id: str, review: dict, db_path: Path = DEFAULT_DB_PATH) -> None:
    state = review["final_hand"]["state"]
    hero_seat = review["final_hand"]["hero_seat"]
    hero = next(player for player in state["players"] if player["seat"] == hero_seat)
    pot = sum(player["total_commitment"] for player in state["players"])
    hero_result = hero["stack"] - hero["starting_stack"]
    with closing(_connect(db_path)) as connection:
        connection.execute(
            """
            INSERT INTO hand_reviews (
                hand_id, completed_at, hero_seat, hero_cards, player_count,
                street, pot, hero_result, action_count, data_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(hand_id) DO UPDATE SET
                completed_at=excluded.completed_at,
                hero_cards=excluded.hero_cards,
                street=excluded.street,
                pot=excluded.pot,
                hero_result=excluded.hero_result,
                action_count=excluded.action_count,
                data_json=excluded.data_json
            """,
            (
                hand_id,
                datetime.now(timezone.utc).isoformat(),
                hero_seat,
                " ".join(hero.get("hole_cards") or []),
                len(state["players"]),
                state["street"],
                pot,
                hero_result,
                len(state["actions"]),
                json.dumps(review, ensure_ascii=False),
            ),
        )
        connection.commit()


def list_reviews(query: str = "", db_path: Path = DEFAULT_DB_PATH) -> list[dict]:
    sql = """
        SELECT hand_id, completed_at, hero_seat, hero_cards, player_count,
               street, pot, hero_result, action_count
        FROM hand_reviews
    """
    parameters: list[object] = []
    if query:
        sql += " WHERE hand_id LIKE ? OR hero_cards LIKE ?"
        match = f"%{query}%"
        parameters.extend([match, match])
    sql += " ORDER BY completed_at DESC"
    with closing(_connect(db_path)) as connection:
        return [dict(row) for row in connection.execute(sql, parameters).fetchall()]


def get_review(hand_id: str, db_path: Path = DEFAULT_DB_PATH) -> dict:
    with closing(_connect(db_path)) as connection:
        row = connection.execute(
            "SELECT data_json FROM hand_reviews WHERE hand_id = ?", (hand_id,)
        ).fetchone()
    if row is None:
        raise ValueError("复盘记录不存在")
    return json.loads(row["data_json"])
