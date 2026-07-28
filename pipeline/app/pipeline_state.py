import threading

# in-memory only, deliberately not persisted anywhere - if the process
# restarts mid-run (a deploy, a crash), _running resets to False
# automatically rather than getting permanently stuck "running" forever
_lock = threading.Lock()
_running = False
_last_result = None  # None | 'success' | 'error'
_last_error = None
_last_details = None  # row counts from the last successful run


def try_start():
    """Atomically claim the run slot. Returns True if this call starts a
    new run, False if one is already in progress."""
    global _running, _last_result, _last_error, _last_details
    with _lock:
        if _running:
            return False
        _running = True
        _last_result = None
        _last_error = None
        _last_details = None
        return True


def finish(result, error=None, details=None):
    global _running, _last_result, _last_error, _last_details
    with _lock:
        _running = False
        _last_result = result
        _last_error = error
        _last_details = details


def snapshot():
    with _lock:
        return {
            'running': _running,
            'last_result': _last_result,
            'last_error': _last_error,
            'last_details': _last_details,
        }
