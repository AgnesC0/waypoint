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

Waypoint reads your terminal's working directory and matches it against your configured projects. The result is a persistent floating panel showing every workspace at a glance — each one labeled with the last thing you were working on.

No manual tagging. No switching to a dashboard. No commands to memorize.

---

## Features

- **Automatic workspace detection** — knows which project your active terminal belongs to
- **Always-visible HUD** — a persistent panel, never hidden behind a click
- **Resume hints** — shows your last git branch per project so you re-enter the right mental context
- **Click to return** — click any workspace row to jump directly to that terminal
- **Session duration** — see at a glance how long you've been in the current project
- **Manual hint override** — set your own hint when git isn't enough
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

Waypoint remembers the last git branch you were working on for each project.
When you return to a workspace after an interruption, you see exactly where you left off.

```
Waypoint        · 42m
↳ fix resume hint logic

My App          · 3m
↳ auth refactor

API Server
↳ rate limiting
```

You can also set a hint manually from anywhere inside a project:

```bash
python main.py hint "redesigning onboarding flow"
```

Clear it to let git take over again:

```bash
python main.py hint --clear
```

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
