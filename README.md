# Waypoint

**Always know where you are.**

You have five terminals open. Three AI sessions mid-thought. Two repositories in progress.
Then you pause and wonder: *which project is this?*

Waypoint answers that automatically — with a small floating panel that lives quietly on your screen.

---

<!-- Demo GIF -->

---

## Why

Modern development is fragmented by design.

You open a terminal for a feature branch. Then another for a quick bug fix. Then a third because the first one is running a build. An AI session spawns alongside each one. Repositories blur together.

At some point in the day, you find yourself staring at a prompt with no immediate memory of what you were doing there.

That moment of re-orientation is small. But it happens dozens of times a day.

Waypoint eliminates it.

---

## What it does

Waypoint is a lightweight floating HUD for terminal-based workspace context.

It detects open Terminal workspaces by reading the current working directory of each shell process — no keystrokes, no terminal output, no file contents are ever read. It shows only workspaces that are currently open, and identifies the truly active Terminal tab on macOS by comparing tty devices.

Each workspace row shows session duration, relative recency, and a resume hint. Resume hints are inferred from safe local signals in this order:

1. **Manual hint** — set explicitly via the CLI
2. **Semantic diff hint** — function or class names extracted from the current working-tree diff
3. **Last commit subject** — the most recent git commit message
4. **Foreground command** — a specific non-generic process running in that terminal (e.g. `pytest auth_test.py`)

Waypoint infers lightweight context from these signals. It does not understand everything you are doing, and it never reads your commands, keystrokes, or file contents.

---

## Features

- **Automatic workspace detection** — detects open workspaces by shell cwd; shows only currently open terminals
- **Active tab identification** — on macOS, identifies the focused Terminal tab via tty; on Windows, detects the focused terminal window (tab-level detection not yet implemented)
- **Always-visible HUD** — a persistent panel, never hidden behind a click
- **Resume hints** — inferred from git diff, last commit, or foreground command; manual override available
- **Click to return** — click any workspace row to jump directly to that terminal
- **Session duration** — see at a glance how long you've been in the current project
- **Manual hint override** — set your own hint when auto-detection isn't specific enough
- **Lightweight** — no daemon, no background service, no Electron
- **Cross-platform** — macOS and Windows

---

## Quick Start

```bash
git clone https://github.com/Agneschen99/waypoint.git ~/waypoint
cd ~/waypoint
pip install -r requirements.txt
```

Add your projects to `config.yaml`:

```yaml
projects:
  - name: My App
    path: ~/code/my-app
  - name: API Server
    path: ~/code/api-server
```

Run:

```bash
python main.py
```

> **macOS:** On first run, grant **Automation** permission when prompted.
> If the prompt doesn't appear: `osascript -e 'tell application "Terminal" to get name of windows'`

---

## Configuration

```yaml
projects:
  - name: My App          # display name shown in the HUD
    path: ~/code/my-app   # any subdirectory also counts as a match

poll_interval: 2          # seconds between workspace scans
opacity: 0.88             # 0.0 (invisible) → 1.0 (solid)
position: bottom-right    # top-left | top-right | bottom-left | bottom-right
```

Drag the HUD to any corner. Right-click for opacity options.

---

## Resume Hints

For each open workspace, Waypoint infers a resume hint from local signals. The hint priority is:

1. **Manual hint** — always respected; set via the CLI
2. **Semantic diff** — function/class names from the current working-tree diff (staged changes preferred)
3. **Last commit subject** — falls back here when the tree is clean
4. **Foreground command** — shown when a specific non-generic process is running (e.g. `pytest`)

```
Waypoint        · 42m
↳ improve semantic hint generation

My App          · 3m
↳ auth refactor

API Server
↳ rate limiting
```

Set a hint manually from anywhere inside a project:

```bash
python main.py hint "redesigning onboarding flow"
```

Clear it to let auto-detection resume:

```bash
python main.py hint --clear
```

Read the current hint without changing it:

```bash
python main.py hint
```

---

## Troubleshooting

If the HUD shows a stale workspace, wrong active tab, or unexpected hint, run:

```bash
python main.py status
```

This prints the live detection state for every open workspace — path, tty, pid, whether it matches the focused tab, the inferred hint, the stored hint, and last-seen recency.

---

## Auto-launch

Start Waypoint automatically with every new shell session:

```bash
echo 'source ~/waypoint/waypoint_launch.sh' >> ~/.zshrc
```

Safe to source from multiple tabs — only one instance runs per session.

---

## Roadmap

- iTerm2 support
- Menu bar mode
- Session persistence across restarts
- Per-project active-time statistics

---

## License

MIT
