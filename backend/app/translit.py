"""Devanagari names and places in Latin letters, the way they are usually written in English: कमला देवी -> Kamla Devi.

The site and the forms are in English, so a Hindi document's details are written out in Latin letters. Hindi drops
the inherent "a" at the end of a word and between a vowel-consonant and consonant-vowel pair (कमला is Kamla, not
Kamala), and this follows that rule. It is a reading aid, not an official spelling: every field stays editable.
"""
import re

_VOWELS = {
    "अ": "a", "आ": "a", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u", "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
}
_SIGNS = {"ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au"}
_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h", "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "d", "ढ़": "dh", "फ़": "f",
}
_NUKTA_FORMS = {"क़": "क़", "ख़": "ख़", "ग़": "ग़", "ज़": "ज़", "ड़": "ड़", "ढ़": "ढ़", "फ़": "फ़"}
_VIRAMA, _ANUSVARA, _CHANDRABINDU, _VISARGA = "्", "ं", "ँ", "ः"
_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def has_devanagari(text: str) -> bool:
    return bool(_DEVANAGARI.search(text))


def _syllables(word: str) -> list[list[str]]:
    """[consonant letters, vowel] per syllable. A vowel of None is the inherent 'a' that may be dropped."""
    for composed, decomposed in _NUKTA_FORMS.items():
        word = word.replace(composed, decomposed)
    out: list[list] = []
    cluster: list[str] = []
    i = 0
    while i < len(word):
        ch = word[i]
        if ch + "़" in _CONSONANTS and word[i + 1:i + 2] == "़":
            ch, i = ch + "़", i + 1
        if ch in _CONSONANTS:
            nxt = word[i + 1:i + 2]
            cluster.append(_CONSONANTS[ch])
            if nxt == _VIRAMA:
                i += 2
                continue
            if nxt in _SIGNS:
                out.append([cluster, _SIGNS[nxt]])
                cluster, i = [], i + 2
                continue
            out.append([cluster, None])
            cluster = []
        elif ch in _VOWELS:
            out.append([[], _VOWELS[ch]])
        elif ch in (_ANUSVARA, _CHANDRABINDU) and out:
            out[-1].append("n")
        elif ch == _VISARGA and out:
            out[-1].append("h")
        elif ch.isdigit() or ch in "०१२३४५६७८९":
            out.append([[ch.translate(_DIGITS)], ""])
        i += 1
    if cluster:
        out.append([cluster, ""])
    return out


def _word(word: str) -> str:
    parts = _syllables(word)
    if not parts:
        return word
    vowels = [p[1] for p in parts]
    # The last inherent 'a' goes (राम is Ram), unless the word is a single letter or ends in a cluster (मित्र is Mitra).
    if len(parts) > 1 and vowels[-1] is None and len(parts[-1][0]) == 1:
        vowels[-1] = ""
    # Inside a word, an inherent 'a' goes between vowel-consonant and consonant-vowel (कमला is Kamla).
    for k in range(1, len(parts) - 1):
        if vowels[k] is None and vowels[k - 1] not in ("",) and len(parts[k][0]) == 1 \
                and parts[k + 1][0] and vowels[k + 1] not in ("",):
            vowels[k] = ""
            break
    text = "".join("".join(p[0]) + ("a" if v is None else v) + "".join(p[2:]) for p, v in zip(parts, vowels))
    return text[:1].upper() + text[1:]


def to_latin(text: str) -> str:
    if not has_devanagari(text):
        return text
    return re.sub(r"[ऀ-ॿ]+", lambda m: _word(m.group()), text)
