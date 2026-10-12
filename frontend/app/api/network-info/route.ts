import { NextResponse } from 'next/server';
import os from 'os';

export interface NetworkInterfaceItem {
  name: string;
  address: string;
  family: string;
  isWifi: boolean;
  isVirtual: boolean;
}

export async function GET() {
  try {
    const interfaces = os.networkInterfaces();
    const candidates: NetworkInterfaceItem[] = [];

    for (const [name, addrs] of Object.entries(interfaces)) {
      if (!addrs) continue;
      const lowerName = name.toLowerCase();

      const isVirtual =
        lowerName.includes('vethernet') ||
        lowerName.includes('virtual') ||
        lowerName.includes('wsl') ||
        lowerName.includes('docker') ||
        lowerName.includes('vmware') ||
        lowerName.includes('tailscale') ||
        lowerName.includes('loopback');

      const isWifi =
        lowerName.includes('wi-fi') ||
        lowerName.includes('wifi') ||
        lowerName.includes('wlan') ||
        lowerName.includes('wireless');

      for (const addr of addrs) {
        if (addr.internal) continue;
        // Check IPv4
        const isIpv4 = addr.family === 'IPv4' || (addr.family as unknown) === 4;
        if (!isIpv4) continue;
        // Filter out APIPA / auto-configured link-local (169.254.x.x)
        if (addr.address.startsWith('169.254.')) continue;

        candidates.push({
          name,
          address: addr.address,
          family: 'IPv4',
          isWifi,
          isVirtual,
        });
      }
    }

    // Prioritize physical Wi-Fi first, then other non-virtual adapters, then virtual
    candidates.sort((a, b) => {
      if (a.isWifi && !b.isWifi) return -1;
      if (!a.isWifi && b.isWifi) return 1;
      if (!a.isVirtual && b.isVirtual) return -1;
      if (a.isVirtual && !b.isVirtual) return 1;
      return 0;
    });

    const primaryIp = candidates.length > 0 ? candidates[0].address : '127.0.0.1';

    return NextResponse.json({
      success: true,
      primaryIp,
      interfaces: candidates,
      hostname: os.hostname(),
    });
  } catch (error: any) {
    return NextResponse.json(
      {
        success: false,
        error: error.message || 'Failed to detect network interfaces',
        primaryIp: '127.0.0.1',
        interfaces: [],
      },
      { status: 500 }
    );
  }
}
