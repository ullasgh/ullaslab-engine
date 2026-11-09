import React from "react";
import { Sequence, useCurrentFrame, useVideoConfig, interpolate } from "remotion";
import { C, endParts, fmt, t } from "../brand";
import { ease, useEnter, useScene } from "../hooks";
import { useCtx } from "../layout";
import { Scene, TlScene } from "../types";
import { Body, Card, Content, Headline, SourceStamp, Title } from "./common";
import { BarChart, Counter, Legend, LineChart } from "./charts";

const useBeat = (tl: TlScene) => {
  const s = useScene(tl);
  return { s, beat: { index: s.beatIndex, count: s.beatCount, since: s.sinceBeat } };
};

const ChartBlock: React.FC<{ scene: Scene; tl: TlScene }> = ({ scene, tl }) => {
  const { p, L, tpl } = useCtx();
  const { s, beat } = useBeat(tl);
  const chart = scene.chart_data!;
  const enter = useEnter(tpl.enter);
  const titleH = L.type.headline * 1.2 * (L.vertical ? 2 : 1);
  const mirror = chart.type === "compare" && tpl.compareStyle === "mirror";
  const legendH = chart.type === "compare" && !mirror ? 56 : 0;
  const W = L.cw - 64;
  const H = Math.min(L.vertical ? 620 : 470, L.ch - titleH - 56 - legendH - 48 - 64 - 48);
  return (
    <Content style={enter}>
      <Title chart={chart} headline={t(scene.headline, p.lang)} />
      <Card style={{ padding: 32 }}>
        {chart.type === "compare" && !mirror && <div style={{ marginBottom: 12 }}><Legend series={chart.series!} /></div>}
        <div data-audit="chart">
          {mirror ? <Mirror chart={chart} W={W} H={H} frame={s.frame} fps={s.fps} beat={beat} /> :
            chart.type === "bar" ? <BarChart chart={chart} W={W} H={H} frame={s.frame} fps={s.fps} beat={beat} /> :
              <LineChart chart={chart} W={W} H={H} frame={s.frame} fps={s.fps} beat={beat} area={tpl.chartArea} dots={tpl.chartDots} />}
        </div>
      </Card>
      <SourceStamp chart={chart} />
    </Content>
  );
};

// India-vs-US style: latest value of each series as mirrored horizontal bars.
const Mirror: React.FC<{ chart: NonNullable<Scene["chart_data"]>; W: number; H: number; frame: number; fps: number; beat: { index: number; count: number; since: number } }> = ({ chart, W, H, frame, fps, beat }) => {
  const { p, L } = useCtx();
  const vals = chart.series!.map((s) => s.points[s.points.length - 1].y);
  const max = Math.max(...vals.map(Math.abs), 1e-9);
  const dec = chart.decimals ?? 1;
  return (
    <div style={{ width: W, height: H, display: "flex", flexDirection: "column", justifyContent: "space-around" }}>
      {chart.series!.map((s, i) => {
        const w = ease(frame, i * 6, i * 6 + fps) * (Math.abs(vals[i]) / max);
        const on = beat.index % chart.series!.length === i;
        return (
          <div key={i} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div data-audit="label" style={{ fontSize: L.type.label, color: C.muted }}>{t(s.name, p.lang)}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
              <div style={{ height: 56, width: `${Math.max(4, w * 70)}%`, background: i === 0 ? C.primary : C.secondary, borderRadius: 10, opacity: on ? 1 : 0.65 }} />
              <div data-audit="body" style={{ fontSize: L.type.body, fontWeight: 700, direction: "ltr" }}>{fmt(vals[i], dec, p.numberLocale)}{chart.unit ?? ""}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

const CounterScene: React.FC<{ scene: Scene; tl: TlScene }> = ({ scene, tl }) => {
  const { p, tpl } = useCtx();
  const { s, beat } = useBeat(tl);
  const chart = scene.chart_data!;
  const enter = useEnter(tpl.enter);
  return (
    <Content style={enter}>
      <Card style={{ padding: 40 }}>
        <Counter chart={chart} frame={s.frame} fps={s.fps} beat={beat} label={t(scene.headline, p.lang) || t(chart.label ?? chart.title, p.lang)} />
      </Card>
      <SourceStamp chart={chart} />
    </Content>
  );
};

const GridScene: React.FC<{ scene: Scene; tl: TlScene }> = ({ scene, tl }) => {
  const { p, L, tpl } = useCtx();
  const { s, beat } = useBeat(tl);
  const items = scene.items ?? [];
  const enter = useEnter(tpl.enter);
  const cols = tpl.gridStyle === "calendar" ? 2 : L.vertical ? 1 : Math.min(3, items.length || 1);
  return (
    <Content style={enter}>
      {scene.headline && <Headline text={t(scene.headline, p.lang)} />}
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${cols}, 1fr)`, gap: 20 }}>
        {items.map((it, i) => {
          const on = beat.index % Math.max(1, items.length) === i;
          const a = ease(s.frame, i * 5, i * 5 + 12);
          const ticker = tpl.gridStyle === "ticker";
          return (
            <div key={i} style={{ background: C.panel, borderRadius: 24, padding: "20px 28px", opacity: a, border: `4px solid ${on ? tpl.accent : "transparent"}`,
              display: "flex", flexDirection: ticker ? "row" : "column", justifyContent: "space-between", alignItems: ticker ? "center" : "flex-start", gap: 8, direction: p.rtl ? "rtl" : "ltr" }}>
              <div data-audit="label" style={{ fontSize: L.type.label, color: C.muted }}>{t(it.label, p.lang)}</div>
              {it.value && <div data-audit="headline" style={{ fontSize: L.type.headline, fontWeight: 700, direction: "ltr" }}>{it.value}</div>}
            </div>
          );
        })}
      </div>
    </Content>
  );
};

const Rail: React.FC<{ tl: TlScene }> = ({ tl }) => {
  const { beat, s } = useBeat(tl);
  const { tpl } = useCtx();
  const target = (beat.index + 1) / Math.max(1, beat.count);
  const prev = beat.index / Math.max(1, beat.count);
  const w = prev + (target - prev) * ease(beat.since, 0, 0.5);
  return <div style={{ height: 10, borderRadius: 5, background: C.grid }}><div style={{ height: 10, borderRadius: 5, width: `${w * 100}%`, background: tpl.accent }} /></div>;
};

const TextScene: React.FC<{ scene: Scene; tl: TlScene }> = ({ scene, tl }) => {
  const { p, tpl } = useCtx();
  const enter = useEnter(tpl.enter);
  const wb = tpl.textStyle === "whiteboard";
  return (
    <Content style={{ ...enter, justifyContent: "center" }}>
      <Card style={{ padding: 44, background: wb ? "#F2F5F9" : C.panel, color: wb ? "#0E1726" : C.text, display: "flex", flexDirection: "column", gap: 28 }}>
        <Headline text={t(scene.headline, p.lang)} style={{ color: wb ? "#0E1726" : tpl.accent }} />
        {scene.body && <Body text={t(scene.body, p.lang)} style={{ color: wb ? "#1E293B" : C.text }} />}
        <Rail tl={tl} />
      </Card>
    </Content>
  );
};

const MythScene: React.FC<{ scene: Scene; tl: TlScene }> = ({ scene, tl }) => {
  const { p, tpl } = useCtx();
  const { s } = useBeat(tl);
  const half = (s.dur / 2) * s.fps;
  const flip = ease(s.frame, half, half + 12);
  const showAnswer = flip > 0.5;
  const rot = interpolate(flip, [0, 0.5, 1], [0, 90, 0]);
  return (
    <Content style={{ justifyContent: "center" }}>
      <Card style={{ padding: 44, transform: `perspective(1200px) rotateX(${rot}deg)`, border: `6px solid ${showAnswer ? C.primary : tpl.accent}`, display: "flex", flexDirection: "column", gap: 28 }}>
        <Headline text={showAnswer ? t(scene.body, p.lang) || t(scene.headline, p.lang) : t(scene.headline, p.lang)} style={{ color: showAnswer ? C.primary : tpl.accent }} />
        <Rail tl={tl} />
      </Card>
    </Content>
  );
};

const QAScene: React.FC<{ scene: Scene; tl: TlScene }> = ({ scene, tl }) => {
  const { p, tpl } = useCtx();
  const { s } = useBeat(tl);
  const ans = ease(s.frame, 0.8 * s.fps, 1.3 * s.fps);
  return (
    <Content style={{ justifyContent: "center" }}>
      <Card style={{ padding: 40, display: "flex", gap: 24, alignItems: "flex-start" }}>
        <div style={{ width: 64, height: 64, borderRadius: 32, background: tpl.accent, flex: "none" }} />
        <Headline text={t(scene.headline, p.lang)} />
      </Card>
      {scene.body && <Card style={{ padding: 40, opacity: ans, borderLeft: `8px solid ${C.primary}` }}><Body text={t(scene.body, p.lang)} /></Card>}
      <Rail tl={tl} />
    </Content>
  );
};

// End card (scene kind "disclaimer" kept for manifest compatibility): "Follow UllasLab" + "Education only" in the video's language.
// The full disclaimer is NOT shown in the video; it is the first line of the description / caption (owner decision 2026-11-09).
const DisclaimerScene: React.FC = () => {
  const { p, L } = useCtx();
  const [follow, edu] = endParts(p.lang);
  return (
    <Content style={{ justifyContent: "center" }}>
      <Card style={{ padding: 44, border: `4px solid ${C.grid}`, textAlign: "center", direction: p.rtl ? "rtl" : "ltr" }}>
        <div data-audit="headline" style={{ fontSize: L.type.headline, fontWeight: 700, lineHeight: 1.2, color: C.text }}>{follow}</div>
        <div data-audit="body" style={{ fontSize: L.type.body, lineHeight: 1.4, color: C.muted, marginTop: 16 }}>{edu}</div>
      </Card>
    </Content>
  );
};

const View: React.FC<{ scene: Scene; tl: TlScene }> = ({ scene, tl }) => {
  const { p, tpl } = useCtx();
  const enter = useEnter(tpl.enter);
  switch (scene.kind) {
    case "chart": case "hook":
      if (scene.chart_data) return <ChartBlock scene={scene} tl={tl} />;
      return <Content style={{ ...enter, justifyContent: "center" }}><Headline text={t(scene.headline, p.lang)} style={{ fontSize: 96, color: tpl.accent }} /><Rail tl={tl} /></Content>;
    case "compare": return <ChartBlock scene={scene} tl={tl} />;
    case "counter": return <CounterScene scene={scene} tl={tl} />;
    case "grid": return <GridScene scene={scene} tl={tl} />;
    case "myth": return <MythScene scene={scene} tl={tl} />;
    case "qa": return <QAScene scene={scene} tl={tl} />;
    case "disclaimer": return <DisclaimerScene />;
    default: return <TextScene scene={scene} tl={tl} />;
  }
};

export const Scenes: React.FC = () => {
  const { p } = useCtx();
  const { fps } = useVideoConfig();
  return (
    <>
      {p.timeline.scenes.map((tl) => {
        const scene = p.scenes.find((s) => s.id === tl.id) ?? ({ id: tl.id, kind: tl.kind } as Scene);
        const from = Math.round(tl.start * fps);
        const dur = Math.max(1, Math.round(tl.end * fps) - from);
        return <Sequence key={tl.id} from={from} durationInFrames={dur} layout="none"><View scene={scene} tl={tl} /></Sequence>;
      })}
    </>
  );
};
