import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { formatChange, hourRange, presetRange } from '@/lib/format';
import { AlertStatusBadge, SeverityBadge } from '@/components/AlertBadges';
import { SeriesChart } from '@/components/SeriesChart';
import { hoursFromForm } from '@/app/(console)/settings/BusinessSettings';

describe('report date presets', () => {
  it('computes inclusive ranges from the business-local today', () => {
    expect(presetRange('today', '2026-10-16')).toEqual(['2026-10-16', '2026-10-16']);
    expect(presetRange('yesterday', '2026-10-01')).toEqual(['2026-09-30', '2026-09-30']);
    expect(presetRange('7d', '2026-10-16')).toEqual(['2026-10-10', '2026-10-16']);
    expect(presetRange('month', '2026-10-16')).toEqual(['2026-10-01', '2026-10-16']);
    expect(presetRange('last_month', '2026-03-05')).toEqual(['2026-02-01', '2026-02-28']);
    expect(presetRange('last_month', '2026-01-10')).toEqual(['2025-12-01', '2025-12-31']);
  });

  it('formats period changes honestly', () => {
    expect(formatChange(null)).toBe('no earlier data');
    expect(formatChange(0)).toBe('no change');
    expect(formatChange(12.5)).toBe('+12.5%');
    expect(formatChange(-3)).toBe('-3%');
    expect(hourRange(23)).toBe('23:00–00:00');
  });
});

describe('alert badges', () => {
  it('pair severity colour with an icon and a word', () => {
    const { container } = render(<SeverityBadge severity="high" />);
    expect(screen.getByText('High')).toBeInTheDocument();
    expect(container.querySelector('svg')).not.toBeNull();
    render(<AlertStatusBadge status="dismissed" />);
    expect(screen.getByText('Dismissed')).toBeInTheDocument();
  });
});

describe('SeriesChart', () => {
  it('shows an empty-state message and an accessible table', () => {
    render(
      <SeriesChart
        ariaLabel="Entries by weekday"
        series={[{ key: 'entries', label: 'Entries', color: '#256abf' }]}
        data={[{ label: 'Mon', values: { entries: 0 } }]}
        emptyText="Nothing yet"
      />,
    );
    expect(screen.getByText('Nothing yet')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Entries by weekday' })).toBeInTheDocument();
    expect(screen.getByRole('table', { hidden: true })).toBeInTheDocument();
  });

  it('draws a legend only for two series', () => {
    const series = [
      { key: 'entries', label: 'Entries', color: '#256abf' },
      { key: 'exits', label: 'Exits', color: '#eb6834' },
    ];
    const { container } = render(<SeriesChart ariaLabel="By day" series={series} data={[{ label: '1 Oct', values: { entries: 3, exits: 1 } }]} />);
    expect(container.querySelector('.chart-legend')).not.toBeNull();
    expect(container.querySelectorAll('path').length).toBe(2);
  });
});

describe('business hours form', () => {
  it('only sends open days', () => {
    const closed = { open: false, from: '09:00', to: '21:00' };
    const hours = hoursFromForm({
      name: 'x', address: '', capacity: '', hoursEnabled: true, is_active: true,
      hours: { mon: { open: true, from: '09:00', to: '21:00' }, tue: closed, wed: closed, thu: closed, fri: { open: true, from: '18:00', to: '02:00' }, sat: closed, sun: closed },
    });
    expect(hours).toEqual({ mon: [['09:00', '21:00']], fri: [['18:00', '02:00']] });
  });
});
