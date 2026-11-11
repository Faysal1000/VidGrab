// Figures out which URL to hand to yt-dlp for a given <video> element.
//
// Most sites play videos from blob: URLs, which can't be downloaded directly,
// so we look for the video's "permalink" (e.g. the /reel/ID link of the post
// that contains it). yt-dlp then fetches the real streams from that page.
//
// To support a new site, add an entry to SITE_RULES.

(() => {
  if (globalThis.VidGrabResolver) return;

  const MIN_VIDEO_WIDTH = 160;
  const MIN_VIDEO_HEIGHT = 90;
  const MAX_ANCESTOR_DEPTH = 15;

  function absolute(href) {
    try {
      const url = new URL(href, location.href);
      return /^https?:$/.test(url.protocol) ? url.href : null;
    } catch {
      return null;
    }
  }

  /**
   * Walk up from the video and return the first link matching `pattern`.
   * Stops once an ancestor contains more than one video, so in a feed we never
   * pick up a link that belongs to a neighbouring post.
   */
  function linkNear(video, pattern) {
    let node = video.parentElement;
    for (let depth = 0; node && depth < MAX_ANCESTOR_DEPTH; depth += 1) {
      if (node.querySelectorAll("video").length > 1) return null;
      for (const anchor of node.querySelectorAll("a[href]")) {
        if (pattern.test(anchor.getAttribute("href"))) return absolute(anchor.href);
      }
      if (node.tagName === "A" && pattern.test(node.getAttribute("href") || "")) {
        return absolute(node.href);
      }
      node = node.parentElement;
    }
    return null;
  }

  const pageMatches = (pattern) => pattern.test(location.pathname + location.search);

  const SITE_RULES = [
    {
      name: "youtube",
      hosts: /(^|\.)youtube\.com$/,
      resolve(video) {
        const onWatchPage = pageMatches(/^\/(watch|shorts\/|live\/)/);
        if (onWatchPage && video.closest("#movie_player, ytd-reel-video-renderer, ytd-shorts")) {
          return location.href;
        }
        // Hover previews on the home page / sidebar.
        return linkNear(video, /\/(watch\?v=|shorts\/)/);
      },
    },
    {
      name: "instagram",
      hosts: /(^|\.)instagram\.com$/,
      resolve(video) {
        // On /reels/ID and /p/ID pages the URL tracks the visible reel as you scroll.
        const permalink = /\/(reels?|p|tv)\/(?!audio\b)[\w-]{5,}/;
        if (pageMatches(permalink)) return location.href;
        return linkNear(video, permalink);
      },
    },
    {
      name: "facebook",
      hosts: /(^|\.)facebook\.com$/,
      resolve(video) {
        const permalink = /\/(videos|reel|watch)\/|[?&]v=\d+|\/share\/[vr]\//;
        if (pageMatches(permalink)) return location.href;
        return linkNear(video, permalink);
      },
    },
    {
      name: "x",
      hosts: /(^|\.)(twitter|x)\.com$/,
      resolve(video) {
        return linkNear(video, /\/status\/\d+/) || (pageMatches(/\/status\/\d+/) ? location.href : null);
      },
    },
    {
      name: "tiktok",
      hosts: /(^|\.)tiktok\.com$/,
      resolve(video) {
        if (pageMatches(/\/video\/\d+/)) return location.href;
        return linkNear(video, /\/video\/\d+/);
      },
    },
  ];

  function siteRule() {
    return SITE_RULES.find((rule) => rule.hosts.test(location.hostname));
  }

  function isLargeEnough(video) {
    const rect = video.getBoundingClientRect();
    return rect.width >= MIN_VIDEO_WIDTH && rect.height >= MIN_VIDEO_HEIGHT;
  }

  function visibleArea(element) {
    const rect = element.getBoundingClientRect();
    const width = Math.max(0, Math.min(rect.right, innerWidth) - Math.max(rect.left, 0));
    const height = Math.max(0, Math.min(rect.bottom, innerHeight) - Math.max(rect.top, 0));
    return width * height;
  }

  /** Candidate URLs for a video, best first. */
  function resolveVideo(video) {
    const fromRule = siteRule()?.resolve(video) ?? null;
    const src = video.currentSrc || video.src || "";
    const direct = /^https?:/.test(src) ? src : null;
    return {
      url: fromRule || location.href,
      direct,
      page: location.href,
      title: document.title,
    };
  }

  /** The video the user most likely means: playing first, then the most visible. */
  function findActiveVideo() {
    const videos = [...document.querySelectorAll("video")].filter(
      (v) => isLargeEnough(v) && visibleArea(v) > 0,
    );
    videos.sort((a, b) => {
      const playing = Number(!b.paused) - Number(!a.paused);
      return playing || visibleArea(b) - visibleArea(a);
    });
    return videos[0] ?? null;
  }

  /** Embedded players (YouTube/Vimeo iframes) when there's no <video> in this frame. */
  function findEmbed() {
    const frames = [...document.querySelectorAll("iframe[src]")]
      .filter((f) => /youtube(-nocookie)?\.com\/embed\/|player\.vimeo\.com\/video\//.test(f.src))
      .sort((a, b) => visibleArea(b) - visibleArea(a));
    return frames[0] ? absolute(frames[0].src) : null;
  }

  function resolveActive() {
    const video = findActiveVideo();
    if (video) return resolveVideo(video);
    const embed = findEmbed();
    return { url: embed || location.href, direct: null, page: location.href, title: document.title };
  }

  globalThis.VidGrabResolver = { resolveVideo, resolveActive, isLargeEnough };
})();
