export interface ServerSentEvent {
  event: string;
  data: string;
}

function parse(block: string): ServerSentEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue; // comment, used as a keep-alive
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return data.length > 0 ? { event, data: data.join("\n") } : null;
}

/**
 * Reads a `text/event-stream` response body.
 *
 * EventSource cannot be used for this because it only issues GET requests.
 */
export async function* readServerSentEvents(response: Response): AsyncGenerator<ServerSentEvent> {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const event = parse(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      if (event) yield event;
      boundary = buffer.indexOf("\n\n");
    }

    if (done) {
      const event = parse(buffer);
      if (event) yield event;
      return;
    }
  }
}
