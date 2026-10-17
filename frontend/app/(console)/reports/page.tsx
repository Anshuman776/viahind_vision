import ReportsView from './ReportsView';

// Client-rendered after the session check; see app/(console)/layout.tsx.
export const instant = false;

export default function Page() {
  return <ReportsView />;
}
