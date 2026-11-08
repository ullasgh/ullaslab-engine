// Copies Noto woff2 files (SIL OFL) from @fontsource packages into public/fonts and writes fonts.css.
// Generated output is git-ignored. Weights 400 and 700 only; all unicode-range subsets are kept.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const out = path.join(root, "public", "fonts");
const FAMILIES = {
  "Noto Sans": "noto-sans",
  "Noto Sans Devanagari": "noto-sans-devanagari",
  "Noto Sans Tamil": "noto-sans-tamil",
  "Noto Sans Telugu": "noto-sans-telugu",
  "Noto Sans Kannada": "noto-sans-kannada",
  "Noto Sans Malayalam": "noto-sans-malayalam",
  "Noto Sans Bengali": "noto-sans-bengali",
  "Noto Sans Gujarati": "noto-sans-gujarati",
  "Noto Sans Arabic": "noto-sans-arabic",
  "Noto Sans JP": "noto-sans-jp",
};
fs.mkdirSync(out, { recursive: true });
let css = "";
for (const [family, pkg] of Object.entries(FAMILIES)) {
  const dir = path.join(root, "node_modules", "@fontsource", pkg);
  if (!fs.existsSync(dir)) { console.warn(`fonts: ${pkg} not installed, skipped`); continue; }
  for (const w of [400, 700]) {
    const file = path.join(dir, `${w}.css`);
    if (!fs.existsSync(file)) continue;
    const src = fs.readFileSync(file, "utf8");
    // keep only woff2 sources, rewrite url() to the copied file
    const blocks = src.match(/@font-face\s*{[^}]*}/g) ?? [];
    for (const b of blocks) {
      const m = b.match(/url\(\.\/files\/([^)]+\.woff2)\)/);
      if (!m) continue;
      fs.copyFileSync(path.join(dir, "files", m[1]), path.join(out, m[1]));
      const range = (b.match(/unicode-range:[^;]+;/) ?? [""])[0];
      css += `@font-face{font-family:"${family}";font-style:normal;font-weight:${w};font-display:block;src:url("${m[1]}") format("woff2");${range}}\n`;
    }
  }
}
fs.writeFileSync(path.join(out, "fonts.css"), css);
console.log(`fonts: wrote ${css.split("\n").length - 1} @font-face rules`);
