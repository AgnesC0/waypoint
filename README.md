# Waypoint

![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-macOS-lightgrey.svg)

> A lightweight macOS desktop widget that watches your browser tabs and shows which project's Claude conversation is currently active — as a floating, always-on-top HUD.

---

## What it does

Waypoint scans your open browser tabs every few seconds using AppleScript, matches tab titles against a list of keywords you configure, and displays the matching project name and color in a small floating window. No cloud sync, no account required — just a config file and a Python process.

---

## Features

- **Auto-detection** — reads tab titles from Chrome, Arc, and Safari in real time
- **Config-driven** — add any number of projects by editing one YAML file
- **Floating HUD** — borderless, always-on-top window that stays out of your way
- **Drag to reposition** — click and drag anywhere on the widget
- **Opacity control** — right-click to choose 50 / 75 / 90 / 100 %
- **Color accent** — each project gets its own accent color on the HUD
- **Zero dependencies beyond PyYAML** — tkinter ships with Python on macOS

---

## Quick start (under 5 minutes)

### 1. Prerequisites

- macOS 12 Ventura or later
- Python 3.10+ — check with `python3 --version`
- Chrome, Arc, or Safari with at least one tab open

### 2. Clone the repo

```bash
git clone https://github.com/your-username/waypoint.git
cd waypoint
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

> **Tip:** use a virtual environment to keep things tidy:
> ```bash
> python3 -m venv .venv && source .venv/bin/activate
> pip install -r requirements.txt
> ```

### 4. Grant Automation permissions

Waypoint uses AppleScript to read browser tab titles.
On first run macOS will ask for permission — click **OK** when prompted, or grant it manually:

**System Settings → Privacy & Security → Automation**
→ enable **Terminal** (or your IDE / launcher) → **Google Chrome / Arc / Safari**

### 5. Edit config.yaml

Open `config.yaml` and replace the example projects with your own:

```yaml
poll_interval: 2        # seconds between scans
opacity: 0.92           # window transparency (0.0–1.0)
position: bottom-right  # top-left | top-right | bottom-left | bottom-right

projects:
  - name: My Project
    keywords:
      - my-project
      - unique-slug
    color: "#7e3af2"
```

Any tab whose title contains one of the `keywords` (case-insensitive) will activate that project entry in the HUD.

### 6. Run

```bash
python main.py
```

A small floating window will appear in the corner you chose. Drag it anywhere, right-click for options, and it will update automatically as you switch tabs.

---

## config.yaml reference

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `poll_interval` | float | `2` | Seconds between tab scans |
| `opacity` | float | `0.92` | Window opacity, `0.0`–`1.0` |
| `position` | string | `bottom-right` | Starting corner: `top-left`, `top-right`, `bottom-left`, `bottom-right` |
| `projects[].name` | string | — | Display name shown in the HUD |
| `projects[].keywords` | list | — | Strings to match against tab titles (substring, case-insensitive) |
| `projects[].color` | string | — | Hex color for the accent bar and status dot |

**Keyword tips:**
- Use short, distinctive slugs that only appear in tabs related to that project.
- A Claude conversation titled `"Project Alpha — Claude"` matches the keyword `alpha`.
- Keywords are checked in order; the first project whose keyword matches wins.

---

## Project structure

```
waypoint/
├── main.py          # Entry point — loads config and starts the event loop
├── hud.py           # Floating HUD window (tkinter)
├── detector.py      # AppleScript-based browser tab scanner
├── config.yaml      # User configuration
├── requirements.txt
└── .gitignore
```

---

## Roadmap

- [ ] **More browsers** — Firefox (via native messaging), Brave, Edge
- [ ] **System tray / menu bar mode** — live in the macOS menu bar instead of a floating window using `rumps` or `PyObjC`
- [ ] **Linux / Windows support** — `xdotool` on Linux, `pygetwindow` on Windows
- [ ] **Notifications** — optional macOS notification when the active project changes
- [ ] **Sub-module integration** — designed to be embedded into larger productivity tools as a `detector` module; the `Detector` class has no UI dependency
- [ ] **Multiple simultaneous projects** — show a stacked list when several project keywords are active at once
- [ ] **Usage time tracking** — optional per-project timer that accumulates active seconds

---

## Contributing

Pull requests are welcome. Please open an issue first to discuss significant changes.

1. Fork the repo
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Commit your changes
4. Open a pull request

---

## License

[MIT](https://opensource.org/licenses/MIT) — use it, fork it, ship it.
