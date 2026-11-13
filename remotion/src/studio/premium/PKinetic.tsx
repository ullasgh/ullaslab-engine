import React from "react";
import { useCurrentFrame } from "remotion";
import { useStudio } from "../context";
import { parseKinetic } from "../Kinetic";
import { fitSize, countedText, parseNumberToken } from "../styles";
import { EASE, SPRING, breathe, range, springOut } from "./motion";
import { PT, SP } from "./tokens";
import { usePremium, type Carry } from "./context";
import { landFrame } from "./words";

type W = { w: string; em: boolean; tok: ReturnType<typeof parseNumberToken> };

const parse = (text: string): W[][] => parseKinetic(text).map((l) => l.words.map((x) => ({ ...x, tok: parseNumberToken(x.w) })));

/** Position of a lone hero figure (scene-local px): centred, upper third. Shared with a morph that starts from it. */
export const heroBox = (bw: number, bh: number, size: number, text: string) => ({ x: Math.max(0, (bw - text.length * size * 0.6) / 2), y: bh * 0.3, size });

/** The figure a kinetic number scene hands to the next scene (a chart header), or null when the text has no lone figure. */
export const kineticCarry = (text: string, bw: number, bh: number, size: number): Carry | null => {
  const ws = parse(text).flat();
  const n = ws.find((x) => x.tok);
  if (!n || ws.length > 5) return null;
  const b = heroBox(bw, bh, size, n.w);
  return { text: n.w, x: b.x, y: b.y, size, color: PT.amber };
};

// Kinetic headline. Words land on the frame the narration speaks them (so the text and the voice stay one gesture); a figure
// counts up and ends on the exact written token at its spoken frame. The on-screen text is a distilled headline, never a copy of the
// caption: the director writes it short, and the renderer only times it.
export const PremiumKinetic: React.FC<{ text: string; silent?: boolean }> = ({ text, silent }) => {
  const { numberLocale, L } = useStudio();
  const { bw, bh, T, font, words, dur, morphOut } = usePremium();
  const f = useCurrentFrame();
  if (silent) return null;
  const lines = parse(text);
  const flat = lines.flat();
  const fig = flat.find((x) => x.tok);
  const hero = !!fig && flat.length <= 5;

  // landing frames, in reading order, matched to the narration
  let cursor = 0;
  const land = flat.map((x, i) => {
    const r = landFrame(words, x.w, cursor, Math.round(6 + i * 7));
    cursor = r.next;
    return r.f;
  });
  let k = 0;
  const base = hero ? T.display * 0.62 : Math.round(T.display * (L.vertical ? 0.95 : 1));
  const size = fitSize(lines.map((l) => l.map((x) => x.w).join(" ")), bw, bh * 0.6, base, 56);
  const heroSize = T.hero * (L.vertical ? 0.78 : 0.8);
  const rule = EASE.outExpo(range(f, 0, 18));

  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: bw, height: bh, fontFamily: font, color: PT.ink }}>
      {hero && <div style={{ position: "absolute", left: (bw - 132) / 2, top: heroBox(bw, bh, heroSize, fig!.w).y - size * 1.5 - SP.l, width: 132 * rule, height: 8, background: PT.amber, borderRadius: 4 }} />}
      {hero ? (() => {
        const fi = flat.indexOf(fig!);
        const lf = land[fi];
        const p = EASE.outExpo(range(f, lf - 20, 20));
        const pop = 1 + 0.06 * Math.sin(Math.PI * range(f, lf, 14)) * (1 - range(f, lf, 14));
        const hb = heroBox(bw, bh, heroSize, fig!.w);
        const hideFig = morphOut && f >= dur - 2;
        const before = lines.flat().slice(0, fi), after = lines.flat().slice(fi + 1);
        const wordNode = (x: W, i: number, off: number) => {
          const a = EASE.out(range(f, land[off + i], 14));
          return <span key={off + i} style={{ display: "inline-block", opacity: a, transform: `translateY(${(1 - a) * 26}px)`, marginRight: SP.s, color: x.em ? PT.amber : PT.ink }}>{x.w}</span>;
        };
        return (<>
          <div data-audit="headline" style={{ position: "absolute", left: 0, top: hb.y - size * 1.5, width: bw, textAlign: "center", fontSize: size, fontWeight: 700, lineHeight: 1.1 }}>{before.map((x, i) => wordNode(x, i, 0))}</div>
          <div data-audit="headline" style={{ position: "absolute", left: hb.x, top: hb.y, fontSize: heroSize, lineHeight: 1, fontWeight: 700, color: PT.amber, letterSpacing: -6, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap",
            opacity: hideFig ? 0 : EASE.out(range(f, lf - 24, 8)), transform: `scale(${pop})`, transformOrigin: "50% 60%" }}>{p >= 1 ? fig!.tok!.raw : countedText(fig!.tok!, p, numberLocale)}</div>
          <div data-audit="headline" style={{ position: "absolute", left: 0, top: hb.y + heroSize * 1.1, width: bw, textAlign: "center", fontSize: size, fontWeight: 700, lineHeight: 1.1 }}>{after.map((x, i) => wordNode(x, i, fi + 1))}</div>
        </>);
      })() : (
        <div style={{ position: "absolute", left: 0, top: 0, width: bw, height: bh, display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", textAlign: "center", gap: size * 0.12 }}>
          <div style={{ width: 132 * rule, height: 8, background: PT.amber, borderRadius: 4, marginBottom: size * 0.2 }} />
          {lines.map((line, li) => (
            <div key={li} data-audit="headline" style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: `0 ${size * 0.26}px`, fontSize: size, fontWeight: 700, lineHeight: 1.06, letterSpacing: -2 }}>
              {line.map((x, i) => {
                const idx = k++;
                const t = range(f, land[idx], 16);
                const a = EASE.out(t), s = springOut(t, x.em ? SPRING.pop : SPRING.snappy);
                const tok = x.tok;
                const shown = tok ? (t >= 1 ? tok.raw : countedText(tok, range(f, land[idx] - 18, 18), numberLocale)) : x.w;
                return (
                  <span key={i} style={{ position: "relative", display: "inline-block", overflow: "hidden", paddingBottom: size * 0.1, verticalAlign: "top" }}>
                    <span style={{ display: "inline-block", opacity: a, transform: `translateY(${(1 - s) * size * 0.6}px) scale(${0.94 + 0.06 * s})`, transformOrigin: "0% 90%", color: x.em || tok ? PT.amber : PT.ink }}>{shown}</span>
                    {(x.em || tok) && <span style={{ position: "absolute", left: 0, bottom: size * 0.02, height: 8, width: `${EASE.out(range(f, land[idx] + 6, 18)) * 100}%`, background: PT.amber, borderRadius: 4, opacity: 0.85 }} />}
                  </span>
                );
              })}
            </div>
          ))}
        </div>
      )}
      <div style={{ position: "absolute", left: (bw - (120 + breathe(f, 70, 30))) / 2, bottom: SP.xl, width: 120 + breathe(f, 70, 30), height: 6, background: PT.teal, borderRadius: 3, opacity: 0.55 }} />
    </div>
  );
};
