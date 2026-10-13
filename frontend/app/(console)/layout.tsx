import { CaptureProvider } from '@/components/CaptureProvider';
import { SessionProvider } from '@/components/SessionProvider';
import { Shell } from '@/components/Shell';
import { SystemProvider } from '@/components/SystemProvider';

// Every console page renders on the client after the session check (all data is private and
// per-operator), so there is no static App Shell to validate for instant navigation.
export const instant = false;

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <SystemProvider>
        <CaptureProvider>
          <Shell>{children}</Shell>
        </CaptureProvider>
      </SystemProvider>
    </SessionProvider>
  );
}
