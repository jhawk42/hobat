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
| Border router | `#e4f3e7` / `#28723a` | `#153923` / `#70c982` | square |
| Router | `#dcecf8` / `#4b4237` | `#18354f` / `#f2ede3` | hexagon |
| REED / router-eligible child | `#c2d9fa` / `#24559a` | `#24559a` / `#91baff` | dot |
| MED / receiver-on-when-idle minimal end device | `#c8f0f5` / `#006b80` | `#104655` / `#62d6ed` | dot |
| SED / sleepy end device | `#ffffff` / `#006b80` | `#121416` / `#62d6ed` | dot, hollow-looking |
| Child / subtype unconfirmed | `#fff0c2` / `#806000` | `#3c3218` / `#e8c766` | dot |
| Eve fallback | `#ddf2ef` / `#006b6b` | `#143d3d` / `#6acaca` | adaptor-selected |
| Unknown role | `#e7ebf0` / `#5d6672` | `#303844` / `#b4becc` | dot, dashed outline |

All topology adaptors share the same role emphasis: border routers use
`borderWidth: 5` and `size: 45`, routers use `borderWidth: 3` and `size: 45`,
and child or unknown nodes use `borderWidth: 1` and `size: 27`. This includes
ha-matter-ws commissioned, native, and merged topology nodes. Adaptors may
still select different labels, fonts, and role classifications based on their
source data.

Router outlines use warm graphite in Light and warm white in Dark to separate
hexagons from dense blue High-LQ links. Fills, geometry and interaction colors
are unchanged; border-to-fill contrast is 8.15:1 in Light and 10.84:1 in Dark.

Border routers use green role identity in both themes. Dark outlines have
9.11:1 contrast against the canvas and 6.32:1 against their deep-green fill.
Green does not mean healthy; square geometry and separate health treatments
remain in place.

The browser view model refines presentation roles from canonical node records
and identity-matched child/child-table observations, including indexed router
child tables. The shared REED resolver requires current child evidence plus
FTD capability or explicit REED evidence (flag, role, or device type); an
explicit false flag is respected, and contradictory evidence stays unconfirmed.
FTD capability alone does not establish child role. MED/SED styling requires
confirmed MTD capability and explicit receiver-on-when-idle true/false evidence.
Missing or contradictory subtype evidence retains the amber child fallback;
no child-role evidence retains unknown or the existing source-only fallback.
Names and vendors never determine subtype.

SEDs have an opaque canvas-matched fill, updated on theme changes, so links
cannot show through. Unknown-role outlines use a `[5, 3]` dash pattern to mean
uncertainty, not disconnection or poor health. These presentation refinements
do not change filter classifications, counts, source records, or exports.
The collapsible **Legend** explains link quality, node roles, capability,
sleep behavior, and uncertainty. Its entries scroll inside a bounded panel.

## Edge Styles

| Relationship | Light / dark color | Width | Pattern |
|---|---|---:|---|
| LQ3/high | `#4e8afa` / `#4e8afa` | 10 | solid |
| LQ2/medium | `#30343b` / `#e5ad55` | 8 | dashed |
| LQ1/low | `#b43b24` / `#f18e79` | 4 | dashed |
| No LQ | `#626c7a` / `#adb7c5` | 4 | solid |
| Parent-child | `#934e86` / `#d69cc9` | 8 | solid |
| OTBR/router-neighbor | `#00766a` / `#65c9b8` | 4 | solid |

High uses the connector blue sampled from the user-supplied reference image
in both themes. Its edges and legend swatch target at least 3:1 graphical
contrast against the canvas; the High legend text uses the normal text color
to retain 4.5:1 text contrast. Other relationship colors are unchanged.

The approved Light quality sequence is blue / charcoal / rust. Medium is
intentionally charcoal in Light and amber in Dark. Border-router green and
unclassified-child amber identify role, not health. The node-role palette
preserves existing shapes, sizes, border widths, edge patterns and opacity,
and interaction/health/search precedence.
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

During ordinary inspection, one visible selected node with useful visible
incident links activates neighborhood emphasis. Incident links retain their
base opacity, LQ/relationship color, width, and dashes. Fully opaque unrelated
links use opacity 0.42; already-translucent links retain their original opacity,
including profile caps and explicit zero opacity. No links or nodes are removed,
and displayed counts are unchanged. Isolated, hidden, or multiple selections
do not blanket-dim the graph.

Incident edges temporarily use their LQ color for native selected highlights
and additive `selectionWidth: 0`; node selection and hover behavior remain
intact. Clear selection restores effective base opacity, highlight colors,
and each edge's selection-width increment (vis default: 1.5), not a previous
dimmed snapshot. Selection changes do not fit/focus, move nodes, or restart
physics.

Any nonempty search suppresses neighborhood dimming, including zero or multiple
matches. Search takes precedence over health node colors while active; clearing
it restores the applicable role/health presentation. Explicit health-target
navigation also suppresses neighborhood dimming and preserves its selected
edges and intentional fit. Ordinary node inspection ends that transient
intent; fresh render owners do not inherit it. Health coloring by itself does
not suppress neighborhood emphasis. Selection remains presentation-only and
does not change role classification, source records, filters, or exports.

## Theme and CSS

The topology canvas has its own `--topology-canvas-bg` token: white `#ffffff`
in Light and near-black charcoal `#121416` in Dark (including the system CSS
fallback). Other dashboard surfaces use the
[layered charcoal palette](dashboard_ui_fields.md#dark-surfaces); semantic
node roles, relationships, selection and health colors are unchanged.

DOM controls, legends and canvas share CSS tokens, including label backplates,
selected/hovered states, search emphasis and health overlays. Health status
tokens are separate from finding severity and role identity. Health remains
opt-in. Canonical restoration applies role then health, while active search
applies role then match/dim styles. Neighborhood edge presentation is composed
afterward from immutable, theme-resolved, profile-constrained bases and the
current visibility/selection. Changing appearance recomposes that same state,
including for a hidden Topology view.

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