# Waypoint

**Know where you are. Always.**

You have multiple terminals open. Multiple repos. Multiple AI sessions running in parallel.
At some point, you stop and think: *"Wait — which project is this?"*

Waypoint answers that question automatically.

---

<!-- Demo GIF goes here -->

---

## Why

Modern development is fragmented.

You might have:

- 4 terminal windows across 3 repositories
- 2 Claude sessions mid-thought
- A build running somewhere you can't remember

Context switching has a cost. The small pause of re-orienting yourself — realizing you're in the wrong project, hunting for the right tab — adds up across a day.

Waypoint is a small floating indicator that lives quietly on your screen. It knows which project your active terminal belongs to. You don't have to ask.

---

## Features

- **Automatic detection** — reads your terminal's working directory, no manual tagging
- **Ambient HUD** — stays out of the way until you need it
- **Click to return** — click any workspace to jump directly to that terminal
- **Zero configuration overhead** — just list your project paths, nothing else required
- **Lightweight** — no background service, no daemon, no Electron
- **Cross-platform** — macOS (Terminal.app) and Windows (Windows Terminal, PowerShell, cmd)

---

## Quick Start

**1. Clone and install**

```bash
git clone https://github.com/Agneschen99/waypoint.git ~/waypoint
cd ~/waypoint && pip install -r requirements.txt
```

**2. Add your projects to `config.yaml`**

```yaml
projects:
  - name: My App
    path: ~/code/my-app
  - name: API Server
    path: ~/code/api-server
```

**3. Run**

```bash
python main.py
```

> On first run, macOS will ask for **Automation** permission to read terminal state.
> If the prompt doesn't appear, run: `osascript -e 'tell application "Terminal" to get name of windows'`

---

## Configuration

```yaml
projects:
  - name: My App         # display name in the HUD
    path: ~/code/my-app  # any subdirectory also matches

poll_interval: 2         # how often to scan (seconds)
opacity: 0.88            # HUD opacity: 0.0 (invisible) → 1.0 (solid)
position: bottom-right   # top-left | top-right | bottom-left | bottom-right
```

Drag the HUD anywhere on screen. Position persists between drags within a session.

---

## Auto-launch

To start Waypoint automatically with your shell:

```bash
echo 'source ~/waypoint/waypoint_launch.sh' >> ~/.zshrc
```

Spawns one instance per login session — safe to source from multiple tabs.

---

## Roadmap

- iTerm2 support
- Menu bar mode
- Session persistence across restarts
- Per-project active-time statistics

---

## License

MIT
