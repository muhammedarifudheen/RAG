"use client";

import { useEffect, useMemo, useRef } from "react";

import { along, coil, ribbon, runs, spikes } from "@/lib/dragon";

/**
 * The dragons of Atlas, after Eastern dragons drawn in neon: a navy body of scales, a
 * glowing turquoise line along the belly, violet and pink flame fins, red eyes, a flowing
 * mane, swept horns and open jaws.
 * - DragonHead: a detailed head that crowns a page's heading, glancing towards the pointer.
 * - DragonPillar: the architecture, a temple column with a dragon coiled round it, passing
 *   behind the column and in front; two flank the home page like a gateway.
 * Decorative: hidden from assistive technology.
 */

export const NEON = {
  body: "#0f1838",
  bodyDeep: "#0a1029",
  scale: "#2bb8e6",
  belly: "#3ff0e0",
  pink: "#ff6aa8",
  violet: "#8a5cff",
  eye: "#ff3b5c",
  horn: "#bff6ff",
} as const;

/** Shared paint: the scale pattern, the glow, the gradients. */
function Paint({ id }: { id: string }) {
  return (
    <defs>
      <pattern id={`${id}-scales`} width="10" height="7" patternUnits="userSpaceOnUse">
        <rect width="10" height="7" fill={NEON.body} />
        <path d="M0 7 A5 5 0 0 1 10 7 M-5 3.5 A5 5 0 0 1 5 3.5 M5 3.5 A5 5 0 0 1 15 3.5" fill="none" stroke={NEON.scale} strokeOpacity="0.55" strokeWidth="0.7" />
      </pattern>
      <linearGradient id={`${id}-mane`} x1="0" y1="1" x2="0.4" y2="0">
        <stop offset="0" stopColor={NEON.violet} stopOpacity="0.85" />
        <stop offset="0.6" stopColor={NEON.pink} stopOpacity="0.7" />
        <stop offset="1" stopColor={NEON.belly} stopOpacity="0.5" />
      </linearGradient>
      <linearGradient id={`${id}-horn`} x1="0" y1="1" x2="0" y2="0">
        <stop offset="0" stopColor={NEON.scale} />
        <stop offset="1" stopColor={NEON.horn} />
      </linearGradient>
      <linearGradient id={`${id}-glass`} x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stopColor="#1a2a5e" stopOpacity="0.55" />
        <stop offset="0.45" stopColor="#3a58b0" stopOpacity="0.35" />
        <stop offset="0.55" stopColor="#9fe8ff" stopOpacity="0.25" />
        <stop offset="1" stopColor="#101a40" stopOpacity="0.6" />
      </linearGradient>
      <filter id={`${id}-glow`} x="-20%" y="-20%" width="140%" height="140%">
        <feGaussianBlur stdDeviation="2.4" result="blur" />
        <feMerge>
          <feMergeNode in="blur" />
          <feMergeNode in="SourceGraphic" />
        </feMerge>
      </filter>
    </defs>
  );
}

/** The head, facing right, its neck rising from the lower left. Drawn about the origin
 * (where the neck meets the head), some 230 wide and 230 tall. */
function HeadShape({ id, neck = true }: { id: string; neck?: boolean }) {
  return (
    <g strokeLinejoin="round" strokeLinecap="round">
      {/* The mane: flames streaming back from the head. */}
      <path
        d="M30 10 C0 6 -26 -10 -40 -40 C-24 -30 -12 -30 -2 -34 C-30 -50 -36 -78 -30 -104 C-18 -82 -4 -72 12 -68 C-4 -90 0 -116 16 -134 C20 -110 32 -96 48 -88 C44 -104 50 -118 64 -126 C62 -108 66 -92 74 -80 L62 -40 Z"
        fill={`url(#${id}-mane)`}
        stroke={NEON.pink}
        strokeOpacity="0.8"
        strokeWidth="1.2"
      />
      <path
        d="M20 -6 C-2 -18 -14 -44 -14 -70 M30 -26 C16 -48 18 -76 30 -100 M46 -48 C42 -70 48 -92 60 -108"
        fill="none"
        stroke={NEON.belly}
        strokeOpacity="0.55"
        strokeWidth="1"
      />
      {/* The neck, scaled, with its glowing belly line. */}
      {neck && (
        <>
          <path
            d="M38 2 C20 30 18 70 40 106 L-6 116 C-26 80 -22 34 2 4 Z"
            fill={`url(#${id}-scales)`}
            stroke={NEON.scale}
            strokeOpacity="0.8"
            strokeWidth="1.2"
          />
          <path d="M34 10 C22 38 22 72 38 102" fill="none" stroke={NEON.belly} strokeWidth="2.6" filter={`url(#${id}-glow)`} />
          <path
            d="M6 8 C-6 18 -14 22 -24 20 M-4 34 C-16 42 -24 44 -34 40 M-8 62 C-20 68 -28 70 -38 66 M-6 90 C-18 96 -26 98 -34 94"
            fill="none"
            stroke={NEON.violet}
            strokeWidth="2.2"
          />
        </>
      )}
      {/* Horns, swept back. */}
      <path d="M62 -40 C52 -72 30 -100 0 -120 C30 -96 46 -76 70 -44 Z" fill={`url(#${id}-horn)`} stroke={NEON.horn} strokeOpacity="0.7" strokeWidth="0.8" />
      <path d="M78 -42 C78 -78 66 -110 44 -136 C70 -112 86 -82 88 -44 Z" fill={`url(#${id}-horn)`} stroke={NEON.horn} strokeOpacity="0.7" strokeWidth="0.8" />
      {/* Skull and upper jaw. */}
      <path
        d="M38 -28 C58 -50 92 -50 110 -36 C120 -28 130 -24 146 -22 C156 -20 160 -12 154 -6 L124 -2 C110 0 94 2 80 8 C62 14 44 12 36 0 C30 -10 30 -20 38 -28 Z"
        fill={`url(#${id}-scales)`}
        stroke={NEON.scale}
        strokeWidth="1.4"
      />
      {/* Brow ridge and cheek, carved lines. */}
      <path d="M66 -38 C78 -46 92 -44 102 -34 M50 -10 C60 -4 72 -4 82 -10 M112 -30 C122 -26 132 -24 144 -24" fill="none" stroke={NEON.belly} strokeWidth="1.6" filter={`url(#${id}-glow)`} />
      {/* The mouth, open: its inside, then the lower jaw. */}
      <path d="M124 -2 L154 -6 C150 10 148 22 148 32 C126 20 100 14 80 8 C94 2 110 0 124 -2 Z" fill={NEON.pink} fillOpacity="0.55" />
      <path d="M80 8 C98 14 124 22 148 32 C140 38 122 38 106 36 C92 34 80 26 72 18 Z" fill={`url(#${id}-scales)`} stroke={NEON.scale} strokeWidth="1.3" />
      {/* Teeth and fangs. */}
      <path
        d="M128 -3 l3 9 l3 -9 Z M138 -4 l2.5 7 l2.5 -7 Z M146 -5 l2 6 l2 -6 Z M116 -1 l3 8 l3 -8 Z M110 28 l3 -8 l3 8 Z M122 31 l3 -8 l3 8 Z M134 33 l2.5 -7 l2.5 7 Z"
        fill="#f4fbff"
      />
      {/* Tongue. */}
      <path d="M132 12 C146 14 156 6 164 12 C158 14 152 20 142 18" fill="none" stroke={NEON.pink} strokeWidth="2" />
      {/* Nostril and eye: red, glowing. */}
      <circle cx="148" cy="-16" r="1.8" fill={NEON.bodyDeep} />
      <path d="M78 -30 C84 -36 94 -36 98 -28 C92 -24 84 -24 78 -30 Z" fill={NEON.eye} className="dragon-eye" filter={`url(#${id}-glow)`} />
      <ellipse cx="88" cy="-29.5" rx="1.3" ry="3.2" fill="#14040a" />
      {/* Beard and cheek tufts. */}
      <path d="M58 10 C50 26 60 38 48 52 M72 16 C68 32 78 42 70 58 M88 30 C88 44 96 50 92 62" fill="none" stroke={NEON.violet} strokeWidth="2" />
      {/* Whiskers, long and curling. */}
      <g className="dragon-whiskers">
        <path d="M152 -18 C176 -36 196 -14 186 6 C178 22 196 34 214 24" fill="none" stroke={NEON.pink} strokeWidth="1.6" />
        <path d="M140 30 C150 56 128 74 142 96 C150 108 166 104 170 94" fill="none" stroke={NEON.pink} strokeWidth="1.6" />
      </g>
    </g>
  );
}

/** A detailed head to crown a heading. It glances up or down towards the pointer. */
export function DragonHead({ className = "" }: { className?: string }) {
  const head = useRef<SVGGElement>(null);
  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const turn = (event: PointerEvent) => {
      const node = head.current;
      if (!node) return;
      const box = node.getBoundingClientRect();
      const tilt = Math.max(-8, Math.min(8, ((event.clientY - (box.top + box.height / 2)) / 500) * 12));
      node.setAttribute("transform", `rotate(${tilt.toFixed(1)} 60 0)`);
    };
    window.addEventListener("pointermove", turn);
    return () => window.removeEventListener("pointermove", turn);
  }, []);
  return (
    <svg aria-hidden="true" viewBox="-60 -150 290 280" className={`pointer-events-none overflow-visible ${className}`}>
      <Paint id="head" />
      <g ref={head}>
        <HeadShape id="head" />
      </g>
    </svg>
  );
}

/** A temple pillar with a dragon coiled round it, its head at the top facing the page.
 * `side` is which side of the page it stands on; the right one is mirrored. */
export function DragonPillar({ side, className = "" }: { side: "left" | "right"; className?: string }) {
  const id = `pillar-${side}`;
  const { back, front, belly, fins, head, claws } = useMemo(() => {
    const body = coil({ cx: 100, top: 200, bottom: 960, radius: 70, turns: 2.25, head: 42, tail: 4 });
    const parts = runs(body);
    // Legs where the body is in front of the column, gripping it: from the belly edge to
    // the column's face, three talons there.
    const legs = [0.3, 0.55, 0.8].flatMap((at) => {
      let i = Math.round(at * (body.length - 1));
      while (i < body.length - 1 && !body[i].front) i++;
      const s = body[i];
      if (!s?.front) return [];
      const fromX = s.x - (s.nx * s.w) / 2;
      const fromY = s.y - (s.ny * s.w) / 2;
      const footX = s.x > 100 ? 124 : 76;
      const footY = fromY + 18;
      return [{ fromX, fromY, footX, footY, key: at }];
    });
    return {
      claws: legs,
      back: parts.filter((r) => !r.front).map((r) => ribbon(r.samples)),
      front: parts.filter((r) => r.front).map((r) => ribbon(r.samples)),
      belly: parts.filter((r) => r.front).map((r) => along(r.samples, -0.3)),
      fins: parts.filter((r) => r.front).map((r) => spikes(r.samples, 6, 12)),
      head: body.at(-1)!,
    };
  }, []);
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 220 1000"
      preserveAspectRatio="xMidYMax meet"
      className={`pointer-events-none ${side === "right" ? "-scale-x-100" : ""} ${className}`}
    >
      <Paint id={id} />
      <defs>
        <linearGradient id={`${id}-belly`} x1="0" y1="1" x2="0" y2="0" gradientUnits="objectBoundingBox">
          <stop offset="0" stopColor={NEON.pink} />
          <stop offset="0.45" stopColor={NEON.belly} />
          <stop offset="1" stopColor={NEON.belly} />
        </linearGradient>
      </defs>
      {/* Behind the column: the coils it passes behind, dimmer. */}
      {back.map((d, i) => (
        <path key={`b${i}`} d={d} fill={`url(#${id}-scales)`} stroke={NEON.scale} strokeOpacity="0.4" strokeWidth="1" opacity="0.55" />
      ))}
      {/* The column: base, glass shaft with flutes, capital carved with clouds. */}
      <g>
        <path d="M58 960 H142 L152 984 H48 Z M40 984 H160 V1000 H40 Z" fill={NEON.bodyDeep} stroke={NEON.scale} strokeOpacity="0.7" />
        <rect x="70" y="200" width="60" height="760" fill={`url(#${id}-glass)`} stroke={NEON.scale} strokeOpacity="0.6" />
        <path d="M82 206 V954 M94 206 V954 M106 206 V954 M118 206 V954" stroke={NEON.horn} strokeOpacity="0.12" />
        <path d="M74 200 V960" stroke="#ffffff" strokeOpacity="0.28" strokeWidth="1.5" />
        <path d="M52 176 H148 L136 200 H64 Z" fill={NEON.bodyDeep} stroke={NEON.scale} strokeOpacity="0.8" />
        <path d="M44 160 H156 V176 H44 Z" fill={NEON.bodyDeep} stroke={NEON.violet} strokeOpacity="0.8" />
        <path d="M60 176 C66 168 76 168 80 176 M94 176 C100 168 110 168 114 176 M126 176 C132 168 142 168 146 176" fill="none" stroke={NEON.belly} strokeOpacity="0.7" />
        <path d="M36 148 H164 L156 160 H44 Z" fill={NEON.bodyDeep} stroke={NEON.pink} strokeOpacity="0.6" />
      </g>
      {/* In front: the coils, their fins, the glowing belly line. */}
      {fins.map((d, i) => (
        <path key={`f${i}`} d={d} fill={NEON.violet} fillOpacity="0.55" stroke={NEON.pink} strokeOpacity="0.8" strokeWidth="0.8" />
      ))}
      {front.map((d, i) => (
        <path key={`c${i}`} d={d} fill={`url(#${id}-scales)`} stroke={NEON.scale} strokeOpacity="0.85" strokeWidth="1.1" />
      ))}
      {belly.map((d, i) => (
        <path key={`l${i}`} d={d} fill="none" stroke={`url(#${id}-belly)`} strokeWidth="2.6" filter={`url(#${id}-glow)`} />
      ))}
      {/* Legs and claws gripping the column. */}
      {claws.map(({ fromX, fromY, footX, footY, key }) => {
        const side = footX < 100 ? -1 : 1;
        return (
          <g key={key} strokeLinecap="round" fill="none">
            <path
              d={`M${fromX} ${fromY} Q${(fromX + footX) / 2 + side * 10} ${fromY + 4} ${footX} ${footY}`}
              stroke={NEON.scale}
              strokeWidth="7"
            />
            <path
              d={`M${footX} ${footY} l${-side * 7} 7 M${footX} ${footY} l${-side * 2} 10 M${footX} ${footY} l${side * 4} 9`}
              stroke={NEON.pink}
              strokeWidth="2.4"
            />
          </g>
        );
      })}
      {/* The head, at the top of the coil, facing the page. */}
      <g transform={`translate(${head.x - 10} ${head.y - 2}) scale(0.58)`}>
        <HeadShape id={id} neck={false} />
      </g>
    </svg>
  );
}
