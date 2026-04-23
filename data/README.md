# NFL GG League — Pipeline Outputs

This folder is written to by the `nfl_ggleague` local pipeline's exporter step.
Computer reads these files to power the live dashboard and daily alerts.

## Files

| File | Source (in nfl_ggleague) | What it contains |
|---|---|---|
| `leaderboard.json` | Scraped snapshot (h2hggl.com) | Current 71-player standings, win%, record, advanced stats |
| `elo.json` | `analysis/operator_elo.py` | Current Elo rating per operator + delta vs yesterday |
| `best_team.json` | `analysis/best_team_per_operator.py` | Top teams per operator by win rate |
| `edges.json` | Computed at export time | Elo-implied win prob vs market odds, +EV spots |
| `lines_history.json` | From `lines_history` DB table | Opening → current line snapshots for CLV tracking |
| `meta.json` | Exporter | Last run timestamp, pipeline version, games count |

## Update cadence

Written once per day by `run_daily.py` → `exporter.py` (see `/scripts/export_to_github.py`).

## Consumers

- **Computer dashboard:** live leaderboard + Elo rankings + best-team + edges
- **Computer daily alert:** diffs yesterday's snapshot vs today, fires notifications
