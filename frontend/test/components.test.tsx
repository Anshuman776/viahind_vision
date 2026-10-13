import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EventsTable } from '@/components/EventsTable';
import { HourlyChart } from '@/components/HourlyChart';
import { CameraStatusBadge } from '@/components/Status';
import { mediaErrorMessage } from '@/components/CaptureProvider';
import type { SurveillanceEvent } from '@/lib/types';

const event = (over: Partial<SurveillanceEvent> = {}): SurveillanceEvent => ({
  id: '11111111-1111-1111-1111-111111111111',
  camera_id: 'CAM-1',
  camera_name: 'Main Entrance',
  occurred_at: '2026-10-12T03:12:15+00:00',
  event_type: 'entry',
  original_event_type: 'entry',
  person_label: 'Unknown Person 01',
  visit_id: 1,
  confidence: 0.81,
  has_snapshot: true,
  snapshot_status: 'saved',
  review_status: 'auto',
  match_status: 'not_applicable',
  uncertain_reason: null,
  notes: null,
  is_demo: false,
  ...over,
});

describe('EventsTable', () => {
  it('renders the required columns and values in site time', () => {
    render(<EventsTable events={[event()]} timezone="Asia/Kolkata" onOpen={() => {}} />);
    for (const col of ['Snapshot', 'Person label', 'Event', 'Date', 'Time', 'Camera', 'Review status']) {
      expect(screen.getByRole('columnheader', { name: col })).toBeInTheDocument();
    }
    expect(screen.getByText('Unknown Person 01')).toBeInTheDocument();
    expect(screen.getByText('08:42:15 AM')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Snapshot of Unknown Person 01' })).toHaveAttribute(
      'src',
      '/api/v1/events/11111111-1111-1111-1111-111111111111/snapshot',
    );
  });

  it('marks unmatched exits and missing snapshots without inventing images', () => {
    render(
      <EventsTable
        events={[event({ event_type: 'exit', match_status: 'unmatched', has_snapshot: false, review_status: 'needs_review' })]}
        timezone="UTC"
      />,
    );
    expect(screen.getByText('Unmatched')).toBeInTheDocument();
    expect(screen.getByText('No snapshot')).toBeInTheDocument();
    expect(screen.queryByRole('img')).toBeNull();
    expect(screen.getByText('Needs review')).toBeInTheDocument();
  });
});

describe('HourlyChart', () => {
  const empty = Array.from({ length: 24 }, (_, hour) => ({ hour, entries: 0, exits: 0 }));

  it('says when there is no data instead of drawing bars', () => {
    const { container } = render(<HourlyChart data={empty} />);
    expect(screen.getByText('No entries or exits recorded yet today.')).toBeInTheDocument();
    expect(container.querySelectorAll('path')).toHaveLength(0);
  });

  it('draws one bar per non-zero value, with an accessible table', () => {
    const data = empty.map((d) => (d.hour === 8 ? { ...d, entries: 3, exits: 1 } : d));
    const { container } = render(<HourlyChart data={data} />);
    expect(container.querySelectorAll('path')).toHaveLength(2);
    expect(screen.getByRole('table', { name: /entries and exits per hour/i })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: '8 AM' })).toBeInTheDocument();
  });
});

describe('status and camera errors', () => {
  it('labels camera states', () => {
    render(<CameraStatusBadge status="disconnected" />);
    expect(screen.getByText('Disconnected')).toBeInTheDocument();
  });

  it('explains camera permission problems', () => {
    expect(mediaErrorMessage({ name: 'NotAllowedError' })).toMatch(/permission was denied/);
    expect(mediaErrorMessage({ name: 'NotFoundError' })).toMatch(/No camera was found/);
    expect(mediaErrorMessage({ name: 'NotReadableError' })).toMatch(/in use by another application/);
  });
});
