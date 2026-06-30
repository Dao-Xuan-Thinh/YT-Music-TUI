#import "PythonBootstrap.h"
#import <Python/Python.h>

static int g_initialized = 0;

static char *dup_cstr(NSString *s) {
    return strdup([s UTF8String]);
}

int python_init(void) {
    if (g_initialized) {
        return 0;
    }

    PyStatus status;
    PyPreConfig preconfig;
    PyConfig config;

    NSString *resourcePath = [[NSBundle mainBundle] resourcePath];

    setenv("NO_COLOR", "1", 1);
    setenv("PYTHON_COLORS", "0", 1);

    PyPreConfig_InitIsolatedConfig(&preconfig);
    PyConfig_InitIsolatedConfig(&config);

    preconfig.utf8_mode = 1;
    config.buffered_stdio = 0;       // flush prints immediately to the log
    config.write_bytecode = 0;       // app bundle is read-only / signed
    config.install_signal_handlers = 0;  // don't fight the host app

    status = Py_PreInitialize(&preconfig);
    if (PyStatus_Exception(status)) {
        NSLog(@"[python] pre-init failed: %s", status.err_msg);
        PyConfig_Clear(&config);
        return 1;
    }

    // PYTHONHOME = <bundle>/python (where install_python staged the stdlib).
    NSString *pythonHome = [NSString stringWithFormat:@"%@/python", resourcePath];
    wchar_t *whome = Py_DecodeLocale([pythonHome UTF8String], NULL);
    status = PyConfig_SetString(&config, &config.home, whome);
    PyMem_RawFree(whome);
    if (PyStatus_Exception(status)) {
        NSLog(@"[python] set home failed: %s", status.err_msg);
        PyConfig_Clear(&config);
        return 2;
    }

    status = PyConfig_Read(&config);
    if (PyStatus_Exception(status)) {
        NSLog(@"[python] read config failed: %s", status.err_msg);
        PyConfig_Clear(&config);
        return 3;
    }

    status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) {
        NSLog(@"[python] init failed: %s", status.err_msg);
        return 4;
    }

    // Add app_packages (vendored deps) as a site dir, and app/ (our code) to sys.path.
    NSString *appPackages = [NSString stringWithFormat:@"%@/app_packages", resourcePath];
    NSString *appDir = [NSString stringWithFormat:@"%@/app", resourcePath];
    NSString *boot = [NSString stringWithFormat:
        @"import site, sys\n"
         "site.addsitedir(%@)\n"
         "sys.path.insert(0, %@)\n"
         "print('[python]', sys.version, flush=True)\n",
        [NSString stringWithFormat:@"'%@'", appPackages],
        [NSString stringWithFormat:@"'%@'", appDir]];
    if (PyRun_SimpleString([boot UTF8String]) != 0) {
        NSLog(@"[python] path bootstrap failed");
        return 5;
    }

    g_initialized = 1;
    // Release the GIL from this (init) thread so subsequent calls from any thread can
    // re-acquire it via PyGILState_Ensure. Without this, calling Python from a background
    // thread races the interpreter and crashes (e.g. a second resolve).
    PyEval_SaveThread();
    return 0;
}

// Call resolve.<func>(arg) -> str. Runs on a background thread, so acquire the GIL for
// the whole call. Caller owns the returned C string.
static char *call_str_func(const char *module, const char *func, const char *arg) {
    if (!g_initialized && python_init() != 0) {
        return dup_cstr(@"{\"_ok\": false, \"_error\": \"python_init failed\"}");
    }

    PyGILState_STATE gil = PyGILState_Ensure();
    char *out;

    PyObject *mod = PyImport_ImportModule(module);
    if (!mod) {
        PyErr_Print();
        PyGILState_Release(gil);
        return dup_cstr(@"{\"_ok\": false, \"_error\": \"import failed\"}");
    }
    PyObject *f = PyObject_GetAttrString(mod, func);
    PyObject *args = Py_BuildValue("(s)", arg);
    PyObject *res = f ? PyObject_CallObject(f, args) : NULL;

    if (res && PyUnicode_Check(res)) {
        const char *s = PyUnicode_AsUTF8(res);
        out = strdup(s ? s : "");
    } else {
        PyErr_Print();
        out = dup_cstr(@"{\"_ok\": false, \"_error\": \"call failed\"}");
    }

    Py_XDECREF(res);
    Py_XDECREF(args);
    Py_XDECREF(f);
    Py_XDECREF(mod);
    PyGILState_Release(gil);
    return out;
}

// Two-argument variant (e.g. resolve.search(query, source)).
static char *call_str_func2(const char *module, const char *func,
                            const char *a, const char *b) {
    if (!g_initialized && python_init() != 0) {
        return dup_cstr(@"{\"_ok\": false, \"_error\": \"python_init failed\"}");
    }
    PyGILState_STATE gil = PyGILState_Ensure();
    char *out;
    PyObject *mod = PyImport_ImportModule(module);
    if (!mod) {
        PyErr_Print();
        PyGILState_Release(gil);
        return dup_cstr(@"[]");
    }
    PyObject *f = PyObject_GetAttrString(mod, func);
    PyObject *args = Py_BuildValue("(ss)", a, b);
    PyObject *res = f ? PyObject_CallObject(f, args) : NULL;
    if (res && PyUnicode_Check(res)) {
        const char *s = PyUnicode_AsUTF8(res);
        out = strdup(s ? s : "");
    } else {
        PyErr_Print();
        out = dup_cstr(@"[]");
    }
    Py_XDECREF(res);
    Py_XDECREF(args);
    Py_XDECREF(f);
    Py_XDECREF(mod);
    PyGILState_Release(gil);
    return out;
}

char *python_resolve(const char *url) { return call_str_func("resolve", "resolve", url); }
char *python_search(const char *query, const char *source) {
    return call_str_func2("resolve", "search", query, source);
}
char *python_browse(const char *url) { return call_str_func("resolve", "browse", url); }
char *python_home(void) { return call_str_func("resolve", "home", ""); }
char *python_set_auth(const char *cookie) { return call_str_func("resolve", "set_auth", cookie); }
