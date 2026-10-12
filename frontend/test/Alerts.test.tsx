import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { AlertCard } from '../components/AlertCard';
import { AlertList } from '../components/AlertList';
import { IncidentDetail } from '../components/IncidentDetail';
import { ReviewActions } from '../components/ReviewActions';
import { initialMockAlerts } from '../data/mockAlerts';
import { AlertFilterState } from '../types/alert';

describe('AlertCard Component', () => {
  const sampleAlert = initialMockAlerts[0];

  it('renders alert event type, camera id, floor and severity', () => {
    const onSelect = vi.fn();
    render(<AlertCard alert={sampleAlert} isSelected={false} onSelect={onSelect} />);

    expect(screen.getByText('Physical Altercation')).toBeInTheDocument();
    expect(screen.getByText('CAM-F1-CORR-04')).toBeInTheDocument();
    expect(screen.getByText('Floor 1')).toBeInTheDocument();
    expect(screen.getByText('CRITICAL')).toBeInTheDocument();
    expect(screen.getByText('pending')).toBeInTheDocument();
  });

  it('calls onSelect when clicked', () => {
    const onSelect = vi.fn();
    render(<AlertCard alert={sampleAlert} isSelected={false} onSelect={onSelect} />);

    const card = screen.getByRole('button', { name: /Alert ALT-PG-2026-081/i });
    fireEvent.click(card);
    expect(onSelect).toHaveBeenCalledWith(sampleAlert);
  });
});

describe('AlertList Filtering and States', () => {
  const defaultFilters: AlertFilterState = {
    status: 'all',
    severity: 'all',
    floor: 'all',
    searchQuery: '',
    startDate: '',
    endDate: '',
  };

  it('renders all mock alerts and count tabs', () => {
    render(
      <AlertList
        alerts={initialMockAlerts}
        selectedAlertId={null}
        filters={defaultFilters}
        isLoading={false}
        isError={false}
        isOffline={false}
        onSelectAlert={vi.fn()}
        onFilterChange={vi.fn()}
        onResetFilters={vi.fn()}
      />
    );

    expect(screen.getByText('All Alerts')).toBeInTheDocument();
    expect(screen.getByText('Pending')).toBeInTheDocument();
    expect(screen.getByText('Acknowledged')).toBeInTheDocument();
    expect(screen.getByText('Confirmed')).toBeInTheDocument();
    expect(screen.getByText('Dismissed')).toBeInTheDocument();
  });

  it('filters by status when pending tab is selected', () => {
    const pendingFilters: AlertFilterState = {
      ...defaultFilters,
      status: 'pending',
    };

    render(
      <AlertList
        alerts={initialMockAlerts}
        selectedAlertId={null}
        filters={pendingFilters}
        isLoading={false}
        isError={false}
        isOffline={false}
        onSelectAlert={vi.fn()}
        onFilterChange={vi.fn()}
        onResetFilters={vi.fn()}
      />
    );

    // Initial mock alerts has 3 pending alerts
    expect(screen.getByText('Physical Altercation')).toBeInTheDocument();
    expect(screen.getByText('Perimeter Breach')).toBeInTheDocument();
    expect(screen.queryByText('Suspicious Loitering')).not.toBeInTheDocument(); // was confirmed
  });

  it('renders loading shimmer skeletons when isLoading is true', () => {
    render(
      <AlertList
        alerts={initialMockAlerts}
        selectedAlertId={null}
        filters={defaultFilters}
        isLoading={true}
        isError={false}
        isOffline={false}
        onSelectAlert={vi.fn()}
        onFilterChange={vi.fn()}
        onResetFilters={vi.fn()}
      />
    );

    expect(document.getElementById('skeleton-cards-list')).toBeInTheDocument();
  });

  it('renders empty state when no alerts match filter and allows reset', () => {
    const onReset = vi.fn();
    const noMatchFilters: AlertFilterState = {
      ...defaultFilters,
      searchQuery: 'NonExistentCameraZone99',
    };

    render(
      <AlertList
        alerts={initialMockAlerts}
        selectedAlertId={null}
        filters={noMatchFilters}
        isLoading={false}
        isError={false}
        isOffline={false}
        onSelectAlert={vi.fn()}
        onFilterChange={vi.fn()}
        onResetFilters={onReset}
      />
    );

    expect(screen.getByText('No Security Alerts Found')).toBeInTheDocument();
    const resetBtn = screen.getByRole('button', { name: /Clear All Filters/i });
    fireEvent.click(resetBtn);
    expect(onReset).toHaveBeenCalled();
  });
});

describe('IncidentDetail & AI Fight-Classifier Output', () => {
  const sampleAlert = initialMockAlerts[0];

  it('displays CCTV video evidence area, camera id, floor, and location', () => {
    render(
      <IncidentDetail
        alert={sampleAlert}
        isLoading={false}
        isOffline={false}
        onUpdateStatus={vi.fn()}
      />
    );

    expect(screen.getByText('Physical Altercation Detected')).toBeInTheDocument();
    expect(screen.getAllByText(/CAM-F1-CORR-04/i)[0]).toBeInTheDocument();
    expect(screen.getByText('Floor 1')).toBeInTheDocument();
    expect(screen.getByText('Boys Wing Corridor near Room 112')).toBeInTheDocument();
  });

  it('prominently marks the fight-classifier score as model output requiring human review', () => {
    render(
      <IncidentDetail
        alert={sampleAlert}
        isLoading={false}
        isOffline={false}
        onUpdateStatus={vi.fn()}
      />
    );

    expect(screen.getByText('Fight-Classifier Model Output')).toBeInTheDocument();
    expect(screen.getByText('94.8%')).toBeInTheDocument();
    expect(
      screen.getByText(/\[AI MODEL OUTPUT - REQUIRES HUMAN REVIEW\]/i)
    ).toBeInTheDocument();
  });
});

describe('ReviewActions Component', () => {
  const sampleAlert = initialMockAlerts[0];

  it('allows clicking Confirm Incident and invokes callback with reviewer notes', async () => {
    const onUpdateStatus = vi.fn();
    render(
      <ReviewActions
        alert={sampleAlert}
        isOffline={false}
        onUpdateStatus={onUpdateStatus}
      />
    );

    const notesInput = screen.getByPlaceholderText(
      /Document incident verification rationale/i
    );
    fireEvent.change(notesInput, { target: { value: 'Guards dispatched immediately' } });

    const confirmBtn = screen.getByRole('button', { name: /Confirm Incident/i });
    fireEvent.click(confirmBtn);

    await waitFor(
      () => {
        expect(onUpdateStatus).toHaveBeenCalledWith(
          sampleAlert.id,
          'confirmed',
          'Guards dispatched immediately'
        );
      },
      { timeout: 1000 }
    );
  });

  it('disables review actions in offline mode', () => {
    render(
      <ReviewActions
        alert={sampleAlert}
        isOffline={true}
        onUpdateStatus={vi.fn()}
      />
    );

    expect(
      screen.getByText(/Console is currently in Offline Simulation mode/i)
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Acknowledge/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Confirm Incident/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Dismiss/i })).toBeDisabled();
  });
});
