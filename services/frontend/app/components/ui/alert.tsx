import { CircleCheck, Info, TriangleAlert } from 'lucide-react';
import type { ReactNode } from 'react';

export function Alert({
  children,
  tone = 'info',
  requestId,
}: {
  children: ReactNode;
  tone?: 'info' | 'error' | 'success';
  requestId?: string;
}) {
  const Icon = tone === 'error' ? TriangleAlert : tone === 'success' ? CircleCheck : Info;
  return (
    <div className={`alert alert-${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      <Icon size={22} aria-hidden="true" />
      <div>
        {children}
        {requestId && <span className="request-id">ID запроса: {requestId}</span>}
      </div>
    </div>
  );
}
