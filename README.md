# nfl-ggl-outputs

Bridge between the **local `nfl_ggleague` VS Code project** and **Perplexity Computer**.

Your local pipeline (`run_daily.py`) generates Elo ratings, best-team-per-operator splits, and edge calculations. This repo holds the daily JSON outputs so Computer can:

- Power a **live dashboard** showing your model's current state
- Run a **daily alert** that watches for Elo shifts, best-team changes, +EV spots, and CLV line moves

## Setup (one-time, on your PC)

```powershell
# 1. Clone this repo as a SIBLING of nfl_ggleague
cd <folder_containing_nfl_ggleague>
git clone https://github.com/mitchellaventure-svg/nfl-ggl-outputs.git

# 2. Copy the exporter into your project
copy nfl-ggl-outputs\scripts\export_to_github.py nfl_ggleague\scripts\

# 3. Make sure `gh` CLI is authenticated
gh auth status   # if not: gh auth login
```

## Hook into your daily run

Add one line at the end of `nfl_ggleague/run_daily.py`:

```python
# existing pipeline steps...
subprocess.run([sys.executable, "scripts/export_to_github.py"], check=True)
```

Or run it manually after `run_daily.py`:

```powershell
cd nfl_ggleague
python scripts\export_to_github.py
```

## What gets pushed

| File | What |
|---|---|
| `data/elo.json` | Operator Elo ratings, games, W-L |
| `data/best_team.json` | Top teams per operator (min 5 games) |
| `data/lines_history.json` | Opening vs current odds (if your DB has `lines_history` populated) |
| `data/edges.json` | +EV spots where Elo-implied prob exceeds market by ≥3% |
| `data/leaderboard.json` | Raw scraped snapshot from h2hggl.com |
| `data/meta.json` | Timestamp, games count, operator count |

## What Computer does with it

- **Dashboard:** reads directly from this repo's raw.githubusercontent URLs, refreshes on page load.
- **Daily cron (14:00 UTC = 9am ET):** fetches latest, diffs vs yesterday, sends a notification if any of:
  - Operator Elo ±20 points (big move)
  - Top-10 Elo rankings changed
  - +EV spot ≥3% edge appears
  - Best-team changes for a top-10 operator
  - Material CLV move (≥10 cents) on a tracked game

## Tweaking thresholds

Edit constants at the top of `scripts/export_to_github.py`:

```python
EV_THRESHOLD_PCT = 3.0   # minimum edge % to flag
```

Or in the Computer side: tell Computer "raise the EV alert threshold to 5%" and it'll update the cron.
