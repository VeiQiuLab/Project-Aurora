// V4-7B.3A only: reuse the unchanged prior opt-in fixture in memory.
// No generated test source on disk and no production/old audit file edits.
import {readFile} from "node:fs/promises";
import {createHash} from "node:crypto";
import assert from "node:assert/strict";
const original = new URL("./sherpa_melo_feasibility.mjs", import.meta.url);
let source = await readFile(original, "utf8");
assert.equal(createHash("sha256").update(source).digest("hex"),
  "898b90e8d31b0c0f6628535c1353a948d0543640545bc63d2e68f2b1ceca228e");
assert.ok(source.includes("for(const threads of [1,4,16])"));
source = source.replace("for(const threads of [1,4,16])", "for(const threads of [4])")
  .replaceAll("v47b2-coexist", "v47b3a-clean-coexist")
  .replaceAll("import.meta.url", JSON.stringify(original.href));
try {
  await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
} catch (error) {
  console.error(String(error));
  process.exitCode = 1;
}
