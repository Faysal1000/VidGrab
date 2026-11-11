// Content-script entry point: wires the resolver and overlay together and
// answers requests from the popup / background.

(() => {
  if (globalThis.__vidgrabContentLoaded) return;
  globalThis.__vidgrabContentLoaded = true;

  // Mirrors shared/messages.js (content scripts can't import ES modules).
  const MSG = {
    RESOLVE_ACTIVE_VIDEO: "vidgrab:resolve-active-video",
    OPEN_PANEL: "vidgrab:open-panel",
  };

  const { resolveVideo, resolveActive } = globalThis.VidGrabResolver;
  const panel = new VidGrabOverlay.Panel();
  const button = new VidGrabOverlay.DownloadButton((video) => panel.open(resolveVideo(video)));

  // Remember what was right-clicked, for the context-menu entry.
  let lastContextTarget = null;
  document.addEventListener("contextmenu", (e) => { lastContextTarget = e.target; }, true);

  function targetFromContextMenu({ linkUrl }) {
    const video = lastContextTarget?.closest?.("video");
    if (video) return resolveVideo(video);
    if (linkUrl) return { url: linkUrl, direct: null, page: location.href };
    return resolveActive();
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === MSG.RESOLVE_ACTIVE_VIDEO) {
      sendResponse(resolveActive());
    } else if (message?.type === MSG.OPEN_PANEL) {
      panel.open(message.source === "context-menu" ? targetFromContextMenu(message) : resolveActive());
      sendResponse({ ok: true });
    }
    return false;
  });

  // The floating button follows the "showOverlayButton" setting live.
  chrome.storage.sync.get({ showOverlayButton: true }, ({ showOverlayButton }) => {
    button.setEnabled(showOverlayButton);
  });
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "sync" && "showOverlayButton" in changes) {
      button.setEnabled(changes.showOverlayButton.newValue !== false);
    }
  });
})();
