"use client";

import { usePathname } from "next/navigation";

const SRC = `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/dragon.jpg`;

/**
 * The dragon: one image, the only light on a black page. Its black is screened away, so
 * only the glow shows. Strongest on the home page and the assistant, faint elsewhere so
 * the reading stays clear. Decorative; the light theme hides it.
 */
export function DragonBackdrop() {
  const path = usePathname();
  const level = path === "/" ? "strong" : path === "/chat" ? "mid" : "faint";
  return (
    <div
      aria-hidden="true"
      data-level={level}
      className="dragon-backdrop pointer-events-none fixed inset-y-0 right-0 -z-10 w-full max-w-[min(100vw,720px)] select-none"
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- a static export has no image optimiser */}
      <img src={SRC} alt="" className="h-full w-full object-contain object-right" />
    </div>
  );
}

/** The head of the dragon, cropped from the image, as the mark. */
export function DragonMark({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`dragon-mark inline-block shrink-0 border border-line-strong ${className}`}
      style={{ backgroundImage: `url(${SRC})` }}
    />
  );
}
