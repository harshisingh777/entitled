"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ClientConfig } from "./api";
import { canListenOnDevice, prepareSpeech, SPEECH_MODEL_MB, SpeechProgress, speechModelCached, transcribeOnDevice } from "./deviceSpeech";
import { readPref, writePref } from "./prefs";

type RecognitionCtor = new () => {
  lang: string; interimResults: boolean; maxAlternatives: number; start(): void; stop(): void; abort(): void;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
};

function recognitionCtor(): RecognitionCtor | null {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

const LANGUAGE = "en-IN";
const DEVICE_PREF = "entitled.voice";
// The browser has the speech API but nothing behind it. Brave raises "network" on every attempt.
const BROWSER_SERVICE_BROKEN = new Set(["network", "service-not-allowed", "language-not-supported"]);
const MAX_RECORDING_MS = 20_000;
const NOTHING_HEARD_MS = 10_000;
const PAUSE_ENDS_SPEECH_MS = 1_600;

export type ListenState = "idle" | "listening" | "transcribing";
export type VoiceEngine = "server" | "browser" | "device";

/**
 * Picks how speech becomes text. Sarvam or Bhashini when the server has keys. Otherwise the browser's own
 * recognition, except where it is known not to work (Brave, or a browser where it already failed), and then
 * Whisper on the device.
 */
function pickEngine(serverMode: boolean): VoiceEngine | null {
  if (serverMode && typeof MediaRecorder !== "undefined" && navigator.mediaDevices) return "server";
  const brave = "brave" in navigator;
  if (recognitionCtor() && !brave && readPref(DEVICE_PREF) !== "device") return "browser";
  if (canListenOnDevice()) return "device";
  return recognitionCtor() ? "browser" : null;
}

function progressText(progress: SpeechProgress): string | null {
  if (progress.stage === "download") {
    // Steps of 10%: the notice is read out by screen readers, so it should not change with every packet.
    const percent = progress.total ? Math.floor((10 * (progress.loaded ?? 0)) / progress.total) * 10 : 0;
    return `Getting the speech reader ready on this device: ${percent}% of ${SPEECH_MODEL_MB} MB. This happens only once.`;
  }
  return null;
}

/**
 * onText gets what was said. onError gets a short code for the page to explain. onStatus gets a line of progress
 * text to show, or null to clear it.
 */
export function useVoice(config: ClientConfig | null, onText: (text: string) => void, onError: (code: string) => void,
  onStatus: (text: string | null) => void = () => undefined) {
  const [state, setState] = useState<ListenState>("idle");
  const [engine, setEngine] = useState<VoiceEngine | null>(null);
  const [supported, setSupported] = useState(true);
  const stopRef = useRef<(() => void) | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const serverMode = config?.voice.mode === "server";

  useEffect(() => {
    if (!config) return;
    const picked = pickEngine(serverMode);
    setEngine(picked);
    setSupported(picked !== null);
  }, [config, serverMode]);

  const showProgress = useCallback((progress: SpeechProgress) => {
    const text = progressText(progress);
    if (text) onStatus(text);
  }, [onStatus]);

  /** Records until the person stops talking, taps stop, or 20 seconds pass, then hands the recording on. */
  const record = useCallback(async (onRecording: (recording: Blob) => Promise<void>, onStart?: () => void) => {
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    } catch (error) {
      setState("idle");
      return onError(error instanceof DOMException && error.name === "NotFoundError" ? "audio-capture" : "not-allowed");
    }
    onStart?.();
    const recorder = new MediaRecorder(stream);
    const chunks: Blob[] = [];
    recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };

    // A short pause after speaking ends the recording, the way the browser's own recognition does.
    let meter: AudioContext | null = null;
    let timer: ReturnType<typeof setInterval> | null = null;
    try {
      meter = new AudioContext();
      const analyser = meter.createAnalyser();
      analyser.fftSize = 2048;
      meter.createMediaStreamSource(stream).connect(analyser);
      const samples = new Float32Array(analyser.fftSize);
      const started = performance.now();
      let heard = false;
      let lastSound = started;
      timer = setInterval(() => {
        analyser.getFloatTimeDomainData(samples);
        let sum = 0;
        for (const sample of samples) sum += sample * sample;
        const level = Math.sqrt(sum / samples.length);
        const now = performance.now();
        if (level > 0.02) heard = true;
        if (level > 0.01) lastSound = now;
        const done = (heard && now - lastSound > PAUSE_ENDS_SPEECH_MS) || (!heard && now - started > NOTHING_HEARD_MS)
          || now - started > MAX_RECORDING_MS;
        if (done && recorder.state === "recording") recorder.stop();
      }, 100);
    } catch {
      // Without a level meter the person taps stop, and the 20 second limit still applies.
      timer = setTimeout(() => recorder.state === "recording" && recorder.stop(), MAX_RECORDING_MS);
    }

    recorder.onstop = async () => {
      if (timer) clearInterval(timer);
      void meter?.close().catch(() => undefined);
      stream.getTracks().forEach((track) => track.stop());
      setState("transcribing");
      try {
        await onRecording(new Blob(chunks, { type: recorder.mimeType }));
      } finally {
        setState("idle");
      }
    };
    stopRef.current = () => { if (recorder.state === "recording") recorder.stop(); };
    setState("listening");
    recorder.start();
  }, [onError]);

  const hearOnDevice = useCallback(async (recording: Blob) => {
    try {
      const text = await transcribeOnDevice(recording, showProgress);
      onStatus(null);
      if (text) onText(text);
      else onError("no-speech");
    } catch {
      onStatus(null);
      onError("device-failed");
    }
  }, [onError, onStatus, onText, showProgress]);

  const listenOnDevice = useCallback(async (switched = false) => {
    await record(hearOnDevice, () => {
      // The model downloads while the person speaks, so it is often ready by the time they stop.
      void speechModelCached().then((cached) => {
        if (!cached) onStatus(`Listening. The speech reader (${SPEECH_MODEL_MB} MB, only the first time) is downloading meanwhile…`);
        else if (switched) onStatus("This browser's own speech service is not available, so I am listening on this device. Speak now.");
      });
      prepareSpeech(showProgress).catch(() => undefined); // A failure is reported when the recording is read.
    });
  }, [hearOnDevice, onStatus, record, showProgress]);

  const listenOnServer = useCallback(async () => {
    await record(async (recording) => {
      const form = new FormData();
      form.append("file", recording, "speech.webm");
      try {
        const response = await fetch("/api/voice/stt", { method: "POST", body: form });
        if (!response.ok) throw new Error(String(response.status));
        const { text } = await response.json();
        if (text) onText(text);
        else onError("no-speech");
      } catch {
        // The server's speech service is down or out of quota: read the same recording here instead.
        if (canListenOnDevice()) await hearOnDevice(recording);
        else onError("stt-failed");
      }
    });
  }, [hearOnDevice, onError, onText, record]);

  const listenInBrowser = useCallback(() => {
    const Ctor = recognitionCtor();
    if (!Ctor) return onError("unsupported");
    const recognition = new Ctor();
    let switching = false;
    recognition.lang = LANGUAGE;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.onresult = (event) => {
      const text = event.results[0]?.[0]?.transcript;
      if (text) onText(text);
    };
    recognition.onerror = (event) => {
      if (BROWSER_SERVICE_BROKEN.has(event.error) && canListenOnDevice()) {
        // Remembered for this browser, and the person keeps talking without having to tap again.
        switching = true;
        writePref(DEVICE_PREF, "device");
        setEngine("device");
        void listenOnDevice(true);
        return;
      }
      if (event.error !== "aborted") onError(event.error);
    };
    recognition.onend = () => { if (!switching) setState("idle"); };
    stopRef.current = () => recognition.stop();
    setState("listening");
    try {
      recognition.start();
    } catch {
      setState("idle");
      onError("unsupported");
    }
  }, [listenOnDevice, onError, onText]);

  const toggleListening = useCallback(() => {
    if (state === "listening") {
      stopRef.current?.();
      return;
    }
    if (state !== "idle") return;
    audioRef.current?.pause();
    window.speechSynthesis?.cancel();
    onStatus(null);
    if (engine === "server") void listenOnServer();
    else if (engine === "device") void listenOnDevice();
    else listenInBrowser();
  }, [engine, listenInBrowser, listenOnDevice, listenOnServer, onStatus, state]);

  const speakInBrowser = useCallback((text: string) => {
    const synth = window.speechSynthesis;
    if (!synth) return;
    synth.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = LANGUAGE;
    const voice = synth.getVoices().find((v) => v.lang === LANGUAGE) || synth.getVoices().find((v) => v.lang.startsWith("en"));
    if (voice) utterance.voice = voice;
    synth.speak(utterance);
  }, []);

  const speak = useCallback(async (text: string) => {
    if (!serverMode) return speakInBrowser(text);
    try {
      const response = await fetch("/api/voice/tts", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, language: LANGUAGE }),
      });
      if (!response.ok) throw new Error(String(response.status));
      const { audio, mime } = await response.json();
      audioRef.current?.pause();
      audioRef.current = new Audio(`data:${mime};base64,${audio}`);
      await audioRef.current.play();
    } catch {
      speakInBrowser(text);
    }
  }, [serverMode, speakInBrowser]);

  const stopSpeaking = useCallback(() => {
    audioRef.current?.pause();
    window.speechSynthesis?.cancel();
  }, []);

  return { state, engine, supported, toggleListening, speak, stopSpeaking };
}
