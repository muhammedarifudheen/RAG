"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// The Web Speech API: dictation (Chrome, Edge, Safari) and read-aloud (all browsers).
// Neither sends anything to Atlas's server.

interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  onresult: ((event: { resultIndex: number; results: ArrayLike<RecognitionResult> }) => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error: string }) => void) | null;
}
interface RecognitionResult {
  isFinal: boolean;
  0: { transcript: string };
}
type RecognitionConstructor = new () => Recognition;

function recognitionClass(): RecognitionConstructor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: RecognitionConstructor;
    webkitSpeechRecognition?: RecognitionConstructor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

/**
 * Dictation: `start` listens and passes each finished phrase to `onText`; `stop`
 * ends it. `supported` is false where the browser has no speech recognition.
 */
export function useDictation(onText: (text: string) => void) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recognition = useRef<Recognition | null>(null);
  const handler = useRef(onText);
  handler.current = onText;

  useEffect(() => setSupported(recognitionClass() !== null), []);

  const stop = useCallback(() => {
    recognition.current?.stop();
  }, []);

  const start = useCallback(() => {
    const Klass = recognitionClass();
    if (!Klass) return;
    const listener = new Klass();
    listener.lang = navigator.language || "en-US";
    listener.continuous = true;
    listener.interimResults = false;
    listener.onresult = (event) => {
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) handler.current(result[0].transcript.trim());
      }
    };
    listener.onerror = (event) => {
      setError(
        event.error === "not-allowed"
          ? "The browser did not allow the microphone."
          : `Voice input stopped (${event.error}).`,
      );
    };
    listener.onend = () => setListening(false);
    recognition.current = listener;
    setError(null);
    setListening(true);
    listener.start();
  }, []);

  useEffect(() => () => recognition.current?.stop(), []);

  return { supported, listening, error, start, stop };
}

/** Markdown reduced to what reads well aloud. */
export function speakable(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, " (code block) ")
    .replace(/\[([^\]]*?\/[^\]]*?:\d+(?:-\d+)?)\]/g, "") // [path:lines] citations
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/\$\$?([^$]+)\$\$?/g, "$1")
    .replace(/[*_`#>|]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Read-aloud: `speak(id, text)` reads a text, `stop()` silences it, and `speaking`
 * names what is being read.
 */
export function useSpeaker() {
  const [supported, setSupported] = useState(false);
  const [speaking, setSpeaking] = useState<string | null>(null);

  useEffect(() => {
    setSupported(typeof window !== "undefined" && "speechSynthesis" in window);
    return () => {
      if (typeof window !== "undefined" && "speechSynthesis" in window) {
        window.speechSynthesis.cancel();
      }
    };
  }, []);

  const stop = useCallback(() => {
    window.speechSynthesis?.cancel();
    setSpeaking(null);
  }, []);

  const speak = useCallback((id: string, text: string) => {
    if (!("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(speakable(text));
    utterance.lang = navigator.language || "en-US";
    utterance.onend = () => setSpeaking((current) => (current === id ? null : current));
    utterance.onerror = () => setSpeaking((current) => (current === id ? null : current));
    setSpeaking(id);
    window.speechSynthesis.speak(utterance);
  }, []);

  return { supported, speaking, speak, stop };
}
