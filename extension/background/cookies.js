// Collect this browser's cookies for a page so the helper can download
// logged-in content (private Instagram accounts, Facebook groups, ...).
// Cookies are sent only to the local helper and only for the target site.

const YOUTUBE_HOSTS = /(^|\.)(youtube\.com|youtu\.be|youtube-nocookie\.com)$/i;

const COOKIE_FIELDS = ["name", "value", "domain", "path", "secure", "hostOnly", "expirationDate"];

export async function cookiesFor(url, settings) {
  if (!settings.useCookies) return null;
  let host;
  try {
    host = new URL(url).hostname;
  } catch {
    return null;
  }
  if (YOUTUBE_HOSTS.test(host) && !settings.useCookiesForYouTube) return null;

  const cookies = await chrome.cookies.getAll({ url });
  if (!cookies.length) return null;
  return cookies.map((cookie) =>
    Object.fromEntries(COOKIE_FIELDS.map((field) => [field, cookie[field]])),
  );
}
