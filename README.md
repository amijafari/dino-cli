# dinosaur-game-cli

Chrome's offline T-Rex Runner as a terminal game. Single-file Python, stdlib only.

## Run

```sh
python3 dino.py
```

Requires Python 3.8+ and a terminal at least 60×15. macOS and Linux work out of the box; Windows needs `pip install windows-curses`.

## Controls

| Key | Action |
|---|---|
| `SPACE` / `↑` / `W` | Jump (also starts game) |
| `↓` / `S` | Duck (hold during jump for fast-fall) |
| `R` | Restart after game over |
| `Q` / `Esc` | Quit |

## Features

- Running dino with leg animation
- Jump and duck physics, fast-fall on hold-down
- Cacti (3 variants) and pterodactyls (after score 450) at heights that force jump or duck
- Speed ramps up over distance, capped
- Day/night cycle every 700 points (terminal colors invert)
- Hi-score persisted to `~/.dinosaur-game-cli/highscore.json`
- Terminal-bell chime every 100 points

## Test

```sh
python3 dino.py --test
```

Runs a small collision sanity check (no curses required, no game launched).

## Why Python + curses

`curses` ships with CPython on macOS/Linux, so no install step. The game is ASCII at 30 FPS — Python is more than fast enough, and a single-file script is easy to read and modify.
