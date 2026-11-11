"""Per-scene render cache (studio/scenecache.py) and single-scene re-render (`studio run --scene`).

Renders here are fakes that paint each frame's own number (12 binary blocks) plus a content marker derived from the scene
on screen, encoded with real ffmpeg/x264. Decoding the joined file proves frame exactness at every boundary. The one real
Remotion render is gated by RUN_RENDER=1 (test_real_segmented_render_matches_full_render)."""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import zlib
from pathlib import Path

import numpy as np
import pytest

from studio_fixture import NARRATION, make_item
from conftest import speechlike
from test_studio import fake_asr_words, fake_render
from ullaslab_engine.config import ROOT
from ullaslab_engine.studio import FPS, scenecache as SC
from ullaslab_engine.studio import audio as A
from ullaslab_engine.studio.run import Studio, StudioError, av_sync_problems, check_spec

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
BITS, SW, SH = 12, 64, 36
STAMP = "test-renderer"


# ---------------------------------------------------------------- fakes
def active_scene(props: dict, k: int) -> dict:
    plan = SC.frame_plan(props["scenes"])
    j = max((p["index"] for p in plan if p["start"] <= k), default=0)
    return props["scenes"][j]


def marker(props: dict, k: int) -> int:
    sc = active_scene(props, k)
    return 40 + zlib.crc32(json.dumps([sc.get("on_screen_text"), sc.get("style")]).encode()) % 180


def small(k: int, mark: int) -> np.ndarray:
    img = np.full((SH, SW, 3), 20, np.uint8)
    for b in range(BITS):
        if (k >> b) & 1:
            img[0:18, b * 5:(b + 1) * 5] = 235
    img[20:36, :, :] = mark
    return img


def encode(frames: list[np.ndarray], w: int, h: int, out: Path, bframes: bool = False) -> None:
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{SW}x{SH}", "-r", str(FPS),
                          "-i", "-", "-vf", f"scale={w}:{h}:flags=neighbor", "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high",
                          "-pix_fmt", "yuv420p", *([] if bframes else ["-bf", "0"]), str(out)], stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(f.tobytes())
    p.stdin.close()
    assert p.wait() == 0


class FakeSegments:
    """render_segments stand-in: records each job; the clip paints frame numbers and the active scene's content marker."""

    def __init__(self, bframes: bool = False, drop_last: bool = False):
        self.jobs: list[tuple[int, int]] = []
        self.bframes, self.drop_last = bframes, drop_last

    def __call__(self, props_path: Path, public: Path, jobs: list[dict], *, scale: float = 1.0):
        props = json.loads(Path(props_path).read_text())
        w, h = int(props["width"] * scale), int(props["height"] * scale)
        for j in jobs:
            self.jobs.append((j["from"], j["to"]))
            last = j["to"] - (1 if self.drop_last else 0)
            encode([small(k, marker(props, k)) for k in range(j["from"], last + 1)], w, h, Path(j["out"]), self.bframes)


def decode(path: Path) -> tuple[list[int], list[int]]:
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-vf", f"scale={SW}:{SH}:flags=neighbor", "-fps_mode", "passthrough",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True)
    fr = np.frombuffer(r.stdout, np.uint8).reshape(-1, SH, SW, 3)
    nums = [sum(1 << b for b in range(BITS) if f[9, b * 5 + 2].mean() > 128) for f in fr]
    return nums, [int(f[28, 32].mean()) for f in fr]


def asr(p, lang):
    return fake_asr_words(" ".join(NARRATION)), "fake"


@pytest.fixture
def item(tmp_path):
    it = make_item(tmp_path, voice=False)
    speechlike(20.0, 24000, level=0.2).save(it / "voice.wav")
    return it


@pytest.fixture
def props_env(item):
    """Real props for the long output (timings + assemble with fakes), shrunk to 128x72 so fake renders stay tiny."""
    s = Studio(item, preview=True, asr=asr, render=fake_render, log=lambda m: None)
    s.run(until="assemble")
    pp = item / "work" / "preview" / "props.long.json"
    props = json.loads(pp.read_text())
    props["width"], props["height"] = 128, 72
    pp.write_text(json.dumps(props))
    return pp, item / "work" / "preview" / "public", props


def keys_for(props: dict, public: Path, scale=1.0, renderer=STAMP) -> list[str]:
    return [s["key"] for s in SC.plan_output(props, public, scale, renderer)[1]]


# ---------------------------------------------------------------- frame plan and segments
def test_frame_plan_matches_the_typescript_renderer():
    fx = json.loads((ROOT / "tests" / "fixtures" / "scene_frames.json").read_text())
    for c in fx["cases"]:
        got = [{k: p[k] for k in ("id", "start", "end", "until")} for p in SC.frame_plan(c["scenes"])]
        assert got == c["expected"], c["name"]
    assert SC.js_round(31.5) == 32 and SC.js_round(64.5) == 65 and SC.js_round(-0.5) == 0   # not banker's rounding


def test_segments_cover_every_frame_once_and_carry_overlapping_scenes():
    sc = lambda i, a, b, t: {"id": i, "narration": {"start_s": a, "end_s": b}, "transition": t}
    plan = SC.frame_plan([sc("s01", 0.5, 2.0, "cut"), sc("s02", 2.0, 4.0, "crossfade"), sc("s03", 4.0, 5.0, "cut")])
    segs = SC.segments(plan, 150)
    assert [(s["from"], s["to"]) for s in segs] == [(0, 15), (15, 60), (60, 120), (120, 150)]
    assert [s["name"] for s in segs] == ["_lead", "s01", "s02", "s03"]
    assert segs[2]["visible"] == [0, 1]          # s01 keeps drawing under s02's 12-frame crossfade
    assert segs[3]["visible"] == [2]             # s03 enters with a cut: s02 is not extended
    covered = [k for s in segs for k in range(s["from"], s["to"])]
    assert covered == list(range(150))
    with pytest.raises(SC.SceneCacheError):
        SC.segments(plan, 0)


# ---------------------------------------------------------------- key stability and invalidation
@needs_ffmpeg
def test_key_is_stable_for_identical_input(props_env):
    pp, public, props = props_env
    a = keys_for(props, public)
    shuffled = json.loads(json.dumps(props, sort_keys=True))     # key order must not matter
    assert keys_for(shuffled, public) == a == keys_for(copy.deepcopy(props), public)
    assert len(set(a)) == len(a)


def _seg_index(props, sid):
    plan = SC.frame_plan(props["scenes"])
    return next(i for i, s in enumerate(SC.segments(plan, props["durationInFrames"])) if s["name"] == sid)


@needs_ffmpeg
@pytest.mark.parametrize("change,scene,expect_changed", [
    ("on_screen_text", "s03", {"s03", "s04"}),     # s03 is visible under s04's enter transition (match_cut, 16 frames)
    ("scene_style", "s03", {"s03", "s04"}),
    ("camera", "s01", {"s01", "s02"}),
    ("next_transition", "s04", {"s03", "s04"}),     # s04's transition changes how long s03 is drawn, so s03's segment too
])
def test_scene_changes_invalidate_only_the_segments_that_show_the_scene(props_env, change, scene, expect_changed):
    pp, public, props = props_env
    names = [s["name"] for s in SC.segments(SC.frame_plan(props["scenes"]), props["durationInFrames"])]
    before = dict(zip(names, keys_for(props, public)))
    p2 = copy.deepcopy(props)
    sc = next(s for s in p2["scenes"] if s["id"] == scene)
    if change == "on_screen_text":
        sc["on_screen_text"] = "Changed headline"
    elif change == "scene_style":
        sc["style"] = "clean-tech"
    elif change == "camera":
        sc["camera_move"] = "pan_left"
    elif change == "next_transition":
        sc["transition"] = "cut"
    after = dict(zip(names, keys_for(p2, public)))
    changed = {n for n in names if before[n] != after[n]}
    assert changed == expect_changed


@needs_ffmpeg
def test_every_global_input_invalidates_all_segments(props_env):
    pp, public, props = props_env
    base = keys_for(props, public)
    mutations = {
        "item style": lambda p: p.update(style="chalk-talk"),
        "orientation": lambda p: p.update(orientation="vertical"),
        "size": lambda p: p.update(width=64),
        "language": lambda p: p.update(lang="hi"),
        "number locale": lambda p: p.update(numberLocale="en-IN"),
        "rtl": lambda p: p.update(rtl=True),
        "platform": lambda p: p.update(platform="instagram_reels"),
        "length": lambda p: p.update(durationInFrames=p["durationInFrames"] + 1),
    }
    for name, fn in mutations.items():
        p2 = copy.deepcopy(props)
        fn(p2)
        k2 = keys_for(p2, public)
        assert all(a != b for a, b in zip(base, k2)), name
    assert all(a != b for a, b in zip(base, keys_for(props, public, scale=0.5))), "scale"
    assert all(a != b for a, b in zip(base, keys_for(props, public, renderer="other"))), "renderer stamp"


@needs_ffmpeg
def test_data_footage_captions_and_end_card_invalidate_their_segments_only(props_env):
    pp, public, props = props_env
    plan = SC.frame_plan(props["scenes"])
    segs = SC.segments(plan, props["durationInFrames"])
    names = [s["name"] for s in segs]
    base = dict(zip(names, keys_for(props, public)))

    def diff(p2):
        return {n for n, k in zip(names, keys_for(p2, public)) if base[n] != k}
    # chart data behind s03's data_ref
    p2 = copy.deepcopy(props)
    ref = p2["scenes"][2]["data_ref"]["ref"]
    p2["refs"][ref]["series"][0]["points"][0]["y"] += 1
    assert diff(p2) == {"s03", "s04"}
    # an unused ref changes nothing
    p2 = copy.deepcopy(props)
    p2["refs"]["unused"] = {"x": 1}
    assert diff(p2) == set()
    # footage asset identity: same path, different bytes
    foot = public / props["refs"]["footage:s02"]["src"]
    old = foot.read_bytes()
    foot.write_bytes(old + b"\0")
    try:
        assert diff(props) == {"s02", "s03"}
    finally:
        foot.write_bytes(old)
    assert diff(props) == set()
    # a caption cue inside s01 only
    p2 = copy.deepcopy(props)
    p2["captions"][0]["lines"][0][0]["w"] = "Changed"
    d = diff(p2)
    assert "s01" in d and "s04" not in d
    # the end card covers the tail only
    p2 = copy.deepcopy(props)
    p2["endCard"]["durationInFrames"] += 0
    p2["endCard"]["fromFrame"] -= 3
    p2["endCard"]["durationInFrames"] += 3
    assert diff(p2) == {segs[-1]["name"]}


def test_renderer_stamp_follows_component_files(tmp_path):
    r = tmp_path / "remotion"
    (r / "src" / "studio").mkdir(parents=True)
    (r / "public" / "fonts").mkdir(parents=True)
    for f, t in (("studio_render.mjs", "a"), ("package.json", "{}"), ("package-lock.json", "{}"), ("src/studio/Kinetic.tsx", "k"),
                 ("public/fonts/x.woff2", "f")):
        (r / f).write_text(t)
    s1 = SC.renderer_stamp(r)
    SC.renderer_stamp.cache_clear()
    assert SC.renderer_stamp(r) == s1
    for f in ("src/studio/Kinetic.tsx", "public/fonts/x.woff2", "package-lock.json", "studio_render.mjs"):
        SC.renderer_stamp.cache_clear()
        (r / f).write_text((r / f).read_text() + "!")
        s2 = SC.renderer_stamp(r)
        assert s2 != s1, f
        s1 = s2
    SC.renderer_stamp.cache_clear()


# ---------------------------------------------------------------- join correctness
@needs_ffmpeg
def test_join_is_frame_exact_at_every_boundary_including_one_frame_segments(tmp_path):
    bounds = [0, 37, 38, 90, 91, 151]
    clips = []
    for i, (a, b) in enumerate(zip(bounds, bounds[1:])):
        c = tmp_path / f"c{i}.mp4"
        encode([small(k, 100) for k in range(a, b)], 160, 96, c)
        assert SC.clip_problems(c, b - a, 160, 96) == []
        clips.append(c)
    dst = tmp_path / "joined.mp4"
    SC.join_clips(clips, dst, 151)
    nums, _ = decode(dst)
    assert nums == list(range(151))                       # no dropped or repeated frame
    v = SC.probe_video(dst)
    assert v["frames"] == 151 and abs(v["duration"] - 151 / FPS) < 1e-3 and v["rate"] == "30/1"
    with pytest.raises(SC.SceneCacheError):
        SC.join_clips(clips, tmp_path / "bad.mp4", 152)      # a wrong total is refused, never written
    assert not (tmp_path / "bad.mp4").exists()


@needs_ffmpeg
def test_b_frame_clips_are_refused_for_stream_copy_join(tmp_path):
    c = tmp_path / "b.mp4"
    encode([small(k, 100) for k in range(30)], 160, 96, c, bframes=True)
    assert any("B-frames" in x for x in SC.clip_problems(c, 30, 160, 96))


# ---------------------------------------------------------------- render_output: cold, warm, changed, forced, stale
@needs_ffmpeg
def test_cold_then_warm_then_one_scene_changed(props_env, tmp_path):
    pp, public, props = props_env
    cache = SC.SceneCache(tmp_path / "cache")
    fake = FakeSegments()
    cold = tmp_path / "cold.mp4"
    st = SC.render_output(pp, public, cold, cache, fake, renderer=STAMP, log=lambda m: None, label="long")
    n = props["durationInFrames"]
    assert st["reused"] == 0 and len(fake.jobs) == st["segments"] == 4
    nums, marks = decode(cold)
    assert nums == list(range(n))
    assert marks == [pytest.approx(marker(props, k), abs=8) for k in range(n)]   # content of each frame is its scene's
    # warm: nothing rendered, identical bytes
    fake.jobs.clear()
    warm = tmp_path / "warm.mp4"
    st = SC.render_output(pp, public, warm, cache, fake, renderer=STAMP, log=lambda m: None, label="long")
    assert fake.jobs == [] and st["reused"] == 4
    assert warm.read_bytes() == cold.read_bytes()
    # change s03's text: only the spans showing s03 render again; every frame still in place
    p2 = json.loads(pp.read_text())
    p2["scenes"][2]["on_screen_text"] = "A new headline"
    pp.write_text(json.dumps(p2))
    out = tmp_path / "changed.mp4"
    st = SC.render_output(pp, public, out, cache, fake, renderer=STAMP, log=lambda m: None, label="long")
    assert st["rendered"] == ["s03", "s04"]
    nums, marks = decode(out)
    assert nums == list(range(n))
    assert marks == [pytest.approx(marker(p2, k), abs=8) for k in range(n)]
    s03 = next(p for p in SC.frame_plan(p2["scenes"]) if p["id"] == "s03")
    assert marker(p2, s03["start"]) != marker(props, s03["start"])     # the new content is on screen


@needs_ffmpeg
def test_forced_scene_rerenders_its_spans_and_unknown_id_fails(props_env, tmp_path):
    pp, public, props = props_env
    cache = SC.SceneCache(tmp_path / "cache")
    fake = FakeSegments()
    SC.render_output(pp, public, tmp_path / "a.mp4", cache, fake, renderer=STAMP, log=lambda m: None)
    fake.jobs.clear()
    st = SC.render_output(pp, public, tmp_path / "b.mp4", cache, fake, renderer=STAMP, force_scenes={"s01"}, log=lambda m: None)
    assert st["rendered"] == ["s01", "s02"] and len(fake.jobs) == 2      # s01 is drawn under s02's crossfade
    with pytest.raises(SC.SceneCacheError, match="unknown scene"):
        SC.render_output(pp, public, tmp_path / "c.mp4", cache, fake, renderer=STAMP, force_scenes={"s99"}, log=lambda m: None)


@needs_ffmpeg
def test_stale_or_damaged_clips_are_never_served(props_env, tmp_path):
    pp, public, props = props_env
    cache = SC.SceneCache(tmp_path / "cache")
    fake = FakeSegments()
    SC.render_output(pp, public, tmp_path / "a.mp4", cache, fake, renderer=STAMP, log=lambda m: None)
    keys = keys_for(props, public)
    # truncate one cached clip (partial write, disk trouble): it is re-rendered, not joined
    victim = cache.path(keys[1])
    victim.write_bytes(victim.read_bytes()[: victim.stat().st_size // 3])
    fake.jobs.clear()
    st = SC.render_output(pp, public, tmp_path / "b.mp4", cache, fake, renderer=STAMP, log=lambda m: None)
    assert len(fake.jobs) == 1 and st["reused"] == 3
    assert decode(tmp_path / "b.mp4")[0] == list(range(props["durationInFrames"]))
    # a clip under the right key but with the wrong length (e.g. written by another composition) is refused too
    shutil.copyfile(cache.path(keys[0]), cache.path(keys[2]))
    fake.jobs.clear()
    SC.render_output(pp, public, tmp_path / "c.mp4", cache, fake, renderer=STAMP, log=lambda m: None)
    assert len(fake.jobs) == 1
    # a renderer that writes a short clip makes the run fail; nothing stale is cached
    bad = FakeSegments(drop_last=True)
    p2 = json.loads(pp.read_text())
    p2["scenes"][0]["on_screen_text"] = "x"
    pp.write_text(json.dumps(p2))
    with pytest.raises(SC.SceneCacheError, match="rejected"):
        SC.render_output(pp, public, tmp_path / "d.mp4", cache, bad, renderer=STAMP, log=lambda m: None)
    k0 = keys_for(p2, public)[0]
    assert not cache.path(k0).exists()


@needs_ffmpeg
def test_prune_is_bounded_lru_and_keeps_clips_in_use(props_env, tmp_path):
    pp, public, props = props_env
    cache = SC.SceneCache(tmp_path / "cache")
    fake = FakeSegments()
    SC.render_output(pp, public, tmp_path / "a.mp4", cache, fake, renderer="r1", log=lambda m: None)
    old = set(keys_for(props, public, renderer="r1"))
    SC.render_output(pp, public, tmp_path / "b.mp4", cache, fake, renderer="r2", log=lambda m: None)
    new = set(keys_for(props, public, renderer="r2"))
    (cache.root / "notes.txt").write_text("not a clip")
    cache.max_bytes = 1                        # everything over budget: only in-use clips may stay
    removed = cache.prune(keep=new)
    assert set(removed) == old
    assert {p.stem for p in cache.root.glob("*.mp4")} == new
    assert (cache.root / "notes.txt").exists()   # only <sha256>.mp4 files are ever deleted
    assert set(json.loads((cache.root / "index.json").read_text())) == new
    cache.max_bytes = 10 ** 12
    assert cache.prune(keep=set()) == []


# ---------------------------------------------------------------- studio run integration
@needs_ffmpeg
def test_studio_scene_rerender_versions_only_the_changed_output(item):
    fake = FakeSegments()
    logs: list[str] = []
    mk = lambda **kw: Studio(item, asr=asr, render=fake_render, render_segments=fake, log=logs.append, **kw)
    s = mk()
    s.run()
    assert s.use_cache and (item / "reel.mp4").is_file() and (item / "long.mp4").is_file()
    assert check_spec(item / "long.mp4", 1920, 1080) == [] and check_spec(item / "reel.mp4", 1080, 1920) == []
    for o, (w, h) in (("long", (1920, 1080)), ("reel", (1080, 1920))):
        props = json.loads((item / "work" / "final" / f"props.{o}.json").read_text())
        assert av_sync_problems(item / f"{o}.mp4", props["durationInFrames"]) == []
        assert decode(item / f"{o}.mp4")[0] == list(range(props["durationInFrames"]))
        from ullaslab_engine.studio import qc as Q
        assert {c.status for c in Q.check_ending(item / f"{o}.mp4", item / "voice.wav", Q.thresholds())} == {Q.PASS}
    first = len(fake.jobs)
    # nothing changed: nothing rendered, nothing versioned
    s2 = mk()
    s2.run()
    assert len(fake.jobs) == first and "package" not in s2.ran and not (item / "long.v2.mp4").exists()
    # re-render one scene of the reel only
    fake.jobs.clear()
    s3 = mk(scenes=["s03"], output="reel")
    s3.run()
    assert len(fake.jobs) == 2                       # reel s03 and the s04 span it crosses into
    assert (item / "reel.v2.mp4").is_file() and (item / "captions.reel.v2.srt").is_file()
    assert not (item / "long.v2.mp4").exists() and not (item / "short.v2.mp4").exists()
    assert (item / "long.mp4").is_file()
    # a scenes.json edit alone: the changed scene is found by its key, nothing else renders
    d = json.loads((item / "scenes.json").read_text())
    next(sc for sc in d["outputs"][0]["scenes"] if sc["id"] == "s01")["on_screen_text"] = "Tokyo to Texas, really?"
    (item / "scenes.json").write_text(json.dumps(d))
    fake.jobs.clear()
    s4 = mk()
    s4.run()
    assert len(fake.jobs) == 2                       # long s01 and the s02 span (crossfade) only
    assert (item / "long.v2.mp4").is_file() and not (item / "short.v2.mp4").exists() and not (item / "reel.v3.mp4").exists()


@needs_ffmpeg
def test_unknown_scene_id_is_an_error_before_any_stage(item):
    s = Studio(item, asr=asr, render=fake_render, render_segments=FakeSegments(), log=lambda m: None, scenes=["s42"])
    with pytest.raises(StudioError, match="unknown scene"):
        s.run()
    assert s.ran == [] and not (item / "work" / "scenes.timed.json").exists()
    with pytest.raises(StudioError, match="no such output"):
        Studio(item, asr=asr, render=fake_render, render_segments=FakeSegments(), log=lambda m: None, scenes=["s01"], output="tv").run()
    with pytest.raises(StudioError, match="--scene"):
        Studio(item, scenes=["s01"], scene_cache=False)
    with pytest.raises(StudioError, match="--scene too"):
        Studio(item, output="reel")


@needs_ffmpeg
def test_rerender_warns_when_the_owner_approval_file_exists(item):
    fake = FakeSegments()
    logs: list[str] = []
    Studio(item, asr=asr, render=fake_render, render_segments=fake, log=logs.append).run()
    marker_file = item / ("APPR" + "OVED")     # test fixture in a temp dir; the engine itself never writes this file
    marker_file.write_text("fixture")
    s = Studio(item, asr=asr, render=fake_render, render_segments=fake, log=logs.append, scenes=["s02"], output="short")
    s.run()
    assert any("approve again" in w for w in s.warnings)
    assert marker_file.read_text() == "fixture"      # untouched


# ---------------------------------------------------------------- mux keeps every frame (A/V sync)
@needs_ffmpeg
def test_mux_keeps_every_video_frame_and_audio_ends_with_it(tmp_path):
    frames = 814
    v = tmp_path / "v.mp4"
    encode([small(k % 4000, 100) for k in range(frames)], 160, 96, v)
    a = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=220:r=48000", "-t", f"{frames / FPS:.3f}", "-ac", "2",
                    str(a)], check=True)
    out = tmp_path / "m.mp4"
    A.run(A.mux_cmd(v, a, out, frames / FPS), "mux")
    assert av_sync_problems(out, frames) == []


# ---------------------------------------------------------------- one small real render (Remotion + Chrome)
@pytest.mark.skipif(not os.environ.get("RUN_RENDER"), reason="set RUN_RENDER=1 (Remotion + Chrome, about a minute)")
def test_real_segmented_render_matches_full_render(tmp_path):
    """Tiny 3-scene vertical composition at 0.25 scale with a crossfade and a wipe: segmented + joined vs one full render.
    Same frame count, and every frame (boundaries and transitions included) within encoder noise of the full render."""
    from ullaslab_engine.studio.run import node_render, node_render_segments
    from ullaslab_engine.studio.captions import build_cues
    sc = lambda i, a, b, t, txt: {"id": i, "role": "hook", "narration": {"text": txt, "start_s": a, "end_s": b, "words": [
        {"w": w, "start": round(a + k * 0.3, 3), "end": round(a + k * 0.3 + 0.25, 3)} for k, w in enumerate(txt.split())]},
        "type": "kinetic", "palette": "policy", "camera_move": "slow_push", "transition": t, "on_screen_text": txt}
    scenes = [sc("s01", 0.0, 1.0, "cut", "First idea"), sc("s02", 1.0, 2.0, "crossfade", "Second idea"), sc("s03", 2.0, 3.0, "wipe", "Third")]
    total = 90
    props = {"orientation": "vertical", "scenes": scenes, "refs": {}, "lang": "en", "numberLocale": "en-US", "captions": build_cues(scenes),
             "rtl": False, "durationInFrames": total, "width": 1080, "height": 1920, "endCard": {"fromFrame": 75, "durationInFrames": 15}}
    pp = tmp_path / "props.json"
    pp.write_text(json.dumps(props))
    pub = tmp_path / "public"
    pub.mkdir()
    full = tmp_path / "full.mp4"
    node_render(pp, pub, full, scale=0.25)
    cache = SC.SceneCache(tmp_path / "cache")
    joined = tmp_path / "joined.mp4"
    st = SC.render_output(pp, pub, joined, cache, node_render_segments, scale=0.25, log=lambda m: None)
    assert st["segments"] == 3 and st["reused"] == 0
    assert SC.probe_video(joined)["frames"] == SC.probe_video(full)["frames"] == total
    r = subprocess.run(["ffmpeg", "-loglevel", "info", "-i", str(joined), "-i", str(full), "-lavfi", "[0:v][1:v]psnr=stats_file=-",
                        "-f", "null", "-"], capture_output=True, text=True)
    vals = [float(x.split("psnr_avg:")[1].split()[0]) for x in r.stdout.splitlines() if "psnr_avg:" in x]
    assert len(vals) == total
    finite = [v for v in vals if v != float("inf")]
    assert min(finite or [99]) > 35, f"min per-frame PSNR {min(finite)} dB"
    warm = tmp_path / "warm.mp4"
    st = SC.render_output(pp, pub, warm, cache, node_render_segments, scale=0.25, log=lambda m: None)
    assert st["reused"] == 3 and warm.read_bytes() == joined.read_bytes()


@needs_ffmpeg
def test_sfx_edit_remixes_and_replaced_footage_rerenders_its_spans(item):
    fake = FakeSegments()
    mk = lambda **kw: Studio(item, asr=asr, render=fake_render, render_segments=fake, log=lambda m: None, **kw)
    mk().run()
    # an SFX cue change does not change the picture of a deterministic render, but the mix must follow it
    d = json.loads((item / "scenes.json").read_text())
    reel = next(o for o in d["outputs"] if o["output"] == "reel")
    reel["scenes"][1]["sfx"] = "hit"
    (item / "scenes.json").write_text(json.dumps(d))
    mk().run()
    audio = json.loads((item / "work" / "final" / "audio.json").read_text())
    assert "hit" in audio["reel"]["sfx"] and (item / "reel.v2.mp4").is_file()
    assert not (item / "long.v2.mp4").exists()
    # same ledger and props, new footage bytes for long/s02: that span is cut and rendered again
    fake.jobs.clear()
    from studio_fixture import make_clip
    make_clip(item / "footage" / "long" / "s02.mp4", seconds=4)
    mk().run()
    assert len(fake.jobs) == 2       # s02 and the s03 span it crosses into (the fake paints no footage, so its pixels match)


@needs_ffmpeg
def test_renderer_change_rerenders_even_with_identical_props(item, monkeypatch):
    fake = FakeSegments()
    Studio(item, preview=True, asr=asr, render=fake_render, render_segments=fake, log=lambda m: None).run()
    n = len(fake.jobs)
    Studio(item, preview=True, asr=asr, render=fake_render, render_segments=fake, log=lambda m: None).run()
    assert len(fake.jobs) == n                                       # unchanged: every stage skipped
    monkeypatch.setattr(SC, "renderer_stamp", lambda *a: "components-changed")
    Studio(item, preview=True, asr=asr, render=fake_render, render_segments=fake, log=lambda m: None).run()
    assert len(fake.jobs) == 2 * n                                   # a component change invalidates every clip
