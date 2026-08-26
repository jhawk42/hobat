import { SOURCE_PRECEDENCE } from "../../src/js/tdash-constants.js";
import { MERGE_FIELD_HANDLERS, createMergeContext } from "../../src/js/tdash-merge.js";


const context = createMergeContext("high.json", "unknown.json", {
  sourcePriorities: { "high.json": 10 },
  ownerRloc16: "0x1000",
});

process.stdout.write(`${JSON.stringify({
  sourcePrecedence: SOURCE_PRECEDENCE,
  handlerPaths: Object.keys(MERGE_FIELD_HANDLERS),
  context,
  contextFrozen: Object.isFrozen(context),
})}\n`);