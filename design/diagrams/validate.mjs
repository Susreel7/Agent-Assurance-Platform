/**
 * Layout checks for the generated sketches, so "clean" is verified rather than claimed.
 *
 *   node design/diagrams/validate.mjs
 *
 * Reports four classes of defect:
 *   TEXT_OVERLAP   a label intersects a box it does not belong to
 *   PANEL_OVERLAP  two filled boxes collide (zones are transparent and may contain boxes)
 *   TEXT_OVERFLOW  a label runs past the right edge of its own box
 *   ARROW_CROSSES  a connector passes through a box that is not its source or target
 */
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const DIR = dirname(fileURLToPath(import.meta.url));
const EPS = 2;

const box = (el) => ({ x1: el.x, y1: el.y, x2: el.x + el.width, y2: el.y + el.height });
const intersects = (a, b) =>
  a.x1 < b.x2 - EPS && a.x2 > b.x1 + EPS && a.y1 < b.y2 - EPS && a.y2 > b.y1 + EPS;
const contains = (outer, inner) =>
  inner.x1 >= outer.x1 - EPS &&
  inner.x2 <= outer.x2 + EPS &&
  inner.y1 >= outer.y1 - EPS &&
  inner.y2 <= outer.y2 + EPS;

/** Liang–Barsky: does the segment enter the rectangle's interior? */
function segmentHitsRect([px, py], [qx, qy], r) {
  const dx = qx - px;
  const dy = qy - py;
  let t0 = 0;
  let t1 = 1;
  const clip = (p, q) => {
    if (p === 0) return q >= 0;
    const t = q / p;
    if (p < 0) {
      if (t > t1) return false;
      if (t > t0) t0 = t;
    } else {
      if (t < t0) return false;
      if (t < t1) t1 = t;
    }
    return true;
  };
  const pad = 4; // a connector grazing a border is not a crossing
  return (
    clip(-dx, px - (r.x1 + pad)) &&
    clip(dx, r.x2 - pad - px) &&
    clip(-dy, py - (r.y1 + pad)) &&
    clip(dy, r.y2 - pad - py) &&
    t1 - t0 > 0.02
  );
}

let defects = 0;

for (const name of readdirSync(DIR).filter((f) => f.endsWith(".excalidraw")).sort()) {
  const { elements } = JSON.parse(readFileSync(join(DIR, name), "utf8"));
  const rects = elements.filter((el) => el.type === "rectangle");
  const texts = elements.filter((el) => el.type === "text");
  const arrows = elements.filter((el) => el.type === "arrow");
  const problems = [];

  // A zone is a rectangle that fully contains another rectangle. Zones are backdrops:
  // things are meant to sit inside them, so they take no part in the collision checks.
  const zones = rects.filter((r) => rects.some((other) => other !== r && contains(box(r), box(other))));
  const panels = rects.filter((r) => !zones.includes(r));

  for (const t of texts) {
    const tb = box(t);
    const owner = panels.find((r) => contains(box(r), tb));
    for (const r of panels) {
      const rb = box(r);
      if (r === owner || !intersects(tb, rb)) continue;
      problems.push(`TEXT_OVERLAP   "${t.text.split("\n")[0].slice(0, 46)}" × box at ${r.x},${r.y}`);
    }
    if (owner && tb.x2 > box(owner).x2 - 6) {
      problems.push(`TEXT_OVERFLOW  "${t.text.split("\n")[0].slice(0, 46)}"`);
    }
  }

  for (let i = 0; i < panels.length; i += 1) {
    for (let j = i + 1; j < panels.length; j += 1) {
      if (intersects(box(panels[i]), box(panels[j]))) {
        problems.push(`PANEL_OVERLAP  ${panels[i].x},${panels[i].y} × ${panels[j].x},${panels[j].y}`);
      }
    }
    for (const z of zones) {
      const pb = box(panels[i]);
      if (intersects(pb, box(z)) && !contains(box(z), pb)) {
        problems.push(`ZONE_ESCAPE    box at ${panels[i].x},${panels[i].y} spills out of zone at ${z.x},${z.y}`);
      }
    }
  }

  for (const a of arrows) {
    const [p, q] = a.points.map(([dx, dy]) => [a.x + dx, a.y + dy]);
    for (const r of panels) {
      const rb = box(r);
      const touchesEnd = [p, q].some(
        (pt) => pt[0] >= rb.x1 - 6 && pt[0] <= rb.x2 + 6 && pt[1] >= rb.y1 - 6 && pt[1] <= rb.y2 + 6,
      );
      if (touchesEnd) continue;
      if (segmentHitsRect(p, q, rb)) {
        problems.push(`ARROW_CROSSES  (${p.map(Math.round)}) → (${q.map(Math.round)}) through box at ${r.x},${r.y}`);
      }
    }
  }

  defects += problems.length;
  console.log(`${problems.length ? "FAIL" : "ok  "}  ${name}${problems.length ? ` — ${problems.length}` : ""}`);
  for (const problem of problems) console.log(`        ${problem}`);
}

console.log(defects ? `\n${defects} layout defects` : "\nno layout defects");
process.exit(defects ? 1 : 0);
