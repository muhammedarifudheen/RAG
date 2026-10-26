"use client";

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type ClipboardEvent,
  type DragEvent,
  type FormEvent,
  type KeyboardEvent,
} from "react";

import { describeSize, imageSource, MAX_FILES, prepareAttachment } from "@/lib/attachments";
import type { StoredAttachment } from "@/lib/chats";
import { useDictation } from "@/lib/speech";

export interface ComposerHandle {
  focus: () => void;
  setText: (text: string) => void;
}

interface Props {
  pending: boolean;
  onSend: (text: string, attachments: StoredAttachment[], draw: boolean) => void;
  onStop: () => void;
  /** ↑ in an empty box: the last question, to edit. */
  onEditLast: () => void;
}

const ACCEPT =
  "image/png,image/jpeg,image/webp,image/gif,.pdf,.epub,.html,.htm,.txt,.md,.markdown,.csv,.tsv,.json,.xml,.yaml,.yml,.toml,.ini,.log,.py,.ts,.tsx,.js,.jsx,.go,.rs,.java,.kt,.c,.h,.cpp,.hpp,.cs,.rb,.php,.swift,.sh,.sql,.css,.scss";

interface Pending {
  key: string;
  name: string;
  attachment?: StoredAttachment;
  error?: string;
}

export const ChatComposer = forwardRef<ComposerHandle, Props>(function ChatComposer(
  { pending, onSend, onStop, onEditLast },
  ref,
) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<Pending[]>([]);
  const [draw, setDraw] = useState(false);
  const [dragging, setDragging] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const dictation = useDictation((spoken) =>
    setText((current) => (current ? `${current.trimEnd()} ${spoken}` : spoken)),
  );

  useImperativeHandle(ref, () => ({
    focus: () => box.current?.focus(),
    setText: (value: string) => {
      setText(value);
      requestAnimationFrame(() => {
        box.current?.focus();
        box.current?.setSelectionRange(value.length, value.length);
      });
    },
  }));

  // The box grows with its text, up to a limit.
  useEffect(() => {
    const element = box.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 240)}px`;
  }, [text]);

  const reading = files.some((f) => !f.attachment && !f.error);
  const ready = files.flatMap((f) => (f.attachment ? [f.attachment] : []));

  function add(list: FileList | File[]) {
    const incoming = Array.from(list).slice(0, Math.max(0, MAX_FILES - files.length));
    for (const file of incoming) {
      const key = `${file.name}-${file.size}-${Math.random().toString(36).slice(2, 7)}`;
      setFiles((current) => [...current, { key, name: file.name }]);
      prepareAttachment(file)
        .then((attachment) =>
          setFiles((current) => current.map((f) => (f.key === key ? { ...f, attachment } : f))),
        )
        .catch((error: unknown) => {
          const message = error instanceof Error ? error.message : "could not be read";
          setFiles((current) => current.map((f) => (f.key === key ? { ...f, error: message } : f)));
        });
    }
  }

  function submit(event?: FormEvent) {
    event?.preventDefault();
    if (pending || reading || !text.trim()) return;
    if (dictation.listening) dictation.stop();
    onSend(text, ready, draw);
    setText("");
    setFiles([]);
    setDraw(false);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    } else if (event.key === "ArrowUp" && text === "") {
      event.preventDefault();
      onEditLast();
    }
  }

  function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const pasted = Array.from(event.clipboardData.files);
    if (pasted.length) {
      event.preventDefault();
      add(pasted);
    }
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer.files.length) add(event.dataTransfer.files);
  }

  return (
    <form
      onSubmit={submit}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      className="sticky bottom-0 border-t border-line bg-ink/95 px-4 pb-3 pt-3 backdrop-blur"
    >
      <div
        className={`mx-auto max-w-3xl border bg-panel transition-colors ${
          dragging ? "border-acid" : draw ? "border-signal" : "border-line-strong focus-within:border-paper/50"
        }`}
      >
        {files.length > 0 && (
          <ul aria-label="Attached files" className="flex flex-wrap gap-2 border-b border-line p-2">
            {files.map((file) => {
              const preview = file.attachment ? imageSource(file.attachment) : null;
              return (
                <li
                  key={file.key}
                  className={`flex max-w-[15rem] items-center gap-2 border px-2 py-1 text-xs ${
                    file.error ? "border-danger/50 text-danger" : "border-line text-soft"
                  }`}
                >
                  {preview ? (
                    // eslint-disable-next-line @next/next/no-img-element -- a local preview
                    <img src={preview} alt="" className="h-7 w-7 object-cover" />
                  ) : (
                    <span aria-hidden="true" className="font-mono text-[10px] text-acid">
                      {file.attachment ? "TXT" : file.error ? "ERR" : "…"}
                    </span>
                  )}
                  <span className="min-w-0 truncate" title={file.error ?? file.name}>
                    {file.error ? `${file.name}: ${file.error}` : file.name}
                  </span>
                  {file.attachment?.size ? (
                    <span className="shrink-0 text-faint">{describeSize(file.attachment.size)}</span>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => setFiles((current) => current.filter((f) => f.key !== file.key))}
                    aria-label={`Remove attachment ${file.name}`}
                    className="text-muted hover:text-danger"
                  >
                    ✕
                  </button>
                </li>
              );
            })}
          </ul>
        )}

        <label htmlFor="question" className="sr-only">
          Question
        </label>
        <textarea
          id="question"
          ref={box}
          rows={1}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
          placeholder={
            draw
              ? "Describe the picture to draw…"
              : dictation.listening
                ? "Listening… speak now"
                : "Ask anything…"
          }
          autoComplete="off"
          maxLength={32000}
          className="block max-h-60 min-h-[3rem] w-full resize-none bg-transparent px-4 py-3 text-[15px] outline-none placeholder:text-faint"
        />

        <div className="flex items-center gap-1 px-2 pb-2">
          <ToolButton label="Attach files" onClick={() => picker.current?.click()} disabled={files.length >= MAX_FILES}>
            <span aria-hidden="true">＋</span> Files
          </ToolButton>
          <input
            ref={picker}
            type="file"
            multiple
            accept={ACCEPT}
            className="hidden"
            aria-label="Files to attach"
            onChange={(event) => {
              if (event.target.files) add(event.target.files);
              event.target.value = "";
            }}
          />
          <ToolButton label="Draw a picture" pressed={draw} onClick={() => setDraw((on) => !on)}>
            <span aria-hidden="true">◐</span> Draw
          </ToolButton>
          {dictation.supported && (
            <ToolButton
              label="Voice input"
              pressed={dictation.listening}
              onClick={() => (dictation.listening ? dictation.stop() : dictation.start())}
            >
              <span aria-hidden="true" className={dictation.listening ? "animate-pulse text-signal" : ""}>
                ●
              </span>{" "}
              Voice
            </ToolButton>
          )}
          {dictation.error && <span className="text-[11px] text-danger">{dictation.error}</span>}

          <span className="ml-auto" />
          {pending ? (
            <button
              type="button"
              onClick={onStop}
              className="border border-line-strong px-4 py-1.5 font-mono text-xs uppercase tracking-[0.14em] text-paper hover:border-paper"
            >
              Stop
            </button>
          ) : (
            <button
              type="submit"
              disabled={text.trim() === "" || reading}
              className="bg-signal px-4 py-1.5 font-display text-xs font-bold uppercase tracking-[0.14em] text-ink transition-colors hover:bg-signal-hover disabled:cursor-not-allowed disabled:bg-raised disabled:text-faint"
            >
              Ask
            </button>
          )}
        </div>
      </div>
      <p className="label mx-auto mt-2 hidden max-w-3xl text-faint sm:block">
        Enter to send · Shift+Enter new line · Ctrl+/ shortcuts · drop or paste files
      </p>
    </form>
  );
});

function ToolButton({
  label,
  pressed,
  onClick,
  disabled = false,
  children,
}: {
  label: string;
  pressed?: boolean;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      aria-pressed={pressed}
      title={label}
      className={`flex items-center gap-1 px-2.5 py-1 font-mono text-[11px] uppercase tracking-[0.1em] transition-colors disabled:opacity-40 ${
        pressed ? "bg-signal/15 text-signal" : "text-muted hover:bg-raised hover:text-paper"
      }`}
    >
      {children}
    </button>
  );
}
