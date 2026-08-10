import crypto from "node:crypto";
import fs from "node:fs";

// Deterministic gate on the critic's output. Mirrors the v1 repository's
// .github/ai-review/validate-review.mjs: the structured items are the source of
// truth, and every derived field is recomputed here rather than trusted from
// the model.

const inputPath = process.env.GPT_CRITIQUE;
const outputPath = process.env.GITHUB_OUTPUT;

if (!inputPath) throw new Error("GPT_CRITIQUE is empty.");
if (!outputPath) throw new Error("GITHUB_OUTPUT is unavailable.");

const raw = fs.readFileSync(inputPath, "utf8");
if (Buffer.byteLength(raw, "utf8") > 512 * 1024) {
  throw new Error("Critique exceeds the 512 KiB handoff limit.");
}

let critique;
try {
  critique = JSON.parse(raw);
} catch (error) {
  throw new Error(`Critique is not valid JSON: ${error.message}`);
}

const MAX_BINDING = 7;
const MIN_IMPACT = 30;
const SEV_MAJOR = "\uD575\uC2EC";
const SEV_MINOR = "\uC0AC\uC18C";

const topKeys = ["advisory", "binding", "generated_at", "inputs", "model",
                 "phase", "round", "tag"];
const itemKeys = ["claim", "evidence_in_report", "id", "impact",
                  "requires_author_decision", "severity", "suggested_check", "title"];

function assert(cond, msg) { if (!cond) throw new Error(msg); }

function assertExactKeys(v, expected, label) {
  assert(v && typeof v === "object" && !Array.isArray(v), `${label} must be an object.`);
  const actual = Object.keys(v).filter((k) => expected.includes(k)).sort();
  assert(JSON.stringify(actual) === JSON.stringify(expected),
         `${label} has unexpected or missing keys.`);
}

function assertText(v, label, max, allowEmpty = false) {
  assert(typeof v === "string", `${label} must be a string.`);
  assert(!/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/u.test(v),
         `${label} contains control characters.`);
  if (!allowEmpty) assert(v.trim().length > 0, `${label} must not be empty.`);
  assert(v.length <= max, `${label} exceeds ${max} characters.`);
}

assertExactKeys(critique, topKeys, "critique");
assertText(critique.tag, "tag", 40);
assert(/^[A-Za-z0-9_-]+$/.test(critique.tag), "tag has an unsafe format.");
assert(Number.isInteger(critique.round) && critique.round >= 1 && critique.round <= 2,
       "round must be 1 or 2.");
assert(Array.isArray(critique.binding), "binding must be an array.");
assert(Array.isArray(critique.advisory), "advisory must be an array.");
assert(critique.binding.length + critique.advisory.length <= 40,
       "too many items; the critic ignored the cap.");

const ids = new Set();
for (const list of [critique.binding, critique.advisory]) {
  for (const [i, item] of list.entries()) {
    const label = `item[${item?.id ?? i}]`;
    assertExactKeys(item, itemKeys, label);
    assertText(item.id, `${label}.id`, 16);
    assert(/^[KA]\d+$/.test(item.id), `${label}.id has an unsafe format.`);
    assert(!ids.has(item.id), `${label}.id is duplicated.`);
    ids.add(item.id);
    assert([SEV_MAJOR, SEV_MINOR].includes(item.severity), `${label}.severity is invalid.`);
    assert(typeof item.requires_author_decision === "boolean",
           `${label}.requires_author_decision must be boolean.`);
    assertText(item.title, `${label}.title`, 300);
    assertText(item.claim, `${label}.claim`, 4000);
    assertText(item.evidence_in_report, `${label}.evidence_in_report`, 4000);
    assertText(item.impact, `${label}.impact`, 2000, true);
    assertText(item.suggested_check, `${label}.suggested_check`, 2000, true);
  }
}

// Derived fields are recomputed, never trusted. An item can only lose binding
// status here; it can never gain it. This is the whole point of the validator:
// the critic does not get to decide how much work it creates for the author.
const demoted = critique.binding.filter(
  (it) => it.severity !== SEV_MAJOR || it.impact.trim().length < MIN_IMPACT);
if (demoted.length) {
  console.warn(`::warning::${demoted.length} item(s) demoted to advisory: `
    + `impact statement shorter than ${MIN_IMPACT} chars or severity not major.`);
}
let binding = critique.binding.filter((it) => !demoted.includes(it));

if (binding.length > MAX_BINDING) {
  console.warn(`::warning::${binding.length - MAX_BINDING} item(s) beyond the `
    + `${MAX_BINDING}-item cap moved to advisory.`);
}
const overflow = binding.slice(MAX_BINDING);
binding = binding.slice(0, MAX_BINDING);

const advisory = [...demoted, ...overflow, ...critique.advisory];
binding.forEach((it, n) => { it.id = `K${n + 1}`; it.severity = SEV_MAJOR; });
advisory.forEach((it, n) => { it.id = `A${n + 1}`; it.severity = SEV_MINOR; });

critique.binding = binding;
critique.advisory = advisory;

const delimiter = `GPT_CRITIQUE_${crypto.randomUUID()}`;
fs.appendFileSync(outputPath, [
  `critique<<${delimiter}`, JSON.stringify(critique), delimiter,
  `binding_count=${binding.length}`, "",
].join("\n"));

console.log(`binding=${binding.length} advisory=${advisory.length}`);
