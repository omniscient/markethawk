import React, { useEffect, useRef, useState } from 'react';
import { AlertCircle, ChevronDown, ChevronUp, ExternalLink, X } from 'lucide-react';

interface ServerErrorDetail {
  message: string;
  error_id: string | null;
  detail?: string | null;
  stack_trace?: string | null;
}

const SEQ_UI_BASE = import.meta.env.VITE_SEQ_UI_URL ?? 'http://localhost:5380';

function buildSeqLink(errorId: string): string {
  return `${SEQ_UI_BASE}/#/events?filter=ErrorId%3D'${errorId}'`;
}

export function GlobalErrorToast() {
  const [error, setError] = useState<ServerErrorDetail | null>(null);
  const [expanded, setExpanded] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const handleServerError = (e: Event) => {
      const detail = (e as CustomEvent<ServerErrorDetail>).detail;
      setError(detail);
      setExpanded(false);

      // Auto-dismiss after 20 s (longer so the user can read it)
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setError(null), 20_000);
    };

    window.addEventListener('server-error', handleServerError);
    return () => {
      window.removeEventListener('server-error', handleServerError);
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const dismiss = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setError(null);
  };

  if (!error) return null;

  const hasTrace = !!(error.stack_trace || error.detail);

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="fixed bottom-4 right-4 z-[9999] w-full max-w-md"
      style={{ fontFamily: 'Inter, system-ui, sans-serif' }}
    >
      <div
        style={{
          background: 'linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%)',
          border: '1px solid rgba(239,68,68,0.4)',
          borderLeft: '4px solid #ef4444',
          borderRadius: '12px',
          boxShadow: '0 25px 50px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.05)',
          overflow: 'hidden',
        }}
      >
        {/* Header row */}
        <div className="flex items-start gap-3 p-4">
          <div
            style={{
              background: 'rgba(239,68,68,0.15)',
              borderRadius: '8px',
              padding: '6px',
              flexShrink: 0,
            }}
          >
            <AlertCircle style={{ width: 18, height: 18, color: '#f87171' }} />
          </div>

          <div className="flex-1 min-w-0">
            <p style={{ color: '#f1f5f9', fontWeight: 600, fontSize: 14, margin: 0 }}>
              Server Error
            </p>
            <p style={{ color: '#94a3b8', fontSize: 13, margin: '2px 0 0', lineHeight: 1.4 }}>
              {error.message}
            </p>
          </div>

          <button
            onClick={dismiss}
            aria-label="Dismiss error notification"
            style={{
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: '#64748b',
              padding: 2,
              flexShrink: 0,
              lineHeight: 1,
            }}
            onMouseEnter={(e) => (e.currentTarget.style.color = '#cbd5e1')}
            onMouseLeave={(e) => (e.currentTarget.style.color = '#64748b')}
          >
            <X style={{ width: 16, height: 16 }} />
          </button>
        </div>

        {/* Error ID + Seq link */}
        {error.error_id && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              background: 'rgba(0,0,0,0.3)',
              borderTop: '1px solid rgba(255,255,255,0.06)',
              padding: '10px 16px',
              gap: 12,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
              <span
                style={{
                  fontSize: 11,
                  textTransform: 'uppercase',
                  letterSpacing: '0.08em',
                  color: '#64748b',
                  flexShrink: 0,
                }}
              >
                Error ID
              </span>
              <code
                style={{
                  fontFamily: 'monospace',
                  fontSize: 13,
                  color: '#f87171',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {error.error_id}
              </code>
            </div>

            <a
              href={buildSeqLink(error.error_id)}
              target="_blank"
              rel="noreferrer"
              id={`seq-link-${error.error_id}`}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                background: 'linear-gradient(135deg, #4f46e5, #7c3aed)',
                color: '#fff',
                fontSize: 12,
                fontWeight: 600,
                padding: '6px 12px',
                borderRadius: 6,
                textDecoration: 'none',
                flexShrink: 0,
                boxShadow: '0 2px 8px rgba(79,70,229,0.4)',
                transition: 'opacity 0.15s',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.opacity = '0.85')}
              onMouseLeave={(e) => (e.currentTarget.style.opacity = '1')}
            >
              Trace in Seq
              <ExternalLink style={{ width: 12, height: 12 }} />
            </a>
          </div>
        )}

        {/* Expandable dev detail / stack trace */}
        {hasTrace && (
          <>
            <button
              onClick={() => setExpanded((v) => !v)}
              style={{
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                background: 'transparent',
                border: 'none',
                borderTop: '1px solid rgba(255,255,255,0.06)',
                padding: '8px 16px',
                cursor: 'pointer',
                color: '#64748b',
                fontSize: 12,
              }}
              onMouseEnter={(e) => (e.currentTarget.style.color = '#94a3b8')}
              onMouseLeave={(e) => (e.currentTarget.style.color = '#64748b')}
            >
              <span>Developer details</span>
              {expanded ? (
                <ChevronUp style={{ width: 14, height: 14 }} />
              ) : (
                <ChevronDown style={{ width: 14, height: 14 }} />
              )}
            </button>

            {expanded && (
              <pre
                style={{
                  margin: 0,
                  padding: '12px 16px',
                  background: 'rgba(0,0,0,0.5)',
                  color: '#fca5a5',
                  fontSize: 11,
                  lineHeight: 1.6,
                  overflow: 'auto',
                  maxHeight: 260,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  borderTop: '1px solid rgba(255,255,255,0.06)',
                }}
              >
                {error.stack_trace ?? error.detail}
              </pre>
            )}
          </>
        )}
      </div>
    </div>
  );
}
