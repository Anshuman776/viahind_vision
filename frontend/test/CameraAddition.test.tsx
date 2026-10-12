import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { CameraGrid } from '../components/CameraGrid';
import PhoneStreamerPage from '../app/streamer/page';

describe('CameraGrid & Multi-Floor Phone Camera Addition', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/network-info')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              success: true,
              primaryIp: '10.167.189.1',
              interfaces: [
                {
                  name: 'Wi-Fi',
                  address: '10.167.189.1',
                  family: 'IPv4',
                  isWifi: true,
                  isVirtual: false,
                },
              ],
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
      });
    });
  });

  it('renders the camera matrix with filter bar and connect phone camera button', () => {
    render(<CameraGrid />);

    expect(screen.getByText(/Filter by PG Floor/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /\+ Connect Phone Camera/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Floor 1' })).toBeInTheDocument();
  });

  it('opens modal, populates preset, and adds camera to the grid', async () => {
    render(<CameraGrid />);

    // Click + Connect Phone Camera
    const addBtn = screen.getByRole('button', { name: /\+ Connect Phone Camera/i });
    fireEvent.click(addBtn);

    // Modal should be visible
    expect(screen.getByText(/Connect Smartphone as CCTV Camera/i)).toBeInTheDocument();
    expect(screen.getByText(/SCAN TO CONNECT PHONE/i)).toBeInTheDocument();

    // Click Floor 1 West preset chip
    const f1WestPreset = screen.getByRole('button', { name: /Floor 1 West/i });
    fireEvent.click(f1WestPreset);

    // Inputs should be updated
    const idInput = screen.getByDisplayValue('CAM-F1-PHONE-02') as HTMLInputElement;
    expect(idInput).toBeInTheDocument();

    // Submit addition
    const submitBtn = screen.getByRole('button', { name: /Add Phone Camera Feed/i });
    fireEvent.click(submitBtn);

    // Modal should close and new camera should appear in grid
    await waitFor(() => {
      expect(screen.queryByText(/Connect Smartphone as CCTV Camera/i)).not.toBeInTheDocument();
    });

    expect(screen.getByText('CAM-F1-PHONE-02')).toBeInTheDocument();
  });

  it('filters cameras by selected floor', () => {
    render(<CameraGrid />);

    // Click Floor 1 filter button
    const floor1Btn = screen.getByRole('button', { name: /^Floor 1$/i });
    fireEvent.click(floor1Btn);

    // Should display Floor 1 cameras and hide cameras from other floors
    expect(screen.getByText('CAM-F1-PHONE-01')).toBeInTheDocument();
    expect(screen.queryByText('CAM-G-DINING-02')).not.toBeInTheDocument();
  });

  it('dynamically detects host IP without hardcoded 20.20.6.18, and matches QR with displayed URL', async () => {
    render(<CameraGrid />);

    const addBtn = screen.getByRole('button', { name: /\+ Connect Phone Camera/i });
    fireEvent.click(addBtn);

    // Wait for network-info to resolve
    await waitFor(() => {
      expect(screen.getByText('10.167.189.1')).toBeInTheDocument();
    });

    // Verify 20.20.6.18 is NEVER present
    expect(screen.queryByText(/20\.20\.6\.18/)).not.toBeInTheDocument();

    // Verify displayed URL contains the detected host and query parameters
    const urlDisplay = screen.getByText((content) =>
      content.includes('http://10.167.189.1:3000/streamer?id=CAM-PHONE-01')
    );
    expect(urlDisplay).toBeInTheDocument();
    const displayedUrl = urlDisplay.textContent || '';

    // Verify QR code encodes the exact displayed URL
    const qrImage = screen.getByAltText(/Scan QR code with phone/i) as HTMLImageElement;
    expect(qrImage).toBeInTheDocument();
    expect(qrImage.src).toContain(encodeURIComponent(displayedUrl));

    // Verify all query parameters are preserved in the URL
    expect(displayedUrl).toContain('id=CAM-PHONE-01');
    expect(displayedUrl).toContain('floor=Floor%201');
    expect(displayedUrl).toContain('name=My%20Phone%20Camera');
    expect(displayedUrl).toContain('loc=Corridor%20East');
  });

  it('allows manual host override and updates QR code and URL immediately', async () => {
    render(<CameraGrid />);

    const addBtn = screen.getByRole('button', { name: /\+ Connect Phone Camera/i });
    fireEvent.click(addBtn);

    await waitFor(() => {
      expect(screen.getByText('10.167.189.1')).toBeInTheDocument();
    });

    const overrideInput = screen.getByLabelText(/Manual Host Override/i) as HTMLInputElement;
    expect(overrideInput).toBeInTheDocument();

    // Type a custom override IP (e.g., 192.168.1.99)
    fireEvent.change(overrideInput, { target: { value: '192.168.1.99' } });

    // Displayed URL must immediately update to use the override
    await waitFor(() => {
      const updatedUrlDisplay = screen.getByText((content) =>
        content.includes('http://192.168.1.99:3000/streamer?id=CAM-PHONE-01')
      );
      expect(updatedUrlDisplay).toBeInTheDocument();
    });

    // QR code must encode the updated URL with the override
    const qrImage = screen.getByAltText(/Scan QR code with phone/i) as HTMLImageElement;
    expect(qrImage.src).toContain(encodeURIComponent('http://192.168.1.99:3000/streamer?id=CAM-PHONE-01'));

    // Reset button should be visible when override is active
    const resetBtn = screen.getByRole('button', { name: /Reset to Auto/i });
    expect(resetBtn).toBeInTheDocument();
    fireEvent.click(resetBtn);

    // After reset, URL should revert to detected 10.167.189.1
    await waitFor(() => {
      expect(
        screen.getByText((content) =>
          content.includes('http://10.167.189.1:3000/streamer?id=CAM-PHONE-01')
        )
      ).toBeInTheDocument();
    });
  });

  it('copies complete streamer URL with clipboard API', async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    render(<CameraGrid />);

    const addBtn = screen.getByRole('button', { name: /\+ Connect Phone Camera/i });
    fireEvent.click(addBtn);

    await waitFor(() => {
      expect(screen.getByText('10.167.189.1')).toBeInTheDocument();
    });

    const copyBtn = screen.getByRole('button', { name: /Copy streamer link/i });
    fireEvent.click(copyBtn);

    expect(writeTextMock).toHaveBeenCalledTimes(1);
    expect(writeTextMock).toHaveBeenCalledWith(
      expect.stringContaining('http://10.167.189.1:3000/streamer?id=CAM-PHONE-01')
    );

    // Button feedback changes to Copied
    await waitFor(() => {
      expect(screen.getByText(/Copied Link!/i)).toBeInTheDocument();
    });
  });

  it('renders network connectivity warning and allows expanding firewall instructions', () => {
    render(<CameraGrid />);

    const addBtn = screen.getByRole('button', { name: /\+ Connect Phone Camera/i });
    fireEvent.click(addBtn);

    // Warning banner should be present
    expect(
      screen.getByText(/Network Connectivity Notice: Same Wi-Fi Required/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Mobile Data \(4G\/5G\) will not work/i)
    ).toBeInTheDocument();

    // Toggle firewall setup instructions
    const firewallToggleBtn = screen.getByRole('button', {
      name: /View Windows Firewall & Port Setup/i,
    });
    fireEvent.click(firewallToggleBtn);

    // Firewall commands should be displayed
    expect(
      screen.getByText(/New-NetFirewallRule -DisplayName "VIAHIND Vision Frontend"/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/New-NetFirewallRule -DisplayName "VIAHIND Vision Backend"/i)
    ).toBeInTheDocument();
  });
});

describe('PhoneStreamerPage Query Parameter Ingestion', () => {
  it('pre-populates camera fields from URL parameters', async () => {
    // Simulate browser URL with deep-link query parameters
    delete (window as any).location;
    window.location = new URL(
      'http://10.167.189.1:3000/streamer?id=CAM-F1-PHONE-02&floor=Floor%201&name=Floor%201%20West&loc=Corridor%20West'
    ) as any;

    // Mock mediaDevices for jsdom
    Object.defineProperty(navigator, 'mediaDevices', {
      value: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: vi.fn() }],
        }),
      },
      writable: true,
    });

    render(<PhoneStreamerPage />);

    expect(screen.getByDisplayValue('CAM-F1-PHONE-02')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Floor 1 West')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Corridor West')).toBeInTheDocument();
  });
});
