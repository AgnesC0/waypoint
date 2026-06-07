# Waypoint

![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-macOS-lightgrey.svg)

> A lightweight macOS HUD that tracks which Claude Code sessions belong to which project — and lets you jump back to them in one click.

---

## How it works

When you run `claude` in a Terminal window, Waypoint detects the process, resolves its working directory, and matches the path against your project list in `config.yaml`. A floating HUD shows every active Claude session with its project name, color, and folder. Click any entry to bring that Terminal window to the front.

```
╔══════════════════════╗
║ WAYPOINT             ║
╠══════════════════════╣
║▌ Project Alpha       ║  ← click to focus Terminal
║  code/project-alpha  ║
╠══════════════════════╣
║▌ Project Beta        ║
║  work/project-beta   ║
╚══════════════════════╝
```

---

## Features

- **Auto-detection** — finds every running `claude` process and resolves its working directory
- **Click to focus** — click a session row to bring that Terminal window to the front
- **Config-driven** — add projects by editing one YAML file, no code changes needed
- **Always-on-top HUD** — borderless, transparent, floats above all windows
- **Drag to reposition** — click-drag anywhere on the widget
- **Opacity control** — right-click to adjust transparency (50 / 75 / 90 / 100%)
- **Auto-launch** — optional shell hook starts Waypoint with every new terminal tab
- **Zero runtime dependencies** beyond PyYAML — tkinter, lsof, and osascript are all macOS built-ins

---

## Installation (5 minutes)

### 1. Prerequisites

- macOS 12 Ventura or later
- Python 3.10+ — check with `python3 --version`
- Claude Code CLI installed — check with `claude --version`

### 2. Clone

```bash
git clone https://github.com/Agneschen99/waypoint.git
cd waypoint
```

### 3. Install the one dependency

```bash
pip install -r requirements.txt
```

> Using a virtual environment is recommended:
> ```bash
> python3 -m venv .venv && source .venv/bin/activate
> pip install -r requirements.txt
> ```

### 4. Configure your projects

Open `config.yaml` and replace the example entries with your own:

```yaml
projects:
  - name: My Project
    keywords:
      - my-project       # matched against your working directory path
    color: "#7e3af2"
```

The keyword just needs to appear somewhere in the folder path where you run `claude`. If you work in `~/code/my-project`, the keyword `my-project` is all you need.

### 5. Run

```bash
python main.py
```

The HUD appears in the corner configured by `position` in `config.yaml`. Open a new terminal, `cd` into a project, and run `claude` — Waypoint will detect it within a few seconds.

---

## Auto-launch on every terminal tab

To have Waypoint start automatically whenever you open a new terminal:

```bash
echo 'source ~/waypoint/waypoint_launch.sh' >> ~/.zshrc
```

The launch script checks if Waypoint is already running before starting a new instance, so opening multiple tabs is safe.

---

## config.yaml reference

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `poll_interval` | float | `2` | Seconds between scans |
| `opacity` | float | `0.92` | Window opacity `0.0`–`1.0` |
| `position` | string | `bottom-right` | Starting corner: `top-left` `top-right` `bottom-left` `bottom-right` |
| `projects[].name` | string | — | Display name in the HUD |
| `projects[].keywords` | list | — | Substrings matched against the process working directory (case-insensitive) |
| `projects[].color` | string | — | Hex accent color for the stripe and top bar |

**Tips:**
- Keywords match against the full path (e.g. `/Users/you/code/project-alpha`), so any unique directory name or path fragment works.
- The first matching project wins — put more specific keywords earlier in the list.
- You can run `python -c "from detector import Detector; d=Detector([]); print(d._run(['lsof','-a','-p','$(pgrep -x claude)','-d','cwd','-Fn']))"` to inspect what paths are being detected.

---

## Supported environments

| Component | Supported | Notes |
|-----------|-----------|-------|
| Terminal.app | ✅ | Click-to-focus works |
| iTerm2 | 🔜 | Planned — process detection works, window focus not yet |
| Claude Code CLI | ✅ | Detects the `claude` process |
| macOS 12+ | ✅ | Requires Automation permission for Terminal |
| macOS 11 or older | ⚠️ | Untested |

---

## Permissions

On first run, macOS will ask for **Automation** permission so Waypoint can read Terminal window titles and focus windows via AppleScript. Grant it via:

**System Settings → Privacy & Security → Automation → Terminal → enable Terminal.app**

If the permission prompt doesn't appear, trigger it manually:

```bash
osascript -e 'tell application "Terminal" to get name of windows'
```

---

## Roadmap

- [ ] **iTerm2 support** — window focus via iTerm2's AppleScript dictionary
- [ ] **Menu bar / system tray mode** — live in the macOS menu bar using `rumps` instead of a floating window
- [ ] **Multiple terminal emulators** — Warp, Alacritty, Ghostty
- [ ] **Session timer** — track how long you've been active in each project
- [ ] **Notifications** — optional macOS notification when the active project changes
- [ ] **Cognitive scheduling integration** — designed as a sub-module that can be embedded into larger productivity or context-switching tools; `Detector` has no UI dependency

---

## Contributing

Pull requests are welcome. Please open an issue first for significant changes.

```bash
git checkout -b feat/my-feature
# make changes
git commit -m "feat: describe what and why"
git push origin feat/my-feature
# open a pull request
```

---

## License

[MIT](https://opensource.org/licenses/MIT) — use it, fork it, ship it.
