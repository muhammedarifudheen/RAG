import type {
  ApiErrorBody,
  AskResponse,
  CodeChunk,
  FileDetail,
  FileGraph,
  HealthReport,
  IngestFailure,
  IngestProgress,
  IngestResult,
} from "@atlas/shared";
import type { Locator, Page, Route } from "@playwright/test";

export const MODELS_SOURCE = `"""Domain models."""


class Base:
    def describe(self) -> str:
        return self.label()

    def label(self) -> str:
        return "base"


class User(Base):
    def __init__(self, name: str) -> None:
        self.name = name

    def label(self) -> str:
        return format_name(self.name)


def format_name(name: str) -> str:
    return name.strip().title()
`;

export const MODELS_FILE: FileDetail = {
  path: "pkg/models.py",
  language: "python",
  loc: 21,
  content: MODELS_SOURCE,
  symbols: [
    { id: 2, name: "Base", kind: "class", start_line: 4, end_line: 9, signature: "class Base" },
    {
      id: 3,
      name: "Base.describe",
      kind: "method",
      start_line: 5,
      end_line: 6,
      signature: "def describe(self) -> str",
    },
    {
      id: 8,
      name: "format_name",
      kind: "function",
      start_line: 20,
      end_line: 21,
      signature: "def format_name(name: str) -> str",
    },
  ],
};

const FORMAT_NAME_CHUNK: CodeChunk = {
  symbol_id: 8,
  name: "format_name",
  kind: "function",
  signature: "def format_name(name: str) -> str",
  file: "pkg/models.py",
  language: "python",
  start_line: 20,
  end_line: 21,
  score: 0.83,
  snippet: "def format_name(name: str) -> str:\n    return name.strip().title()",
  snippet_end_line: 21,
  truncated: false,
  citation: "[pkg/models.py:20-21]",
};

export const ANSWER: AskResponse = {
  question: "How are user names formatted?",
  answer: [
    "Names are **title-cased** by `format_name` [pkg/models.py:20-21].",
    "",
    "- Whitespace is stripped first [pkg/models.py:21].",
    "- They are persisted elsewhere [pkg/store.py:1-9].",
    "",
    "Inside code a citation is left alone: `[pkg/models.py:1-2]`.",
  ].join("\n"),
  citations: [
    { ref: "[pkg/models.py:20-21]", file: "pkg/models.py", start_line: 20, end_line: 21, verified: true },
    { ref: "[pkg/models.py:21]", file: "pkg/models.py", start_line: 21, end_line: 21, verified: true },
    { ref: "[pkg/store.py:1-9]", file: "pkg/store.py", start_line: 1, end_line: 9, verified: false },
  ],
  chunks: [FORMAT_NAME_CHUNK],
  model: "claude-opus-5-5",
  complete: true,
};

// service.py -> models.py, and cycle_a.py <-> cycle_b.py.
export const FILE_GRAPH: FileGraph = {
  nodes: [
    { id: 1, path: "pkg/models.py", language: "python", loc: 21, symbols: 8, in_cycle: false },
    { id: 2, path: "pkg/service.py", language: "python", loc: 9, symbols: 3, in_cycle: false },
    { id: 3, path: "pkg/cycle_a.py", language: "python", loc: 5, symbols: 2, in_cycle: true },
    { id: 4, path: "pkg/cycle_b.py", language: "python", loc: 5, symbols: 2, in_cycle: true },
  ],
  edges: [
    { source: 2, target: 1, imports: 2, calls: 2, inherits: 0, in_cycle: false },
    { source: 3, target: 4, imports: 1, calls: 1, inherits: 0, in_cycle: true },
    { source: 4, target: 3, imports: 1, calls: 0, inherits: 0, in_cycle: true },
  ],
  cycles: [[3, 4]],
};

export const HEALTH: HealthReport = {
  summary: {
    files: 5,
    symbols: 18,
    edges: 12,
    dead_symbols: 4,
    file_cycles: 1,
    call_cycles: 1,
    long_functions: 1,
    high_fan_out_files: 0,
  },
  thresholds: { max_function_loc: 50, min_fan_out: 10 },
  dead_symbols: [
    { id: 3, name: "Base.describe", kind: "method", file: "pkg/models.py", start_line: 5, end_line: 6 },
    { id: 7, name: "User.label", kind: "method", file: "pkg/models.py", start_line: 16, end_line: 17 },
    { id: 10, name: "create_user", kind: "function", file: "pkg/service.py", start_line: 4, end_line: 5 },
    { id: 11, name: "unused_helper", kind: "function", file: "pkg/service.py", start_line: 8, end_line: 9 },
  ],
  circular_dependencies: {
    files: [["pkg/cycle_a.py", "pkg/cycle_b.py"]],
    calls: [
      [
        { id: 13, name: "ping", kind: "function", file: "pkg/cycle_a.py", start_line: 4, end_line: 5 },
        { id: 15, name: "pong", kind: "function", file: "pkg/cycle_b.py", start_line: 4, end_line: 5 },
      ],
    ],
  },
  long_functions: [
    { id: 17, name: "long_job", kind: "function", file: "pkg/big.py", start_line: 1, end_line: 60, loc: 60 },
  ],
  high_fan_out_files: [],
};

/** What /health returns when asked for rankings: thresholds of 1, so everything is listed. */
export const HEALTH_RANKING: HealthReport = {
  ...HEALTH,
  thresholds: { max_function_loc: 1, min_fan_out: 1 },
  long_functions: [
    { id: 17, name: "long_job", kind: "function", file: "pkg/big.py", start_line: 1, end_line: 60, loc: 60 },
    { id: 8, name: "format_name", kind: "function", file: "pkg/models.py", start_line: 20, end_line: 21, loc: 2 },
    { id: 10, name: "create_user", kind: "function", file: "pkg/service.py", start_line: 4, end_line: 5, loc: 2 },
  ],
  high_fan_out_files: [
    { file: "pkg/cycle_a.py", fan_out: 1, depends_on: ["pkg/cycle_b.py"] },
    { file: "pkg/service.py", fan_out: 1, depends_on: ["pkg/models.py"] },
  ],
};

export const EMPTY_HEALTH: HealthReport = {
  summary: {
    files: 0,
    symbols: 0,
    edges: 0,
    dead_symbols: 0,
    file_cycles: 0,
    call_cycles: 0,
    long_functions: 0,
    high_fan_out_files: 0,
  },
  thresholds: { max_function_loc: 50, min_fan_out: 10 },
  dead_symbols: [],
  circular_dependencies: { files: [], calls: [] },
  long_functions: [],
  high_fan_out_files: [],
};

type IngestStreamEvent =
  | { event: "progress"; data: IngestProgress }
  | { event: "done"; data: IngestResult }
  | { event: "error"; data: IngestFailure };

/** A `text/event-stream` body, with a keep-alive comment the client has to skip. */
export function eventStream(events: IngestStreamEvent[]): string {
  const blocks = events.map(({ event, data }) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
  return `: keep-alive\n\n${blocks.join("")}`;
}

/** The app's own alerts. Next.js adds a hidden route announcer that also has role="alert". */
export function alerts(page: Page): Locator {
  return page.locator('[role="alert"]:not(#__next-route-announcer__)');
}

export function apiError(route: Route, status: number, detail: string): Promise<void> {
  const body: ApiErrorBody = { detail };
  return route.fulfill({ status, json: body });
}

/** Answers GET /api/file for the paths given, and 404 for any other. */
export async function mockFiles(page: Page, files: FileDetail[]): Promise<void> {
  await page.route("**/api/file?*", (route) => {
    const path = new URL(route.request().url()).searchParams.get("path");
    const file = files.find((candidate) => candidate.path === path);
    return file
      ? route.fulfill({ json: file })
      : apiError(route, 404, `No ingested file at '${path}'.`);
  });
}

export async function mockHealth(
  page: Page,
  report: HealthReport,
  ranking: HealthReport,
): Promise<void> {
  await page.route("**/api/health*", (route) => {
    const params = new URL(route.request().url()).searchParams;
    return route.fulfill({ json: params.has("max_function_loc") ? ranking : report });
  });
}
