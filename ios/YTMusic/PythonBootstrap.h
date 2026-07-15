#ifndef PythonBootstrap_h
#define PythonBootstrap_h

#import <Foundation/Foundation.h>

/// Initialize the embedded CPython runtime (isolated config, bundled stdlib +
/// app_packages + app). Safe to call once; returns 0 on success, non-zero on error.
int python_init(void);

/// Resolve a YouTube URL/ID to a JSON track dict (with a direct m4a stream_url).
/// Caller owns the returned C string (free it). Never returns NULL.
char *python_resolve(const char *url);

/// Playback-failure re-resolve: skips the anonymous mobile clients (whose URLs
/// just 403'd) and goes straight to the default web/tv clients, signed-in when
/// possible. Caller owns the returned C string (free it). Never returns NULL.
char *python_resolve_fresh(const char *url);

/// Keyword search → JSON list of lite track dicts {id,title,uploader,duration,thumbnail}.
/// source is "yt", "ytm", or "both". Caller owns the returned C string (free it).
char *python_search(const char *query, const char *source);

/// Resolve a YouTube/YT-Music URL (playlist or single video) → JSON list of lite dicts.
/// Caller owns the returned C string (free it). Never returns NULL.
char *python_browse(const char *url);

/// "For You" home feed → JSON list of lite track dicts. Caller owns the returned C string.
char *python_home(void);

/// Set (or clear, with "") the account session from a cookie string. Returns JSON
/// {"ok":bool,"name":string} — the signed-in account display name. Caller owns the string.
char *python_set_auth(const char *cookie);

/// Top artist match for a query → JSON {name,channelId,thumbnail} or {}. Caller owns it.
char *python_search_artist(const char *query);

/// Artist page for a channelId → JSON {name,thumbnail,subscribers,sections:[…]}. Caller owns it.
char *python_artist(const char *channel_id);

/// Album tracks for a browseId → JSON list of lite song dicts. Caller owns it.
char *python_album(const char *browse_id);

/// Real durations for a comma-separated videoId list → JSON {id:seconds}. Caller owns it.
char *python_durations(const char *ids_csv);

/// Lyrics for a videoId → JSON {ok,synced,lines,text,source}. Caller owns the string.
char *python_lyrics(const char *video_id);

/// Translate `text` to language `target` → JSON {ok,text}. Caller owns the returned string.
char *python_translate(const char *text, const char *target);

/// Endless mix seeded from a videoId → JSON list of lite track dicts. Caller owns it.
char *python_radio(const char *video_id);

/// The recent Python-side engine log as plain text (newest last). Caller owns it.
char *python_get_log(void);

#endif /* PythonBootstrap_h */
