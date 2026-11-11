// UI injected into web pages: the floating "Download" button that appears
// over videos, and the panel (an iframe of popup.html) it opens.
// Everything lives in a closed shadow root so page CSS can't affect it.

(() => {
  if (globalThis.VidGrabOverlay) return;

  const Z_TOP = "2147483647";
  const HIDE_DELAY_MS = 500;
  const EXTENSION_ORIGIN = new URL(chrome.runtime.getURL("/")).origin;

  // Neumorphic pill: soft matte surface with a light/dark shadow pair, coral accent.
  const BUTTON_CSS = `
    :host { all: initial; }
    button {
      position: fixed; display: none; align-items: center; gap: 7px;
      padding: 8px 14px 8px 11px; border: 0; border-radius: 999px; cursor: pointer;
      font: 650 13px/1 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      color: #2c313c; background: #e7eaf0;
      box-shadow: 4px 4px 10px rgba(0,0,0,.28), -2px -2px 6px rgba(255,255,255,.55),
                  inset 1px 1px 0 rgba(255,255,255,.7);
      transition: transform .15s, box-shadow .15s, background .15s, color .15s;
      z-index: ${Z_TOP};
    }
    button.visible { display: inline-flex; }
    button svg { width: 16px; height: 16px; color: #ff6a3d; transition: color .15s; }
    button:hover {
      transform: translateY(-1px); color: #fff;
      background: linear-gradient(135deg, #ffa24c, #ff6a3d);
      box-shadow: 4px 6px 16px rgba(255,106,61,.45), inset 1px 1px 0 rgba(255,255,255,.35);
    }
    button:hover svg { color: #fff; }
    button:active { transform: none; box-shadow: inset 2px 2px 5px rgba(0,0,0,.2); }
    @media (prefers-color-scheme: dark) {
      button { color: #e8eaef; background: #2a2e36;
               box-shadow: 4px 4px 10px rgba(0,0,0,.45), -2px -2px 6px rgba(255,255,255,.06),
                           inset 1px 1px 0 rgba(255,255,255,.06); }
    }
  `;
  const DOWNLOAD_ICON = `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
         stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M12 3.5v11.5M7.5 10.5 12 15l4.5-4.5M4.5 13.5v2.5A3.5 3.5 0 0 0 8 19.5h8a3.5 3.5 0 0 0 3.5-3.5v-2.5"/>
    </svg>`;

  const PANEL_CSS = `
    :host { all: initial; }
    iframe {
      position: fixed; top: 16px; right: 16px; width: 380px; height: 520px;
      max-height: calc(100vh - 32px); max-width: calc(100vw - 32px);
      border: 0; border-radius: 24px; color-scheme: normal;
      box-shadow: 14px 18px 44px rgba(0,0,0,.35), -4px -4px 14px rgba(255,255,255,.08);
      z-index: ${Z_TOP}; background: transparent;
    }
  `;

  function createHost(css, html) {
    const host = document.createElement("vidgrab-ui");
    const shadow = host.attachShadow({ mode: "closed" });
    shadow.innerHTML = `<style>${css}</style>${html}`;
    return { host, shadow };
  }

  /** Re-parent our UI into the fullscreen element so it stays visible. */
  function mountPoint() {
    const fs = document.fullscreenElement;
    return fs && !(fs instanceof HTMLVideoElement) ? fs : document.documentElement;
  }

  class DownloadButton {
    #host;
    #button;
    #video = null;
    #hideTimer = null;
    #frame = 0;
    #enabled = false;
    #onClick;

    constructor(onClick) {
      this.#onClick = onClick;
      const { host, shadow } = createHost(BUTTON_CSS,
        `<button type="button" title="Download this video">${DOWNLOAD_ICON}<span>Download</span></button>`);
      this.#host = host;
      this.#button = shadow.querySelector("button");
      this.#button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (this.#video) this.#onClick(this.#video);
      });
      this.#button.addEventListener("pointerenter", () => this.#cancelHide());

      document.addEventListener("pointermove", (e) => this.#schedule(e.clientX, e.clientY),
        { passive: true, capture: true });
      addEventListener("scroll", () => this.#hide(), { passive: true, capture: true });
      document.addEventListener("fullscreenchange", () => this.#mount());
    }

    setEnabled(enabled) {
      this.#enabled = enabled;
      if (enabled) this.#mount();
      else this.#host.remove();
    }

    #mount() {
      if (this.#enabled) mountPoint().appendChild(this.#host);
    }

    #schedule(x, y) {
      if (!this.#enabled || this.#frame) return;
      this.#frame = requestAnimationFrame(() => {
        this.#frame = 0;
        this.#update(x, y);
      });
    }

    #update(x, y) {
      const video = this.#videoAt(x, y);
      if (!video) {
        this.#scheduleHide();
        return;
      }
      this.#cancelHide();
      this.#video = video;
      if (!this.#host.isConnected) this.#mount();
      const rect = video.getBoundingClientRect();
      this.#button.classList.add("visible");
      const width = this.#button.offsetWidth;
      this.#button.style.top = `${Math.max(rect.top, 0) + 12}px`;
      this.#button.style.left = `${Math.min(rect.right, innerWidth) - width - 12}px`;
    }

    #videoAt(x, y) {
      // Sites cover videos with transparent overlays, so hit-test by geometry
      // instead of relying on the element under the pointer.
      let best = null;
      for (const video of document.querySelectorAll("video")) {
        const r = video.getBoundingClientRect();
        if (x < r.left || x > r.right || y < r.top || y > r.bottom) continue;
        if (!VidGrabResolver.isLargeEnough(video)) continue;
        if (!best || r.width * r.height < best.area) best = { video, area: r.width * r.height };
      }
      return best?.video ?? null;
    }

    #scheduleHide() {
      if (this.#hideTimer) return;
      this.#hideTimer = setTimeout(() => this.#hide(), HIDE_DELAY_MS);
    }

    #cancelHide() {
      clearTimeout(this.#hideTimer);
      this.#hideTimer = null;
    }

    #hide() {
      this.#cancelHide();
      this.#button.classList.remove("visible");
      this.#video = null;
    }
  }

  class Panel {
    #host = null;
    #iframe = null;

    constructor() {
      addEventListener("message", (event) => {
        if (event.origin !== EXTENSION_ORIGIN || event.source !== this.#iframe?.contentWindow) return;
        if (event.data?.type === "vidgrab:close-panel") this.close();
        if (event.data?.type === "vidgrab:resize" && this.#iframe) {
          this.#iframe.style.height = `${Math.ceil(event.data.height)}px`;
        }
      });
      document.addEventListener("keydown", (e) => e.key === "Escape" && this.close(), true);
      document.addEventListener("pointerdown", (e) => {
        if (this.#host && !e.composedPath().includes(this.#host)) this.close();
      }, true);
    }

    /** @param {{url: string, direct?: string|null, page?: string, title?: string}} target */
    open(target) {
      this.close();
      const params = new URLSearchParams({ embedded: "1", url: target.url });
      if (target.direct) params.set("direct", target.direct);
      if (target.page) params.set("page", target.page);
      const { host, shadow } = createHost(PANEL_CSS, "<iframe allow=\"clipboard-write\"></iframe>");
      this.#iframe = shadow.querySelector("iframe");
      this.#iframe.src = chrome.runtime.getURL(`popup/popup.html?${params}`);
      this.#host = host;
      mountPoint().appendChild(host);
    }

    close() {
      this.#host?.remove();
      this.#host = null;
      this.#iframe = null;
    }
  }

  globalThis.VidGrabOverlay = { DownloadButton, Panel };
})();
