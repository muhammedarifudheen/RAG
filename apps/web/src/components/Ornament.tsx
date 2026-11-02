import type { ReactNode } from "react";

/**
 * Mughal architecture as layout:
 * - the pishtaq: a rectangular frame (alfiz) inlaid with stone, around a pointed-arch
 *   recess whose spandrels carry geometric inlay; it frames each page's heading;
 * - the charbagh: a garden in four quadrants divided by water channels, a fountain where
 *   they cross; it lays out what Atlas reads;
 * - pietra dura: lapis, turquoise, jade, carnelian and gold set into dark stone, as a
 *   frieze and in the frame. Futuristic in finish: iridescent edges and light that flows.
 * Decorative parts are hidden from assistive technology.
 */

// The pietra dura stones.
export const STONES = {
  lapis: "#4a6dff",
  turquoise: "#2fd4d0",
  jade: "#34c88a",
  carnelian: "#ec5c4c",
  gold: "#f0ba4c",
  amethyst: "#a46eff",
} as const;

/** The eight-pointed star: gold and lapis squares, a jade heart. Atlas's mark. */
export function StarMark({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 32 32" className={className}>
      <defs>
        <linearGradient id="star-gold" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#fbe3a6" />
          <stop offset="1" stopColor="#c98a1e" />
        </linearGradient>
        <linearGradient id="star-lapis" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor={STONES.lapis} />
          <stop offset="1" stopColor={STONES.turquoise} />
        </linearGradient>
      </defs>
      <rect x="7" y="7" width="18" height="18" rx="1.5" fill="url(#star-lapis)" />
      <rect
        x="7"
        y="7"
        width="18"
        height="18"
        rx="1.5"
        fill="url(#star-gold)"
        opacity="0.92"
        transform="rotate(45 16 16)"
      />
      <circle cx="16" cy="16" r="5.4" style={{ fill: "rgb(var(--ink))" }} />
      <circle cx="16" cy="16" r="3.4" fill={STONES.jade} />
      <circle cx="16" cy="16" r="1.4" fill={STONES.carnelian} />
    </svg>
  );
}

/** A divider: an inlaid rule, a star, an inlaid rule. */
export function StarRule({ className = "" }: { className?: string }) {
  return (
    <span aria-hidden="true" className={`flex items-center gap-3 ${className}`}>
      <span className="inlay-rule h-[3px] flex-1" />
      <StarMark className="h-4 w-4" />
      <span className="inlay-rule h-[3px] flex-1 -scale-x-100" />
    </span>
  );
}

/** The pishtaq: an inlaid rectangular frame around a pointed-arch recess. */
export function Pishtaq({ children, className = "" }: { children: ReactNode; className?: string }) {
  // The recess: a four-centred pointed arch on straight jambs.
  const arch = "M26 300 V132 C26 70 96 42 200 14 C304 42 374 70 374 132 V300";
  // A cusped line inside it, lobes between cusps.
  const cusps =
    "M48 300 V150 A24 24 0 0 1 68 112 A28 28 0 0 1 104 84 A30 30 0 0 1 150 62 A28 28 0 0 1 200 38 A28 28 0 0 1 250 62 A30 30 0 0 1 296 84 A28 28 0 0 1 332 112 A24 24 0 0 1 352 150 V300";
  return (
    <div className={`pishtaq ${className}`}>
      <div className="pishtaq-recess">
        <svg
          aria-hidden="true"
          viewBox="0 0 400 300"
          preserveAspectRatio="none"
          className="pointer-events-none absolute inset-0 h-full w-full"
          fill="none"
        >
          <defs>
            <pattern id="spandrel" width="18" height="18" patternUnits="userSpaceOnUse">
              <path d="M9 1 L17 9 L9 17 L1 9 Z" stroke={STONES.gold} strokeOpacity="0.35" strokeWidth="0.6" />
              <circle cx="9" cy="9" r="2" fill={STONES.turquoise} fillOpacity="0.35" />
              <circle cx="0" cy="0" r="1.4" fill={STONES.carnelian} fillOpacity="0.4" />
              <circle cx="18" cy="18" r="1.4" fill={STONES.lapis} fillOpacity="0.5" />
            </pattern>
            <radialGradient id="recess-light" cx="0.5" cy="0.25" r="0.75">
              <stop offset="0" stopColor={STONES.turquoise} stopOpacity="0.16" />
              <stop offset="0.5" stopColor={STONES.lapis} stopOpacity="0.08" />
              <stop offset="1" stopColor={STONES.lapis} stopOpacity="0" />
            </radialGradient>
            <linearGradient id="arch-iris" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" stopColor={STONES.lapis} />
              <stop offset="0.3" stopColor={STONES.turquoise} />
              <stop offset="0.5" stopColor={STONES.gold} />
              <stop offset="0.7" stopColor={STONES.jade} />
              <stop offset="1" stopColor={STONES.carnelian} />
            </linearGradient>
          </defs>
          {/* Spandrels: the frame's corners outside the arch, inlaid. */}
          <path
            d="M0 0 H400 V300 H374 V132 C374 70 304 42 200 14 C96 42 26 70 26 132 V300 H0 Z"
            fill="url(#spandrel)"
          />
          <path d={`${arch} Z`} fill="url(#recess-light)" />
          <path d={arch} stroke="url(#arch-iris)" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
          <path
            d={cusps}
            stroke={STONES.gold}
            strokeOpacity="0.45"
            strokeWidth="0.8"
            vectorEffect="non-scaling-stroke"
          />
          {/* Light flowing along the arch. */}
          <path
            className="arch-flow"
            pathLength={1000}
            d={arch}
            stroke="#ffffff"
            strokeWidth="2"
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
        <div className="relative">{children}</div>
      </div>
    </div>
  );
}

export interface Quadrant {
  title: string;
  text: string;
  stone: keyof typeof STONES;
}

/** The charbagh: four quadrants, water channels between them, a fountain at the centre. */
export function Charbagh({ quadrants, label }: { quadrants: Quadrant[]; label: string }) {
  return (
    <section aria-label={label} className="charbagh relative mt-10 grid grid-cols-2 gap-5">
      <span aria-hidden="true" className="channel channel-v" />
      <span aria-hidden="true" className="channel channel-h" />
      {quadrants.map((quadrant) => (
        <div
          key={quadrant.title}
          className="glass relative overflow-hidden rounded-glass p-4 sm:p-5"
          style={{ ["--stone" as string]: STONES[quadrant.stone] }}
        >
          <span aria-hidden="true" className="quadrant-glow" />
          <p className="relative flex items-center gap-2 font-display text-lg font-semibold text-paper sm:text-xl">
            <span aria-hidden="true" className="quadrant-gem" />
            {quadrant.title}
          </p>
          <p className="relative mt-1.5 text-[13px] leading-snug text-soft">{quadrant.text}</p>
        </div>
      ))}
      <span aria-hidden="true" className="fountain">
        <StarMark className="h-9 w-9" />
      </span>
    </section>
  );
}
