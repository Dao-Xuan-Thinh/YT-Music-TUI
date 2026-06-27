# Signing in to your YouTube account

The app can sign into your Google/YouTube account so it shows **personalized**
content (your "For You" home feed, and personalized search ranking). Open the
**Account** screen with the **`g`** key and pick a method.

> ### ⚠️ Which method? Use **Browser**.
> **Browser** sign-in reads your *live* music.youtube.com session straight from your
> browser at every launch, so it **never goes stale** while you stay logged in — no
> manual re-export. **Cookies** (a manual `cookies.txt` export) works too but expires
> and must be re-exported. **OAuth was removed** — YouTube rejects those tokens
> (`HTTP 400`), verified; it can't authenticate.

---

## A. Browser sign-in (recommended — durable)

The app reads the cookies of a logged-in **browser profile** directly (via yt-dlp), each
time it starts. No password is stored; nothing is exported by hand.

### 1. Be logged in to music.youtube.com in a supported browser
- **Firefox-family browsers work everywhere:** Firefox, **Zen**, LibreWolf, Waterfox.
  Their cookie store is unencrypted, so the app can read it.
- **Chromium browsers (Chrome / Edge / Brave) on Windows do NOT work:** they use
  *App-Bound Encryption*, which blocks any external app from decrypting their cookies
  (a known yt-dlp limitation — closing the browser doesn't help). On macOS/Linux they
  work. If you only have Chrome/Edge on Windows, use a Firefox-family browser (e.g. Zen)
  for the YouTube Music login, or fall back to **Cookies** (section B).

### 2. Pick your profile in the app
Press **`g`** → in the **Browser** section open the dropdown and choose your profile
(e.g. *Zen — &lt;your profile&gt;*) → **Sign in from browser**. The app reads the live
session in the background; on success the footer shows **♥ &lt;your name&gt;** and your
For You feed personalizes. It re-reads on every launch, so you stay signed in as long as
that browser profile stays logged in.

> The list shows detected Firefox-family profiles plus the standard Chromium browser
> names. If your browser isn't listed, make sure it's logged in to music.youtube.com and
> restart the app.

---

## B. Cookie auth (manual — works, but expires)

Authenticates as your logged-in browser session from a **cookies.txt** you export while
logged in to music.youtube.com. Same mechanism as Browser sign-in, but from a frozen
file — so the session eventually expires and you must re-export to renew.

### 1. Export cookies.txt
- **Browser extension:** install "Get cookies.txt LOCALLY" (Chrome/Edge/Firefox), open
  <https://music.youtube.com> **while logged in**, click the extension → **Export** →
  save the `.txt` (Netscape format).
- **Or via yt-dlp:** `yt-dlp --cookies-from-browser firefox --cookies cookies.txt --skip-download "https://music.youtube.com"`
  (swap `firefox` for your browser).

The file must contain your `__Secure-3PAPISID` / `SAPISID` cookies (a logged-in export
does).

### 2. Use it in the app
Press **`g`** → put the cookies.txt path in the **Cookies** field → **Use these
cookies**. The app signs in in the background; the footer shows **♥ &lt;you&gt;** on
success and your For You feed personalizes. Re-export when the cookies eventually expire.

> **These account cookies are used only for YouTube Music metadata/personalization —
> never for audio streaming.** An authenticated YouTube session makes the underlying
> yt-dlp extractor receive a format set it can't play (you'd get no audio and the queue
> skipping track-to-track), so streaming always stays anonymous. The separate
> *Streaming cookies* field in **Settings (`s`)** is only for age-restricted videos and
> is independent of sign-in.

---

## Troubleshooting

- **My Chrome/Edge profile isn't in the Browser list (or fails)** — on Windows these are
  blocked by App-Bound Encryption. Use a Firefox-family browser (e.g. Zen) for the YT
  Music login, or use Cookies (section B).
- **"sign-in expired — press g"** — the session is no longer valid. For Browser sign-in,
  re-open the browser/log back in; for Cookies, re-export cookies.txt.
- **Nothing personalized after signing in** — the feed is fetched when the **home
  screen** opens; press `h` to return home and reload the For You tab.

---

## Privacy / security notes

- Your **password is never entered into the app** — it only reads existing browser
  session cookies.
- `config.json` (which stores your chosen browser/profile or cookies path) is
  **gitignored** and stays on your machine. No cookie *values* are written to it.
- OAuth was removed from the UI because YouTube rejects the tokens; the `oauth.json`
  cache (if any from a past attempt) is gitignored and unused.
