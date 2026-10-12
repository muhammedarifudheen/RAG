import { useEffect, useState } from "react";

export type Loadable<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: T };

/** Runs `load` on mount and whenever `key` changes, ignoring results that arrive late. */
export function useApi<T>(load: () => Promise<T>, key: string = ""): Loadable<T> {
  const [state, setState] = useState<Loadable<T>>({ status: "loading" });

  useEffect(() => {
    let current = true;
    setState({ status: "loading" });
    load().then(
      (data) => {
        if (current) setState({ status: "ready", data });
      },
      (error: unknown) => {
        const message = error instanceof Error ? error.message : "Request failed";
        if (current) setState({ status: "error", message });
      },
    );
    return () => {
      current = false;
    };
    // `load` is expected to be an inline function; `key` says when to re-run it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return state;
}
