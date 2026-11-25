"""VidGrab native helper: bridges the browser extension to yt-dlp."""

__version__ = "1.0.1"

# Must match the "name" in the native-messaging host manifest.
HOST_NAME = "com.vidgrab.helper"

# GitHub repository whose Releases provide one-click updates ("owner/name").
# Forks: change this and UPDATE_REPO in extension/shared/messages.js.
UPDATE_REPO = "Faysal1000/VidGrab"
