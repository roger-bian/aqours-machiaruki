import { useEffect, useRef, useState } from 'react';
import { useAuth0 } from '@auth0/auth0-react';
import { Toast } from './Toast';
import type { ToastVariant } from './Toast';
import { getFreshIdToken } from '../auth/freshIdToken';

const PIPELINE_BASE = import.meta.env.VITE_PIPELINE_API_BASE;
const POLL_INTERVAL_MS = 3000;
const TOAST_DURATION_MS = 5000;

const BUTTON_STYLE: React.CSSProperties = {
  position: 'fixed',
  top: 10,
  left: '50%',
  transform: 'translateX(-50%)',
  zIndex: 900,
  backgroundColor: 'white',
  padding: '8px 12px',
  borderRadius: 8,
  boxShadow: '0 2px 8px rgba(0, 0, 0, 0.3)',
  fontSize: 14,
  border: 'none',
  cursor: 'pointer',
  display: 'flex',
  alignItems: 'center',
  gap: 8,
};

type Status = 'idle' | 'checking';

// Triggers the pipeline's KML re-fetch/validate/upsert cycle. The backend
// (pipeline/app/main.py's POST /pipeline/run) does a fast lock-protected
// check-and-kickoff and returns immediately - the actual pipeline work runs
// afterward via FastAPI's BackgroundTasks, so this component polls
// GET /pipeline/status to learn when it finishes, rather than awaiting one
// long-lived request. This also means completion is detected the same way
// whether this click started the run, joined one already in progress, or
// (via the mount effect below) neither - some earlier, now-abandoned
// session's run is still going when this component first mounts.
export function RefreshDataButton() {
  const { getAccessTokenSilently, getIdTokenClaims, loginWithRedirect } = useAuth0();
  const [status, setStatus] = useState<Status>('idle');
  const [toast, setToast] = useState<{ variant: ToastVariant; message: string } | null>(null);
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const toastTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (pollTimeoutRef.current) clearTimeout(pollTimeoutRef.current);
      if (toastTimeoutRef.current) clearTimeout(toastTimeoutRef.current);
    };
  }, []);

  function showToast(variant: ToastVariant, message: string, reloadAfter = false) {
    if (toastTimeoutRef.current) clearTimeout(toastTimeoutRef.current);
    setToast({ variant, message });
    toastTimeoutRef.current = setTimeout(() => {
      setToast(null);
      if (reloadAfter) window.location.reload();
    }, TOAST_DURATION_MS);
  }

  async function authHeader() {
    const token = await getFreshIdToken({ getAccessTokenSilently, getIdTokenClaims, loginWithRedirect });
    return { Authorization: `Bearer ${token}` };
  }

  async function fetchStatus() {
    const res = await fetch(`${PIPELINE_BASE}/pipeline/status`, { headers: await authHeader() });
    if (!res.ok) throw new Error(`status check failed: ${res.status}`);
    return res.json() as Promise<{ running: boolean; last_result: 'success' | 'error' | null }>;
  }

  function pollUntilDone() {
    const poll = async () => {
      try {
        const s = await fetchStatus();
        if (s.running) {
          pollTimeoutRef.current = setTimeout(poll, POLL_INTERVAL_MS);
          return;
        }
        if (s.last_result === 'success') {
          showToast('success', '更新が完了しました。ページをリロードします。', true);
        } else {
          showToast('error', '更新中にエラーが発生しました。');
        }
      } catch {
        pollTimeoutRef.current = setTimeout(poll, POLL_INTERVAL_MS);
      }
    };
    poll();
  }

  // on mount: a run from some earlier, now-abandoned session may still be
  // in progress - regain visibility into it without requiring a click
  useEffect(() => {
    (async () => {
      try {
        const s = await fetchStatus();
        if (s.running) {
          showToast('info', '更新処理がすでに実行中です。しばらくお待ちください。');
          pollUntilDone();
        }
      } catch {
        // no auth yet / transient failure - a manual click still works
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleClick() {
    setStatus('checking');
    try {
      const res = await fetch(`${PIPELINE_BASE}/pipeline/run`, {
        method: 'POST',
        headers: await authHeader(),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail ?? `pipeline trigger failed: ${res.status}`);

      setStatus('idle');
      if (body.status === 'already_running') {
        showToast('info', '更新処理がすでに実行中です。しばらくお待ちください。');
      } else {
        showToast('info', 'データ更新を開始しました。しばらくお待ち下さい。');
      }
      pollUntilDone();
    } catch {
      setStatus('idle');
      showToast('error', '更新中にエラーが発生しました。');
    }
  }

  return (
    <>
      <button style={BUTTON_STYLE} onClick={handleClick} disabled={status === 'checking'}>
        {status === 'checking' && <span className="spinner" />}
        データ更新
      </button>
      {toast && <Toast variant={toast.variant} message={toast.message} />}
    </>
  );
}
