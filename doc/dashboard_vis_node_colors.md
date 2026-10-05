# Topology Node Styling

Topology style constants are owned by `src/js/tdash-constants.js`. Adaptors
classify nodes and `tdash-topology-utils.js`/`tdash-topology-renderer.js` apply
the final vis-network presentation.

## Role Styles

| Role | Background | Border | Shape |
|---|---|---|---|
| Border router | `#c8e6c9` | `#4caf50` | square |
| Router | `#d9ecff` | `#1565c0` | hexagon |
| FTD/MTD child | `#fff4cc` | `#d9a400` | dot |
| Eve fallback | `#e8f5e9` | `#2e7d32` | adaptor-selected |
| Unknown | `#f2f2f2` | `#808080` | dot |

All topology adaptors share the same role emphasis: border routers use
`borderWidth: 5` and `size: 45`, routers use `borderWidth: 3` and `size: 45`,
and child or unknown nodes use `borderWidth: 1` and `size: 27`. This includes
ha-matter-ws commissioned, native, and merged topology nodes. Adaptors may
still select different labels, fonts, and role classifications based on their
source data.

## Edge Styles

| Relationship | Color | Width | Pattern |
|---|---|---:|---|
| LQ3/high | `#008080` | 12 | solid |
| LQ2/medium | `#D55E00` | 8 | dashed |
| LQ1/low | `#c62828` | 4 | dashed |
| No LQ | `#8a8a8a` | 4 | solid |
| Parent-child | `#cc79a7` | 8 | solid |
| OTBR/router-neighbor | `#009e73` | 4 | solid |

Adaptors attach relationship categories and an `lqLevel`; filters use those
semantic values rather than inspecting colors.

## Search and Selection

When search is active, matching nodes are emphasized and non-matches are
dimmed. The topology renderer captures original node styling after each render
and restores it when search is cleared. A single match is selected, its details
are published, and the viewport focuses it.

Selection styling applied by vis-network is temporary and does not change the
role classification or stored source record.

## Theme and CSS

Canvas node/edge colors come from JavaScript constants. DOM controls, panels,
legends, focus states, and responsive layout come from `tdash.css`. When adding
or changing a semantic color, update the owning constant and the visible legend
or CSS token that presents the same meaning.

See [Webpage, Web Server, and Data Flow](codebase_webpage_web_server_data_flow.md).