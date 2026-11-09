import type { I18n } from "./types";

// Calm, data-first palette. Every text/background pair below is >= 4.5:1 (checked in scripts/brand.test.mjs).
export const C = {
  bg: "#0E1726",        // deep ink
  panel: "#16233A",     // card surface
  caption: "#0A1220",   // caption box
  text: "#F2F5F9",
  muted: "#A9B6C8",
  primary: "#4FD1C5",   // teal
  secondary: "#F6C177", // amber
  accent: "#8AB4F8",    // soft blue
  negative: "#F28B82",
  grid: "#2A3A55",
  tagText: "#0E1726",
} as const;

export const TAG_COLOR: Record<string, string> = {
  LIVE: "#7EE2A8", RECENT: "#8AB4F8", LAGGED: "#F6C177", EXPECTATION: "#C4B5FD", INFERRED: "#E5E7EB",
};

export const FPS = 30;

// Mirrors config/safe_zones.json (QA reads the JSON; keep in sync, covered by a test).
export const SAFE = {
  vertical: { w: 1080, h: 1920, top: 220, bottom: 420, sides: 60 },
  horizontal: { w: 1920, h: 1080, top: 54, bottom: 54, sides: 96 },
} as const;

// Type scale (px). Minimums from quality.yaml A5: body 44, label 36.
export const TYPE = {
  vertical: { headline: 72, body: 48, label: 36, caption: 44 },
  horizontal: { headline: 84, body: 52, label: 38, caption: 48 },
} as const;

const NOTO = (s: string) => (s ? `"Noto Sans ${s}", "Noto Sans", sans-serif` : `"Noto Sans", sans-serif`);
// Noto family per language script (13 languages, 9 scripts + Latin). Arabic is RTL.
export const FONT: Record<string, string> = {
  en: NOTO(""), es: NOTO(""), pt: NOTO(""),
  hi: NOTO("Devanagari"), mr: NOTO("Devanagari"),
  ta: NOTO("Tamil"), te: NOTO("Telugu"), kn: NOTO("Kannada"), ml: NOTO("Malayalam"),
  bn: NOTO("Bengali"), gu: NOTO("Gujarati"), ar: NOTO("Arabic"), ja: NOTO("JP"),
};
export const FONT_FAMILIES = ["Noto Sans", "Noto Sans Devanagari", "Noto Sans Tamil", "Noto Sans Telugu", "Noto Sans Kannada",
  "Noto Sans Malayalam", "Noto Sans Bengali", "Noto Sans Gujarati", "Noto Sans Arabic", "Noto Sans JP"];
export const fontFor = (lang: string) => FONT[lang] ?? FONT.en;

export const t = (v: I18n | undefined, lang: string): string =>
  v === undefined ? "" : typeof v === "string" ? v : v[lang] ?? v.en ?? Object.values(v)[0] ?? "";

export const fmt = (n: number, decimals: number, locale: string) =>
  n.toLocaleString(locale, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });

// "Source" in the 13 launch languages (stamp prefix). Tag codes (LIVE, RECENT, ...) stay Latin on purpose.
export const SOURCE_WORD: Record<string, string> = {
  en: "Source", hi: "स्रोत", ta: "ஆதாரம்", te: "మూలం", kn: "ಮೂಲ", ml: "ഉറവിടം", mr: "स्रोत", bn: "সূত্র",
  gu: "સ્ત્રોત", es: "Fuente", pt: "Fonte", ar: "المصدر", ja: "出典",
};

// Stamp text "<Source word>: <name> · <as_of>". Source names that already start with a source word
// ("Source: FRED", "Fuente: INE") would print "Source: Source: ..."; strip any leading source prefix first.
export const cleanSourceName = (name: string): string => {
  const words = [...new Set(Object.values(SOURCE_WORD)), "Sources", "Source"].map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const re = new RegExp(`^\\s*(?:${words.join("|")})\\s*[:：\\-–—]\\s*`, "i");
  let out = name.trim();
  for (let i = 0; i < 3 && re.test(out); i++) out = out.replace(re, "");
  return out || name.trim();
};
export const stampText = (lang: string, name: string, asOf: string): string =>
  `${SOURCE_WORD[lang] ?? SOURCE_WORD.en}: ${cleanSourceName(name)}${asOf ? ` · ${asOf}` : ""}`;

// Footage disclosure tag in the 13 launch languages (machine-seeded; native review owed before first publication in each).
export const ILLUSTRATIVE_FOOTAGE: Record<string, string> = {
  en: "Illustrative footage", hi: "प्रतीकात्मक फ़ुटेज", ta: "விளக்கக் காட்சிகள்", te: "ఉదాహరణ దృశ్యాలు", kn: "ವಿವರಣಾತ್ಮಕ ದೃಶ್ಯಗಳು",
  ml: "ചിത്രീകരണ ദൃശ്യങ്ങൾ", mr: "प्रातिनिधिक फुटेज", bn: "উদাহরণমূলক ফুটেজ", gu: "દર્શાવવા માટેનું ફૂટેજ",
  es: "Imágenes ilustrativas", pt: "Imagens ilustrativas", ar: "لقطات توضيحية", ja: "イメージ映像",
};
export const illustrativeTag = (lang: string): string => ILLUSTRATIVE_FOOTAGE[lang] ?? ILLUSTRATIVE_FOOTAGE.en;
