/**
 * Ornaments after Mughal architecture: the cusped (multifoil) arch of a pishtaq, drawn
 * in gold with a light that runs along it, and the eight-pointed star of its inlay work.
 * Decorative only: hidden from assistive technology.
 */

/** A cusped arch to frame a heading: an outer pointed arch, an inner multifoil line, a
 * finial with a star at the apex, and two slender minarets. */
export function MughalArch({ className = "" }: { className?: string }) {
  const outer =
    "M24 330 V150 C24 92 70 62 120 50 C160 40 186 30 200 8 C214 30 240 40 280 50 C330 62 376 92 376 150 V330";
  // Seven lobes along the inner arch, each a small arc between cusps.
  const inner =
    "M52 330 V158 A24 24 0 0 1 72 122 A28 28 0 0 1 108 94 A30 30 0 0 1 150 74 A28 28 0 0 1 200 46 A28 28 0 0 1 250 74 A30 30 0 0 1 292 94 A28 28 0 0 1 328 122 A24 24 0 0 1 348 158 V330";
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 400 340"
      preserveAspectRatio="none"
      className={`pointer-events-none text-signal ${className}`}
      fill="none"
    >
      <defs>
        <linearGradient id="arch-gold" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="currentColor" stopOpacity="0.95" />
          <stop offset="0.7" stopColor="currentColor" stopOpacity="0.35" />
          <stop offset="1" stopColor="currentColor" stopOpacity="0" />
        </linearGradient>
        <radialGradient id="arch-glow" cx="0.5" cy="0.2" r="0.6">
          <stop offset="0" stopColor="currentColor" stopOpacity="0.12" />
          <stop offset="1" stopColor="currentColor" stopOpacity="0" />
        </radialGradient>
      </defs>
      <path d={`${outer} Z`} fill="url(#arch-glow)" stroke="none" />
      <path className="arch-line" pathLength={1000} d={outer} stroke="url(#arch-gold)" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
      <path className="arch-line" pathLength={1000} d={inner} stroke="url(#arch-gold)" strokeWidth="0.9" vectorEffect="non-scaling-stroke" opacity="0.8" />
      <path className="arch-shimmer" pathLength={1000} d={outer} style={{ stroke: "rgb(var(--acid))" }} strokeWidth="1.6" vectorEffect="non-scaling-stroke" opacity="0.9" />
      {/* The finial: a stem and a star above the apex. */}
      <path d="M200 8 V-2" stroke="currentColor" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      {/* Minarets either side. */}
      <path d="M8 330 V120 M392 330 V120" stroke="url(#arch-gold)" strokeWidth="0.8" vectorEffect="non-scaling-stroke" />
      <circle cx="8" cy="114" r="3" stroke="currentColor" strokeWidth="0.8" vectorEffect="non-scaling-stroke" />
      <circle cx="392" cy="114" r="3" stroke="currentColor" strokeWidth="0.8" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/** The eight-pointed star (two squares, one turned 45°) with an emerald at its heart:
 * Atlas's mark. */
export function StarMark({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 32 32" className={className}>
      <defs>
        <linearGradient id="star-gold" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#f7e9c4" />
          <stop offset="0.5" stopColor="#d4af6a" />
          <stop offset="1" stopColor="#8f6626" />
        </linearGradient>
      </defs>
      <g fill="url(#star-gold)">
        <rect x="7" y="7" width="18" height="18" rx="1.5" />
        <rect x="7" y="7" width="18" height="18" rx="1.5" transform="rotate(45 16 16)" />
      </g>
      <circle cx="16" cy="16" r="5.2" style={{ fill: "rgb(var(--ink))" }} />
      <circle cx="16" cy="16" r="3.4" style={{ fill: "rgb(var(--acid))" }} />
    </svg>
  );
}

/** A small ornamental divider: a rule, a star, a rule. */
export function StarRule({ className = "" }: { className?: string }) {
  return (
    <span aria-hidden="true" className={`flex items-center gap-3 ${className}`}>
      <span className="h-px flex-1 bg-gradient-to-r from-transparent to-signal/60" />
      <StarMark className="h-3.5 w-3.5" />
      <span className="h-px flex-1 bg-gradient-to-l from-transparent to-signal/60" />
    </span>
  );
}
