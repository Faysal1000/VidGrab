// Content-script entry point: wires the resolver and overlay together and
// answers requests from the popup / background.

(() => {
  // After the extension is reloaded or updated, the background injects this
  // script again into open tabs. Depending on the browser, the new copy may
  // share globals with the old one. Skip if a working copy is already running;
  // retire a copy that was cut off from the extension.
  const isAlive = () => {
    try {
      return Boolean(chrome.runtime?.getURL(""));
    } catch {
      return false; // "Extension context invalidated"
    }
  };
  const previous = globalThis.__vidgrabContent;
  if (previous?.isAlive()) return;
  previous?.retire();

  // Mirrors shared/messages.js (content scripts can't import ES modules).
  const MSG = {
    RESOLVE_ACTIVE_VIDEO: "vidgrab:resolve-active-video",
    OPEN_PANEL: "vidgrab:open-panel",
  };

  const { resolveVideo, resolveActive } = globalThis.VidGrabResolver;
  const panel = new VidGrabOverlay.Panel();
  const button = new VidGrabOverlay.DownloadButton((video) => panel.open(resolveVideo(video)));

  // A copy cut off by a reload/update can't open the panel any more: hide its
  // button (the freshly injected copy shows its own).
  const retire = () => {
    button.setEnabled(false);
    panel.close();
    document.removeEventListener("pointermove", retireIfOrphaned, true);
  };
  const retireIfOrphaned = () => {
    if (!isAlive()) retire();
  };
  document.addEventListener("pointermove", retireIfOrphaned, { capture: true, passive: true });
  globalThis.__vidgrabContent = { isAlive, retire };

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
