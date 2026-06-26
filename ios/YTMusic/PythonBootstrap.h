#ifndef PythonBootstrap_h
#define PythonBootstrap_h

#import <Foundation/Foundation.h>

/// Initialize the embedded CPython runtime (isolated config, bundled stdlib +
/// app_packages + app). Safe to call once; returns 0 on success, non-zero on error.
int python_init(void);

/// Resolve a YouTube URL/ID to a JSON track dict (with a direct m4a stream_url).
/// Caller owns the returned C string (free it). Never returns NULL.
char *python_resolve(const char *url);

#endif /* PythonBootstrap_h */
