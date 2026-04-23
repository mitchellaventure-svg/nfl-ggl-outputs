"""
Export nfl_ggleague pipeline outputs to the nfl-ggl-outputs GitHub repo.

Drop this in your local nfl_ggleague project and run it at the end of run_daily.py.

Usage:
    python scripts/export_to_github.py

Requirements:
    - `gh` CLI authenticated (gh auth login)  OR  a classic PAT in env var GH_TOKEN
    - nfl_ggleague/nfl_gg.db populated (run_daily.py already did this)
    - You've cloned the outputs repo ONCE locally:
        git clone https://github.com/mitchellaventure-svg/nfl-ggl-outputs.git ../nfl-ggl-outputs
      (adjust path if you prefer)

What it does:
    1. Reads your SQLite DB for latest Elo, best-team, games, operators.
    2. Computes +EV edges vs any stored market odds in lines_history.
    3. Writes JSON files into ../nfl-ggl-outputs/data/
    4. Commits and pushes to GitHub.
    5. Computer's daily cron reads from GitHub and alerts you on changes.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ───────── config ─────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent          # nfl_ggleague/
DB_PATH = PROJECT_ROOT / "nfl_gg.db"
OUTPUT_REPO = PROJECT_ROOT.parent / "nfl-ggl-outputs"          # sibling clone
DATA_DIR = OUTPUT_REPO / "data"

# Edge threshold in %. A 3% edge = Elo win prob exceeds implied odds by 3+ points.
EV_THRESHOLD_PCT = 3.0


# ───────── helpers ─────────
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def american_to_implied_prob(odds: int) -> float:
    """Convert American odds to implied probability (0-1)."""
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return -odds / (-odds + 100.0)


def elo_win_prob(elo_a: float, elo_b: float) -> float:
    """Standard Elo expectation for A beating B."""
    return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))


# ───────── db queries ─────────
def load_elo(conn) -> list[dict]:
    """Current Elo per operator, ordered desc."""
    rows = conn.execute(
        """
        SELECT operator, elo, games_played, wins, losses, last_updated
        FROM operator_elo
        ORDER BY elo DESC
        """
    ).fetchall()
    return [
        {
            "operator": r[0],
            "elo": round(r[1], 2),
            "games": r[2],
            "wins": r[3],
            "losses": r[4],
            "last_updated": r[5],
        }
        for r in rows
    ]


def load_best_team(conn) -> list[dict]:
    """Best-team-per-operator view."""
    rows = conn.execute(
        """
        SELECT operator, team, games, wins, win_pct
        FROM best_team_per_operator
        WHERE games >= 5
        ORDER BY operator, win_pct DESC
        """
    ).fetchall()
    return [
        {
            "operator": r[0],
            "team": r[1],
            "games": r[2],
            "wins": r[3],
            "win_pct": round(r[4], 3),
        }
        for r in rows
    ]


def load_lines_history(conn) -> list[dict]:
    """Opening → current line snapshots for CLV."""
    try:
        rows = conn.execute(
            """
            SELECT game_id, operator_home, operator_away,
                   opening_odds_home, opening_odds_away,
                   current_odds_home, current_odds_away,
                   captured_at
            FROM lines_history
            ORDER BY captured_at DESC
            LIMIT 200
            """
        ).fetchall()
        return [
            {
                "game_id": r[0],
                "home": r[1],
                "away": r[2],
                "open_home": r[3],
                "open_away": r[4],
                "cur_home": r[5],
                "cur_away": r[6],
                "captured_at": r[7],
            }
            for r in rows
        ]
    except sqlite3.OperationalError:
        return []  # table may not exist yet


def compute_edges(elo: list[dict], lines: list[dict]) -> list[dict]:
    """Find +EV spots where Elo-implied prob exceeds market implied prob by threshold."""
    elo_map = {e["operator"]: e["elo"] for e in elo}
    edges = []
    for line in lines:
        h, a = line["home"], line["away"]
        if h not in elo_map or a not in elo_map:
            continue
        cur_h, cur_a = line.get("cur_home"), line.get("cur_away")
        if cur_h is None or cur_a is None:
            continue

        elo_prob_h = elo_win_prob(elo_map[h], elo_map[a])
        mkt_prob_h = american_to_implied_prob(cur_h)
        edge_h = (elo_prob_h - mkt_prob_h) * 100

        elo_prob_a = 1 - elo_prob_h
        mkt_prob_a = american_to_implied_prob(cur_a)
        edge_a = (elo_prob_a - mkt_prob_a) * 100

        if edge_h >= EV_THRESHOLD_PCT:
            edges.append({
                "game_id": line["game_id"],
                "side": h, "opponent": a,
                "odds": cur_h,
                "elo_prob": round(elo_prob_h, 3),
                "market_prob": round(mkt_prob_h, 3),
                "edge_pct": round(edge_h, 2),
            })
        if edge_a >= EV_THRESHOLD_PCT:
            edges.append({
                "game_id": line["game_id"],
                "side": a, "opponent": h,
                "odds": cur_a,
                "elo_prob": round(elo_prob_a, 3),
                "market_prob": round(mkt_prob_a, 3),
                "edge_pct": round(edge_a, 2),
            })
    return sorted(edges, key=lambda e: -e["edge_pct"])


# ───────── git push ─────────
def git(*args: str, cwd: Path = OUTPUT_REPO) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True)


def push_to_github() -> None:
    git("add", "data/")
    # No-op if nothing changed
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=OUTPUT_REPO
    )
    if result.returncode == 0:
        print("No changes to push.")
        return
    msg = f"Daily export {utc_now_iso()}"
    git("commit", "-m", msg)
    git("push", "origin", "main")
    print(f"Pushed: {msg}")


# ───────── main ─────────
def main() -> int:
    if not DB_PATH.exists():
        print(f"DB not found at {DB_PATH}. Run run_daily.py first.", file=sys.stderr)
        return 1
    if not OUTPUT_REPO.exists():
        print(
            f"Output repo not cloned at {OUTPUT_REPO}. Clone it once:\n"
            f"  git clone https://github.com/mitchellaventure-svg/nfl-ggl-outputs.git {OUTPUT_REPO}",
            file=sys.stderr,
        )
        return 1

    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    elo = load_elo(conn)
    best_team = load_best_team(conn)
    lines = load_lines_history(conn)
    edges = compute_edges(elo, lines)

    games_count = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    operators_count = conn.execute(
        "SELECT COUNT(DISTINCT operator) FROM games"
    ).fetchone()[0]

    meta = {
        "last_run": utc_now_iso(),
        "pipeline_version": "0.1.0",
        "games_count": games_count,
        "operators_count": operators_count,
        "edges_count": len(edges),
        "ev_threshold_pct": EV_THRESHOLD_PCT,
    }

    (DATA_DIR / "elo.json").write_text(json.dumps(elo, indent=2))
    (DATA_DIR / "best_team.json").write_text(json.dumps(best_team, indent=2))
    (DATA_DIR / "lines_history.json").write_text(json.dumps(lines, indent=2))
    (DATA_DIR / "edges.json").write_text(json.dumps(edges, indent=2))
    (DATA_DIR / "meta.json").write_text(json.dumps(meta, indent=2))

    conn.close()

    push_to_github()
    print(f"Exported: {len(elo)} operators · {games_count} games · {len(edges)} edges")
    return 0


if __name__ == "__main__":
    sys.exit(main())
