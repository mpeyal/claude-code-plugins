# claude-pinger

Keeps Claude's 5-hour usage windows lined up with my day. A Windows scheduled task checks every 10 minutes, and when no window is open during active hours it sends `hello` on Haiku, so a fresh window is already running and resets earlier.

With a 10:00 start, a 07:00 ping opens 07:00–12:00: two hours of full limit before work, then a fresh window at lunch. When I'm already working, my own messages keep a window open and it does nothing.

It also reads Claude Code's local logs (`~/.claude/projects`) to report how I use each window. Not a plugin: it's a plain Python script run by Task Scheduler, so it works with Claude Code closed.

## Set up on a new PC

Needs Python 3.9+ and Claude Code, signed in (`claude`, then `/login`).

```
git clone git@github.com:mpeyal/claude-code-plugins.git
cd claude-code-plugins\tools\claude-pinger
python claude_pinger.py ping
python claude_pinger.py install
```

`ping` checks that the CLI is signed in (the log should say `PING ok`). `install` copies the script to `~/.claude-pinger\`, writes `config.json` there and registers two tasks:

| Task | When | What |
|---|---|---|
| `ClaudeHelloPinger` | every 10 min | pings only if no window is open, 07:00–23:00 |
| `ClaudeHelloPinger-Wake` | daily at 07:00 | wakes the PC from sleep for the first ping |

Both run only while I'm logged in to Windows: after a restart they resume at login, and nothing runs while the PC is shut down.

## Commands

`python %USERPROFILE%\.claude-pinger\claude_pinger.py <command>`

| Command | What it does |
|---|---|
| `status` | current window, reset time, next ping |
| `report [--days 14] [--start 10:00]` | windows, tokens by model, hours worked, best first-ping time |
| `ping` | send a ping now |
| `log` | recent pings and errors |
| `config` | settings and where they live |
| `install` / `uninstall` | add or remove the scheduled tasks |

## Settings

`~/.claude-pinger/config.json`. Re-run `install` after changing times or days.

| Key | Default | Meaning |
|---|---|---|
| `active_start` | `07:00` | first ping, about 3h before work starts |
| `active_end` | `23:00` | no pings from this time |
| `active_days` | every day | `["Mon", ...]` |
| `model` / `ping_message` | `haiku` / `hello` | what the ping sends |
| `check_every_minutes` | `10` | how often the task checks |
| `wake_pc_for_first_ping` | `true` | wake from sleep at `active_start` |

## Limits

- Windows are rebuilt from local logs, assumed to start on the hour. Use on claude.ai, the phone app or another PC shares the limit but isn't seen here.
- It moves resets earlier; it doesn't raise the weekly limit.
- If a ping fails with `OAuth session expired`, sign in again with `claude` → `/login`.
