# paste-cli

A lightweight clipboard manager for macOS. Stores everything you copy, lets you search and re-paste from history.

## Install

```bash
uv tool install paste-cli
# or
pip install paste-cli
```

## Setup

```bash
pst start                # start the clipboard monitor
pst service install      # auto-start on login (never think about it again)
```

## Usage

Press **`Cmd+Ctrl+V`** to open the picker overlay.

```
┌──────────────────────────────────────────────────────────────┐
│  Clipboard          ⌕ Type to search…              7 items  │
│  [All]  Text   Image   File                                 │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│ │ console  │ │ function │ │ https:// │ │ import   │  ←→    │
│ │ .log(x)  │ │ getData  │ │ example  │ │ os       │        │
│ │          │ │ () {     │ │ .com/api │ │          │        │
│ │ 24 chars │ │ 89 chars │ │ 42 chars │ │ 1 file   │        │
│ │ TXT Term │ │ TXT Code │ │ TXT Chro │ │ FILE Fin │        │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘        │
│  ← → Navigate · Enter Paste · ⌘C Copy · Click Copy · Esc  │
└──────────────────────────────────────────────────────────────┘
```

| Action | What it does |
|--------|-------------|
| `← →` | Navigate cards |
| `Enter` | Copy + paste into the active app |
| `⌘C` | Copy to clipboard only |
| `Click` | Copy to clipboard only |
| `Tab` | Cycle filter (All / Text / Image / File) |
| Type | Search history |
| `Esc` | Close |

## CLI

```bash
pst list                    # show recent history
pst list -t image           # filter by type
pst list -a Chrome          # filter by app
pst search "TODO"           # search content
pst show 42                 # full details of an item
pst copy 42                 # re-copy item #42 to clipboard
pst pick                    # open the GUI picker
pst pick --tui              # terminal picker (curses)
pst stats                   # history stats
pst delete 42               # delete an item
pst clear                   # clear all history
```

## What it stores

- Text, images, and file paths (up to 100KB each)
- Source app name (e.g. "VS Code", "Chrome")
- Browser URL when copied from a browser
- Timestamp, use count

Stored in SQLite at `~/.pastepy/history.db`.

## Requirements

- macOS
- Python 3.12+
