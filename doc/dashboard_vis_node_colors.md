# Topology Node Styling

Live topology colors are owned by the semantic tokens in
[tdash.css](../src/tdash.css). Adaptors classify nodes and relationships;
[tdash-topology-renderer.js](../src/js/tdash-topology-renderer.js) reads one
validated palette per effective theme through `readThemePalette()`.
[tdash-constants.js](../src/js/tdash-constants.js) retains geometry and
compatibility colors for pure adaptor consumers, not a second live palette.

## Role Styles

| Role | Light background / border | Dark background / border | Shape |
|---|---|---|---|
| Border router | `#f8e3cf` / `#8b4700` | `#442d1b` / `#f3b56c` | square |
| Router | `#dcecf8` / `#175a9c` | `#18354f` / `#79b8f3` | hexagon |
| FTD/MTD child | `#fff0c2` / `#806000` | `#3c3218` / `#e8c766` | dot |
| Eve fallback | `#ddf2ef` / `#006b6b` | `#143d3d` / `#6acaca` | adaptor-selected |
| Unknown | `#e7ebf0` / `#5d6672` | `#303844` / `#b4becc` | dot |

All topology adaptors share the same role emphasis: border routers use
`borderWidth: 5` and `size: 45`, routers use `borderWidth: 3` and `size: 45`,
and child or unknown nodes use `borderWidth: 1` and `size: 27`. This includes
ha-matter-ws commissioned, native, and merged topology nodes. Adaptors may
still select different labels, fonts, and role classifications based on their
source data.

## Edge Styles

| Relationship | Light / dark color | Width | Pattern |
|---|---|---:|---|
| LQ3/high | `#00649b` / `#70b7ed` | 12 | solid |
| LQ2/medium | `#30343b` / `#e5ad55` | 8 | dashed |
| LQ1/low | `#b43b24` / `#f18e79` | 4 | dashed |
| No LQ | `#626c7a` / `#adb7c5` | 4 | solid |
| Parent-child | `#934e86` / `#d69cc9` | 8 | solid |
| OTBR/router-neighbor | `#00766a` / `#65c9b8` | 4 | solid |

The approved Light quality sequence is blue / charcoal / rust. Medium is
intentionally charcoal in Light and amber in Dark. Border-router orange is role
identity, not Moderate health. This colors-only revision preserves existing
shapes, widths, dashes, opacity and interaction/health/search treatments.
Colors alone do not certify red-green color-blind accessibility: Medium and
Low still share a dash pattern, Medium and No LQ share neutral hues, thin
fit-zoom strokes can be hard to trace, and hover can replace quality colors.
Distinct patterns and separate role-preserving state cues remain follow-up work.

Adaptors attach relationship categories and an `lqLevel`; filters use those
semantic values rather than inspecting colors. Presentation-only `themeRole`
and `themeColorKey` metadata select CSS colors at the final renderer boundary.
Higher-LQ merges retain the winning color key; equal-LQ merges keep the existing
winner. Measured quality takes precedence over a relationship category.
Unkeyed parent-child edges use the parent-child color; other visible unclassified
edges use No LQ instead of inherited vis colors. This is presentation-only:
thresholds, relationship categories, evidence and exports are unchanged.
Invisible layout anchors remain invisible; profile-specific opacity is retained.

## Search and Selection

When search is active, matching nodes are emphasized and non-matches are
dimmed. The topology renderer captures original node styling after each render
and maintains current-theme restore maps. A single match is selected, its details
are published, and the viewport focuses it.

Selection styling applied by vis-network is temporary and does not change the
role classification or stored source record.

## Theme and CSS

DOM controls, legends and canvas share CSS tokens, including label backplates,
selected/hovered states, search emphasis and health overlays. Health status
tokens are separate from finding severity and role identity. Health remains
opt-in. Existing last-action overlay behavior is retained: canonical restore
applies role then health, while search applies role then match/dim styles.
Changing appearance repeats the last applied style mode, not a new overlay order.

The renderer updates existing vis DataSets with presentation-only patches.
It does not recreate the network, reseed layout, fit/focus the camera, select
devices, change filters, or restart paused physics. Font metrics are retained.
Navigation uses local SVG masks and named, focusable controls; Enter and Space
perform the corresponding public network action while existing pointer/hold
behavior remains in the vendored renderer.

Missing/invalid required CSS colors are reported through console and Appearance
status; the existing canvas retains its last complete palette. An unresolved
initial palette reports a topology rendering error rather than guessing colors.

See [Webpage, Web Server, and Data Flow](codebase_webpage_web_server_data_flow.md).