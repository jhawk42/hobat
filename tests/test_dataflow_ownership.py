from __future__ import annotations

import ast
import asyncio
import json
import re
import shutil
import subprocess
import warnings
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from td_dataset_catalog import load_dataset_catalog
from td_webserver import TD_CATALOG_APP_KEY, handle_catalog_api


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "src"
JAVASCRIPT = PYTHON / "js"
MANIFEST = PYTHON / "td-dataset-manifest.json"
FALLBACK = JAVASCRIPT / "tdash-catalog-fallback.js"
FIELD_MODULES = ("tdash-constants.js", "tdash-utils.js", "tdash-search.js", "tdash-filters.js")
FIELD_NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9.]*\Z")
JS_DECLARATION = re.compile(
    r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(Object\.freeze\(\s*)?([\[{])",
    re.MULTILINE,
)
JS_PAIR = re.compile(
    r"\s*(?:(['\"])([^'\"]+)\1|([A-Za-z_$][\w$]*))\s*:\s*(?:(['\"])([^'\"]+)\4|(\d+))\s*\Z"
)

# Source-shape allowlist: canonical field names are derived from FIELD_DEFINITIONS.
# The wire adapter converts collector keys, not browser-visible aliases.
ALIAS_OWNERS = {
    "td_device_fields.py:PREFERRED_FIELD_NAMES": "canonical Python field model",
    "td_json_key_normalizer.py:EXPLICIT_KEY_MAP": "collector wire-format conversion",
    "tdash-device-fields.js:PREFERRED_FIELD_NAMES": "canonical browser field model",
}


def _text(path: Path, overrides: dict[str, str]) -> str:
    return overrides[path.name] if path.name in overrides else path.read_text(encoding="utf-8")


def _python_mappings(overrides: dict[str, str]):
    for path in (*PYTHON.glob("*.py"), *(PYTHON / name for name in overrides if name.endswith(".py"))):
        if not path.exists() and path.name not in overrides:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(_text(path, overrides), filename=path.name)
        for statement in tree.body:
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                value = statement.value
                names = ([target.id for target in statement.targets if isinstance(target, ast.Name)]
                         if isinstance(statement, ast.Assign)
                         else [statement.target.id] if isinstance(statement.target, ast.Name) else [])
                if isinstance(value, ast.Dict):
                    pairs = [(key.value, item.value) for key, item in zip(value.keys, value.values)
                             if isinstance(key, ast.Constant) and isinstance(item, ast.Constant)]
                    for name in names:
                        yield path.name, name, pairs


def _js_items(text: str, start: int) -> list[str]:
    opening = text[start]
    closing = {"[": "]", "{": "}"}[opening]
    stack = [closing]
    items: list[str] = []
    item_start = start + 1
    quote = ""
    cursor = item_start
    while cursor < len(text):
        char = text[cursor]
        if quote:
            if char == "\\":
                cursor += 2
                continue
            if char == quote:
                quote = ""
        elif char in "'\"`":
            quote = char
        elif text.startswith("//", cursor):
            cursor = text.find("\n", cursor)
            if cursor < 0:
                break
            continue
        elif text.startswith("/*", cursor):
            cursor = text.find("*/", cursor + 2)
            if cursor < 0:
                break
            cursor += 2
            continue
        elif char in "[{(":
            stack.append({"[": "]", "{": "}", "(": ")"}[char])
        elif char == stack[-1]:
            stack.pop()
            if not stack:
                items.append(text[item_start:cursor].strip())
                return items
        elif char == "," and len(stack) == 1:
            items.append(text[item_start:cursor].strip())
            item_start = cursor + 1
        cursor += 1
    raise ValueError("Unclosed JavaScript declaration")


def _js_declarations(overrides: dict[str, str], names: tuple[str, ...] | None = None):
    paths = (tuple(JAVASCRIPT / name for name in names) if names is not None
             else (*JAVASCRIPT.glob("*.js"), *(JAVASCRIPT / name for name in overrides if name.endswith(".js"))))
    for path in paths:
        if not path.exists() and path.name not in overrides:
            continue
        source = _text(path, overrides)
        for match in JS_DECLARATION.finditer(source):
            yield path.name, match[1], match[2] is not None, match[3], _js_items(source, match.start(3))


def _js_pairs(items: list[str]) -> list[tuple[str, str | int]]:
    result = []
    for item in items:
        match = JS_PAIR.fullmatch(re.sub(r"/\*.*?\*/|//[^\n]*", "", item, flags=re.DOTALL))
        if match:
            result.append((match[2] or match[3], match[5] if match[5] is not None else int(match[6])))
    return result


def _check_alias_ownership(overrides: dict[str, str] | None = None) -> None:
    overrides = overrides or {}
    assert all(ALIAS_OWNERS.values()), "Every alias allowlist entry needs a reason"
    for owner in ALIAS_OWNERS:
        filename, symbol = owner.split(":")
        path = (JAVASCRIPT if filename.endswith(".js") else PYTHON) / filename
        source = _text(path, overrides)
        if filename.endswith(".js"):
            present = re.search(rf"^export\s+const\s+{symbol}\s*=", source, flags=re.MULTILINE)
        else:
            tree = ast.parse(source, filename=filename)
            present = any(
                isinstance(statement, (ast.Assign, ast.AnnAssign))
                and symbol in ([target.id for target in statement.targets if isinstance(target, ast.Name)]
                               if isinstance(statement, ast.Assign)
                               else [statement.target.id] if isinstance(statement.target, ast.Name) else [])
                for statement in tree.body
            )
        assert present, f"Missing alias owner {owner}: {ALIAS_OWNERS[owner]}"
    for filename, name, pairs in _python_mappings(overrides):
        if len(pairs) > 20 and all(isinstance(key, str) and FIELD_NAME.fullmatch(key)
                                    and isinstance(value, str) and FIELD_NAME.fullmatch(value)
                                    for key, value in pairs):
            owner = f"{filename}:{name}"
            assert owner in ALIAS_OWNERS, f"{owner} duplicates td_device_fields.py:PREFERRED_FIELD_NAMES"
    for filename, name, _, kind, items in _js_declarations(overrides):
        if kind != "{":
            continue
        pairs = _js_pairs(items)
        if len(pairs) > 20 and all(isinstance(value, str) and FIELD_NAME.fullmatch(key)
                                    and FIELD_NAME.fullmatch(value) for key, value in pairs):
            owner = f"{filename}:{name}"
            assert owner in ALIAS_OWNERS, f"{owner} duplicates tdash-device-fields.js:PREFERRED_FIELD_NAMES"


def _check_authority_ownership(overrides: dict[str, str] | None = None) -> None:
    overrides = overrides or {}
    for filename, name, pairs in _python_mappings(overrides):
        if any(isinstance(key, str) and key.startswith("td-") and key.endswith(".json")
               and isinstance(value, int) for key, value in pairs):
            pytest.fail(f"{filename}:{name} duplicates td-dataset-manifest.json:authority.sourceDefaults")
    for filename, name, _, kind, items in _js_declarations(overrides):
        if kind == "{" and any(key.startswith("td-") and key.endswith(".json")
                                 and isinstance(value, int) for key, value in _js_pairs(items)):
            pytest.fail(f"{filename}:{name} duplicates td-dataset-manifest.json:authority.sourceDefaults")


def _check_field_lists(overrides: dict[str, str] | None = None) -> None:
    overrides = overrides or {}
    seen: dict[tuple[str, ...], str] = {}
    for filename, name, frozen, kind, items in _js_declarations(overrides, FIELD_MODULES):
        if not frozen:
            continue
        if kind == "[":
            values = []
            for item in items:
                stripped = re.sub(r"/\*.*?\*/|//[^\n]*", "", item, flags=re.DOTALL).strip()
                try:
                    values.append(ast.literal_eval(stripped))
                except (SyntaxError, ValueError):
                    break
            if len(values) != len([item for item in items if item]):
                continue
        else:
            pairs = _js_pairs(items)
            if len(pairs) != len([item for item in items if item]):
                continue
            values = [value for _, value in pairs]
        if len(values) < 3 or not all(isinstance(value, str) and FIELD_NAME.fullmatch(value) for value in values):
            continue
        key = tuple(values)
        owner = f"{filename}:{name}"
        # SEARCH_TARGET_FIELDS is curated for display; it is not a second alias table.
        assert key not in seen, f"{owner} duplicates {seen.get(key)}: {', '.join(values[:3])}"
        seen[key] = owner


def _check_adaptors(overrides: dict[str, str] | None = None) -> None:
    overrides = overrides or {}
    for path in (*JAVASCRIPT.glob("tdash-adaptor-*.js"),
                 *(JAVASCRIPT / name for name in overrides if name.startswith("tdash-adaptor-") and name.endswith(".js"))):
        if not path.exists() and path.name not in overrides:
            continue
        source = _text(path, overrides)
        functions = re.findall(r"^(?:export\s+)?function\s+(adapt\w+)\s*\(", source, flags=re.MULTILINE)
        functions += re.findall(r"^(?:export\s+)?const\s+(adapt\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>", source, flags=re.MULTILINE)
        for function in functions:
            assert "emitThroughAdaptorModel(" in source or "emitAdaptorResult(" in source, (
                f"{path.name}:{function} must emit through tdash-adaptor-model"
            )


def _dataset_tuples(catalog: dict) -> set[tuple[str, str, tuple[str, ...]]]:
    return {(entry["source"], entry["value"], tuple(entry["files"])) for entry in catalog["datasets"]}


def _check_catalog_parity(manifest: dict, served: dict, fallback: dict) -> None:
    definitions = {"td-dataset-manifest.json": _dataset_tuples(manifest),
                   "GET /api/catalog": _dataset_tuples(served),
                   "tdash-catalog-fallback.js": _dataset_tuples(fallback)}
    for owner, entries in definitions.items():
        for other, other_entries in definitions.items():
            assert entries == other_entries, (
                f"{owner} vs {other}: only in {owner}: {sorted(entries - other_entries)}; "
                f"only in {other}: {sorted(other_entries - entries)}"
            )


async def _served_catalog() -> dict:
    app = web.Application()
    app[TD_CATALOG_APP_KEY] = load_dataset_catalog()
    app.router.add_get("/api/catalog", handle_catalog_api)
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/api/catalog")
        assert response.status == 200
        return await response.json()


def test_one_alias_authority_per_runtime() -> None:
    _check_alias_ownership()
    injected = "NEW_ALIASES = {" + ", ".join(f"'field_{index}': 'name_{index}'" for index in range(25)) + "}"
    with pytest.raises(AssertionError, match="rogue_aliases.py:NEW_ALIASES duplicates td_device_fields.py"):
        _check_alias_ownership({"rogue_aliases.py": injected})
    browser_aliases = "const EXTRA_ALIASES = Object.freeze({" + ", ".join(
        f"field_{index}: 'name_{index}'" for index in range(25)
    ) + "});"
    with pytest.raises(AssertionError, match="rogue_aliases.js:EXTRA_ALIASES duplicates tdash-device-fields.js"):
        _check_alias_ownership({"rogue_aliases.js": browser_aliases})
    _check_alias_ownership({"td_device_fields.py": _text(PYTHON / "td_device_fields.py", {}) + "\n# A new field is owned here.\n"})
    with pytest.raises(AssertionError, match="Missing alias owner tdash-device-fields.js:PREFERRED_FIELD_NAMES"):
        _check_alias_ownership({"tdash-device-fields.js": "export const FIELD_DEFINITIONS = [];"})


def test_one_dataset_declaration() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required to load the browser catalog fallback")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    served = asyncio.run(_served_catalog())
    result = subprocess.run([node, "--input-type=module", "-e",
                             "import { DATASET_CATALOG_FALLBACK } from " + json.dumps(FALLBACK.as_uri())
                             + "; console.log(JSON.stringify(DATASET_CATALOG_FALLBACK))"],
                            capture_output=True, text=True, check=True)
    fallback = json.loads(result.stdout)
    _check_catalog_parity(manifest, served, fallback)
    changed = {**fallback, "datasets": [*fallback["datasets"],
                                        {"source": "eve", "value": "eve_extra", "files": ["td-eve-topology.json"]}]}
    with pytest.raises(AssertionError, match="td-dataset-manifest.json.*tdash-catalog-fallback.js.*eve_extra"):
        _check_catalog_parity(manifest, served, changed)


def test_one_authority_table() -> None:
    _check_authority_ownership()
    with pytest.raises(pytest.fail.Exception, match="tdash-constants.js:EXTRA_PRIORITY.*td-dataset-manifest.json"):
        _check_authority_ownership({"tdash-constants.js": "const EXTRA_PRIORITY = { 'td-extra.json': 100 };"})
    with pytest.raises(pytest.fail.Exception, match="rogue_priority.py:SOURCE_PRIORITY.*td-dataset-manifest.json"):
        _check_authority_ownership({"rogue_priority.py": "SOURCE_PRIORITY = {'td-extra.json': 100}"})


def test_no_duplicate_field_lists() -> None:
    _check_field_lists()
    field_list = next(items for filename, name, _, kind, items in _js_declarations({})
                      if filename == "tdash-search.js" and name == "SEARCH_TARGET_FIELDS" and kind == "[")
    copy = "\nconst COPIED_SEARCH_TARGET_FIELDS = Object.freeze([" + ",".join(field_list) + "]);\n"
    with pytest.raises(AssertionError, match="tdash-filters.js:COPIED_SEARCH_TARGET_FIELDS duplicates tdash-search.js:SEARCH_TARGET_FIELDS"):
        _check_field_lists({"tdash-filters.js": _text(JAVASCRIPT / "tdash-filters.js", {}) + copy})


def test_source_adaptors_emit_through_model() -> None:
    _check_adaptors()
    with pytest.raises(AssertionError, match="tdash-adaptor-new.js:adaptNew.*tdash-adaptor-model"):
        _check_adaptors({"tdash-adaptor-new.js": "export function adaptNew(data) { return data; }"})