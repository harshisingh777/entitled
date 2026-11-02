"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ClientConfig } from "./api";

type RecognitionCtor = new () => {
  lang: string; interimResults: boolean; maxAlternatives: number; start(): void; stop(): void;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
};

function recognitionCtor(): RecognitionCtor | null {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

const LANGUAGE = "en-IN";

export type ListenState = "idle" | "listening" | "transcribing";

/** Sarvam or Bhashini when the server has keys, otherwise whatever speech the browser offers. */
export function useVoice(config: ClientConfig | null, onText: (text: string) => void, onError: (code: string) => void) {
  const [state, setState] = useState<ListenState>("idle");
  const [supported, setSupported] = useState(true);
  const stopRef = useRef<(() => void) | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const serverMode = config?.voice.mode === "server";

  useEffect(() => {
    if (!config) return;
    setSupported(serverMode ? typeof MediaRecorder !== "undefined" && !!navigator.mediaDevices : !!recognitionCtor());
  }, [config, serverMode]);

  const listenInBrowser = useCallback(() => {
    const Ctor = recognitionCtor();
    if (!Ctor) return onError("unsupported");
    const recognition = new Ctor();
    recognition.lang = LANGUAGE;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.onresult = (event) => {
      const text = event.results[0]?.[0]?.transcript;
      if (text) onText(text);
    };
    recognition.onerror = (event) => onError(event.error);
    recognition.onend = () => setState("idle");
    stopRef.current = () => recognition.stop();
    setState("listening");
    recognition.start();
  }, [onError, onText]);

  const listenOnServer = useCallback(async () => {
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      return onError("not-allowed");
    }
    const recorder = new MediaRecorder(stream);
    const chunks: Blob[] = [];
    recorder.ondataavailable = (event) => chunks.push(event.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach((track) => track.stop());
      setState("transcribing");
      const form = new FormData();
      form.append("file", new Blob(chunks, { type: recorder.mimeType }), "speech.webm");
      try {
        const response = await fetch("/api/voice/stt", { method: "POST", body: form });
        if (!response.ok) throw new Error(String(response.status));
        const { text } = await response.json();
        if (text) onText(text);
      } catch {
        onError("stt-failed");
      } finally {
        setState("idle");
      }
    };
    stopRef.current = () => recorder.stop();
    setState("listening");
    recorder.start();
  }, [onError, onText]);

  const toggleListening = useCallback(() => {
    if (state === "listening") {
      stopRef.current?.();
      return;
    }
    if (state === "idle") {
      audioRef.current?.pause();
      window.speechSynthesis?.cancel();
      void (serverMode ? listenOnServer() : listenInBrowser());
    }
  }, [listenInBrowser, listenOnServer, serverMode, state]);

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

  return { state, supported, toggleListening, speak, stopSpeaking };
}
