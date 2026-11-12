import React, { useLayoutEffect, useRef, useState } from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { useFont, useStudio } from "./context";
import { countedText, fitSize, parseCards, parseNumberToken, parseSteps, sketchLine, sketchRect } from "./styles";
import { parseKinetic } from "./Kinetic";

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const ease = (x: number) => 1 - Math.pow(1 - clamp01(x), 3);

// Original scene components for the video styles. Colours come from the palette only; numbers come from the text passed in.

const Rule: React.FC = () => {
  const { pal } = useStudio();
  const f = useCurrentFrame();
  return <div style={{ width: ease(f / 22) * 120, height: 8, background: pal.accent, borderRadius: 4 }} />;
};

const Column: React.FC<{ gap?: number; children: React.ReactNode }> = ({ gap = 24, children }) => {
  const { L } = useStudio();
  const font = useFont();
  return <div style={{ position: "absolute", left: L.x0, top: L.y0, width: L.cw, height: L.ch, fontFamily: font, display: "flex", flexDirection: "column", justifyContent: "center", gap }}>{children}</div>;
};

/* ---------------------------------------------------------------------------------- creator-motion */
// Large kinetic type. *word* marks an emphasis word; a number word (6.4%, $85, 1,200) counts up to exactly the written token.
export const CreatorKinetic: React.FC<{ text: string }> = ({ text }) => {
  const { L, pal, preset, numberLocale } = useStudio();
  const f = useCurrentFrame();
  const lines = parseKinetic(text);
  const flat = lines.map((l) => l.words.map((w) => w.w).join(" "));
  const size = fitSize(flat, L.cw, L.ch * 0.86, Math.round(L.type.display * (L.vertical ? 1.05 : 1)), 56);
  const { stagger, enter, overshoot } = preset.motion;
  let wi = 0;
  return (
    <Column gap={size * 0.14}>
      <Rule />
      {lines.map((line, li) => (
        <div key={li} data-audit="headline" style={{ display: "flex", flexWrap: "wrap", gap: `0 ${size * 0.24}px`, fontSize: size, fontWeight: 700, lineHeight: 1.1, letterSpacing: -2, color: pal.ink, fontVariantNumeric: "tabular-nums" }}>
          {line.words.map((wd, i) => {
            const idx = wi++;
            const s = 4 + idx * stagger;
            const k = ease((f - s) / enter);
            const tok = parseNumberToken(wd.w);
            const hot = wd.em || !!tok;
            const pop = 0.92 + 0.08 * k + (hot ? overshoot * Math.sin(Math.PI * k) : 0);
            const shown = tok ? countedText(tok, (f - s - 4) / 30, numberLocale) : wd.w;
            return (
              <span key={i} style={{ position: "relative", display: "inline-block", opacity: k, transform: `translateY(${(1 - k) * size * 0.4}px) scale(${pop})`, transformOrigin: "0% 80%", color: hot ? pal.accent : pal.ink }}>
                {shown}
                {hot && <span style={{ position: "absolute", left: 0, bottom: -size * 0.03, height: 8, width: `${ease((f - s - 8) / 18) * 100}%`, background: pal.accent2, borderRadius: 4 }} />}
              </span>
            );
          })}
        </div>
      ))}
    </Column>
  );
};

/* -------------------------------------------------------------------------------------- chalk-talk */
const useBox = () => {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => { const el = ref.current; if (el) setSize({ w: el.offsetWidth, h: el.offsetHeight }); }, []);
  return { ref, ...size };
};

const Step: React.FC<{ text: string; result: boolean; index: number; from: number; write: number; size: number }> = ({ text, result, index, from, write, size }) => {
  const { pal } = useStudio();
  const f = useCurrentFrame();
  const { ref, w, h } = useBox();
  const p = clamp01((f - from) / write);                 // stroke-on writing, left to right
  const done = clamp01((f - from - write) / 14);          // underline / box drawn once the text is written
  const col = result ? pal.accent2 : pal.ink;
  const padX = size * 0.35, padY = size * 0.12;
  return (
    <div style={{ position: "relative", display: "flex", alignItems: "center", gap: size * 0.3, paddingLeft: result ? padX : 0 }}>
      {!result && (
        <svg width={size * 0.7} height={size * 0.7} style={{ flex: "none", opacity: clamp01(p * 6) }}>
          <path d={`M 4 ${size * 0.35} L ${size * 0.6} ${size * 0.35} M ${size * 0.42} ${size * 0.15} L ${size * 0.62} ${size * 0.35} L ${size * 0.42} ${size * 0.55}`} stroke={pal.accent} strokeWidth={5} fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
      <div style={{ position: "relative", display: "inline-block" }}>
        <div ref={ref} data-audit="headline" style={{ display: "inline-block", fontSize: size, fontWeight: 700, lineHeight: 1.12, color: col, padding: result ? `${padY}px ${padX}px` : 0, clipPath: `inset(-20% ${(1 - p) * 100}% -20% -10%)`, fontVariantNumeric: "tabular-nums" }}>{text}</div>
        {p > 0 && p < 1 && <div style={{ position: "absolute", top: "50%", left: `${p * 100}%`, width: 14, height: 14, marginTop: -7, marginLeft: -7, borderRadius: 7, background: pal.accent, opacity: 0.9 }} />}
        {w > 0 && result && (
          <svg width={w} height={h} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
            <path d={sketchRect(w, h, index + 3, 3)} stroke={pal.accent2} strokeWidth={5} fill="none" strokeLinecap="round" strokeLinejoin="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - done} />
          </svg>
        )}
        {w > 0 && !result && (
          <svg width={w} height={12} style={{ position: "absolute", left: 0, bottom: -size * 0.1, overflow: "visible" }}>
            <path d={sketchLine(w, index + 1, 2.5)} transform="translate(0 6)" stroke={pal.grid} strokeWidth={4} fill="none" strokeLinecap="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - done} />
          </svg>
        )}
      </div>
    </div>
  );
};

// Step-by-step worked example. "|" separates steps; a step starting with "=" is the highlighted result.
export const ChalkSteps: React.FC<{ text: string }> = ({ text }) => {
  const { L, preset } = useStudio();
  const { durationInFrames } = useVideoConfig();
  const steps = parseSteps(text);
  const size = fitSize(steps.map((s) => s.text), L.cw - 120, L.ch * 0.8, Math.round(L.type.headline * (L.vertical ? 1.05 : 1.1)), 44);
  const write = preset.motion.enter;
  // finish by ~70% of the scene so the finished work is held on screen long enough to read
  const room = durationInFrames * 0.7 - 8 - write - 14;   // 14 = the box / underline draw after the last step is written
  const step = Math.max(8, Math.min(preset.motion.stagger, steps.length > 1 ? room / (steps.length - 1) : preset.motion.stagger));
  return (
    <Column gap={size * 0.5}>
      <Rule />
      {steps.map((s, i) => <Step key={i} text={s.text} result={s.result} index={i} from={8 + i * step} write={write} size={size} />)}
    </Column>
  );
};

/* ------------------------------------------------------------------------------------- clean-tech */
// Cards in a tidy grid. "|" separates cards; "Title: detail" splits on the first colon.
export const CardStack: React.FC<{ text: string }> = ({ text }) => {
  const { L, pal, preset } = useStudio();
  const f = useCurrentFrame();
  const cards = parseCards(text);
  const n = cards.length;
  if (!n) return null;
  const cols = L.vertical ? 1 : n <= 3 ? n : n === 4 ? 2 : 3;
  const rows = Math.ceil(n / cols);
  const gap = 26;
  const boxH = L.ch * 0.8;
  const cardH = Math.min(L.vertical ? 260 : 340, (boxH - gap * (rows - 1)) / rows);
  const cardW = (L.cw - gap * (cols - 1)) / cols;
  const titleSize = fitSize(cards.map((c) => c.title), cardW - 90, cardH * 0.55, L.type.body + (n <= 2 ? 8 : 0), 40);
  return (
    <Column gap={30}>
      <Rule />
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${cols}, ${cardW}px)`, gridAutoRows: cardH, gap }}>
        {cards.map((c, i) => {
          const k = ease((f - (8 + i * preset.motion.stagger)) / preset.motion.enter);
          return (
            <div key={i} style={{ position: "relative", opacity: k, transform: `translateY(${(1 - k) * 30}px)`, background: pal.panel, borderRadius: preset.layout.radius, border: `${preset.layout.border}px solid ${pal.grid}`, boxSizing: "border-box", padding: "0 28px 0 40px", display: "flex", flexDirection: "column", justifyContent: "center", gap: 8, overflow: "hidden" }}>
              <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 10, background: i % 2 ? pal.accent2 : pal.accent }} />
              <div data-audit="headline" style={{ fontSize: titleSize, fontWeight: 700, lineHeight: 1.12, color: pal.ink, fontVariantNumeric: "tabular-nums" }}>{c.title}</div>
              {c.detail && <div data-audit="label" style={{ fontSize: L.type.label, lineHeight: 1.2, color: pal.muted }}>{c.detail}</div>}
            </div>
          );
        })}
      </div>
    </Column>
  );
};

