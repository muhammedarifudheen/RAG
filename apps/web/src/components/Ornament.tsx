"use client";

/**
 * Small pieces of the dragon look (the dragons themselves are in DragonArt):
 * - the mark, a dragon coiled round its pearl;
 * - the pearl alone, the sign that Atlas is thinking;
 * - a rule with the pearl at its centre, and glass cards lit in the dragon's colours.
 * Decorative: hidden from assistive technology. Still for viewers who reduce motion.
 */

// Its colours: jade, turquoise, violet, magenta, gold and flame.
export const SCALES = {
  jade: "#2ee59d",
  turquoise: "#33d6f0",
  violet: "#8b6cff",
  magenta: "#ff4fb3",
  gold: "#ffc44d",
  flame: "#ff7a3d",
} as const;

function Gradients({ id }: { id: string }) {
  return (
    <defs>
      <linearGradient id={`${id}-body`} x1="0" y1="1" x2="1" y2="0">
        <stop offset="0" stopColor={SCALES.jade} />
        <stop offset="0.25" stopColor={SCALES.turquoise} />
        <stop offset="0.5" stopColor={SCALES.violet} />
        <stop offset="0.75" stopColor={SCALES.magenta} />
        <stop offset="1" stopColor={SCALES.gold} />
      </linearGradient>
      <linearGradient id={`${id}-head`} x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor={SCALES.magenta} />
        <stop offset="0.6" stopColor={SCALES.gold} />
        <stop offset="1" stopColor={SCALES.flame} />
      </linearGradient>
      <radialGradient id={`${id}-pearl`} cx="0.38" cy="0.32" r="0.7">
        <stop offset="0" stopColor="#ffffff" />
        <stop offset="0.35" stopColor={SCALES.turquoise} />
        <stop offset="1" stopColor={SCALES.violet} stopOpacity="0.2" />
      </radialGradient>
    </defs>
  );
}

/** The mark: the dragon coiled round itself, its head at the gap. */
export function DragonMark({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 32 32" className={className} fill="none">
      <Gradients id="mark" />
      <circle cx="16" cy="16" r="10.5" stroke="url(#mark-body)" strokeWidth="4.5" strokeDasharray="56 10" strokeLinecap="round" transform="rotate(-62 16 16)" />
      <circle cx="16" cy="16" r="10.5" stroke="#ffffff" strokeOpacity="0.5" strokeWidth="0.8" strokeDasharray="1 3" transform="rotate(-62 16 16)" />
      {/* The head, at the top of the coil, and its eye. */}
      <path d="M20 3.5 C24 3 27.5 5 28.5 8 C26.5 8.5 24.5 8.2 23 9.6 C21.6 8 20.4 6.4 20 3.5 Z" fill="url(#mark-head)" />
      <circle cx="24.2" cy="6.2" r="0.9" fill="#120a1c" />
      {/* The pearl in the middle. */}
      <circle cx="16" cy="16" r="3.6" fill="url(#mark-pearl)" />
    </svg>
  );
}

/** The pearl alone, glowing and turning: the sign that Atlas is thinking. */
export function Pearl({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20" className={`pearl ${className}`}>
      <Gradients id="pearl" />
      <circle cx="10" cy="10" r="7" fill="url(#pearl-pearl)" />
      <circle cx="10" cy="10" r="7" fill="none" stroke="#ffffff" strokeOpacity="0.6" strokeWidth="0.8" />
    </svg>
  );
}

/** A divider: a glass rule in the dragon's colours, the pearl at its centre. */
export function PearlRule({ className = "" }: { className?: string }) {
  return (
    <span aria-hidden="true" className={`flex items-center gap-3 ${className}`}>
      <span className="scale-rule h-[2px] flex-1" />
      <Pearl className="h-4 w-4" />
      <span className="scale-rule h-[2px] flex-1 -scale-x-100" />
    </span>
  );
}

export interface Feature {
  title: string;
  text: string;
  scale: keyof typeof SCALES;
}

/** Glass cards, each lit by one of the dragon's colours. */
export function GlassCards({ features, label }: { features: Feature[]; label: string }) {
  return (
    <section aria-label={label} className="mt-10 grid grid-cols-2 gap-4">
      {features.map((feature) => (
        <div
          key={feature.title}
          className="glass glass-card relative overflow-hidden rounded-glass p-4 sm:p-5"
          style={{ ["--scale" as string]: SCALES[feature.scale] }}
        >
          <span aria-hidden="true" className="card-light" />
          <p className="relative flex items-center gap-2 font-display text-lg font-semibold text-paper sm:text-xl">
            <span aria-hidden="true" className="card-gem" />
            {feature.title}
          </p>
          <p className="relative mt-1.5 text-[13px] leading-snug text-soft">{feature.text}</p>
        </div>
      ))}
    </section>
  );
}
