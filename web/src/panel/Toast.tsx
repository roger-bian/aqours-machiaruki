export type ToastVariant = 'info' | 'success' | 'error';

const COLORS: Record<ToastVariant, string> = {
  info: '#2563eb',
  success: '#16a34a',
  error: '#dc2626',
};

const TOAST_STYLE = (variant: ToastVariant): React.CSSProperties => ({
  position: 'fixed',
  bottom: 24,
  left: '50%',
  transform: 'translateX(-50%)',
  zIndex: 1000,
  backgroundColor: COLORS[variant],
  color: 'white',
  padding: '10px 20px',
  borderRadius: 20,
  textAlign: 'center',
  userSelect: 'none',
  boxShadow: '0 2px 8px rgba(0, 0, 0, 0.3)',
});

export function Toast({ variant, message }: { variant: ToastVariant; message: string }) {
  return <div style={TOAST_STYLE(variant)}>{message}</div>;
}
