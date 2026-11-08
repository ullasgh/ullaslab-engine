"""Number, currency, percent and date verbalisation per language, applied before TTS.

Coverage (rules + tests): en, hi (own lakh/crore rules), es, pt, ar, ja, te, bn (num2words, LGPL-2.1,
used as an unmodified dependency; te and bn are not native-reviewed). Languages without a verified
rule set (ta, kn, ml, mr, gu: num2words kn is wrong, the others are missing) pass digits through and
report `passthrough` so the QA report can flag them. Hindi tables should be reviewed by a native speaker.
"""
from __future__ import annotations
import re
from datetime import date

VERBALIZED = {"en", "hi", "es", "pt", "ar", "ja", "te", "bn"}

_HI_0_99 = (
    "शून्य एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस "
    "बीस इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस तैंतीस चौंतीस पैंतीस "
    "छत्तीस सैंतीस अड़तीस उनतालीस चालीस इकतालीस बयालीस तैंतालीस चौवालीस पैंतालीस छियालीस सैंतालीस अड़तालीस "
    "उनचास पचास इक्यावन बावन तिरपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ साठ इकसठ बासठ तिरसठ चौंसठ पैंसठ "
    "छियासठ सड़सठ अड़सठ उनहत्तर सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर छिहत्तर सतहत्तर अठहत्तर उनासी "
    "अस्सी इक्यासी बयासी तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी नवासी नब्बे इक्यानवे बानवे तिरानवे "
    "चौरानवे पचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे"
).split()
assert len(_HI_0_99) == 100

_EN_0_19 = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
            "sixteen seventeen eighteen nineteen").split()
_EN_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _en_0_99(n: int) -> str:
    if n < 20:
        return _EN_0_19[n]
    t, u = divmod(n, 10)
    return _EN_TENS[t] + (f"-{_EN_0_19[u]}" if u else "")


def _indian(n: int, below100, hundred: str, thousand: str, lakh: str, crore: str, join: str = " ") -> str:
    """Indian digit grouping words (…crore, lakh, thousand, hundred). Crore part recurses (any size)."""
    if n < 100:
        return below100(n)
    parts = []
    cr, n = divmod(n, 10_000_000)
    if cr:
        parts.append(_indian(cr, below100, hundred, thousand, lakh, crore, join) + join + crore)
    for size, word in ((100_000, lakh), (1000, thousand)):
        q, n = divmod(n, size)
        if q:
            parts.append(below100(q) + join + word)
    h, n = divmod(n, 100)
    if h:
        parts.append(below100(h) + join + hundred)
    if n:
        parts.append(below100(n))
    return join.join(parts)


def hi_words(n: int) -> str:
    return _indian(n, lambda k: _HI_0_99[k], "सौ", "हज़ार", "लाख", "करोड़")


def en_indian_words(n: int) -> str:
    return _indian(n, _en_0_99, "hundred", "thousand", "lakh", "crore")


def _n2w(n: int, lang: str) -> str:
    from num2words import num2words
    return num2words(n, lang=lang)


def int_words(n: int, lang: str, indian: bool = False) -> str:
    if n < 0:
        raise ValueError("negative")
    if lang == "hi":
        return hi_words(n)
    if lang == "en":
        return en_indian_words(n) if indian and n >= 100_000 else _n2w(n, "en")
    return _n2w(n, lang)


_POINT = {"en": "point", "hi": "दशमलव", "es": "coma", "pt": "vírgula", "ar": "فاصلة", "ja": "点", "te": "దశాంశం", "bn": "দশমিক"}
_PERCENT = {"en": "percent", "hi": "प्रतिशत", "es": "por ciento", "pt": "por cento", "ar": "في المئة", "ja": "パーセント", "te": "శాతం", "bn": "শতাংশ"}

_JA_DIGITS = "〇一二三四五六七八九"
_CUR = {  # symbol -> ISO
    "₹": "INR", "Rs.": "INR", "Rs": "INR", "$": "USD", "US$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "R$": "BRL",
}
_CUR_WORD = {
    "en": {"INR": "rupees", "USD": "dollars", "EUR": "euros", "GBP": "pounds", "JPY": "yen", "BRL": "reais"},
    "hi": {"INR": "रुपये", "USD": "डॉलर", "EUR": "यूरो", "GBP": "पाउंड", "JPY": "येन", "BRL": "रियाल"},
    "es": {"INR": "rupias", "USD": "dólares", "EUR": "euros", "GBP": "libras", "JPY": "yenes", "BRL": "reales"},
    "pt": {"INR": "rúpias", "USD": "dólares", "EUR": "euros", "GBP": "libras", "JPY": "ienes", "BRL": "reais"},
    "ar": {"INR": "روبية", "USD": "دولار", "EUR": "يورو", "GBP": "جنيه إسترليني", "JPY": "ين", "BRL": "ريال برازيلي"},
    "ja": {"INR": "ルピー", "USD": "ドル", "EUR": "ユーロ", "GBP": "ポンド", "JPY": "円", "BRL": "レアル"},
}
_MONTHS = {
    "en": "January February March April May June July August September October November December".split(),
    "hi": "जनवरी फ़रवरी मार्च अप्रैल मई जून जुलाई अगस्त सितंबर अक्टूबर नवंबर दिसंबर".split(),
    "es": "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split(),
    "pt": "janeiro fevereiro março abril maio junho julho agosto setembro outubro novembro dezembro".split(),
    "ar": "يناير فبراير مارس أبريل مايو يونيو يوليو أغسطس سبتمبر أكتوبر نوفمبر ديسمبر".split(),
}
_EN_MONTH_IDX = {m.lower(): i for i, m in enumerate(_MONTHS["en"], 1)}

_NUM_WEST = r"\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_NUM_EU = r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?"  # es, pt: '.' groups, ',' decimal
_EU = {"es", "pt"}
_CUR_SYM = "|".join(re.escape(s) for s in sorted(_CUR, key=len, reverse=True))

def _res(num: str) -> dict:
    return {
        "cur": re.compile(rf"(?P<sym>{_CUR_SYM})\s?(?P<num>(?:{num}))(?:\s?(?P<mag>lakh|crore|million|billion|trillion|thousand|bn|mn|k|m|b|tn|लाख|करोड़|करोड|millones|millón|mil|milhões|milhão|bilhões)(?![A-Za-z0-9_]))?", re.I),
        "pct": re.compile(rf"(?P<num>(?:{num}))\s?%"),
        "num": re.compile(rf"(?<![A-Za-z0-9_.,])(?P<n>(?:{num}))(?P<suf>x|bn|mn|tn|k)?(?![A-Za-z0-9_])"),
    }


_RES = {"west": _res(_NUM_WEST), "eu": _res(_NUM_EU)}
_RE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_RE_DMY = re.compile(r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b")
_MAG = {"millones": "million", "millón": "million", "mil": "thousand", "milhões": "million", "milhão": "million", "bilhões": "billion", "लाख": "lakh", "करोड़": "crore", "करोड": "crore", "bn": "billion", "mn": "million", "tn": "trillion", "k": "thousand", "m": "million", "b": "billion"}
_MAG_LOCAL = {  # magnitude word per language (only where the English word would sound wrong)
    "hi": {"lakh": "लाख", "crore": "करोड़", "thousand": "हज़ार", "million": "मिलियन", "billion": "बिलियन", "trillion": "ट्रिलियन"},
    "es": {"thousand": "mil", "million": "millones", "billion": "mil millones", "trillion": "billones", "lakh": "lakh", "crore": "crore"},
    "pt": {"thousand": "mil", "million": "milhões", "billion": "bilhões", "trillion": "trilhões", "lakh": "lakh", "crore": "crore"},
    "ar": {"thousand": "ألف", "million": "مليون", "billion": "مليار", "trillion": "تريليون", "lakh": "لاخ", "crore": "كرور"},
    "ja": {"thousand": "千", "million": "百万", "billion": "十億", "trillion": "兆", "lakh": "十万", "crore": "千万"},
    "en": {k: k for k in ("lakh", "crore", "thousand", "million", "billion", "trillion")},
}


def _plain(num: str, lang: str = "en") -> str:
    if lang in _EU:
        return num.replace(".", "").replace(",", ".")
    return num.replace(",", "")


def number_to_words(num: str, lang: str, indian: bool = False, money: bool = False) -> str:
    """'1,234.56' -> words. Decimals are read digit by digit. Unsupported language -> digits unchanged."""
    if lang not in VERBALIZED:
        return num
    s = _plain(num, lang)
    whole, _, frac = s.partition(".")
    out = int_words(int(whole), lang, indian)
    if frac:
        sp = "" if lang == "ja" else " "
        if money and len(frac) == 2 and frac[0] != "0":  # cents read as one number: "fifty", not "five zero"
            tail = int_words(int(frac), lang)
        else:
            tail = sp.join(int_words(int(d), lang) for d in frac)
        out += f"{sp}{_POINT[lang]}{sp}" + tail
    return out


def _cur(m: re.Match, lang: str, indian: bool) -> str:
    iso = _CUR[next(k for k in _CUR if k.lower() == m["sym"].lower())]
    mag = (m["mag"] or "").lower()
    mag = _MAG.get(mag, mag)
    words = number_to_words(m["num"], lang, indian, money=not mag)
    if mag:
        words += " " + _MAG_LOCAL.get(lang, _MAG_LOCAL["en"]).get(mag, mag)
        if lang in ("es", "pt") and mag in ("million", "billion", "trillion"):
            words += " de"
    cw = _CUR_WORD.get(lang, {}).get(iso)
    if not cw:
        return m.group(0)
    return f"{words}{cw}" if lang == "ja" else f"{words} {cw}"


def _date(y: int, mo: int, d: int, lang: str) -> str | None:
    try:
        date(y, mo, d)
    except ValueError:
        return None
    if lang == "ja":
        return f"{number_to_words(str(y), 'ja')}年{number_to_words(str(mo), 'ja')}月{number_to_words(str(d), 'ja')}日"
    mn = _MONTHS.get(lang)
    if not mn:
        return None
    yw = number_to_words(str(y), lang)
    if lang == "en":
        return f"{d_ord_en(d)} of {mn[mo-1]}, {_en_year(y)}"  # "the fourteenth of March, twenty twenty-six"
    if lang == "ar":
        return f"{number_to_words(str(d), lang)} {mn[mo-1]} {yw}"
    if lang == "hi":
        return f"{number_to_words(str(d), lang)} {mn[mo-1]} {yw}"
    return f"{number_to_words(str(d), lang)} de {mn[mo-1]} de {yw}"  # es, pt


def d_ord_en(d: int) -> str:
    from num2words import num2words
    return "the " + num2words(d, to="ordinal")


def _en_year(y: int) -> str:
    from num2words import num2words
    return num2words(y, to="year")


def normalize_text(text: str, lang: str, number_format: str | None = None) -> str:
    """Verbalise currency, percentages, dates and numbers. number_format 'indian' enables lakh/crore for en."""
    if lang not in VERBALIZED:
        return text
    indian = number_format == "indian"
    rx = _RES["eu" if lang in _EU else "west"]
    text = rx["cur"].sub(lambda m: _cur(m, lang, indian), text)
    text = rx["pct"].sub(lambda m: number_to_words(m['num'], lang, indian) + ("" if lang == "ja" else " ") + _PERCENT[lang], text)

    def iso(m):
        r = _date(int(m[1]), int(m[2]), int(m[3]), lang)
        return r or ", ".join(number_to_words(g, lang) for g in m.groups())  # impossible date: read the parts
    text = _RE_ISO.sub(iso, text)
    if lang == "en":
        text = _RE_DMY.sub(lambda m: _date(int(m[3]), _EN_MONTH_IDX[m[2].lower()], int(m[1]), "en") or m.group(0), text)
    text = rx["num"].sub(lambda m: _num_token(m["n"], lang, indian) + _suffix(m["suf"], lang), text)
    return text


_SUF_EN = {"x": " times", "bn": " billion", "mn": " million", "tn": " trillion", "k": " thousand"}


def _suffix(suf: str | None, lang: str) -> str:
    if not suf:
        return ""
    if suf == "x":
        return _SUF_EN["x"] if lang == "en" else " x"
    key = {"bn": "billion", "mn": "million", "tn": "trillion", "k": "thousand"}[suf]
    return " " + _MAG_LOCAL.get(lang, _MAG_LOCAL["en"]).get(key, key)


def _num_token(tok: str, lang: str, indian: bool) -> str:
    whole = _plain(tok, lang).partition(".")[0]
    if lang == "en" and "." not in tok and "," not in tok and len(whole) == 4 and 1900 <= int(whole) <= 2099:
        return _en_year(int(whole))
    return number_to_words(tok, lang, indian)
