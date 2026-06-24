# Signing in to your YouTube account

The app can sign into your Google/YouTube account so it shows **personalized**
content (your "For You" home feed, and personalized search ranking). It uses
Google's **OAuth device flow** — you never type your Google password into the app;
you authorize it in a browser and the app stores a refresh token locally
(`oauth.json`, which is gitignored).

Because Google retired the shared credentials `ytmusicapi` used to ship with, you
provide **your own** OAuth client. It's free and takes ~5 minutes, once.

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
