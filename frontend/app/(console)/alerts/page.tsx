import AlertsView from './AlertsView';

// Client-rendered after the session check; see app/(console)/layout.tsx.
export const instant = false;

export default function Page() {
  return <AlertsView />;
}
