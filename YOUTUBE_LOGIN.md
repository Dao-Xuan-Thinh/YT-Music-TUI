# Signing in to your YouTube account

The app can sign into your Google/YouTube account so it shows **personalized**
content (your "For You" home feed, and personalized search ranking). Open the
**Account** screen with the **`g`** key and pick a method.

> ### ⚠️ Which method? Use **Cookies**.
> YouTube Music's internal API currently **rejects OAuth tokens** from
> user-created Google Cloud clients (every call returns `HTTP 400 INVALID_ARGUMENT`).
> This is a known, Google-side limitation — not a bug in this app — and there's no
> client-side fix. **Cookie auth is the working method.** The OAuth flow is kept for
> when/if Google re-enables it, but expect it to fail today.

---

## A. Cookie auth (recommended — works today)

The app authenticates as your logged-in browser session (no password stored; it uses
your session cookies). You provide a **cookies.txt** exported while logged in to
music.youtube.com.

### 1. Export cookies.txt
- **Browser extension:** install "Get cookies.txt LOCALLY" (Chrome/Edge/Firefox), open
  <https://music.youtube.com> **while logged in**, click the extension → **Export** →
  save the `.txt` (Netscape format).
- **Or via yt-dlp:** `yt-dlp --cookies-from-browser chrome --cookies cookies.txt --skip-download "https://music.youtube.com"`
  (swap `chrome` for your browser).

The file must contain your `__Secure-3PAPISID` / `SAPISID` cookies (a logged-in export
does).

### 2. Use it in the app
Press **`g`** → put the cookies.txt path in the **Cookies** field → **Use these
cookies**. It verifies by fetching your account; on success it shows
**"Signed in as &lt;you&gt; ✓"**, the footer shows `cookies`, and your For You feed
personalizes. Re-export when the cookies eventually expire (months).

---

## B. OAuth (device login) — currently rejected by YT Music

Kept for completeness; **expect `HTTP 400` today**. If you still want to try it: Google
retired the shared credentials `ytmusicapi` used to ship with, so you provide **your
own** OAuth client (free, ~5 min).

---

## 1. Create a Google Cloud OAuth client (one-time)

1. Go to <https://console.cloud.google.com/> and sign in with the Google account
   you want to use.
2. **Create a project** (top bar → project dropdown → *New Project*). Name it
   anything, e.g. `ytm-tui`. Select it once created.
3. **Enable the API:** APIs & Services → *Library* → search **"YouTube Data API v3"**
   → open it → **Enable**.
4. **Configure the consent screen:** APIs & Services → *OAuth consent screen*.
   - User type: **External** → *Create*.
   - Fill in the required app name + your email; *Save and continue* through the
     Scopes step (no scopes needed) to *Test users*.
   - **Add your own Google email as a Test user.** *Save and continue.*
   - (Leaving the app in "Testing" mode is fine — you don't need to publish it.)
5. **Create the credential:** APIs & Services → *Credentials* → *Create Credentials*
   → **OAuth client ID**.
   - Application type: **TVs and Limited Input devices**.
   - Name it anything → *Create*.
6. Google shows a **Client ID** and **Client secret**. Keep them handy (you can
   reopen the credential later to copy them again).

---

## 2. Sign in from the app

1. Run the app and press **`g`** (Account).
2. Paste your **Client ID** and **Client secret** into the two fields.
3. Press **Log in**. The app shows a URL and a short code, e.g.:

   ```
   Go to  https://www.google.com/device
   Enter code:  ABCD-EFGH
   ```

4. Open that URL in any browser, sign in with the **same** Google account you added
   as a Test user, and enter the code. Approve the access request.
5. Back in the app, the screen flips to **Signed in ✓** and the footer shows
   `signed in`. Your **For You** tab on the home screen now reflects your account.

The token is saved to `oauth.json` next to the app and refreshes itself; you won't
need to repeat this unless you **Log out** (which deletes the token) or the token is
revoked.

---

## Troubleshooting

- **"OAuth client failure … YouTubeData API is not enabled"** — finish step 1.3
  (enable YouTube Data API v3) and double-check the client_id/secret match.
- **"access_denied"** in the browser — the Google account you authorized with isn't
  added as a **Test user** on the consent screen (step 1.4), or it's a different
  account than the one you intend to use.
- **Code expired** — the device code is short-lived; press **Log in** again to get a
  fresh one.
- Nothing personalized after signing in — the feed is fetched when the **home
  screen** opens; press `h` to return home and reload the For You tab.

---

## Privacy / security notes

- Your **password is never entered into the app** — authorization happens on
  Google's site.
- `oauth.json` (the refresh token) and `config.json` (which stores your client
  id/secret) are both **gitignored** and stay on your machine.
- The client_secret for a "Limited Input device" client is low-sensitivity, but
  treat it like any credential — don't paste it into shared logs.
- **Log out** (press `g` → *Log out*) removes the local token.
