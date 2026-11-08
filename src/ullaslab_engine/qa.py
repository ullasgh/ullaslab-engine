"""QA gates A1-A5 (config/quality.yaml) plus duration. Writes qa.json. Contains numbers only:
never transcripts, script text or URLs (this repo is public and its artifacts must stay content-free)."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

from .audio import Wav, loudness_lufs, max_silence_s, true_peak_dbtp
from .bundle import seg_text
from .config import ROOT, quality

SAFE_ZONES = json.loads((ROOT / "config" / "safe_zones.json").read_text())
VISUAL_KINDS = {"hook", "chart", "counter", "compare", "grid", "myth", "qa"}
# Duration windows (seconds) from CLAUDE.md rule 7 / docs/formats.md.
DURATION = {"vertical": (30.0, 60.0), "horizontal": (360.0, 600.0)}
# Audit roles (remotion/src/components/audit.tsx). Mandatory compliance text (disclaimer card, source stamp,
# freshness tag, brand mark) and axis tick labels are exempt from the 12-word budget, which covers
# headlines, body copy and data labels. Owner decision logged in the WP4 report.
BODY_ROLES = {"headline", "body", "caption", "legal"}
LABEL_ROLES = {"label", "axis", "stamp", "tag"}
COUNTED_ROLES = {"headline", "body", "label"}
SENTENCE_END = "。.!?!?।؟"


def chart_hash(chart: dict) -> str:
    c = {k: v for k, v in chart.items() if k != "chart_hash"}
    return hashlib.sha256(json.dumps(c, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _check(name: str, value, limit, ok: bool) -> dict:
    return {"name": name, "value": value if not isinstance(value, float) else round(value, 3),
            "limit": limit, "passed": bool(ok)}


def _gate(checks: list[dict], note: str | None = None) -> dict:
    g = {"passed": all(c["passed"] for c in checks), "checks": checks}
    if note:
        g["note"] = note
    return g


def contrast_ratio(fg: str, bg: str) -> float:
    def lum(h: str) -> float:
        h = h.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
    a, b = sorted((lum(fg), lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def gate_a1(m: dict) -> dict:
    q = quality()["A1_financial_clarity"]
    charts = [s["chart_data"] for s in m["scenes"] if "chart_data" in s]
    checks = [_check("charts_with_claim_id", sum(1 for c in charts if c.get("claim_id")), len(charts),
                     all(c.get("claim_id") for c in charts) if q["figures_with_claim_id_pct"] == 100 else True)]
    hashed = [c for c in charts if c.get("chart_hash")]
    checks.append(_check("chart_hash_matches", sum(chart_hash(c) == c["chart_hash"] for c in hashed), len(hashed),
                         all(chart_hash(c) == c["chart_hash"] for c in hashed)))
    checks.append(_check("charts_have_hash", len(hashed), len(charts), len(hashed) == len(charts) or not q["chart_hash_must_match"]))
    return _gate(checks, "takeaway and forbidden-language lint run in the private content repo")


def gate_a2(m: dict) -> dict:
    q = quality()["A2_visual_storytelling"]
    n = sum(1 for s in m["scenes"] if "chart_data" in s)
    return _gate([_check("original_data_visuals", n, q["original_data_visual_min"], n >= q["original_data_visual_min"])],
                 "template overlap runs in the private content repo; engine renders no stock footage")


def gate_a3(m: dict, lang: str, wav: Wav, tl: dict, hyp_error_pct: float | None) -> dict:
    q = quality()["A3_narration"]
    lufs, tp = loudness_lufs(wav), true_peak_dbtp(wav)
    checks = [
        _check("lufs", lufs, f"{q['loudness_lufs']}+-{q['loudness_tolerance_lu']}", abs(lufs - q["loudness_lufs"]) <= q["loudness_tolerance_lu"]),
        _check("true_peak_dbtp", tp, q["true_peak_max_dbtp"], tp <= q["true_peak_max_dbtp"]),
    ]
    segs = tl["segments"]
    a, b = segs[0]["start"], segs[-1]["end"]
    inner = Wav(wav.samples[int(a * wav.sr): int(b * wav.sr)], wav.sr)
    checks.append(_check("max_silence_s", max_silence_s(inner), q["max_silence_s"], max_silence_s(inner) <= q["max_silence_s"]))
    if lang == "ja":  # no word boundaries: wpm and sentence-length gates do not apply
        wpm_note = "wpm and sentence-length gates not applicable to Japanese"
    else:
        wpm_note = None
        texts = [seg_text(m, s, lang) for s in m["segments"]]
        nwords = sum(len(t.split()) for t in texts)
        span_min = max((b - a) / 60, 1e-6)
        wpm = nwords / span_min
        checks.append(_check("wpm", wpm, f"{q['wpm_min']}-{q['wpm_max']}", q["wpm_min"] <= wpm <= q["wpm_max"]))
        longest = 0
        for t in texts:
            cur = 0
            for w in t.split():
                cur += 1
                if w and w[-1] in SENTENCE_END:
                    longest, cur = max(longest, cur), 0
            longest = max(longest, cur)
        checks.append(_check("max_sentence_words", longest, q["max_sentence_words"], longest <= q["max_sentence_words"]))
    if hyp_error_pct is None:
        checks.append(_check("wer_pct", "not_run", q["max_wer_pct"], False))
    else:
        checks.append(_check("wer_pct", hyp_error_pct, q["max_wer_pct"], hyp_error_pct <= q["max_wer_pct"]))
    return _gate(checks, wpm_note)


def gate_a4(tl: dict) -> dict:
    q = quality()["A4_visual_pacing"]
    scenes = [s for s in tl["scenes"] if s["kind"] != "disclaimer"]
    lens = [s["end"] - s["start"] for s in scenes]
    pts = sorted({b for s in tl["scenes"] for b in s["beats"]} | {s["start"] for s in tl["scenes"]} | {tl["total_s"]})
    gap = max(b - a for a, b in zip(pts, pts[1:])) if len(pts) > 1 else tl["total_s"]
    first = tl["scenes"][0]
    return _gate([
        _check("hook_visual_start_s", first["start"], q["hook_visual_within_s"], first["kind"] in VISUAL_KINDS and first["start"] <= q["hook_visual_within_s"]),
        _check("scene_len_min_s", min(lens), q["scene_len_min_s"], min(lens) >= q["scene_len_min_s"]),
        _check("scene_len_max_s", max(lens), q["scene_len_max_s"], max(lens) <= q["scene_len_max_s"]),
        _check("max_seconds_between_changes", gap, q["max_seconds_between_changes"], gap <= q["max_seconds_between_changes"]),
        _check("max_static_frame_s", gap, q["max_static_frame_s"], gap <= q["max_static_frame_s"]),
    ], "visual changes are the beat points the renderer animates (timeline.scenes[].beats)")


def gate_a5(layout: dict | None, cues: list[dict], orientation: str) -> dict:
    q = quality()["A5_mobile_readability"]
    if layout is None:
        return _gate([_check("layout_audit", "missing", "present", False)])
    sz = SAFE_ZONES[orientation]
    W, H = layout["width"], layout["height"]
    out_of_zone = small_body = small_label = low_contrast = 0
    worst_words = 0
    min_cr = 99.0
    for fr in layout["frames"]:
        non_caption_words = 0
        for e in fr["elements"]:
            if e["role"] == "bg":
                continue
            if (e["x"] < sz["sides"] - 0.5 or e["x"] + e["w"] > W - sz["sides"] + 0.5
                    or e["y"] < sz["top"] - 0.5 or e["y"] + e["h"] > H - sz["bottom"] + 0.5):
                out_of_zone += 1
            if e["role"] in BODY_ROLES and e["fontPx"] < q["min_body_text_px"] - 0.01:
                small_body += 1
            if e["role"] in LABEL_ROLES and e["fontPx"] < q["min_label_text_px"] - 0.01:
                small_label += 1
            if e.get("fg") and e.get("bg"):
                cr = contrast_ratio(e["fg"], e["bg"])
                min_cr = min(min_cr, cr)
                low_contrast += cr < q["min_contrast_ratio"]
            if e["role"] in COUNTED_ROLES:
                non_caption_words += e.get("words", 0)
        worst_words = max(worst_words, non_caption_words)
    max_lines = max((len(c["lines"]) for c in cues), default=0)
    max_chars = max((len(l) for c in cues for l in c["lines"]), default=0)
    cap_chars = q["caption_max_chars_per_line"]
    return _gate([
        _check("elements_outside_safe_zone", out_of_zone, 0, out_of_zone == 0),
        _check("body_text_below_min_px", small_body, 0, small_body == 0),
        _check("label_text_below_min_px", small_label, 0, small_label == 0),
        _check("contrast_failures", low_contrast, 0, low_contrast == 0),
        _check("min_contrast_ratio", min_cr, q["min_contrast_ratio"], min_cr >= q["min_contrast_ratio"]),
        _check("max_non_caption_words_per_scene", worst_words, q["max_non_caption_words_per_scene"], worst_words <= q["max_non_caption_words_per_scene"]),
        _check("caption_lines", max_lines, q["caption_max_lines"], max_lines <= q["caption_max_lines"]),
        _check("caption_chars_per_line", max_chars, cap_chars, max_chars <= cap_chars),
        _check("frame_size", f"{W}x{H}", f"{q['width_px']}x{q['height_px']}" if orientation == "vertical" else "1920x1080",
               (W, H) == ((q["width_px"], q["height_px"]) if orientation == "vertical" else (1920, 1080))),
    ])


def gate_duration(tl: dict, orientation: str, master_total: float | None) -> dict:
    lo, hi = DURATION[orientation]
    checks = [_check("duration_s", tl["total_s"], f"{lo}-{hi}", lo <= tl["total_s"] <= hi),
              _check("dub_overruns", len(tl.get("overruns", [])), 0, not tl.get("overruns"))]
    if master_total is not None:
        checks.append(_check("matches_master_s", abs(tl["total_s"] - master_total), 0.5, abs(tl["total_s"] - master_total) <= 0.5))
    return _gate(checks)


def run_qa(m: dict, lang: str, wav: Wav, tl: dict, cues: list[dict], layout: dict | None,
           hyp_error_pct: float | None, orientation: str, master_total: float | None = None) -> dict:
    """layout=None fails A5; audio-only dubs pass an empty-frames layout (caption limits still checked)."""
    gates = {"A1": gate_a1(m), "A2": gate_a2(m), "A3": gate_a3(m, lang, wav, tl, hyp_error_pct),
             "A4": gate_a4(tl), "A5": gate_a5(layout, cues, orientation),
             "duration": gate_duration(tl, orientation, master_total)}
    return {"lang": lang, "slug": m["slug"], "passed": all(g["passed"] for g in gates.values()), "gates": gates}


def write_qa(qa: dict, path: Path) -> None:
    Path(path).write_text(json.dumps(qa, indent=2, ensure_ascii=False), encoding="utf-8")
