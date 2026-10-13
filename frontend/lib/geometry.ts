import type { EntranceLine } from './types';

export interface Point {
  x: number;
  y: number;
}

/**
 * Pixel-space geometry for drawing the entrance line: its endpoints, midpoint and an arrow
 * pointing to the "inside" side. Mirrors backend/vision/line_crossing.py: inside is the
 * left-hand normal of (x1,y1)->(x2,y2) when entry_side is +1, the right-hand normal when -1.
 */
export function lineGeometry(line: EntranceLine, width: number, height: number, arrowLength = 0.12) {
  const a = { x: line.x1 * width, y: line.y1 * height };
  const b = { x: line.x2 * width, y: line.y2 * height };
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.hypot(dx, dy) || 1;
  const sign = line.entry_side >= 0 ? 1 : -1;
  const normal = { x: (-dy / len) * sign, y: (dx / len) * sign };
  const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  const reach = Math.min(width, height) * arrowLength;
  return {
    a,
    b,
    mid,
    inside: { x: mid.x + normal.x * reach, y: mid.y + normal.y * reach },
    outside: { x: mid.x - normal.x * reach, y: mid.y - normal.y * reach },
    normal,
  };
}

export function clamp01(v: number): number {
  return Math.min(1, Math.max(0, v));
}

export function lineLength(line: Pick<EntranceLine, 'x1' | 'y1' | 'x2' | 'y2'>): number {
  return Math.hypot(line.x2 - line.x1, line.y2 - line.y1);
}
