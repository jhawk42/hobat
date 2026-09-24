import { sourceDefaults, sourceRank, fieldRank } from "../../src/js/tdash-source-authority.js";
import { MERGE_FIELD_HANDLERS, createMergeContext } from "../../src/js/tdash-merge.js";


const context = createMergeContext("high.json", "unknown.json", {
  sourcePriorities: { "high.json": 10 },
  ownerRloc16: "0x1000",
});

process.stdout.write(`${JSON.stringify({
  sourcePrecedence: sourceDefaults(),
  authorityCases: {
    sourceDefault: sourceRank("td-otbr-cli-networkdiag-fetch-all.json"),
    fieldOverride: fieldRank("extAddress", "td-otbr-cli-networkdiag-fetch-all.json"),
    unknownSource: fieldRank("extAddress", "not-listed.json"),
  },
  handlerPaths: Object.keys(MERGE_FIELD_HANDLERS),
  context,
  contextFrozen: Object.isFrozen(context),
})}\n`);