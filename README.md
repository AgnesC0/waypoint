# Waypoint

A floating window that remembers where you left off across coding projects.

![Waypoint Demo](waypoint_demo.gif)

## Why

When working across multiple terminals and AI coding sessions, it's easy to forget:

- Which project am I in?
- What was I doing?
- Which terminal should I return to?

Waypoint keeps that context visible.

## Features

- Automatically detects active coding projects
- Remembers where you left off
- One-click jump back to the correct terminal
- Marks recently ended sessions
- Reduces context switching

## Install

```bash
git clone https://github.com/AgnesC0/waypoint
cd waypoint
pip install -r requirements.txt
python main.py
```

## Config

`config.yaml` is optional. Add entries to give projects friendly names:

```yaml
projects:
  - name: My App
    path: ~/code/my-app
```

## Local-first

- Runs locally
- No account required
- No cloud dependency
- Anonymous telemetry is optional and disabled by default

## Roadmap

- Better context recovery
- Smarter project hints
- Cross-platform improvements
- Team mode
