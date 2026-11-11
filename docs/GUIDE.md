# VidGrab user guide

← [Back to README](../README.md)

- [Install details](#install-details)
- [Downloading](#downloading)
- [Updates](#updates)
- [Settings](#settings)
- [Troubleshooting](#troubleshooting)
- [Uninstall](#uninstall)
- [FAQ](#faq)

---

## Install details

The installer sets up Python, **yt-dlp** (download engine), **ffmpeg** (merging and conversion) and the
browser connection. It copies VidGrab to:

| OS | Install folder | Folder to "Load unpacked" |
|---|---|---|
| Windows | `%LOCALAPPDATA%\VidGrab` | `%LOCALAPPDATA%\VidGrab\extension` |
| macOS | `~/Library/Application Support/VidGrab` | `…/VidGrab/extension` |
| Linux | `~/.local/share/vidgrab` | `…/vidgrab/extension` |

**Notes**

- **Windows:** if asked *"Do you want to allow this app to make changes?"* (Python or ffmpeg), click **Yes**.
- **macOS:** to run the installer, open Terminal, type `cd ` (with a space), drag the folder into the window, press Enter, then run `bash install_mac.sh`.
- **Linux:** it may ask for your password to install `python3-venv` and `ffmpeg`.
- Load the extension **once in each browser** you use. On macOS quit the browser with `Cmd + Q` afterwards.
- Pin it: click the 🧩 puzzle icon in the toolbar, then the pin next to VidGrab.

Why "Load unpacked"? Browsers only allow one-click installs from their store, and the Chrome Web Store
doesn't allow YouTube downloaders.

---

## Downloading

There are three ways to start:

1. Hover a video and click **⬇ Download**.
2. Click the **VidGrab toolbar icon**. It picks the video that's playing.
3. Right-click a video or link and choose **Download video with VidGrab**.

| Option | Choices |
|---|---|
| Quality | 1080p (default), 720p, 480p…, or **Best**, which can be 4K and very large |
| Video format | **MP4** (plays everywhere), MKV, WebM |
| Audio only | MP3, M4A, WAV |

- **Only the video you're on** is downloaded, even when you opened it from a playlist.
- **Playlists:** when the video is part of a playlist, a **Download all N** button appears. It uses the
  same quality and format, and saves into a folder named after the playlist, with files numbered in
  playlist order. Private or removed videos are skipped.
- **Progress:** YouTube sends picture and sound separately, so you'll see `1/2 video` then `2/2 sound`.
  Both count toward one progress bar.
- **Instagram/Facebook feeds:** if the wrong video is picked, open the post or reel on its own page first.
- **Private videos** work when you're logged in to the site in the same browser.
- Downloads keep running when you close the panel or switch to another app. Click **Show** or the
  notification to open the file.

---

## Updates

| Situation | What to do |
|---|---|
| A site stopped working | Click **Update yt-dlp** in the panel footer (or in Settings). No reinstall needed. |
| New VidGrab version | Download it, run the installer again, then click **reload ↻** on VidGrab in the extensions page. |

Each computer updates its own copy.

Don't reload the extension while a download is running, because that cancels it.

---

## Settings

Open them with the ⚙ gear in the panel.

| Setting | What it does |
|---|---|
| Save to folder | Empty = Downloads. Or a full path like `~/Movies/VidGrab` or `C:\Users\you\Videos`. |
| Show download button on videos | Turn off to use only the toolbar icon or right-click menu. |
| Use my browser login | Needed for private or login-only videos (Instagram, Facebook…). |
| Also use my login for YouTube | Off by default. Only for age-restricted videos or "confirm you're not a bot". It can occasionally sign you out of YouTube. |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Finish setting up VidGrab" | Run the installer, then fully quit and reopen the browser. |
| Site stopped working / "Unsupported URL" | Click **Update yt-dlp**. |
| Instagram/Facebook "login required" | Log in to the site in this browser and keep **Use my browser login** on. |
| YouTube "confirm you're not a bot" | Turn on **Also use my login for YouTube**, and make sure you're signed in to YouTube. |
| Wrong video picked in a feed | Open the post or reel on its own page. |
| No ⬇ button | Reload the page (tabs opened before installing need a refresh), or use the toolbar icon. |
| Download is slow or huge | Pick **1080p** instead of **Best** (Best may be 4K). |
| "Manifest file is missing" | You picked the wrong folder. Choose the `extension` folder inside the install folder. |
| macOS: "…access files in your Downloads folder" | Click **Allow**. |
| Windows: "Windows protected your PC" | Click **More info → Run anyway**. |
| File won't play | Choose **MP4**. MKV/WebM may need [VLC](https://www.videolan.org/). |

Still stuck? Open an issue with the error message, and attach `logs/helper.log` from the install folder.

---

## Uninstall

1. Remove VidGrab on each browser's extensions page.
2. From the downloaded folder, run:
   - Windows: `install_windows.bat --uninstall`
   - macOS: `bash install_mac.sh --uninstall`
   - Linux: `bash install_linux.sh --uninstall`

Python and ffmpeg stay installed.

---

## FAQ

**Is it safe?**
All the code is in this repo. There are no servers and no tracking. Files go straight from the site to your computer.

**What does "Use my browser login" do?**
For the site you're downloading from only, VidGrab passes that site's login cookies to its helper on
your own computer. They're stored in a temporary file that's deleted after the download.

**Why does it need an installer?**
Extensions can't download most videos on their own. VidGrab uses [yt-dlp](https://github.com/yt-dlp/yt-dlp),
which runs as a small program on your computer, and the browser only starts it while you're downloading.

**Firefox, Safari or phones?**
Not supported.
