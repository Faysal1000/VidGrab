# VidGrab developer notes

← [Back to README](../README.md)

## How it works

```
┌────────────────────────┐  native messaging  ┌────────────────────────┐       ┌───────────────┐
│ Browser extension      │ ─────────────────► │ Python helper (venv)   │ ────► │ yt-dlp        │
│ button · panel · jobs  │ ◄───────────────── │ helper.py              │ ◄──── │ ffmpeg · deno │
└────────────────────────┘  progress / result └────────────────────────┘       └───────────────┘
```

- The browser starts the helper on demand, and it exits about 30 seconds after the last job. No network
  port is opened, and only this extension's ID may launch it.
- The extension ID (`gafplimobpeodpgeiamfedbhoodklmem`) is pinned by the `key` in `manifest.json`.
- The installer copies `helper/` and `extension/` to the per-user install folder. macOS blocks
  browsers from launching programs in Desktop, Documents or Downloads, and copying also lets users
  delete the download afterwards.
- `deno` (from PyPI, inside the venv) is the JavaScript runtime yt-dlp needs for YouTube.
- While downloads run, the service worker calls a trivial API every 20 seconds so the browser doesn't put it to sleep.

## Layout

```
extension/
  background/main.js          Message router, jobs, notifications, context menu, keep-alive
  background/native-host.js   Request/response client for the helper (one shared port)
  background/job-store.js     Jobs, mirrored to storage.session for the UI
  background/cookies.js       Cookies for the target site (opt-out in settings)
  content/resolver.js         Finds the right URL for a <video> (per-site SITE_RULES)
  content/overlay.js          Hover button + in-page panel (closed shadow DOM)
  content/main.js             Content-script entry point
  popup/                      Panel UI (toolbar popup and in-page iframe)
  options/                    Settings page
  shared/                     Message types, settings, formatting, theme.css
  icons/                      icon.svg + generated PNGs

helper/
  helper.py                   Entry point launched by the browser
  run_helper.sh / .bat        Run helper.py inside the venv
  requirements.txt            yt-dlp[default], deno
  vidgrab/protocol.py         Native-messaging framing (4-byte length + JSON)
  vidgrab/commands.py         ping, info, download, cancel, reveal, update
  vidgrab/ytdlp_runner.py     yt-dlp calls, playlist probe, progress, cancellation
  vidgrab/formats.py          Formats → choices, choices → yt-dlp options
  vidgrab/cookies.py          Cookies → temporary Netscape cookie file
  vidgrab/environment.py      Locates ffmpeg/deno, download folder, config

installer/install.py          Copy, venv, register browsers, self-test, uninstall
install_*.sh / .bat           OS wrappers (install Python/ffmpeg, then install.py)
tests/test_helper.py          Helper unit tests
tools/make_icons.py           Regenerate PNG icons from the glyph
```

## Workflow

```bash
python3 -m unittest discover tests     # unit tests (progress tests need yt-dlp)
python3 tools/make_icons.py            # regenerate icons
bash install_mac.sh                    # copy your changes into the install folder
```

Then click **reload ↻** on the extensions page, and reload open tabs if you changed content scripts.

## Common changes

- **Wrong video picked on a site:** add a rule to `SITE_RULES` in `extension/content/resolver.js`.
- **New format option:** `helper/vidgrab/formats.py` (summary + options) and the labels in `extension/popup/popup.js`.
- **Single video vs playlist:** single downloads use `noplaylist` + `playlist_items: "1"`. Playlist mode is
  `choice.playlist = true` (see `DownloadJob.run`).

## Debugging

- Helper log: `<install folder>/logs/helper.log`. It records each job's start, finish and failure,
  and notes when the browser disconnects mid-download. Reloading the extension clears the log and the
  downloads list, so each reload starts fresh.
- Extension: on the extensions page, click **Inspect views: service worker** on VidGrab.

## Credits

[yt-dlp](https://github.com/yt-dlp/yt-dlp) · [FFmpeg](https://ffmpeg.org/) · [Deno](https://deno.com/)
