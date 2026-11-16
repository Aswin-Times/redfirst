/**
 * Turn the verdict's evidence strings (backend/redfirst/verification/rules.py) into labelled
 * parts the page can lay out. The strings are the API's only evidence format, so this parser is
 * deliberately forgiving: anything it does not recognise is kept, in order, in `notes`. A change
 * to the backend's wording can make the page plainer, never hide evidence.
 */

export type PathKind = "target" | "test" | "library" | "code";

export interface Location {
  path: string;
  function: string;
  kind: PathKind;
}

export interface ParsedEvidence {
  failure: { type: string; message: string } | null;
  /** Where the failure came from: inside target code, or a failed assertion on its result. */
  origin: "target" | "assertion" | null;
  locations: Location[];
  exitCode: number | null;
  notes: string[];
}

const FAILURE = /^([A-Za-z_][\w.]*): ([\s\S]*)$/; // "KeyError: 'x'"; not "got KeyError: 'x'"
const FRAME = /^(target )?frame (.+):([^:]+)$/; // the last colon separates the function
const TEST_ASSERTION = /^assertion in the generated test at (\w+)$/;
const EXIT_CODE = /^pytest exit code observed by the runner: (-?\d+)$/;
const IN_TARGET = "failure raised inside target code";
const ASSERTION = "assertion on target code's result failed in the main test";

/** A path as shown to people: repository-relative, with the machine-specific prefix removed. */
export function displayPath(raw: string): { path: string; kind: PathKind } {
  const p = raw.replaceAll("\\", "/");
  const lib = p.indexOf("site-packages/");
  if (lib >= 0) return { path: p.slice(lib), kind: "library" };
  if (p.split("/").pop() === "test_redfirst.py") return { path: "test_redfirst.py", kind: "test" };
  const repo = /(?:^|\/)repo\/(.+)$/.exec(p);
  return { path: repo ? repo[1] : p, kind: "code" };
}

export function parseEvidence(lines: string[]): ParsedEvidence {
  const out: ParsedEvidence = { failure: null, origin: null, locations: [], exitCode: null, notes: [] };
  lines.forEach((line, i) => {
    const failure = i === 0 ? FAILURE.exec(line) : null;
    if (failure) {
      out.failure = { type: failure[1], message: failure[2] };
      return;
    }
    if (line === IN_TARGET) {
      out.origin = "target";
      return;
    }
    if (line === ASSERTION) {
      out.origin = "assertion";
      return;
    }
    const frame = FRAME.exec(line);
    if (frame) {
      const shown = displayPath(frame[2]);
      out.locations.push({
        path: shown.path, function: frame[3], kind: frame[1] ? "target" : shown.kind,
      });
      return;
    }
    const test = TEST_ASSERTION.exec(line);
    if (test) {
      out.locations.push({ path: "test_redfirst.py", function: test[1], kind: "test" });
      return;
    }
    const exit = EXIT_CODE.exec(line);
    if (exit) {
      out.exitCode = Number(exit[1]);
      return;
    }
    out.notes.push(line);
  });
  return out;
}
