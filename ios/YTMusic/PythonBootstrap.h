#ifndef PythonBootstrap_h
#define PythonBootstrap_h

#import <Foundation/Foundation.h>

/// Initialize the embedded CPython runtime (isolated config, bundled stdlib +
/// app_packages + app). Safe to call once; returns 0 on success, non-zero on error.
int python_init(void);

/// Resolve a YouTube URL/ID to a JSON track dict (with a direct m4a stream_url).
/// Caller owns the returned C string (free it). Never returns NULL.
char *python_resolve(const char *url);

/// Keyword search → JSON list of lite track dicts {id,title,uploader,duration,thumbnail}.
/// source is "yt", "ytm", or "both". Caller owns the returned C string (free it).
char *python_search(const char *query, const char *source);

/// Resolve a YouTube/YT-Music URL (playlist or single video) → JSON list of lite dicts.
/// Caller owns the returned C string (free it). Never returns NULL.
char *python_browse(const char *url);

#endif /* PythonBootstrap_h */
