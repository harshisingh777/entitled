"""Speech: Sarvam first, Bhashini as the fallback. With neither key the browser's own speech takes over."""
import base64

import httpx

from . import config


class NoVoiceProvider(Exception):
    pass


def providers() -> dict:
    server = []
    if config.SARVAM_API_KEY:
        server.append("sarvam")
    if config.BHASHINI_API_KEY and config.BHASHINI_USER_ID:
        server.append("bhashini")
    return {"server": server, "mode": "server" if server else "browser"}


def _sarvam_stt(audio: bytes, filename: str, content_type: str) -> str:
    response = httpx.post(
        f"{config.SARVAM_BASE_URL}/speech-to-text",
        headers={"api-subscription-key": config.SARVAM_API_KEY},
        files={"file": (filename, audio, content_type)},
        data={"model": config.SARVAM_STT_MODEL, "language_code": "unknown"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["transcript"]


def _sarvam_tts(text: str, language: str) -> tuple[str, str]:
    response = httpx.post(
        f"{config.SARVAM_BASE_URL}/text-to-speech",
        headers={"api-subscription-key": config.SARVAM_API_KEY},
        json={"text": text[:2500], "language_code": language, "model": config.SARVAM_TTS_MODEL,
              "speaker": config.SARVAM_TTS_SPEAKER, "output_audio_codec": "mp3"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["audios"][0], "audio/mpeg"


def _bhashini(task: dict, input_data: dict) -> dict:
    response = httpx.post(
        config.BHASHINI_URL,
        headers={"userID": config.BHASHINI_USER_ID, "ulcaApiKey": config.BHASHINI_API_KEY},
        json={"pipelineTasks": [task], "inputData": input_data},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["pipelineResponse"][0]


def _bhashini_stt(audio: bytes) -> str:
    task = {"taskType": "asr", "config": {"language": {"sourceLanguage": "hi"}}}
    result = _bhashini(task, {"audio": [{"audioContent": base64.b64encode(audio).decode()}]})
    return result["output"][0]["transcript"]


def _bhashini_tts(text: str) -> tuple[str, str]:
    task = {"taskType": "tts", "config": {"language": {"sourceLanguage": "hi"}, "gender": "female"}}
    result = _bhashini(task, {"input": [{"source": text}]})
    return result["audio"][0]["audioContent"], "audio/wav"


def transcribe(audio: bytes, filename: str, content_type: str) -> tuple[str, str]:
    errors = []
    if config.SARVAM_API_KEY:
        try:
            return _sarvam_stt(audio, filename, content_type), "sarvam"
        except (httpx.HTTPError, KeyError) as exc:
            errors.append(f"sarvam: {exc}")
    if config.BHASHINI_API_KEY and config.BHASHINI_USER_ID:
        try:
            return _bhashini_stt(audio), "bhashini"
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            errors.append(f"bhashini: {exc}")
    raise NoVoiceProvider("; ".join(errors) or "No speech provider configured")


def synthesize(text: str, language: str = "hi-IN") -> tuple[str, str, str]:
    errors = []
    if config.SARVAM_API_KEY:
        try:
            return (*_sarvam_tts(text, language), "sarvam")
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            errors.append(f"sarvam: {exc}")
    if config.BHASHINI_API_KEY and config.BHASHINI_USER_ID and language.startswith("hi"):
        try:
            return (*_bhashini_tts(text), "bhashini")
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            errors.append(f"bhashini: {exc}")
    raise NoVoiceProvider("; ".join(errors) or "No speech provider configured")
