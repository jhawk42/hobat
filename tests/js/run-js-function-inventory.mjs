import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const espreePath = process.env.ESPREE_PATH;
if (!espreePath) throw new Error("Set ESPREE_PATH to Espree's espree.js entry point.");
const espree = await import(pathToFileURL(path.resolve(espreePath)));
const packagePath = path.resolve(path.dirname(espreePath), "package.json");
const espreeVersion = JSON.parse(fs.readFileSync(packagePath, "utf8")).version;
const files = process.argv.slice(2).sort();
const functionTypes = new Set([
  "FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression",
]);
const functions = [];
const modules = [];
let currentFile = "";

function functionName(node, parent) {
  if (node.id?.name) return node.id.name;
  if (parent?.type === "VariableDeclarator" && parent.id?.name) return parent.id.name;
  if (parent?.type === "Property" || parent?.type === "MethodDefinition") {
    return parent.key?.name ?? parent.key?.value ?? "<anonymous>";
  }
  if (parent?.type === "CallExpression") {
    const callee = parent.callee;
    return `${callee?.property?.name ?? callee?.name ?? "callback"} callback`;
  }
  return "<anonymous>";
}

function walk(node, parent = null, containingFunctions = []) {
  if (!node || typeof node !== "object") return;
  const isFunction = functionTypes.has(node.type);
  const currentFunctions = isFunction ? [...containingFunctions, node] : containingFunctions;
  if (isFunction) {
    functions.push({ node, parent, descendants: [], file: currentFile });
    containingFunctions.forEach((ancestor) => {
      functions.find((entry) => entry.node === ancestor)?.descendants.push(node);
    });
  }
  for (const [key, value] of Object.entries(node)) {
    if (["loc", "range", "tokens", "comments"].includes(key)) continue;
    if (Array.isArray(value)) value.forEach((child) => walk(child, node, currentFunctions));
    else if (value && typeof value === "object" && typeof value.type === "string") {
      walk(value, node, currentFunctions);
    }
  }
}

for (const file of files) {
  currentFile = file;
  const source = fs.readFileSync(file, "utf8");
  modules.push({ file, lines: source.split("\n").length - 1 });
  walk(espree.parse(source, {
    ecmaVersion: "latest",
    sourceType: "module",
    loc: true,
  }));
}

const records = functions.map(({ node, parent, descendants, file }) => {
  const covered = new Set();
  descendants.forEach((child) => {
    for (let line = child.loc.start.line; line <= child.loc.end.line; line += 1) covered.add(line);
  });
  const span = node.loc.end.line - node.loc.start.line + 1;
  return {
    file,
    name: functionName(node, parent),
    start: node.loc.start.line,
    end: node.loc.end.line,
    span,
    ownLines: span - covered.size,
  };
});
const buckets = { "1-49": 0, "50-99": 0, "100-149": 0, "150-199": 0, "200+": 0 };
records.forEach(({ span }) => {
  if (span < 50) buckets["1-49"] += 1;
  else if (span < 100) buckets["50-99"] += 1;
  else if (span < 150) buckets["100-149"] += 1;
  else if (span < 200) buckets["150-199"] += 1;
  else buckets["200+"] += 1;
});
console.log(JSON.stringify({
  espreeVersion,
  inputs: files,
  moduleCount: files.length,
  functionCount: records.length,
  buckets,
  over150: records.filter(({ span }) => span > 150),
  exactly150: records.filter(({ span }) => span === 150),
  modules,
}, null, 2));
