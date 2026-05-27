# Node Coloring in the Topology Visualization

_Covers node colors, styling, and visual appearance in the vis.js network topology view._

---

## Overview

The topology view represents Thread mesh network devices as nodes in a network graph. Node color, size, shape, and border styling all convey information about the device's role and type.

---

## Node Types and Colors

### 1. **Border Router** — Green with thick border
- **Background:** Green (`PALETTE.borderRouterBg`)
- **Border:** Green (`PALETTE.borderRouterBorder`)
- **Border Width:** 5px
- **Shape:** Rectangle
- **Font Size:** 19.5px (monospace)
- **Size:** 187×77 pixels
- **Meaning:** A Thread border router that bridges the Thread mesh network to external networks (e.g., IP6, Matter, HAP, mDNS scopes)

### 2. **Router** — Blue with thick border
- **Background:** Blue (`PALETTE.routerBg`)
- **Border:** Blue (`PALETTE.routerBorder`)
- **Border Width:** 3px
- **Shape:** Rectangle
- **Font Size:** 19.5px (monospace)
- **Size:** 187×77 pixels
- **Meaning:** A Thread router node that routes packets within the mesh and can have child nodes

### 3. **Child Node** — Beige/tan with thin border
- **Background:** Beige/tan (`PALETTE.childBg`)
- **Border:** Tan (`PALETTE.childBorder`)
- **Border Width:** 1px
- **Shape:** Ellipse (oval)
- **Font Size:** 13px (monospace)
- **Size:** 109×41 pixels
- **Meaning:** A Thread child device (sleepy end device, FTD, or non-router node) that connects to a router parent

### 4. **Eve Node** — Specific color for external topology data
- **Background:** Eve-specific color (`PALETTE.eveBg`)
- **Border:** Eve-specific color (`PALETTE.eveBorder`)
- **Meaning:** Nodes sourced from Eve simulation or network simulation tools

### 5. **Unknown Node** — Light color with thin border
- **Background:** Unknown color (`PALETTE.unknownBg`)
- **Border:** Unknown color (`PALETTE.unknownBorder`)
- **Shape:** Ellipse (oval)
- **Meaning:** Nodes with unrecognized or missing device labels; typically child nodes with no device_label information

---

## Search Highlighting

When a search query is executed and matches are found, the topology applies temporary highlighting:

### **Matched Nodes** (search found)
- **Background:** Retains original color (router blue, border router green, child beige, etc.)
- **Border:** Changes to orange (`#d97706`)
- **Border Width:** Increased to 4px or more
- **Meaning:** Nodes whose device record contains the search query term

### **Non-Matched Nodes** (search did not find)
- **Background:** Changes to light gray (`#e8e8e8`)
- **Border:** Changes to medium gray (`#c0c0c0`)
- **Border Width:** Reduced to 1px
- **Font Color:** Changes to dark gray (`#aaaaaa`)
- **Meaning:** Nodes that do not match the search query; visually dimmed to de-emphasize

### **Single Match Special Behavior**
When exactly one node matches the search:
- The matching node is **selected** (visually highlighted by vis.js)
- The device **details panel** populates with the node's properties
- The **viewport zooms and pans** to center the node in the upper-center of the canvas

---

## Search Clearing and Color Restoration

When the search is cleared (either by clicking the **Clear** button or manually deleting the query and pressing Find), all nodes are **restored to their original colors**:

- **Matched nodes** return to their original role-based colors (blue for routers, green for border routers, beige for children, etc.)
- **Non-matched nodes** return to their original colors
- **Border colors** return to original values
- **Border widths** return to original values (1px for child nodes, 3px for routers, 5px for border routers)
- **Font colors** return to original values

**Implementation note:** Original styling is stored in `_originalNodeStyling` (a Map keyed by node ID) immediately after the topology is rendered, before any mutations by search highlighting. This preserves the true original state independent of how vis.js mutates the node objects internally.

---

## Visual Summary

| Node Type | Background | Border | Border Width | Shape | Size | Font Size |
|---|---|---|---|---|---|---|
| **Border Router** | Green | Green | 5px | Rectangle | 187×77px | 19.5px |
| **Router** | Blue | Blue | 3px | Rectangle | 187×77px | 19.5px |
| **Child Node** | Beige | Tan | 1px | Ellipse | 109×41px | 13px |
| **Eve Node** | Eve color | Eve color | 1px | Varies | Varies | Varies |
| **Unknown** | Light | Light | 1px | Ellipse | 109×41px | 13px |

---

## Related Files

- [tdash-constants.js](../src/js/tdash-constants.js) — Defines `NODE_COLORS` palette and `PALETTE` constants
- [tdash-topology-utils.js](../src/js/tdash-topology-utils.js) — `buildVisNodeData()` applies color and style to nodes
- [tdash-topology-renderer.js](../src/js/tdash-topology-renderer.js) — `applySearchHighlight()` handles search-based color changes
- [tdash-search.js](../src/js/tdash-search.js) — Query parsing and row matching logic

---

## Search Query Fields

Nodes match search queries based on fields in their device record, including:

- **Identity**: rloc16, extaddr, eui64, device_label, name
- **Role**: Type, Role, br (border router flag), leader
- **Version**: thread_stack_version, thread_version
- **Network**: omr_ipv6_addr, mlEidIid
- **Other**: scope, status, vendor information

For a complete list, see `SEARCH_TARGET_FIELDS` in [tdash-search.js](../src/js/tdash-search.js).
