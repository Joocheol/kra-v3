import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const raw = process.env.CLAUDE_REVIEW;
const outputPath = process.env.GITHUB_OUTPUT;
if (!raw) throw new Error("CLAUDE_REVIEW is empty.");
if (!outputPath) throw new Error("GITHUB_OUTPUT is unavailable.");
if (Buffer.byteLength(raw, "utf8") > 512 * 1024) throw new Error("Review is too large.");

let review;
try { review = JSON.parse(raw); }
catch (error) { throw new Error(`Review is not valid JSON: ${error.message}`); }

const topKeys = ["author_questions", "findings", "needs_changes", "summary"];
const findingKeys = [
  "category", "evidence", "file", "id", "line", "recommendation",
  "requires_author_decision", "severity",
];
function assert(ok, message) { if (!ok) throw new Error(message); }
function exactKeys(value, expected, label) {
  assert(value && typeof value === "object" && !Array.isArray(value), `${label} must be an object.`);
  assert(JSON.stringify(Object.keys(value).sort()) === JSON.stringify(expected), `${label} has invalid keys.`);
}
function text(value, label, max, empty = false) {
  assert(typeof value === "string", `${label} must be text.`);
  assert(empty || value.trim(), `${label} must not be empty.`);
  assert(value.length <= max, `${label} is too long.`);
  assert(!/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/u.test(value), `${label} has controls.`);
}

exactKeys(review, topKeys, "review");
assert(typeof review.needs_changes === "boolean", "needs_changes must be boolean.");
text(review.summary, "summary", 6000, true);
assert(Array.isArray(review.findings) && review.findings.length <= 15, "too many findings.");
assert(Array.isArray(review.author_questions) && review.author_questions.length <= 5, "too many questions.");
const ids = new Set();
for (const [index, finding] of review.findings.entries()) {
  const label = `findings[${index}]`;
  exactKeys(finding, findingKeys, label);
  text(finding.id, `${label}.id`, 80);
  assert(/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(finding.id), `${label}.id is unsafe.`);
  assert(!ids.has(finding.id), `${label}.id is duplicated.`); ids.add(finding.id);
  assert(["high", "medium", "low"].includes(finding.severity), `${label}.severity is invalid.`);
  text(finding.category, `${label}.category`, 120);
  text(finding.file, `${label}.file`, 500);
  const normalized = path.posix.normalize(finding.file.replaceAll("\\", "/"));
  assert(!path.posix.isAbsolute(normalized) && normalized !== ".." && !normalized.startsWith("../"), `${label}.file escapes repo.`);
  assert(Number.isInteger(finding.line) && finding.line >= 0, `${label}.line is invalid.`);
  text(finding.evidence, `${label}.evidence`, 4000);
  text(finding.recommendation, `${label}.recommendation`, 4000);
  assert(typeof finding.requires_author_decision === "boolean", `${label}.decision is invalid.`);
}
for (const [index, question] of review.author_questions.entries()) text(question, `question[${index}]`, 2000);

const derivedNeedsChanges = review.findings.some(
  (finding) => !finding.requires_author_decision
);
// Never erase the reviewer's own needs_changes=true judgment.  The derived
// flag can only make the final decision more conservative.
review.needs_changes = review.needs_changes || derivedNeedsChanges;
const delimiter = `CLAUDE_REVIEW_${crypto.randomUUID()}`;
fs.appendFileSync(outputPath, [
  `review<<${delimiter}`, JSON.stringify(review), delimiter,
  `summary<<${delimiter}`, review.summary, delimiter,
  `needs_changes=${review.needs_changes}`, "",
].join("\n"));
