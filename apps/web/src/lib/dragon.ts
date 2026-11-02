/** Geometry for the dragons: a body as a tapering ribbon along a centre line, and the
 * coil of a dragon wound round a pillar, passing behind it and in front. */

export interface Point {
  x: number;
  y: number;
}

export interface Sample extends Point {
  /** Unit normal, pointing to the body's back (left of the direction of travel). */
  nx: number;
  ny: number;
  /** Unit tangent, from tail to head. */
  tx: number;
  ty: number;
  /** Width of the body here. */
  w: number;
  /** In front of the pillar (true) or behind it. */
  front: boolean;
}

const round = (value: number) => Math.round(value * 10) / 10;

/** The outline of a ribbon through `samples`: back edge forward, belly edge back. */
export function ribbon(samples: Sample[]): string {
  if (samples.length < 2) return "";
  const back = samples.map((s) => `${round(s.x + (s.nx * s.w) / 2)} ${round(s.y + (s.ny * s.w) / 2)}`);
  const belly = samples
    .map((s) => `${round(s.x - (s.nx * s.w) / 2)} ${round(s.y - (s.ny * s.w) / 2)}`)
    .reverse();
  return `M${back.join(" L")} L${belly.join(" L")} Z`;
}

/** A line along the body at `offset` (−0.5 the belly edge, 0.5 the back edge). */
export function along(samples: Sample[], offset: number): string {
  return (
    "M" +
    samples
      .map((s) => `${round(s.x + s.nx * s.w * offset)} ${round(s.y + s.ny * s.w * offset)}`)
      .join(" L")
  );
}

/** Spikes along the back: flame-like triangles every `every` samples. */
export function spikes(samples: Sample[], every: number, length: number): string {
  const parts: string[] = [];
  for (let i = every; i < samples.length - 1; i += every) {
    const s = samples[i];
    const half = s.w * 0.22;
    const bx = s.x + (s.nx * s.w) / 2;
    const by = s.y + (s.ny * s.w) / 2;
    const reach = length * (0.5 + s.w / 40);
    // Swept back, towards the tail, like fins in a current.
    const tipX = bx + s.nx * reach - s.tx * reach * 0.6;
    const tipY = by + s.ny * reach - s.ty * reach * 0.6;
    parts.push(
      `M${round(bx - s.tx * half)} ${round(by - s.ty * half)} Q${round(bx + s.nx * reach * 0.5)} ${round(
        by + s.ny * reach * 0.5,
      )} ${round(tipX)} ${round(tipY)} Q${round(bx + s.nx * reach * 0.3)} ${round(by + s.ny * reach * 0.3)} ${round(
        bx + s.tx * half,
      )} ${round(by + s.ty * half)} Z`,
    );
  }
  return parts.join(" ");
}

/** Contiguous runs of samples in front of the pillar, or behind it, each overlapping the
 * next by a sample so the body has no gaps. */
export function runs(samples: Sample[]): { front: boolean; samples: Sample[] }[] {
  const out: { front: boolean; samples: Sample[] }[] = [];
  for (let i = 0; i < samples.length; i++) {
    const s = samples[i];
    const last = out.at(-1);
    if (last && last.front === s.front) last.samples.push(s);
    else {
      const run = { front: s.front, samples: [s] };
      if (last) last.samples.push(s);
      out.push(run);
    }
  }
  return out;
}

/** A dragon wound round a pillar: from the tail at the foot to the head at the top.
 * `turns` coils, `radius` how far it swings either side of the pillar's axis `cx`. */
export function coil({
  cx,
  top,
  bottom,
  radius,
  turns,
  count = 260,
  head = 26,
  tail = 3,
}: {
  cx: number;
  top: number;
  bottom: number;
  radius: number;
  turns: number;
  count?: number;
  head?: number;
  tail?: number;
}): Sample[] {
  const points: (Point & { front: boolean; w: number })[] = [];
  for (let i = 0; i <= count; i++) {
    const t = i / count; // 0 at the tail, 1 at the head
    // Ends on the right of the pillar, at the top, facing the page.
    const phase = 2 * Math.PI * turns * (t - 1) + Math.PI / 2;
    const y = bottom - (bottom - top) * t;
    const x = cx + radius * Math.sin(phase);
    // Thick through the chest, tapering to the tail and a little to the neck.
    const w = tail + (head - tail) * Math.pow(Math.sin(Math.min(1, t * 1.15) * (Math.PI / 2)), 1.4);
    points.push({ x, y, w, front: Math.cos(phase) > 0 });
  }
  return points.map((p, i) => {
    const a = points[Math.max(0, i - 1)];
    const b = points[Math.min(points.length - 1, i + 1)];
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const length = Math.hypot(dx, dy) || 1;
    const tx = dx / length;
    const ty = dy / length;
    // The back: to the left of travel, which is up the pillar.
    return { ...p, tx, ty, nx: ty, ny: -tx };
  });
}
