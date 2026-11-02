"use client";

import { useEffect, useRef } from "react";

/**
 * The dragon: an Eastern dragon of coloured glass, the look of Atlas, and its several jobs.
 * - It frames the page headings, its body coiled through the hero.
 * - Its head turns, a little, towards the pointer: it watches what you do.
 * - It chases a flaming pearl, as dragons do; the pearl alone is the sign that Atlas is
 *   thinking, and coiled round itself the dragon is the mark.
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

// The body: from the tail (left, low) up over the heading to the head (right, high).
const BODY =
  "M40 300 C80 330 140 312 150 262 C160 212 106 196 128 140 C150 84 230 60 310 76 C390 92 410 150 460 130 C500 114 494 70 520 62";

/** The dragon coiled through a heading. Its head follows the pointer a little. */
export function Dragon({ className = "" }: { className?: string }) {
  const head = useRef<SVGGElement>(null);
  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const turn = (event: PointerEvent) => {
      const node = head.current;
      if (!node) return;
      const box = node.getBoundingClientRect();
      // It looks up or down towards the pointer: up to 14° either way.
      const tilt = Math.max(-14, Math.min(14, ((event.clientY - box.top) / 400) * 20));
      node.setAttribute("transform", `rotate(${tilt.toFixed(1)})`);
    };
    window.addEventListener("pointermove", turn);
    return () => window.removeEventListener("pointermove", turn);
  }, []);

  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 720 360"
      preserveAspectRatio="xMidYMid meet"
      className={`dragon pointer-events-none ${className}`}
      fill="none"
    >
      <Gradients id="dragon" />
      <g className="dragon-float">
      {/* Its glow, the glass body, belly plates, scales flowing along it, a highlight,
          and the spikes down its back. */}
      <path d={BODY} stroke="url(#dragon-body)" strokeWidth="44" strokeLinecap="round" opacity="0.12" />
      <path d={BODY} stroke="url(#dragon-body)" strokeWidth="34" strokeLinecap="round" opacity="0.18" />
      <path d={BODY} stroke="url(#dragon-body)" strokeWidth="26" strokeLinecap="round" opacity="0.55" />
      <path d={BODY} stroke={SCALES.gold} strokeWidth="7" strokeDasharray="6 3" opacity="0.35" transform="translate(0 7)" />
      <path className="dragon-scales" d={BODY} stroke="#ffffff" strokeWidth="12" strokeDasharray="0.1 8" strokeLinecap="round" opacity="0.3" />
      <path d={BODY} stroke="#ffffff" strokeWidth="2" strokeLinecap="round" opacity="0.5" transform="translate(0 -6)" />
      <path className="dragon-scales" d={BODY} stroke={SCALES.magenta} strokeWidth="9" strokeDasharray="2 9" strokeLinecap="round" opacity="0.75" transform="translate(0 -15)" />
      {/* A tail fin like a flame. */}
      <path d="M40 300 C20 296 8 280 14 262 C24 276 32 280 44 282 C30 270 28 252 36 240 C42 262 54 276 64 286" fill={SCALES.flame} fillOpacity="0.45" stroke={SCALES.gold} strokeOpacity="0.7" strokeWidth="1.2" />
      {/* Claws: one foreleg reaching down, one hind leg. */}
      <path d="M420 140 C426 164 418 178 404 186 M404 186 l-9 7 M408 184 l-3 10 M413 180 l4 9" stroke={SCALES.gold} strokeWidth="2.6" strokeLinecap="round" opacity="0.85" />
      <path d="M160 250 C180 262 186 280 180 296 M180 296 l-6 8 M182 292 l2 10 M184 288 l8 6" stroke={SCALES.gold} strokeWidth="2.6" strokeLinecap="round" opacity="0.85" />
      {/* The head, at the end of the body, tilted towards the pointer. */}
      <g transform="translate(520 62) scale(1.45)">
        <g ref={head} className="dragon-head">
          {/* The mane, a crest of flames behind it. */}
          <path d="M4 -8 C-10 -24 -24 -14 -36 -28 M2 0 C-16 -6 -26 6 -42 -2 M6 6 C-6 14 -14 26 -30 24" stroke={SCALES.magenta} strokeWidth="3" strokeLinecap="round" opacity="0.8" />
          {/* Horns. */}
          <path d="M14 -14 C8 -34 -4 -44 -20 -50 M24 -16 C24 -34 16 -48 4 -58" stroke={SCALES.gold} strokeWidth="3" strokeLinecap="round" />
          {/* Skull and snout, glass. */}
          <path d="M2 -14 C22 -26 48 -22 66 -10 C74 -4 74 4 66 6 C52 10 34 8 22 14 C10 20 -2 12 2 -14 Z" fill="url(#dragon-head)" fillOpacity="0.6" stroke="#ffffff" strokeOpacity="0.55" strokeWidth="1.2" />
          {/* The jaw, open a little. */}
          <path d="M22 14 C36 22 52 24 64 18" stroke={SCALES.gold} strokeWidth="1.6" strokeLinecap="round" />
          {/* The eye. */}
          <circle cx="34" cy="-8" r="4.6" fill={SCALES.gold} className="dragon-eye" />
          <ellipse cx="34" cy="-8" rx="1.2" ry="3.6" fill="#120a1c" />
          {/* Whiskers, swaying. */}
          <g className="dragon-whiskers">
            <path d="M64 2 C84 10 98 32 122 30" stroke={SCALES.turquoise} strokeWidth="1.6" strokeLinecap="round" />
            <path d="M62 -6 C86 -24 102 -10 126 -30" stroke={SCALES.turquoise} strokeWidth="1.6" strokeLinecap="round" />
          </g>
        </g>
      </g>
      {/* The flaming pearl it chases. */}
      <g transform="translate(680 150)">
        <g className="dragon-pearl">
        <path d="M0 -24 C8 -14 14 -12 12 0 C10 -8 4 -10 0 -24 Z M-4 -22 C-10 -12 -14 -10 -12 0 C-10 -8 -6 -12 -4 -22 Z" fill={SCALES.flame} opacity="0.8" />
        <circle r="13" fill="url(#dragon-pearl)" />
        <circle r="13" stroke="#ffffff" strokeOpacity="0.6" />
        </g>
      </g>
      </g>
    </svg>
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
