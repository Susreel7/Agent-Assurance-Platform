/**
 * Rasterises the SVG previews to PNG for review in chat, tickets and slides.
 * Excalidraw stays the editable source; SVG is the reviewable form; PNG is for pasting.
 *
 *   node design/diagrams/render-png.mjs            # all
 *   node design/diagrams/render-png.mjs 01 04 11   # selected, by number prefix
 */
import { createRequire } from "node:module";
import { readFileSync, readdirSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SVG_DIR = join(HERE, "preview");
const PNG_DIR = join(HERE, "png");

const require = createRequire(join(HERE, "..", "..", "services", "web", "package.json"));
const { chromium } = require("playwright");

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";

const wanted = process.argv.slice(2);
const files = readdirSync(SVG_DIR)
  .filter((name) => name.endsWith(".svg"))
  .filter((name) => !wanted.length || wanted.some((prefix) => name.startsWith(prefix)));

mkdirSync(PNG_DIR, { recursive: true });

const browser = await chromium.launch({ headless: true, executablePath: EDGE });
const page = await browser.newPage({ deviceScaleFactor: 2 });

for (const name of files) {
  const svg = readFileSync(join(SVG_DIR, name), "utf8");
  const width = Number(svg.match(/width="(\d+)"/)[1]);
  const height = Number(svg.match(/height="(\d+)"/)[1]);
  await page.setViewportSize({ width: Math.min(width, 4000), height: Math.min(height, 4000) });
  await page.setContent(`<body style="margin:0">${svg}</body>`);
  const out = join(PNG_DIR, name.replace(/\.svg$/, ".png"));
  await page.screenshot({ path: out, fullPage: true });
  console.log(`${name} -> ${width}x${height}`);
}

await browser.close();
console.log(`wrote ${files.length} PNGs into ${PNG_DIR}`);
