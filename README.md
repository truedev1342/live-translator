# Live Translator

Reads text from the **Windows 11 Live Captions** app and translates it in real
time. Two panes: the raw caption on the left, the translation on the right.
Pick a translation engine and a target language from the toolbar.

## How it works

Windows Live Captions has no text API, so the caption text is read from the
Windows **UI Automation** accessibility tree (via the `uiautomation` package)
in a background thread. New caption text is translated on a short debounce by
`deep-translator` (free, no key) or an official API if you supply a key.

## Requirements

- Windows 11 (Live Captions is a Windows 11 feature)
- Python 3.10+
- `pip install -r requirements.txt`

## Run

```powershell
pip install -r requirements.txt
python main.py
```

1. Click **Start**.
2. Turn on Live Captions with **Win + Ctrl + L** (keep the caption bar open).
3. Play audio / speak — the current caption appears on the left, its translation
   on the right (the panes show the live text, not the whole history).
4. Click **Stop** — the **full** session (everything from the start) is saved to
   `transcripts\transcript_<timestamp>.txt`, then memory is cleared so the next
   Start begins fresh. **Clear** discards the session without saving.

### Saved transcript

Each file records the engine/languages, then the full source captions and the
full translation:

```
Live Translator transcript — 2026-07-23 11:01:13
Engine: Google (free)  |  Auto detect -> Vietnamese

=== SOURCE (captions) ===
Hello everyone. Welcome to the show. ...

=== TRANSLATION ===
Xin chào tất cả mọi người. Chào mừng đến với chương trình. ...
```

Transcripts are saved next to the app (the `.exe`, or `main.py` in dev).

## Build a standalone .exe

No Python needed on the target machine — produce a single file:

```powershell
pip install -r requirements.txt pyinstaller
build_exe.bat
```

The result is **`dist\TYLT.exe`** (~60 MB, self-contained). Double-click to run.
Windows SmartScreen may warn on first launch because the exe is unsigned —
choose *More info → Run anyway*.

## Engines

| Engine                  | Key needed | Notes                                  |
|-------------------------|:----------:|----------------------------------------|
| Google (free)           | no         | Unofficial endpoint; rate-limited      |
| MyMemory (free)         | no         | Good fallback                          |
| Google Cloud (API key)  | yes        | Needs `google-cloud-translate` + key   |
| DeepL (API key)         | yes        | Highest quality for supported langs    |

For key-based engines, paste the key in the **API key** field (it appears only
when such an engine is selected).

## Notes / troubleshooting

- **"Live Captions window not found"** — Live Captions isn't running. Enable it
  with Win+Ctrl+L and leave the bar on screen (it can be minimized to the edge
  but must stay open).
- Free engines are rate-limited; for heavy/continuous use, add an API key.
- Source language defaults to **Auto detect**; target defaults to Vietnamese —
  change both in the toolbar.
