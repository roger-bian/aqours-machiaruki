import threading

# in-memory only, deliberately not persisted anywhere - if the process
# restarts mid-run (a deploy, a crash), _running resets to False
# automatically rather than getting permanently stuck "running" forever
_lock = threading.Lock()
_running = False
_last_result = None  # None | 'success' | 'error'
_last_error = None


def try_start():
    """Atomically claim the run slot. Returns True if this call starts a
    new run, False if one is already in progress."""
    global _running, _last_result, _last_error
    with _lock:
        if _running:
            return False
        _running = True
        _last_result = None
        _last_error = None
        return True


def finish(result, error=None):
    global _running, _last_result, _last_error
    with _lock:
        _running = False
        _last_result = result
        _last_error = error


def snapshot():
    with _lock:
        return {'running': _running, 'last_result': _last_result, 'last_error': _last_error}
