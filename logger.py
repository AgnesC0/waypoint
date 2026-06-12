"""
logger.py — Workspace session event logger.

Writes workspace-level behavioral signals to ~/.waypoint/activity_log.jsonl.
Only records workspace presence, timing, and inferred task context.
Never records commands, keystrokes, terminal output, or file contents.

Event types
-----------
workspace_start  — a workspace appears for the first time (or after absence)
workspace_switch — exactly one workspace ends and one begins in the same cycle
workspace_end    — a workspace disappears with no simultaneous replacement

For a clean A→B transition only workspace_switch is emitted. For independent
appearances and disappearances, workspace_start / workspace_end are used.
"""

import json
import os
import re
import subprocess
import time
from datetime import datetime
from typing import Optional

from detector import Workspace

_LOG_DIR  = os.path.expanduser("~/.waypoint")
_LOG_PATH = os.path.join(_LOG_DIR, "activity_log.jsonl")

_SHELLS = {"zsh", "bash", "sh", "fish", "tcsh", "csh", "ksh"}

# Generic tool names that are not meaningful as work-context hints.
# If the foreground command matches one of these, skip it and fall through
# to semantic context.
_GENERIC_CMDS = frozenset({
    "claude", "zsh", "bash", "sh", "fish", "csh", "tcsh", "ksh",
    "python", "python3", "ruby", "node", "npm", "pnpm", "yarn",
    "vim", "nvim", "vi", "less", "cat", "tail", "top", "htop",
    "man", "grep", "awk", "sed", "curl", "wget",
})

# Branches too generic to carry task signal
_SKIP_BRANCHES = {
    "main", "master", "develop", "dev",
    "staging", "production", "release", "hotfix", "feature",
}

# Branch prefixes that scope a task name (e.g. "feature/terminal-detection")
_SKIP_PREFIXES = {"feature", "fix", "bugfix", "feat", "chore", "refactor", "hotfix", "release"}

# Tokens too generic to use as a keyword
_SKIP_TOKENS = {"app", "web", "api", "lib", "src", "new", "old", "test", "light", "dark"}

# Task synthesis: verb overrides (checked before domain lookup)
_VERB_SIGNALS: list[tuple[frozenset, str]] = [
    (frozenset({"fix", "bug", "error", "broken", "crash", "issue", "wrong"}), "fix"),
    (frozenset({"debug", "investigate", "trace", "diagnose"}),                "debug"),
    (frozenset({"refactor", "restructure", "cleanup"}),                       "refactor"),
    (frozenset({"optimize", "perf", "performance", "speed"}),                 "optimize"),
    (frozenset({"check", "validate", "verify"}),                              "check"),
]

# Task synthesis: domain vocabulary → (default_verb, subject_phrase)
# Higher intersection count wins; ties broken by list order (specific first).
_DOMAIN_VOCAB: list[tuple[frozenset, str, str]] = [
    (frozenset({"tty", "applescript", "focused"}),    "debug",   "terminal detection"),
    (frozenset({"macos", "platform"}),                "debug",   "terminal detection"),
    (frozenset({"detect", "detector"}),               "debug",   "workspace detection"),
    (frozenset({"semantic", "diff", "hint"}),         "improve", "semantic hint generation"),
    (frozenset({"hint", "resume"}),                   "improve", "hint generation"),
    (frozenset({"redraw", "canvas"}),                 "improve", "HUD rendering"),
    (frozenset({"hud", "live"}),                      "improve", "HUD live hints"),
    (frozenset({"hud", "row"}),                       "improve", "HUD rows"),
    (frozenset({"logger"}),                           "update",  "workspace logging"),
    (frozenset({"log", "session", "event"}),          "update",  "activity logging"),
    (frozenset({"diff", "staged"}),                   "update",  "git diff"),
    (frozenset({"commit", "branch"}),                 "update",  "git integration"),
    (frozenset({"hud"}),                              "improve", "HUD"),
    (frozenset({"config", "yaml"}),                   "update",  "project config"),
    (frozenset({"workspace"}),                        "update",  "workspace handling"),
    (frozenset({"poll", "timer", "refresh"}),         "improve", "polling"),
    (frozenset({"focus", "window", "tab"}),           "improve", "window focus"),
    (frozenset({"test", "spec"}),                     "improve", "tests"),
]

_HINT_STOP = frozenset({
    "the", "and", "for", "with", "from", "into", "onto", "that", "this", "via",
    "self", "cls", "new", "get", "set", "run", "init", "main",
    "src", "lib", "app", "util", "utils", "base", "core",
})


class WorkspaceLogger:
    """Records workspace session start / switch / end events to a JSONL log."""

    def __init__(self, log_path: str = _LOG_PATH) -> None:
        self._log_path = log_path
        os.makedirs(os.path.dirname(log_path), exist_ok=True, mode=0o700)
        # name → {start_time, ws, context, hud_clicked, depth}
        self._sessions: dict[str, dict] = {}

        # ── CogPass training-data state (all in-memory, never persisted as-is) ─
        # Calendar-day ordinal used to reset daily counters at midnight.
        self._cogpass_today:      int                    = datetime.now().toordinal()
        # Per-workspace visit counter for the current calendar day.
        # Keys are workspace names — only len() is ever written to disk.
        self._today_depths:       dict[str, int]         = {}
        # Set of workspace names seen today — only len() is ever written to disk.
        self._today_workspaces:   set[str]               = set()
        # Names where a HUD click arrived before the session was registered
        # (2-second poll gap).  Consumed by _emit_start / _emit_switch.
        self._pending_hud_clicks: set[str]               = set()
        # Latest hint-type label per workspace, written every poll cycle by the
        # HUD and popped (consumed) when the session ends.
        self._session_hint_type:  dict[str, Optional[str]] = {}

    def update(self, workspaces: list[Workspace]) -> None:
        """Diff current workspace set against previous; emit events for changes."""
        now = time.time()
        current        = {ws.name: ws for ws in workspaces}
        previous_names = set(self._sessions)
        current_names  = set(current)

        ended   = previous_names - current_names
        started = current_names  - previous_names

        if len(ended) == 1 and len(started) == 1:
            self._emit_switch(next(iter(ended)), next(iter(started)), current, now)
        else:
            for name in ended:
                self._emit_end(name, "terminal_closed", now)
            for name in started:
                self._emit_start(current[name], now)

        # Keep cwd/tty current for continuing sessions
        for name in current_names & previous_names:
            self._sessions[name]["ws"] = current[name]

    def shutdown(self) -> None:
        """Flush all open sessions with end_reason=app_quit."""
        now = time.time()
        for name in list(self._sessions):
            self._emit_end(name, "app_quit", now)

    # ── CogPass signal API ────────────────────────────────────────────────────

    def record_hud_click(self, name: str) -> None:
        """Mark that the user navigated to this workspace by clicking the HUD.

        Sets recommendation_accepted=True on the session's cogpass record.
        If the session is not yet registered (click arrived during the 2-second
        poll gap), the flag is staged and consumed by _emit_start/_emit_switch.
        """
        if name in self._sessions:
            self._sessions[name]["hud_clicked"] = True
        else:
            self._pending_hud_clicks.add(name)

    def record_hint_type(self, name: str, hint_type: Optional[str]) -> None:
        """Store the hint-type label shown for this workspace this poll cycle.

        Only enum labels from _HINT_TYPES are accepted; None is also valid.
        The hint TEXT is never passed here — callers must resolve it to a label
        before calling.  The latest value before session end is what gets written.
        """
        if hint_type in _HINT_TYPES or hint_type is None:
            self._session_hint_type[name] = hint_type

    # ── CogPass daily-counter helper ──────────────────────────────────────────

    def _refresh_today(self, now: float) -> None:
        """Reset per-day counters when the calendar day has rolled over."""
        today = datetime.fromtimestamp(now).toordinal()
        if today != self._cogpass_today:
            self._cogpass_today = today
            self._today_depths.clear()
            self._today_workspaces.clear()

    # ── Event emitters ────────────────────────────────────────────────────────

    def _emit_start(self, ws: Workspace, now: float) -> None:
        context = self._infer_task(ws)

        self._refresh_today(now)
        self._today_workspaces.add(ws.name)
        self._today_depths[ws.name] = self._today_depths.get(ws.name, 0) + 1
        hud_clicked = ws.name in self._pending_hud_clicks
        self._pending_hud_clicks.discard(ws.name)

        self._sessions[ws.name] = {
            "start_time":  now,
            "ws":          ws,
            "context":     context,
            "hud_clicked": hud_clicked,
            "depth":       self._today_depths[ws.name],
        }
        self._write({
            "event_type":         "workspace_start",
            "timestamp":          now,
            "start_time":         now,
            "end_time":           None,
            "duration_seconds":   None,
            "workspace":          ws.name,
            "context":            context,
            "cwd":                ws.cwd,
            "tty":                ws.tty,
            "window_id":          ws.window_id,
            "tab_id":             ws.tab_index,
            "previous_workspace": None,
            "current_workspace":  ws.name,
            "end_reason":         None,
        })

    def _emit_end(self, name: str, end_reason: str, now: float) -> None:
        session   = self._sessions.pop(name)
        task_load = len(self._sessions)   # other concurrent sessions after this one ends
        ws        = session["ws"]
        self._write({
            "event_type":         "workspace_end",
            "timestamp":          now,
            "start_time":         session["start_time"],
            "end_time":           now,
            "duration_seconds":   round(now - session["start_time"], 2),
            "workspace":          name,
            "context":            session["context"],
            "cwd":                ws.cwd,
            "tty":                ws.tty,
            "window_id":          ws.window_id,
            "tab_id":             ws.tab_index,
            "previous_workspace": name,
            "current_workspace":  None,
            "end_reason":         end_reason,
        })
        self._append_completed(
            name, session["start_time"], now, end_reason,
            task_load             = task_load,
            session_depth         = session.get("depth", 1),
            workspace_count_today = session.get("workspace_count_today", len(self._today_workspaces)),
            hud_clicked           = session.get("hud_clicked", False),
        )

    def _emit_switch(
        self, ended_name: str, started_name: str, current: dict, now: float
    ) -> None:
        session   = self._sessions.pop(ended_name)
        task_load = len(self._sessions)   # concurrent sessions after ended one is removed
        new_ws    = current[started_name]
        context   = self._infer_task(new_ws)

        self._write({
            "event_type":         "workspace_switch",
            "timestamp":          now,
            "start_time":         session["start_time"],
            "end_time":           now,
            "duration_seconds":   round(now - session["start_time"], 2),
            "workspace":          ended_name,
            "context":            session["context"],
            "cwd":                session["ws"].cwd,
            "tty":                session["ws"].tty,
            "window_id":          session["ws"].window_id,
            "tab_id":             session["ws"].tab_index,
            "previous_workspace": ended_name,
            "current_workspace":  started_name,
            "end_reason":         "switch_workspace",
        })

        self._append_completed(
            ended_name, session["start_time"], now, "switch_workspace",
            task_load             = task_load,
            session_depth         = session.get("depth", 1),
            workspace_count_today = session.get("workspace_count_today", len(self._today_workspaces)),
            hud_clicked           = session.get("hud_clicked", False),
        )

        self._refresh_today(now)
        self._today_workspaces.add(started_name)
        self._today_depths[started_name] = self._today_depths.get(started_name, 0) + 1
        hud_clicked_new = started_name in self._pending_hud_clicks
        self._pending_hud_clicks.discard(started_name)

        self._sessions[started_name] = {
            "start_time":  now,
            "ws":          new_ws,
            "context":     context,
            "hud_clicked": hud_clicked_new,
            "depth":       self._today_depths[started_name],
        }

    # ── JSONL writer ─────────────────────────────────────────────────────────

    def _write(self, event: dict) -> None:
        try:
            with open(self._log_path, "a") as fh:
                fh.write(json.dumps(event) + "\n")
        except OSError:
            pass

    def _append_completed(
        self,
        name: str,
        start_time: float,
        end_time: float,
        end_reason: str,
        *,
        task_load: int,
        session_depth: int,
        workspace_count_today: int,
        hud_clicked: bool,
    ) -> None:
        """Append one record to completed_sessions.jsonl (unchanged) and
        one privacy-reduced record to cogpass_sessions.jsonl.

        cogpass_sessions.jsonl never contains: project name, paths, commands,
        window titles, git context, absolute timestamps, or any identifier.
        """
        # ── completed_sessions.jsonl — format unchanged ───────────────────────
        try:
            record = {
                "project":          name,
                "start_time":       start_time,
                "end_time":         end_time,
                "duration_seconds": round(end_time - start_time, 2),
                "hour":             datetime.fromtimestamp(start_time).hour,
                "day":              _weekday_sunday_zero(start_time),
                "end_reason":       end_reason,
                "source":           "waypoint",
            }
            with open(_COMPLETED_PATH, "a") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError:
            pass

        # ── cogpass_sessions.jsonl — privacy-reduced training record ──────────
        # Pop the hint-type label recorded during the session; None if absent.
        hint_type = self._session_hint_type.pop(name, None)
        try:
            cogpass = {
                "schema_version":        1,
                "hour":                  datetime.fromtimestamp(start_time).hour,
                "day":                   _weekday_sunday_zero(start_time),
                "duration_seconds":      round(end_time - start_time, 2),
                "end_reason":            end_reason,
                "task_load":             task_load,
                "session_depth":         session_depth,
                "workspace_count_today": workspace_count_today,
                "hint_type":             hint_type,
                "recommendation_accepted": hud_clicked,
                "feedback_label":        None,
            }
            with open(_COGPASS_PATH, "a") as fh:
                fh.write(json.dumps(cogpass) + "\n")
        except OSError:
            pass

    # ── Task inference ────────────────────────────────────────────────────────

    def _infer_task(self, ws: Workspace) -> str:
        return infer_context(ws)


# ── Module-level helpers ──────────────────────────────────────────────────────

def _foreground_command(tty: str, shell_pid: str) -> str:
    """Return the foreground non-shell process running in this terminal, or ''.

    Uses pgrep to find direct children of the shell PID, then ps to read
    their command lines.  Returns '' when the shell is idle at the prompt
    (no children) or when detection fails.
    """
    if not tty or not shell_pid:
        return ""
    try:
        child_r = subprocess.run(
            ["pgrep", "-P", shell_pid],
            capture_output=True, text=True, timeout=1,
        )
        child_pids = [p.strip() for p in child_r.stdout.strip().splitlines() if p.strip()]
        if not child_pids:
            return ""  # shell is idle

        r = subprocess.run(
            ["ps", "-p", ",".join(child_pids), "-o", "comm=,args="],
            capture_output=True, text=True, timeout=1,
        )
        for line in r.stdout.strip().splitlines():
            parts = line.strip().split(None, 1)
            if not parts:
                continue
            comm = parts[0].strip()
            base = os.path.basename(comm).lstrip("-")
            if base in _SHELLS or base.lower() in _GENERIC_CMDS:
                continue
            full_args = parts[1].strip() if len(parts) > 1 else comm
            tokens = full_args.split()
            cmd_name = os.path.basename(tokens[0]) if tokens else base
            # Include a filename argument when it carries context (has an extension)
            if len(tokens) > 1 and not tokens[1].startswith("-"):
                fname = os.path.basename(tokens[1])
                if fname and "." in fname:
                    return f"{cmd_name} {fname}"[:40]
            return cmd_name[:40]
    except Exception:
        pass
    return ""


def _clean_diff_context(raw: str) -> str:
    """Strip language boilerplate from a diff hunk context and return readable words.

    Input:  'def update_from_workspace(self, ws):'
    Output: 'update from workspace'
    """
    # Remove common keyword prefixes (Python, JS/TS, Rust, Go, …).
    # Longer alternatives must come before shorter ones to avoid partial
    # matches (e.g. 'fn' inside 'function').
    s = re.sub(
        r'^(?:pub\s+)?(?:async\s+)?'
        r'(?:export(?:\s+default)?\s*(?:function\s+|class\s+)?|'
        r'interface|function|struct|method|class|impl|'
        r'const|func|type|def|let|var|fn)\s*',
        '',
        raw.strip(),
        flags=re.IGNORECASE,
    )
    # Extract first identifier; skip leading underscores
    m = re.match(r'_*([A-Za-z][A-Za-z0-9_]*)', s)
    if not m:
        return ''
    name = m.group(1)
    if len(name) < 3 or name.lower() in {'cls', 'self', 'the', 'new'}:
        return ''
    # CamelCase → 'camel case'
    name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    name = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', name)
    # snake_case → 'snake case'
    name = name.replace('_', ' ').lower().strip()
    return name if len(name) > 2 else ''


def _synthesize_task_hint(contexts: list[str], files: list[str]) -> str:
    """Convert diff contexts and changed file names into a natural-language task phrase.

    Answers "what was I working on?" rather than "what function changed?".
    """
    raw = " ".join(contexts) + " " + " ".join(
        re.sub(r'[-_.]', ' ', os.path.splitext(f)[0]) for f in files
    )
    tokens = frozenset(re.findall(r'[a-z]+', raw.lower())) - _HINT_STOP

    if not tokens:
        return ''

    verb_override: Optional[str] = None
    for signals, v in _VERB_SIGNALS:
        if tokens & signals:
            verb_override = v
            break

    best_score = 0
    best_verb = "update"
    best_subject = ""
    for domain_tokens, dv, subj in _DOMAIN_VOCAB:
        score = len(tokens & domain_tokens)
        if score > best_score:
            best_score = score
            best_verb = dv
            best_subject = subj

    if not best_subject:
        sig = sorted(t for t in tokens if len(t) > 3)[:2]
        if not sig:
            return ''
        best_subject = ' '.join(sig)

    return f"{verb_override or best_verb} {best_subject}"[:40]


def _diff_hint(path: str, extra: list[str]) -> str:
    """Parse one git diff and return a semantic hint (staged or unstaged).

    Prefers hunk-context function/class names (most specific);
    falls back to cleaned file names when no contexts are present.
    """
    try:
        r = subprocess.run(
            ['git', '-C', path, 'diff', '-U0'] + extra,
            capture_output=True, text=True, timeout=2,
        )
    except Exception:
        return ''
    if r.returncode != 0 or not r.stdout.strip():
        return ''

    files: list[str] = []
    contexts: list[str] = []
    for line in r.stdout.splitlines():
        if line.startswith('+++ b/'):
            fname = line[6:].strip()
            if fname != '/dev/null':
                files.append(os.path.basename(fname))
        elif line.startswith('@@ '):
            m = re.search(r'@@ [^@]+ @@ (.+)', line)
            if m:
                ctx = _clean_diff_context(m.group(1))
                if ctx:
                    contexts.append(ctx)

    if not files:
        return ''

    return _synthesize_task_hint(contexts, files)


def _git_semantic_hint(path: str) -> str:
    """Return a semantic hint derived from the current working-tree diff.

    Checks staged changes first (more intentional), then unstaged.
    Returns '' for a clean tree.
    """
    return _diff_hint(path, ['--cached']) or _diff_hint(path, [])


def _git_branch(path: str) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", path, "branch", "--show-current"],
            capture_output=True, text=True, timeout=2,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _git_last_commit(path: str) -> str:
    """Return the most recent commit subject, stripped of conventional-commit prefixes."""
    try:
        r = subprocess.run(
            ["git", "-C", path, "log", "-1", "--pretty=format:%s"],
            capture_output=True, text=True, timeout=2,
        )
        if r.returncode != 0:
            return ""
        subject = r.stdout.strip()
        # Strip conventional commit type prefix: "feat: ", "fix(scope): ", etc.
        subject = re.sub(
            r'^(?:feat|fix|docs|chore|refactor|test|style|perf|ci|build)'
            r'(?:\([^)]+\))?!?:\s*',
            '',
            subject,
            flags=re.IGNORECASE,
        )
        return subject[:40] if subject else ""
    except Exception:
        return ""


def _to_display_hint(raw: str) -> str:
    """Split on word separators and join with spaces: 'my-feature' → 'my feature'."""
    tokens = re.split(r"[-_/\s]+", raw.lower())
    return " ".join(t for t in tokens if t)


def infer_context(ws: Workspace) -> str:
    """
    Return a human-readable context string for log events.
    Tries git branch first; falls back to the last commit subject.
    Never reads commands, keystrokes, terminal output, or file contents.
    """
    branch = _git_branch(ws.path)
    if branch and branch not in _SKIP_BRANCHES:
        parts = branch.split("/")
        if parts[0].lower() in _SKIP_PREFIXES | _SKIP_BRANCHES:
            branch = "/".join(parts[1:])
        if branch and branch not in _SKIP_BRANCHES:
            return _to_display_hint(branch)
    return _git_last_commit(ws.path)


_CURRENT_SESSION_PATH = os.path.join(_LOG_DIR, "current_session.json")
_COMPLETED_PATH       = os.path.join(_LOG_DIR, "completed_sessions.jsonl")
_COGPASS_PATH         = os.path.join(_LOG_DIR, "cogpass_sessions.jsonl")

# Allowed enum labels for cogpass hint_type.  Only these values may be written;
# the actual hint text is never stored.
_HINT_TYPES = frozenset({"manual", "semantic_diff", "commit", "foreground_cmd"})


def _weekday_sunday_zero(ts: float) -> int:
    """Return weekday for a Unix timestamp with 0=Sunday (matching JS convention)."""
    return (datetime.fromtimestamp(ts).weekday() + 1) % 7


def write_current_session(
    project: Optional[str], start_time: float, now: float
) -> None:
    """Overwrite current_session.json with the live session, or literal null if none.

    Called every poll tick by the HUD. Safe to call from any thread; OSError is
    silently swallowed so a missing ~/.waypoint dir never crashes the HUD.
    """
    try:
        os.makedirs(_LOG_DIR, exist_ok=True, mode=0o700)
        if project is None:
            content = "null\n"
        else:
            dt = datetime.fromtimestamp(now)
            record = {
                "project":          project,
                "start_time":       start_time,
                "duration_seconds": round(now - start_time, 2),
                "hour":             dt.hour,
                "day":              _weekday_sunday_zero(now),
                "source":           "waypoint",
            }
            content = json.dumps(record) + "\n"
        with open(_CURRENT_SESSION_PATH, "w") as fh:
            fh.write(content)
    except OSError:
        pass


_HINTS_PATH = os.path.join(_LOG_DIR, "hints.json")


class HintStore:
    """
    Persists one resume_hint per workspace to ~/.waypoint/hints.json.

    Each entry is stored as {"hint": str, "manual": bool}.
    Manual hints (set via the CLI) take priority over git-branch auto-detection
    and are never overwritten by the poll loop.

    Storage format:
        {
          "Waypoint":     {"hint": "fix HUD resume hint", "manual": true},
          "CogPass Light": {"hint": "execution cost model", "manual": false}
        }
    """

    def __init__(self, path: str = _HINTS_PATH) -> None:
        self._path  = path
        self._mtime: float = 0.0
        self._hints: dict[str, dict] = self._load()
        # Most-recently-computed hint-type label per workspace.  Set as a side
        # effect of update_from_workspace(); read by WorkspaceLogger via
        # last_hint_type().  Only enum labels — hint text is never stored here.
        self._last_hint_type: dict[str, Optional[str]] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def last_hint_type(self, name: str) -> Optional[str]:
        """Return the hint-type label computed during the last update_from_workspace call."""
        return self._last_hint_type.get(name)

    def get(self, name: str) -> Optional[str]:
        self._maybe_reload()
        entry = self._hints.get(name)
        return entry["hint"] if isinstance(entry, dict) else None

    def set_manual(self, name: str, raw: str) -> None:
        """Validate and store a user-provided hint; marks it as manual."""
        hint = raw.strip().split("\n")[0].strip()[:40]
        if not hint:
            return
        entry = self._hints.get(name, {})
        if isinstance(entry, dict) and entry.get("manual") and entry.get("hint") == hint:
            return
        self._hints[name] = {"hint": hint, "manual": True}
        self._persist()

    def clear(self, name: str) -> None:
        """Remove the hint for a workspace; auto-detection resumes next poll."""
        if name in self._hints:
            del self._hints[name]
            self._persist()

    def update_from_workspace(self, ws: Workspace) -> Optional[str]:
        """Derive the best user-facing hint for this poll cycle.

        Priority (user-facing, most to least specific):
          1. Manual hint  — explicit annotation set via CLI; always respected.
          2. Semantic diff hint — function/class names from the working-tree
             diff; display-only, never persisted, refreshes every cycle.
          3. Last git commit subject — static fallback; persisted as auto-hint
             so the hint survives after the repo becomes clean.
          4. Specific foreground command — only if not a generic tool name
             (see _GENERIC_CMDS); display-only.
        """
        self._maybe_reload()

        # 1. Manual hint
        entry = self._hints.get(ws.name)
        if isinstance(entry, dict) and entry.get("manual"):
            self._last_hint_type[ws.name] = "manual"
            return entry["hint"]

        # 2. Semantic working-tree diff (display-only; hints.json untouched)
        semantic = _git_semantic_hint(ws.path)
        if semantic:
            self._last_hint_type[ws.name] = "semantic_diff"
            return semantic

        # 3. Last commit subject (persisted so hint survives a clean tree)
        commit_hint = _git_last_commit(ws.path)
        if commit_hint:
            self._set_auto(ws.name, commit_hint)
            self._last_hint_type[ws.name] = "commit"
            return commit_hint

        # 4. Specific foreground command filtered for generic tools (display-only)
        cmd = _foreground_command(ws.tty, ws.pid)
        if cmd:
            self._last_hint_type[ws.name] = "foreground_cmd"
            return cmd

        stored = self.get(ws.name)
        self._last_hint_type[ws.name] = "commit" if stored else None
        return stored

    # ── Internal ──────────────────────────────────────────────────────────────

    def _maybe_reload(self) -> None:
        """Reload from disk if hints.json has been modified since last read."""
        try:
            mtime = os.path.getmtime(self._path)
            if mtime != self._mtime:
                self._hints = self._load()
                self._mtime = mtime
        except OSError:
            pass

    def _set_auto(self, name: str, hint: str) -> None:
        entry = self._hints.get(name)
        if isinstance(entry, dict) and entry.get("hint") == hint:
            return
        self._hints[name] = {"hint": hint, "manual": False}
        self._persist()

    def _load(self) -> dict[str, dict]:
        try:
            self._mtime = os.path.getmtime(self._path)
            with open(self._path) as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return {}
            # Only accept entries in the current dict format {hint, manual}.
            # Flat-string values from older versions (folder-name seeds) are
            # discarded — they were never meaningful resume hints.
            return {
                k: v
                for k, v in data.items()
                if isinstance(v, dict) and "hint" in v and "manual" in v
            }
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _persist(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True, mode=0o700)
            with open(self._path, "w") as fh:
                json.dump(self._hints, fh, indent=2)
            self._mtime = os.path.getmtime(self._path)
        except OSError:
            pass


_LAST_SEEN_PATH = os.path.join(_LOG_DIR, "last_seen.json")


class LastSeenStore:
    """
    Tracks the last Unix timestamp each workspace was seen by the detector.
    Persists to ~/.waypoint/last_seen.json so recency survives restarts.

    touch() is called every poll for open workspaces; writes to disk at most
    once per minute per workspace to keep I/O minimal.
    """

    def __init__(self, path: str = _LAST_SEEN_PATH) -> None:
        self._path  = path
        self._mtime: float = 0.0
        self._data: dict[str, float] = self._load()

    def touch(self, name: str) -> None:
        """Record that this workspace was just seen; persist if minute rolled over."""
        now  = time.time()
        prev = self._data.get(name, 0.0)
        self._data[name] = now
        if int(now // 60) != int(prev // 60):
            self._persist()

    def get(self, name: str) -> Optional[float]:
        self._maybe_reload()
        return self._data.get(name)

    def _maybe_reload(self) -> None:
        try:
            mtime = os.path.getmtime(self._path)
            if mtime != self._mtime:
                self._data  = self._load()
                self._mtime = mtime
        except OSError:
            pass

    def _load(self) -> dict[str, float]:
        try:
            self._mtime = os.path.getmtime(self._path)
            with open(self._path) as fh:
                data = json.load(fh)
            return {k: float(v) for k, v in data.items() if isinstance(v, (int, float))}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _persist(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True, mode=0o700)
            with open(self._path, "w") as fh:
                json.dump(self._data, fh, indent=2)
        except OSError:
            pass
