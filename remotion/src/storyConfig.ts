import { SAFE } from "./brand";

// Instagram Story UI keeps the top ~250 px (profile bar) and bottom ~340 px (reply bar) clear.
// Mirrors config/safe_zones.json "story" (QA reads the JSON; covered by a test).
export const STORY_SAFE = { w: 1080, h: 1920, top: 250, bottom: 340, sides: 60 } as const;
export const STORY_MIN_S = 10;
export const STORY_MAX_S = 15;

export type StoryProps = {
  lang: string; text: string; sub: string; source: string; cta: string; aiVoice: string;
  durationS: number; audio: string; rtl: boolean; accent: string; audit?: boolean;
};

// Fixed UI strings. CTA is the owner-approved line "New Reel on our profile" (no link sticker exists in the API).
export const STORY_I18N: Record<string, { cta: string; aiVoice: string; source: string }> = {
  en: { cta: "New Reel on our profile", aiVoice: "AI-generated voice", source: "Source" },
  hi: { cta: "हमारी प्रोफ़ाइल पर नई रील", aiVoice: "एआई-निर्मित आवाज़", source: "स्रोत" },
};
export const storyStrings = (lang: string) => STORY_I18N[lang] ?? STORY_I18N.en;

// Hard text budget (compliance + readability): hook <= 60 chars, sub <= 90.
export const STORY_MAX_TEXT = 60;
export const STORY_MAX_SUB = 90;

export const clampDuration = (s: number) => Math.min(STORY_MAX_S, Math.max(STORY_MIN_S, s));
export const insideStoryZone = (e: { x: number; y: number; w: number; h: number }) =>
  e.x >= STORY_SAFE.sides && e.x + e.w <= STORY_SAFE.w - STORY_SAFE.sides && e.y >= STORY_SAFE.top && e.y + e.h <= STORY_SAFE.h - STORY_SAFE.bottom;
void SAFE;
