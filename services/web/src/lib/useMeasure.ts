/**
 * The pixel width of an element, kept current as it changes.
 *
 * Charts here are drawn in real pixel coordinates rather than in a fixed viewBox scaled
 * with `preserveAspectRatio="none"`. Scaling a viewBox stretches the strokes with the
 * geometry, so a one-pixel gridline becomes three pixels wide on a wide monitor and the
 * axis labels come out italic-looking. Measuring costs one observer per chart and keeps
 * every line the width it was asked to be.
 */

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Returns a ref *callback* rather than a ref object, which matters for more than typing.
 * A callback runs the instant React attaches the node, so the first measurement happens
 * before paint; an effect reading `ref.current` runs a frame later and the chart renders
 * once at zero width first.
 */
export function useMeasure<T extends HTMLElement = HTMLDivElement>(): [
  (node: T | null) => void,
  number,
] {
  const [width, setWidth] = useState(0);
  const observer = useRef<ResizeObserver | null>(null);

  const attach = useCallback((node: T | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!node) return;

    setWidth(node.clientWidth);
    observer.current = new ResizeObserver((entries) => {
      const next = entries[0]?.contentRect.width;
      if (typeof next === "number") setWidth(Math.round(next));
    });
    observer.current.observe(node);
  }, []);

  useEffect(() => () => observer.current?.disconnect(), []);

  return [attach, width];
}
