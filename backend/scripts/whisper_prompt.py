"""Prints the Whisper token ids for the vocabulary prompt in frontend/public/speech/worker.js.

The on-device speech reader starts each transcript with this text as if it had already been said, which steers
Whisper towards the spellings the agent understands (Raebareli rather than "Raya Valley"). Change the text here,
run this, and paste the ids into PROMPT in the worker.

    python scripts/whisper_prompt.py
"""
import json
import re
import sys
import urllib.request

PROMPT = (" Raebareli, Lucknow, Kanpur, Varanasi, Prayagraj, Gorakhpur, Ayodhya, Sitapur, Unnao, Amethi, Sultanpur,"
          " Pratapgarh, Jaunpur, Azamgarh, Ballia, Gonda, Bahraich, Hardoi. BPL card, Antyodaya, Aadhaar, ration card,"
          " widow pension, yearly income.")
# The same model revision the site serves from public/models/whisper-tiny.en.
REPO = "https://huggingface.co/onnx-community/whisper-tiny.en/resolve/2575352d61be1bf7225cf8f8b268a4678025fc58/"


def fetch(name: str) -> str:
    with urllib.request.urlopen(REPO + name, timeout=60) as response:
        return response.read().decode("utf-8")


def byte_encoder() -> dict[int, str]:
    """GPT-2's printable stand-in for every byte."""
    bytes_ = list(range(33, 127)) + list(range(161, 173)) + list(range(174, 256))
    chars = bytes_[:]
    extra = 0
    for b in range(256):
        if b not in bytes_:
            bytes_.append(b)
            chars.append(256 + extra)
            extra += 1
    return {b: chr(c) for b, c in zip(bytes_, chars)}


def encode(text: str, vocab: dict[str, int], ranks: dict[tuple[str, str], int]) -> list[int]:
    to_char = byte_encoder()
    words = re.findall(r"'s|'t|'re|'ve|'m|'ll|'d| ?[A-Za-z]+| ?[0-9]+| ?[^\sA-Za-z0-9]+|\s+(?!\S)|\s+", text)
    ids = []
    for word in words:
        parts = [to_char[b] for b in word.encode("utf-8")]
        while len(parts) > 1:
            rank, at = min((ranks.get((parts[i], parts[i + 1]), float("inf")), i) for i in range(len(parts) - 1))
            if rank == float("inf"):
                break
            parts[at:at + 2] = [parts[at] + parts[at + 1]]
        ids += [vocab[part] for part in parts]
    return ids


def main() -> None:
    vocab = json.loads(fetch("vocab.json"))
    merges = [tuple(line.split()) for line in fetch("merges.txt").splitlines()[1:] if line.strip()]
    ids = encode(PROMPT, vocab, {pair: rank for rank, pair in enumerate(merges)})
    back = {i: t for t, i in vocab.items()}
    from_char = {c: b for b, c in byte_encoder().items()}
    assert bytes(from_char[c] for i in ids for c in back[i]).decode("utf-8") == PROMPT, "round trip failed"
    print(f"{len(ids)} tokens", file=sys.stderr)
    print(json.dumps(ids))


if __name__ == "__main__":
    main()
