import { useLayoutEffect, type RefObject } from "react";

/**
 * Sizes an element so its bottom edge lines up with the bottom of the viewport.
 * Used by the chat so the message box is always visible on phones (no scrolling to find it),
 * and it follows the on-screen keyboard because it listens to visualViewport.
 */
export function useFitHeight(ref: RefObject<HTMLElement>, minPx = 320) {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const fit = () => {
      const top = el.getBoundingClientRect().top + window.scrollY;
      const vh = window.visualViewport?.height ?? window.innerHeight;
      const bottomGap = window.innerWidth >= 1024 ? 32 : 12;
      const h = Math.max(minPx, Math.floor(vh - top - bottomGap));
      if (el.style.height !== `${h}px`) el.style.height = `${h}px`;
    };
    fit();
    window.addEventListener("resize", fit);
    window.visualViewport?.addEventListener("resize", fit);
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(fit) : null;
    ro?.observe(document.body);
    return () => {
      window.removeEventListener("resize", fit);
      window.visualViewport?.removeEventListener("resize", fit);
      ro?.disconnect();
    };
  }, [ref, minPx]);
}
