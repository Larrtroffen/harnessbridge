// E2E read-only loading check using the *real* DSH code from the global CLI install.
//
// Usage: node e2e_load.mjs <session.v4.jsonl.zstd|.jsonl>
// Prints one JSON line: {sessionId, seq, messages, roles, firstUserText}
// Exits non-zero if the DSH loader rejects the file.
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const file = process.argv[2];
if (!file) {
  console.error("usage: node e2e_load.mjs <session.v4.jsonl.zstd>");
  process.exit(2);
}

const NM = `${process.env.HOME}/.local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai`;
const require = createRequire(import.meta.url);
try {
  require.resolve(`${NM}/dsh-session/lib/index.js`);
} catch {
  console.error("SKIP: global @deepseek-ai/dsh package tree not found at " + NM);
  process.exit(3);
}

const raw = file.endsWith(".zstd")
  ? execFileSync("zstd", ["-q", "-d", "-c", file], { maxBuffer: 512 * 1024 * 1024 })
  : readFileSync(file);
const lines = raw.toString("utf8").split("\n").filter(Boolean);
if (lines.length < 2) {
  console.error("FAIL: session file has no event lines");
  process.exit(1);
}

const { Session, SessionId, SessionLogOffset } = await import(`${NM}/dsh-session/lib/index.js`);
const { currentSessionMessageProjections } = await import(
  `${NM}/dsh-session-format-catalog/lib/types/message-projections.js`
);

const { type: _t, ...header } = JSON.parse(lines[0]);
const events = lines.slice(1).map(JSON.parse);
let session;
try {
  session = Session.fromRestore(
    SessionId(header.id),
    events,
    header,
    SessionLogOffset(0),
    "detached",
    currentSessionMessageProjections
  );
} catch (err) {
  console.error("FAIL: DSH Session.fromRestore rejected the file: " + (err && err.message ? err.message : err));
  process.exit(1);
}

const messages = session.deriveMessages();
const firstUser = messages.find((m) => m.role === "user");
const textOf = (m) => {
  const content = m.message?.content ?? m.content ?? [];
  if (typeof content === "string") return content;
  return (Array.isArray(content) ? content : [])
    .map((b) => (b && b.type === "text" ? b.text : ""))
    .filter(Boolean)
    .join("\n");
};
console.log(
  JSON.stringify({
    sessionId: header.id,
    seq: session.seq,
    events: events.length,
    messages: messages.length,
    roles: messages.map((m) => m.role),
    firstUserText: firstUser ? textOf(firstUser).slice(0, 120) : null,
  })
);
