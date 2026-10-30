#!/usr/bin/env python3
"""
claude_pinger.py - analyse your Claude Code usage windows and keep them aligned
with a tiny Haiku "hello" ping.

Claude subscription limits reset in 5-hour windows that start with your first
message. This script reads Claude Code's local transcripts (~/.claude/projects),
rebuilds those windows, reports how you use them and, when run every few
minutes by Task Scheduler, sends "hello" on Haiku whenever no window is open
during your active hours, so a fresh window is always already ticking.

Commands:
  status               current window and when it resets (default)
  report [--days N]    usage analysis + recommended first-ping time
  tick                 ping only if needed (what the scheduled task runs)
  ping                 send a ping right now
  install / uninstall  add / remove the Windows scheduled tasks
  log                  recent pinger activity
  config               show the config file and its values

Note: windows are estimated from local logs. Usage on claude.ai, the mobile
app or another computer shares the same limit but isn't visible here.
"""
import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

APP_DIR = Path.home() / ".claude-pinger"
PING_DIR = APP_DIR / "ping-workdir"      # pings run here so they can be told apart
CONFIG_FILE = APP_DIR / "config.json"
STATE_FILE = APP_DIR / "state.json"
LOG_FILE = APP_DIR / "pinger.log"
TASK_NAME = "ClaudeHelloPinger"
WAKE_TASK_NAME = "ClaudeHelloPinger-Wake"

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

DEFAULT_CONFIG = {
    "ping_message": "hello",
    "model": "haiku",
    "active_start": "07:00",        # first ping of the day (~3h before you start work)
    "active_end": "23:00",          # no pings from this time on
    "active_days": DAYS,
    "check_every_minutes": 10,
    "window_hours": 5,
    "floor_window_to_hour": True,   # windows are assumed to start on the hour
    "retry_after_minutes": 15,
    "wake_pc_for_first_ping": True,
}


# ----------------------------------------------------------------- helpers

def out(s=""):
    if sys.stdout:  # None under pythonw (scheduled runs)
        print(s)


def now_local():
    return datetime.now().astimezone()


def log(msg):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{now_local():%Y-%m-%d %H:%M:%S}  {msg}"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    if LOG_FILE.stat().st_size > 1_000_000:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()[-500:]
        LOG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out(line)


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path, data):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        cfg.update(load_json(CONFIG_FILE, {}))
    else:
        save_json(CONFIG_FILE, cfg)
    return cfg


def load_state():
    return load_json(STATE_FILE, {})


def save_state(state):
    save_json(STATE_FILE, state)


def parse_hhmm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def minutes_of_day(dt):
    return dt.hour * 60 + dt.minute


def fmt_hhmm(minutes):
    minutes %= 24 * 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def fmt_delta(td):
    mins = max(0, int(td.total_seconds() // 60))
    return f"{mins // 60}h {mins % 60:02d}m"


def same_path(a, b):
    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))


# --------------------------------------------------------- reading the logs

@dataclass
class Entry:
    ts: datetime
    model: str
    tokens: int          # input + output + cache writes
    cache_read: int
    is_ping: bool
    synthetic: bool = False


@dataclass
class Block:
    start: datetime
    end: datetime
    entries: list = field(default_factory=list)

    @property
    def real(self):
        return [e for e in self.entries if not e.synthetic]

    @property
    def user_entries(self):
        return [e for e in self.real if not e.is_ping]

    @property
    def tokens(self):
        return sum(e.tokens for e in self.real)

    @property
    def started_by_ping(self):
        return self.entries[0].is_ping

    def is_active(self, now):
        return self.start <= now < self.end


def project_dirs():
    dirs = []
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        dirs += [Path(p) / "projects" for p in env.split(",") if p]
    dirs += [Path.home() / ".claude" / "projects", Path.home() / ".config" / "claude" / "projects"]
    seen, result = set(), []
    for d in dirs:
        key = os.path.normcase(str(d))
        if key not in seen and d.is_dir():
            seen.add(key)
            result.append(d)
    return result


def load_entries(since=None):
    seen, entries = set(), []
    for d in project_dirs():
        for f in d.rglob("*.jsonl"):
            try:
                if since and f.stat().st_mtime < since.timestamp():
                    continue
                with open(f, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        if '"assistant"' not in line or '"usage"' not in line:
                            continue
                        try:
                            d_ = json.loads(line)
                        except ValueError:
                            continue
                        if d_.get("type") != "assistant":
                            continue
                        msg = d_.get("message") or {}
                        usage = msg.get("usage") or {}
                        ts = d_.get("timestamp")
                        model = msg.get("model") or "?"
                        if not ts or not usage or model == "<synthetic>":
                            continue
                        key = (msg.get("id"), d_.get("requestId"))
                        if key != (None, None):
                            if key in seen:
                                continue  # streamed responses are logged more than once
                            seen.add(key)
                        t = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
                        if since and t < since:
                            continue
                        entries.append(Entry(
                            ts=t,
                            model=model,
                            tokens=(usage.get("input_tokens", 0) or 0)
                            + (usage.get("output_tokens", 0) or 0)
                            + (usage.get("cache_creation_input_tokens", 0) or 0),
                            cache_read=usage.get("cache_read_input_tokens", 0) or 0,
                            is_ping=same_path(d_.get("cwd", ""), PING_DIR),
                        ))
            except OSError:
                continue
    # A successful ping always opens a window, even if its transcript is missing.
    last_ping = load_state().get("last_ping")
    if last_ping:
        t = datetime.fromisoformat(last_ping)
        if not since or t >= since:
            entries.append(Entry(t, "ping", 0, 0, is_ping=True, synthetic=True))
    entries.sort(key=lambda e: e.ts)
    return entries


def build_blocks(entries, cfg):
    blocks, length = [], timedelta(hours=cfg["window_hours"])
    for e in entries:
        if not blocks or e.ts >= blocks[-1].end:
            start = e.ts.replace(minute=0, second=0, microsecond=0) if cfg["floor_window_to_hour"] else e.ts
            blocks.append(Block(start, start + length))
        blocks[-1].entries.append(e)
    return blocks


def current_block(cfg, now):
    blocks = build_blocks(load_entries(since=now - timedelta(hours=48)), cfg)
    if blocks and blocks[-1].is_active(now):
        return blocks[-1]
    return None


# ----------------------------------------------------------- active hours

def in_active_hours(cfg, now):
    if DAYS[now.weekday()] not in cfg["active_days"]:
        return False
    start, end, m = parse_hhmm(cfg["active_start"]), parse_hhmm(cfg["active_end"]), minutes_of_day(now)
    return start <= m < end if start < end else (m >= start or m < end)


def next_active_start(cfg, now):
    start = parse_hhmm(cfg["active_start"])
    for i in range(8):
        day = (now + timedelta(days=i)).replace(hour=start // 60, minute=start % 60, second=0, microsecond=0)
        if day > now and DAYS[day.weekday()] in cfg["active_days"]:
            return day
    return None


# ------------------------------------------------------------------ pinging

def find_claude():
    saved = load_state().get("claude_path")
    if saved and Path(saved).exists():
        return saved
    names = ["claude.cmd", "claude.exe", "claude"] if os.name == "nt" else ["claude"]
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    for p in (Path.home() / "AppData/Roaming/npm/claude.cmd",
              Path.home() / ".local/bin/claude.exe",
              Path.home() / ".local/bin/claude"):
        if p.exists():
            return str(p)
    return None


def do_ping(cfg, reason):
    state = load_state()
    state["last_attempt"] = now_local().isoformat()
    save_state(state)

    claude = find_claude()
    if not claude:
        log("ERROR: claude CLI not found - is Claude Code installed?")
        return False
    PING_DIR.mkdir(parents=True, exist_ok=True)
    started = now_local()
    try:
        r = subprocess.run(
            [claude, "-p", cfg["ping_message"], "--model", cfg["model"]],
            cwd=PING_DIR, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=180,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"ERROR ({reason}): {e}")
        return False
    if r.returncode != 0:
        log(f"ERROR ({reason}): exit {r.returncode}: {(r.stderr or r.stdout).strip()[:200]}")
        return False

    state = load_state()
    state["last_ping"] = started.isoformat()
    save_state(state)
    b = current_block(cfg, now_local())
    window = f"window {b.start:%H:%M}-{b.end:%H:%M}" if b else "window unknown"
    log(f"PING ok ({reason}) - {window}. Reply: {r.stdout.strip()[:60]!r}")
    return True


# ----------------------------------------------------------------- commands

def cmd_tick(args):
    cfg, now = load_config(), now_local()
    if not in_active_hours(cfg, now):
        return
    if current_block(cfg, now):
        return  # a window is already open; your work (or an earlier ping) keeps it going
    last = load_state().get("last_attempt")
    if last and now - datetime.fromisoformat(last) < timedelta(minutes=cfg["retry_after_minutes"]):
        return
    do_ping(cfg, "no open window")


def cmd_ping(args):
    do_ping(load_config(), "manual")


def task_installed():
    if os.name != "nt":
        return None
    r = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    return r.returncode == 0


def cmd_status(args):
    cfg, now = load_config(), now_local()
    out(f"Now: {now:%a %d %b %H:%M}")
    b = current_block(cfg, now)
    if b:
        who = "a hello ping" if b.started_by_ping else "your work"
        out(f"Current window: {b.start:%H:%M} -> {b.end:%H:%M}   (resets in {fmt_delta(b.end - now)})")
        out(f"  started by {who}; used {fmt_tokens(b.tokens)} tokens over {len(b.real)} responses")
    else:
        out("No open window - your next message (or ping) starts a fresh 5-hour window.")

    out(f"Active hours: {cfg['active_start']}-{cfg['active_end']} on {', '.join(cfg['active_days'])}")
    if b and in_active_hours(cfg, b.end):
        out(f"Next ping: around {b.end:%H:%M}, only if no new window has started by then.")
    elif not b and in_active_hours(cfg, now):
        out("Next ping: on the next check.")
    else:
        nxt = next_active_start(cfg, now)
        out(f"Next ping: {nxt:%a %H:%M}" if nxt else "Next ping: none (no active days set).")

    installed = task_installed()
    if installed is not None:
        out(f"Scheduled task: {'installed' if installed else 'NOT installed - run: python claude_pinger.py install'}")
    last = load_state().get("last_ping")
    if last:
        out(f"Last ping: {datetime.fromisoformat(last):%a %d %b %H:%M}")


def cmd_report(args):
    cfg, now = load_config(), now_local()
    since = now - timedelta(days=args.days)
    blocks = build_blocks(load_entries(since=since - timedelta(hours=cfg["window_hours"])), cfg)
    blocks = [b for b in blocks if b.end > since]
    user = [e for b in blocks for e in b.user_entries]

    out(f"=== Claude usage - last {args.days} days ===")
    if not blocks:
        out("No usage found in Claude Code logs for this period.")
        return
    worked = [b for b in blocks if b.user_entries]
    total = sum(b.tokens for b in blocks)
    out(f"Windows: {len(blocks)}  ({len(worked)} with your work, "
        f"{sum(b.started_by_ping for b in blocks)} started by a ping)")
    out(f"Tokens (in+out+cache writes): {fmt_tokens(total)}   cache reads: "
        f"{fmt_tokens(sum(e.cache_read for e in user))}")
    if worked:
        per = [b.tokens for b in worked]
        out(f"Per working window: avg {fmt_tokens(int(statistics.mean(per)))}, "
            f"median {fmt_tokens(int(statistics.median(per)))}, max {fmt_tokens(max(per))}")

    models = Counter()
    for e in user:
        models[e.model] += e.tokens
    if models:
        out("\nBy model:")
        for m, t in models.most_common():
            out(f"  {m:<28} {fmt_tokens(t):>7}  {100 * t / max(1, sum(models.values())):5.1f}%")

    out("\nRecent windows:")
    peak = max(b.tokens for b in blocks) or 1
    for b in blocks[-15:]:
        bar = "#" * max(1 if b.tokens else 0, round(20 * b.tokens / peak))
        tag = " (ping)" if b.started_by_ping else ""
        live = "  <- now" if b.is_active(now) else ""
        out(f"  {b.start:%a %d %b %H:%M}-{b.end:%H:%M}  {len(b.user_entries):4d} resp  "
            f"{fmt_tokens(b.tokens):>7}  {bar:<20}{tag}{live}")

    hours = Counter(e.ts.hour for e in user)
    if hours:
        out("\nWhen you work (responses per hour of day):")
        top = max(hours.values())
        for h in range(min(hours), max(hours) + 1):
            out(f"  {h:02d}:00  {'#' * round(30 * hours[h] / top):<30} {hours[h]}")

    # A work session starts with the first response after a 6h+ break.
    starts, prev = Counter(), None
    for e in user:
        if prev is None or e.ts - prev >= timedelta(hours=6):
            starts[e.ts.hour] += 1
        prev = e.ts
    if starts:
        out("\nYour sessions usually start at: " +
            ", ".join(f"{h:02d}:00 ({n}x)" for h, n in starts.most_common(3)))

    # Ping ~3h before you start so the first reset lands ~2h into your work,
    # giving you two windows in your first 5 hours.
    out("\nRecommendation:")
    if args.start:
        start, why = parse_hhmm(args.start), "you said you start"
    elif sum(starts.values()) >= 3:
        start, why = starts.most_common(1)[0][0] * 60, "you most often start"
    else:
        start = None
    if start is None:
        out("  Not enough history yet. Pass your start time, e.g. report --start 10:00")
    else:
        rec = (start // 60 - 3) * 60
        out(f"  {why} at {fmt_hhmm(start)} -> best first ping {fmt_hhmm(rec)}, "
            f"first reset at {fmt_hhmm(rec + 60 * cfg['window_hours'])} (~2h into your work).")
        if fmt_hhmm(rec) != cfg["active_start"]:
            out(f"  Your config uses {cfg['active_start']}. To change it, set \"active_start\": "
                f"\"{fmt_hhmm(rec)}\" in {CONFIG_FILE} and re-run install.")
        else:
            out("  Your config already matches.")
    if any(h < parse_hhmm(cfg["active_start"]) // 60 or h >= parse_hhmm(cfg["active_end"]) // 60
           for h in hours):
        out(f"  Note: you also work outside {cfg['active_start']}-{cfg['active_end']}; pings are paused "
            f"then, but your own messages still open windows as usual.")

    out("")
    cmd_status(args)


def run_powershell(script):
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"PowerShell failed:\n{r.stderr.strip()}")


def cmd_install(args):
    if os.name != "nt":
        out("Not Windows - add this to `crontab -e` instead:")
        out(f"*/10 * * * * {sys.executable} {Path(__file__).resolve()} tick")
        return
    cfg = load_config()
    claude = find_claude()
    if not claude:
        raise SystemExit("claude CLI not found. Install Claude Code first.")
    # Run from a stable copy, so the task keeps working if this file moves.
    target = APP_DIR / "claude_pinger.py"
    if not same_path(Path(__file__).resolve(), target):
        shutil.copy2(__file__, target)
    state = load_state()
    state["claude_path"] = claude
    save_state(state)

    pyw = Path(sys.executable).with_name("pythonw.exe")
    pyw = pyw if pyw.exists() else Path(sys.executable)

    def q(s):
        return str(s).replace("'", "''")

    task_args = f'"{target}" tick'
    action = (f"$a = New-ScheduledTaskAction -Execute '{q(pyw)}' "
              f"-Argument '{q(task_args)}' -WorkingDirectory '{q(APP_DIR)}'")
    common = ("-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable "
              "-MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)")
    script = f"""
$ErrorActionPreference = 'Stop'
{action}
$s = New-ScheduledTaskSettingsSet {common}
$t = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes {int(cfg['check_every_minutes'])})
Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $a -Trigger $t -Settings $s -Force | Out-Null
"""
    if cfg["wake_pc_for_first_ping"]:
        days = ",".join(DAY_NAMES[DAYS.index(d)] for d in cfg["active_days"])
        script += f"""
$ws = New-ScheduledTaskSettingsSet {common} -WakeToRun
$wt = New-ScheduledTaskTrigger -Weekly -DaysOfWeek {days} -At '{cfg['active_start']}'
Register-ScheduledTask -TaskName '{WAKE_TASK_NAME}' -Action $a -Trigger $wt -Settings $ws -Force | Out-Null
"""
    else:
        script += f"Unregister-ScheduledTask -TaskName '{WAKE_TASK_NAME}' -Confirm:$false -ErrorAction SilentlyContinue\n"
    run_powershell(script)
    log(f"Installed: checks every {cfg['check_every_minutes']} min, active "
        f"{cfg['active_start']}-{cfg['active_end']}, model {cfg['model']}")
    out(f"Script copy: {target}\nConfig:      {CONFIG_FILE}\nLog:         {LOG_FILE}")


def cmd_uninstall(args):
    if os.name != "nt":
        out("Remove the claude_pinger line from `crontab -e`.")
        return
    run_powershell(
        f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false -ErrorAction SilentlyContinue;"
        f"Unregister-ScheduledTask -TaskName '{WAKE_TASK_NAME}' -Confirm:$false -ErrorAction SilentlyContinue")
    log("Uninstalled scheduled tasks.")


def cmd_log(args):
    if not LOG_FILE.exists():
        out("No activity yet.")
        return
    for line in LOG_FILE.read_text(encoding="utf-8").splitlines()[-args.lines:]:
        out(line)


def cmd_config(args):
    cfg = load_config()
    out(f"Config file: {CONFIG_FILE}  (re-run install after changing times or days)")
    out(json.dumps(cfg, indent=2))


def main():
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description="Analyse Claude usage windows and keep them aligned with Haiku pings.")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("status")
    r = sub.add_parser("report")
    r.add_argument("--days", type=int, default=14)
    r.add_argument("--start", help="when you usually start work, e.g. 10:00")
    sub.add_parser("tick")
    sub.add_parser("ping")
    sub.add_parser("install")
    sub.add_parser("uninstall")
    lg = sub.add_parser("log")
    lg.add_argument("--lines", type=int, default=30)
    sub.add_parser("config")
    args = p.parse_args()
    {
        None: cmd_status, "status": cmd_status, "report": cmd_report, "tick": cmd_tick,
        "ping": cmd_ping, "install": cmd_install, "uninstall": cmd_uninstall,
        "log": cmd_log, "config": cmd_config,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
