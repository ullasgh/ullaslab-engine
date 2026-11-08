"""Local voice demo: one short finance passage in every language, several voice options per language, an
index.html with audio players and a selection form that downloads a choices JSON.

Runs entirely on this machine. Reference clips are read from a local directory and never copied into the
output; the output folder holds only synthetic audio, but it is still personal data: keep it local."""
from __future__ import annotations
import html
import json
import logging
from pathlib import Path
from typing import Callable
import soundfile as sf
from ..audio import Wav
from ..config import language, languages
from . import naturalness
from .settings import voice_settings

log = logging.getLogger("ullaslab.demo")

# ~20 s passage (RUNBOOK voice passages 1 and 2). Demo drafts for listening only, not for publication;
# the real pipeline uses the translator agent's output.
PASSAGES = {
    "en": "The yield curve plots interest rates against how long you lend. When short rates sit above long rates, the curve is called inverted. Historically, inversions have often come before slowdowns, but not every time. Inflation of 3.2% means that prices rose, on average, by 3.2% over twelve months.",
    "hi": "यील्ड कर्व ब्याज दरों को उधार की अवधि के सामने रखता है। जब छोटी अवधि की दरें लंबी अवधि से ऊपर होती हैं, तो कर्व को उलटा कहा जाता है। ऐतिहासिक रूप से, ऐसा अक्सर मंदी से पहले हुआ है, लेकिन हर बार नहीं। 3.2% महंगाई का मतलब है कि बारह महीनों में कीमतें औसतन 3.2% बढ़ीं।",
    "ta": "வருவாய் வளைவு, கடன் காலத்துக்கு எதிராக வட்டி விகிதங்களைக் காட்டுகிறது. குறுகியகால விகிதங்கள் நீண்டகால விகிதங்களை விட அதிகமாக இருந்தால், அது தலைகீழ் வளைவு எனப்படும். வரலாற்று ரீதியாக இது பொருளாதார மந்தத்துக்கு முன் அடிக்கடி நடந்துள்ளது, ஆனால் எப்போதும் அல்ல. 3.2% பணவீக்கம் என்றால் பன்னிரண்டு மாதங்களில் விலைகள் சராசரியாக 3.2% உயர்ந்தன என்று பொருள்.",
    "te": "దిగుబడి వక్రరేఖ రుణ కాలానికి వ్యతిరేకంగా వడ్డీ రేట్లను చూపిస్తుంది. స్వల్పకాలిక రేట్లు దీర్ఘకాలిక రేట్ల కంటే ఎక్కువగా ఉంటే, దానిని తలకిందులైన వక్రరేఖ అంటారు. చరిత్రలో ఇది తరచుగా మందగమనానికి ముందు జరిగింది, కానీ ప్రతిసారీ కాదు. 3.2% ద్రవ్యోల్బణం అంటే పన్నెండు నెలల్లో ధరలు సగటున 3.2% పెరిగాయని అర్థం.",
    "kn": "ಇಳುವರಿ ವಕ್ರರೇಖೆಯು ಸಾಲದ ಅವಧಿಗೆ ಹೋಲಿಸಿ ಬಡ್ಡಿದರಗಳನ್ನು ತೋರಿಸುತ್ತದೆ. ಅಲ್ಪಾವಧಿ ದರಗಳು ದೀರ್ಘಾವಧಿ ದರಗಳಿಗಿಂತ ಹೆಚ್ಚಿದ್ದರೆ, ಅದನ್ನು ತಲೆಕೆಳಗಾದ ವಕ್ರರೇಖೆ ಎನ್ನುತ್ತಾರೆ. ಇತಿಹಾಸದಲ್ಲಿ ಇದು ಆರ್ಥಿಕ ಕುಸಿತಕ್ಕೆ ಮೊದಲು ಹಲವು ಬಾರಿ ಸಂಭವಿಸಿದೆ, ಆದರೆ ಪ್ರತಿ ಬಾರಿಯೂ ಅಲ್ಲ. 3.2% ಹಣದುಬ್ಬರ ಎಂದರೆ ಹನ್ನೆರಡು ತಿಂಗಳಲ್ಲಿ ಬೆಲೆಗಳು ಸರಾಸರಿ 3.2% ಏರಿದವು ಎಂದರ್ಥ.",
    "ml": "യീൽഡ് കർവ് വായ്പയുടെ കാലയളവിനെതിരെ പലിശ നിരക്കുകൾ കാണിക്കുന്നു. ഹ്രസ്വകാല നിരക്കുകൾ ദീർഘകാല നിരക്കുകളേക്കാൾ ഉയർന്നാൽ അതിനെ തലകീഴായ കർവ് എന്ന് വിളിക്കുന്നു. ചരിത്രത്തിൽ ഇത് പലപ്പോഴും മാന്ദ്യത്തിന് മുമ്പ് സംഭവിച്ചിട്ടുണ്ട്, പക്ഷേ എപ്പോഴും അല്ല. 3.2% പണപ്പെരുപ്പം എന്നാൽ പന്ത്രണ്ട് മാസത്തിൽ വിലകൾ ശരാശരി 3.2% ഉയർന്നു എന്നാണ് അർത്ഥം.",
    "mr": "यील्ड कर्व्ह कर्जाच्या कालावधीच्या तुलनेत व्याजदर दाखवतो. जेव्हा अल्प मुदतीचे दर दीर्घ मुदतीच्या दरांपेक्षा जास्त असतात, तेव्हा त्याला उलटा कर्व्ह म्हणतात. ऐतिहासिकदृष्ट्या हे अनेकदा मंदीपूर्वी घडले आहे, पण प्रत्येक वेळी नाही. 3.2% महागाई म्हणजे बारा महिन्यांत किमती सरासरी 3.2% वाढल्या.",
    "bn": "ইল্ড কার্ভ ঋণের মেয়াদের বিপরীতে সুদের হার দেখায়। যখন স্বল্পমেয়াদি হার দীর্ঘমেয়াদি হারের উপরে থাকে, তখন কার্ভটিকে উল্টানো বলা হয়। ইতিহাসে এটি প্রায়ই মন্দার আগে ঘটেছে, তবে প্রতিবার নয়। ৩.২% মূল্যস্ফীতি মানে বারো মাসে দাম গড়ে ৩.২% বেড়েছে।",
    "gu": "યીલ્ડ કર્વ ઉધારની મુદત સામે વ્યાજ દરો દર્શાવે છે. જ્યારે ટૂંકા ગાળાના દરો લાંબા ગાળાના દરો કરતાં ઊંચા હોય, ત્યારે કર્વને ઊંધો કહેવાય છે. ઐતિહાસિક રીતે આવું ઘણી વાર મંદી પહેલાં બન્યું છે, પરંતુ દર વખતે નહીં. 3.2% મોંઘવારી એટલે બાર મહિનામાં ભાવ સરેરાશ 3.2% વધ્યા.",
    "es": "La curva de rendimientos muestra los tipos de interés frente al plazo del préstamo. Cuando los tipos a corto plazo superan a los de largo plazo, la curva se llama invertida. Históricamente, las inversiones han llegado a menudo antes de una desaceleración, pero no siempre. Una inflación del 3,2% significa que los precios subieron, en promedio, un 3,2% en doce meses.",
    "pt": "A curva de juros mostra as taxas de juros em relação ao prazo do empréstimo. Quando as taxas de curto prazo ficam acima das de longo prazo, a curva é chamada de invertida. Historicamente, as inversões costumam vir antes de uma desaceleração, mas nem sempre. Uma inflação de 3,2% significa que os preços subiram, em média, 3,2% em doze meses.",
    "ar": "يعرض منحنى العائد أسعار الفائدة مقابل مدة الإقراض. عندما تكون أسعار الفائدة قصيرة الأجل أعلى من طويلة الأجل يسمى المنحنى معكوسا. تاريخيا، جاءت حالات الانعكاس غالبا قبل التباطؤ، لكن ليس في كل مرة. تضخم بنسبة 3.2% يعني أن الأسعار ارتفعت في المتوسط بنسبة 3.2% خلال اثني عشر شهرا.",
    "ja": "イールドカーブは、貸し出し期間ごとの金利を示します。短期金利が長期金利を上回ると、カーブは逆転していると呼ばれます。歴史的に、逆転は景気減速の前に起きることが多いですが、毎回ではありません。インフレ率3.2%とは、12か月間で物価が平均3.2%上昇したという意味です。",
}


def plan(langs: list[str] | None = None, max_per_lang: int | None = None) -> list[dict]:
    """Variants to render. Clone languages: 3 clips x {native, mine} (English: mine only, there is no
    accent to localise). Stock languages: the two recommended speakers."""
    rows = []
    for code, cfg in languages().items():
        if langs and code not in langs:
            continue
        v = []
        if cfg["voice_mode"] == "clone":
            accents = ["mine"] if code == "en" else ["native", "mine"]
            v = [{"id": f"clip{c}-{a}", "label": f"Clip {c}, {a} accent", "accent": a, "ref_clip": c}
                 for c in (1, 2, 3) for a in accents]
        elif cfg.get("speakers"):
            v = [{"id": f"spk{i}-{n}", "label": f"Stock voice {n}", "speaker": i} for i, n in enumerate(cfg["speakers"][:2])]
        if max_per_lang:
            v = v[:max_per_lang]
        rows += [{"lang": code, "name": cfg["name"], **x} for x in v]
    return rows


def render_demo(out: Path, refs: Path | None, synth: Callable[..., Wav], langs: list[str] | None = None,
                max_per_lang: int | None = None, passages: dict | None = None) -> Path:
    """synth(text, lang, ref_wav, overrides=...) -> Wav. refs holds clip1.wav..clip3.wav (clone languages)."""
    out = Path(out); (out / "audio").mkdir(parents=True, exist_ok=True)
    texts = passages or PASSAGES
    rows = []
    for v in plan(langs, max_per_lang):
        lang = v["lang"]
        ov = {k: v[k] for k in ("accent", "ref_clip", "speaker") if k in v}
        ref = None
        if "ref_clip" in v:
            ref = (Path(refs) / f"clip{v['ref_clip']}.wav") if refs else None
            if not ref or not ref.is_file():
                v["skipped"] = "reference clip missing"; rows.append(v); continue
        try:
            w = synth(texts[lang], lang, ref, overrides=ov)
        except Exception as e:  # keep going: one missing model must not hide the others
            v["skipped"] = f"{type(e).__name__}: {str(e)[:80]}"; rows.append(v); continue
        fn = f"audio/{lang}-{v['id']}.wav"
        sf.write(str(out / fn), w.samples, w.sr, subtype="PCM_16")
        rep = naturalness.score(w)
        v.update(file=fn, score=rep.score, flags=list(rep.failures), seconds=round(w.duration, 1),
                 engine=getattr(w, "engine", None))
        rows.append(v)
        log.info("rendered %s %s", lang, v["id"])
    prev = out / "variants.json"  # keep earlier runs of other languages (clone and stock engines run separately)
    if prev.is_file():
        done = {r["lang"] for r in rows}
        rows = [r for r in json.loads(prev.read_text(encoding="utf-8")) if r["lang"] not in done] + rows
        order = list(languages())
        rows.sort(key=lambda r: order.index(r["lang"]))
    prev.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "index.html").write_text(_html(rows), encoding="utf-8")
    return out / "index.html"


def _html(rows: list[dict]) -> str:
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["lang"], []).append(r)
    parts = []
    for lang, vs in by.items():
        parts.append(f'<section><h2>{html.escape(vs[0]["name"])} <small>{lang}</small></h2>')
        for v in vs:
            data = json.dumps({k: v[k] for k in ("accent", "ref_clip", "speaker") if k in v})
            if v.get("skipped"):
                parts.append(f'<div class="v skip">{html.escape(v["label"])}: skipped ({html.escape(v["skipped"])})</div>')
                continue
            flag = f' <b class="warn">gate: {html.escape("; ".join(v["flags"]))}</b>' if v["flags"] else ""
            parts.append(
                f'<label class="v"><input type="radio" name="{lang}" value="{html.escape(data, quote=True)}"> '
                f'{html.escape(v["label"])} <small>score {v["score"]}, {v["seconds"]}s</small>{flag}'
                f'<audio controls preload="none" src="{html.escape(v["file"])}"></audio></label>')
        parts.append("</section>")
    return f"""<!doctype html><meta charset="utf-8"><title>UllasLab voice demo (local)</title>
<style>body{{font:16px system-ui;max-width:880px;margin:2rem auto;padding:0 1rem;background:#fff;color:#111}}
section{{border-top:1px solid #ccc;padding:.5rem 0}}.v{{display:block;margin:.4rem 0}}.skip{{color:#888}}
.warn{{color:#a40}}audio{{display:block;width:100%;margin:.2rem 0 .6rem}}
button{{font:inherit;padding:.5rem 1rem}}@media(prefers-color-scheme:dark){{body{{background:#111;color:#eee}}}}</style>
<h1>Voice demo (local only)</h1><p>Pick one option per language, then save the choices file. Do not upload this folder.</p>
<form id="f">{''.join(parts)}<p><button type="button" onclick="save()">Save choices.json</button></p></form>
<script>
function save(){{const o={{}};for(const r of document.querySelectorAll('input[type=radio]:checked'))o[r.name]=JSON.parse(r.value);
const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(o,null,2)],{{type:'application/json'}}));
a.download='voice-choices.json';a.click();}}
</script>"""
