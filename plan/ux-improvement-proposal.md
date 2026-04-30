# UX Improvement Proposal — tdash: Thread Mesh Network Dashboard

> **Status:** Draft — awaiting review before implementation  
> **Author role:** Senior UX Designer  
> **Date:** 2026-04-30  
> **Scope:** `src/tdash.html`, `src/tdash.css`, `src/js/*.js`

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Current UI Audit — 10 Identified Improvements](#current-ui-audit)
3. [Current UI — Pros & Cons](#current-ui-pros--cons)
4. [Alternative Layout A — Command-Center Dashboard](#alternative-a-command-center-dashboard)
5. [Alternative Layout B — Guided Workflow Sidebar](#alternative-b-guided-workflow-sidebar)
6. [Alternative Layout C — Minimal Focused View](#alternative-c-minimal-focused-view)
7. [Comparison Matrix](#comparison-matrix)
8. [Recommended Next Steps](#recommended-next-steps)

---

## Executive Summary

tdash is a technical diagnostic dashboard for engineers who monitor Thread mesh networks. The current UI exposes all controls in a flat toolbar, requiring prior knowledge to use effectively. This proposal identifies **10 UX improvements** and presents **3 alternative layout concepts** that reduce cognitive load, improve logical flow, and make the interface approachable for new users while retaining full power for experienced users.

---

## Current UI Audit

### Improvement 1 — Flat toolbar has no logical grouping

**Problem:** The view-toggle-bar renders 10+ buttons separated only by a `.` spacer character. There is no visual hierarchy between primary actions (Fetch, view switch) and secondary controls (Physics, Animation, Legend, Enhance, More Info, Lab). All buttons look identical and compete equally for attention.

**Impact:** Users must read every button to understand what each one does. First-time users cannot immediately identify the primary call-to-action.

**Recommendation:** Split toolbar into three visually distinct zones:
- **Primary zone** (left): Fetch, Topology/Table toggle
- **Visualization zone** (center): Physics, Auto Zoom, Animation, Legend
- **Data zone** (right): Enhance, More Info, Dev/Lab

---

### Improvement 2 — Dataset dropdown is overwhelming and uncategorised

**Problem:** The dataset `<select>` contains 20+ options with mixed naming prefixes (`otbr-cli:`, `lab:`, `mdns:`, `system:`, `lab: eve`, etc.). Production datasets and experimental `lab:` datasets are interleaved. Users unfamiliar with the data sources cannot quickly identify which dataset is relevant.

**Impact:** New users stall at the dataset selection step. The meaningful starting point (e.g. `otbr-cli: merged [meshdiag, networkdiag, neighbors, children]`) is buried at position 3 in a 20-item list.

**Recommendation:**
- Group datasets using `<optgroup>` into categories: **Live / Standard**, **Lab / Experimental**, **System Utilities**
- Set the most commonly used production dataset as the default selection
- Add a short description tooltip on hover for each dataset

---

### Improvement 3 — No onboarding guidance when the page loads

**Problem:** On load the status bar shows "Select a dataset to load." yet a dataset is already pre-selected in the dropdown. The user does not know that they should click **Fetch** first to pull live data, nor do they understand the difference between Fetch (acquire from network) and simply selecting a dataset (read cached JSON).

**Impact:** Users try to interact with an empty topology canvas, get confused, and cannot discover the intended workflow without reading external documentation.

**Recommendation:**
- Show a prominent "Getting Started" banner on first load with three steps: **1. Fetch data → 2. Select dataset → 3. Explore topology**
- Replace the status text with a more actionable message: *"No data loaded — click Fetch to collect live network data, then select a dataset."*
- Dismiss the banner automatically after the first successful dataset load

---

### Improvement 4 — The Fetch button's relationship to the dataset is unclear

**Problem:** The **Fetch** button is the first button in the toolbar but its action (collect live data from the OTBR into local JSON files) is logically a *prerequisite* step separate from the dataset view rendering. There is no visual or textual connection between Fetch and the dataset select control.

**Impact:** Users may not realise that Fetch needs to run before selecting a dataset, or they may re-run Fetch unnecessarily when switching between cached datasets.

**Recommendation:**
- Position Fetch in a dedicated "Data Collection" section above or alongside the dataset selector
- Show a timestamp of the last successful fetch next to the Fetch button (e.g. *"Last fetched: 3 min ago"*)
- Disable dataset options that require fresh data until Fetch has completed at least once

---

### Improvement 5 — Link filter becomes silently disabled in Table view

**Problem:** When the user switches to Table view, the Link filter dropdown is visually greyed out (via the `filter-disabled` CSS class) but no explanation is given. The select still occupies space and the grey state may be confused with a loading or error state.

**Impact:** Users switch to Table view, see a greyed-out Links dropdown, wonder if something is broken, and cannot discover that the filter is topology-only.

**Recommendation:**
- Hide the Links filter entirely when in Table view, or replace it with a visible tooltip: *"Link filters apply to Topology view only"*
- Alternatively, contextually swap the Links filter for a column-visibility control that is relevant in Table view

---

### Improvement 6 — Button labels use internal/technical jargon

**Problem:** Several button labels expose implementation-level terminology:
- **"Enhance"** — tooltip: "Enhance node labels using static extaddr→device_label map". Non-experts do not know what extaddr means.
- **"More Info"** — vague; it means "show all table columns"
- **"lab"** — completely opaque; it toggles a lab/experimental mode
- **"Physics"** — may be understood by developers but not by network operations staff

**Impact:** Users avoid clicking buttons they do not understand, reducing feature adoption.

**Recommendation:**
- Rename **"Enhance"** → **"Device Labels"** (tooltip: "Apply friendly device name labels")
- Rename **"More Info"** → **"All Columns"**
- Rename **"lab"** → **"Dev Mode"** or hide behind a settings gear icon
- Rename **"Physics"** → **"Animate Layout"** or use a play/pause icon

---

### Improvement 7 — Filter dropdowns lack contextual help

**Problem:** The Nodes, Links, and Diagnostics filter dropdowns contain highly technical option values such as:
- *"Standard: routers, children, 321_links"*
- *"OTBR restapi: route routeData, childTable"*
- *"Router Neighbor Err Rate Frame — Low (≥ 2%)"*

These strings are meaningful to developers but not to network operations users who may not know what "321_links" or "routeData" refers to.

**Impact:** Users cannot confidently choose a filter without trial-and-error, reducing diagnostic efficiency.

**Recommendation:**
- Rename filter options to use plain English: *"Standard (routers, children, 321_links)"* → *"Standard links"*
- Add a small `ℹ` icon next to each filter group label that expands a tooltip explaining the filter category
- Add a "Recommended" label or asterisk to the most commonly used filter option per dataset

---

### Improvement 8 — Active/inactive button states are ambiguous

**Problem:** Buttons such as **Physics**, **Auto Zoom**, **Legend**, and **Animation** use the green `.active` class when enabled, but there is no visual affordance distinguishing a "toggle button" from a regular action button. The initial state (Physics=on, Auto Zoom=on, Legend=on, Animation=off) is set invisibly in JavaScript and has no explanation.

**Impact:** Users click a button that is green (active), it turns grey, and they do not know if something broke or if they toggled a feature off. The lack of an icon or label change reinforces the ambiguity.

**Recommendation:**
- Use toggle button patterns with explicit on/off labels or icons (e.g. ▶ Physics / ■ Physics, or ☑ Legend / ☐ Legend)
- Show a small tooltip on the button indicating its current state: *"Physics: ON — click to disable"*
- Group all toggles in a visually distinct "Visualization Controls" panel to signal they are persistent settings

---

### Improvement 9 — Node details panel is visually equivalent to static placeholder text

**Problem:** Both the topology and table details panels display *"Click a node to view its properties."* as a plain list item. The panel header says "Device details:" in a small `h2`. The panel is always visible and occupies 360px of screen width even when empty, crowding the topology canvas.

**Impact:** Users may not recognise the details panel as interactive. The empty 360px column wastes significant horizontal space on smaller screens, reducing the effective canvas area.

**Recommendation:**
- Collapse the details panel to a thin sidebar sliver or hidden state when no node is selected, and expand it on click
- Style the placeholder state distinctly (e.g. a dashed border with a cursor-pointer arrow icon inviting the user to click)
- Add keyboard shortcut support (Escape to close, arrow keys to navigate between nodes)

---

### Improvement 10 — Status bar provides minimal diagnostic context

**Problem:** The status bar shows *"Devices: 0"* and a loading message. After a dataset loads it shows a brief status message, but it does not persist a useful summary (e.g. total nodes, active border routers, count of degraded links, or data freshness).

**Impact:** Users must visually inspect the topology to understand the network health at a glance. The status bar is an underutilised space that currently communicates very little after initial load.

**Recommendation:**
- Extend the status bar into a **network health summary strip** with badge-style metrics:
  - `🖥 12 Nodes` | `🛤 3 Border Routers` | `⚠ 2 Low-Quality Links` | `✅ Data: 2 min ago`
- Colour-code degraded metrics (e.g. red badge for high error rate)
- Make each badge clickable to auto-apply the corresponding filter

---

## Current UI — Pros & Cons

### ✅ Pros

| # | Strength |
|---|----------|
| 1 | **Information density** — exposes all controls immediately with no drilling needed |
| 2 | **Compact layout** — entire UI fits within one viewport without scrolling |
| 3 | **Responsive CSS** — graceful reflow at 1000px and 720px breakpoints |
| 4 | **Consistent visual theme** — teal accent colour, clean card surfaces, good contrast |
| 5 | **Filter persistence** — active filter state is maintained when switching views |
| 6 | **Sortable table** — column sorting via sortable.js is intuitive |
| 7 | **Details panel** — topology and table both show side-panel properties on click |
| 8 | **Legend** — overlay LQ legend is well-positioned and toggleable |

### ❌ Cons

| # | Weakness |
|---|----------|
| 1 | No logical grouping of controls — toolbar is a flat unsorted sequence |
| 2 | Dataset dropdown is unstructured and overwhelming (20+ options, no categories) |
| 3 | No onboarding flow — new users have no guided entry point |
| 4 | Jargon-heavy labels — "Enhance", "lab", "Physics", "321_links" |
| 5 | Fetch action is visually disconnected from the dataset workflow |
| 6 | Link filter silently disables in table mode without explanation |
| 7 | Toggle button states are ambiguous (on vs off vs broken) |
| 8 | Details panel wastes 360px when empty |
| 9 | Status bar provides minimal persistent context after load |
| 10 | No keyboard navigation support |

---

## Alternative Layout A — Command-Center Dashboard

### Concept

A three-column "mission control" layout inspired by network operations centre (NOC) dashboards. The left column contains a persistent navigation sidebar with data-source controls and filter presets. The centre column is the main topology/table canvas. The right column is a live health monitor strip plus the node details panel.

### Layout Sketch

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ [tdash]  Thread Mesh Network Dashboard          [Fetch ▶]  Last: 2 min ago  │
├──────────────┬──────────────────────────────────────────┬────────────────────┤
│  DATA SOURCE │  [Topology] [Table]    [⚙ Physics] [≡]  │  Network Health    │
│              │                                          │  🖥 12 Nodes        │
│  Dataset:    │  ┌────────────────────────────────────┐  │  🛤 3 BRs           │
│  [▼ Select] │  │                                    │  │  ⚠ 2 Low LQ Links  │
│             │  │                                    │  │  ✅ 0 Errors        │
│  FILTERS    │  │       Topology Canvas              │  ├────────────────────│
│             │  │                                    │  │  Device Details     │
│  Nodes:     │  │                                    │  │  ────────────────── │
│  [▼ All]   │  │                                    │  │  (empty — click a  │
│             │  │                                    │  │   node to view)    │
│  Links:     │  └────────────────────────────────────┘  │                    │
│  [▼ Std]   │  [Legend overlay in canvas top-left]      │                    │
│             │                                          │                    │
│  Diagnostics│                                          │                    │
│  [▼ All]   │                                          │                    │
│             │                                          │                    │
│  ─────────  │                                          │                    │
│  [Device    │                                          │                    │
│   Labels ☑] │                                          │                    │
│  [Dev Mode] │                                          │                    │
└─────────────┴──────────────────────────────────────────┴────────────────────┘
```

### Pros

| Strength |
|----------|
| Clear separation of concerns — data controls left, view centre, health right |
| Network health strip gives instant at-a-glance status without needing to inspect topology |
| Left sidebar can collapse to icon-only mode for maximum canvas space |
| Logical left-to-right workflow: configure → view → inspect |
| Scales well to wide desktop monitors (typical NOC hardware) |
| Persistent sidebar state matches operator expectations from enterprise dashboards |

### Cons

| Weakness |
|----------|
| Requires significant CSS restructuring (3-column grid vs current linear layout) |
| Left sidebar adds visual weight on smaller screens (needs auto-collapse below 1200px) |
| Health strip in right column requires new JS summary computation |
| Risk of over-engineering for a developer tool with small audience |
| Three-panel layout may feel too complex for simple single-dataset inspections |

---

## Alternative Layout B — Guided Workflow Sidebar

### Concept

A step-by-step "wizard" approach with a collapsible left sidebar that guides the user through the workflow: Step 1 Collect → Step 2 Load → Step 3 Filter → Step 4 Inspect. The main canvas occupies the full remaining width. This approach is inspired by analytics tools like Kibana and Grafana.

### Layout Sketch

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  tdash: Thread Mesh Network Dashboard                         [≡ Settings]   │
├────────────────────┬─────────────────────────────────────────────────────────┤
│  ① Collect Data   │  [Topology ●] [Table]               [Device Labels ☑]   │
│  [Fetch ▶]        │  ─────────────────────────────────────────────────────── │
│  Last: 2 min ago  │                                                           │
│                   │  ┌──────────────────────────────────────────────────┐    │
│  ② Load Dataset   │  │                                                  │    │
│  [▼ otbr-cli      │  │                                                  │    │
│     merged all]   │  │             Topology / Table Canvas              │    │
│                   │  │                                                  │    │
│  ③ Filter View    │  │                                                  │    │
│  Nodes  [▼ All]  │  │                                                  │    │
│  Links  [▼ Std]  │  └──────────────────────────────────────────────────┘    │
│  Diag   [▼ All]  │                                                           │
│                   │  ─────────────────────────────────────────────────────── │
│  ④ Inspect Node  │  🖥 12 Nodes  🛤 3 BRs  ⚠ 2 Low-LQ  ✅ 0 Errors        │
│  (click topology) │                                                           │
│  ───────────────  │                                                           │
│  Name: Router-01  │                                                           │
│  RLOC: 0x0400     │                                                           │
│  Type: Router     │                                                           │
│  LQ: High (3)     │                                                           │
│  [Copy] [⟳ More]  │                                                           │
└────────────────────┴─────────────────────────────────────────────────────────┘
```

### Pros

| Strength |
|----------|
| Progressive disclosure — users follow a clear numbered 4-step flow |
| Sidebar unifies dataset loading, filtering, and details into one pane |
| Full-width canvas maximises topology visibility — the most important view |
| Collapsing the sidebar (at narrow widths) pushes it to a bottom drawer |
| Step numbers serve as built-in onboarding guide |
| Node details in sidebar eliminates the awkward side-panel resizing issue |
| Most translatable to a mobile layout (sidebar becomes bottom sheet) |

### Cons

| Weakness |
|----------|
| Sidebar can become very tall when node details expand (many properties) |
| Step numbering implies strict sequence that isn't always necessary (experts may skip steps) |
| Left sidebar requires re-wiring of the dataset select and filter events |
| The details section in the sidebar scrolls independently — could confuse users |
| No dedicated space for the health summary strip (needs to be in the bottom bar) |

---

## Alternative Layout C — Minimal Focused View

### Concept

A "chrome-less" full-bleed topology canvas as the hero, with controls in a floating action bar at the top and a slide-in panel for details and settings. Inspired by mapping tools like Google Maps and network monitoring tools like NetBox. The focus is entirely on the topology graph; everything else is secondary.

### Layout Sketch

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ ┌──────────────────────────────────────────────────────────────────────────┐ │
│ │ [⛁ Fetch]  [▼ otbr-cli: merged all]  [⚙]      [Topo●] [Table]  [🔍] │ │
│ └──────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
│   ┌──── Link Quality ────┐                         ┌──── ⚠ Alerts ─────────┐ │
│   │ ── LQ3 (High)        │                         │ 2 low-quality links   │ │
│   │ ─ ─ LQ1 (Low)        │                         │ 0 errors              │ │
│   └──────────────────────┘                         └───────────────────────┘ │
│                                                                                │
│                                                                                │
│                    F U L L - B L E E D   T O P O L O G Y                     │
│                                                                                │
│                                                                                │
│                                                                                │
│                                    [+] [−] [⌖]   ← zoom controls (top-right)│
│                                                                                │
│                                                                                │
│   ┌─ 🖥 12 Nodes  🛤 3 BRs  ⚠ 2 Low-LQ  ✅ 0 Errors ────────────────────┐  │
│   │                                                                        │  │
│   └────────────────────────────────────────────────────────────────────────┘  │
│                                                                                │
│  ╔═══════ Device Details (slide-in on click) ══════════════╗                 │
│  ║  Router-01  [✕]                                         ║                 │
│  ║  RLOC16: 0x0400 | Type: Router | LQ: High              ║                 │
│  ║  ▼ MAC Counters  ▼ MLE Counters  ▼ Neighbors           ║                 │
│  ╚═════════════════════════════════════════════════════════╝                 │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Pros

| Strength |
|----------|
| Maximum canvas real estate — ideal for large and complex mesh topologies |
| Floating action bar keeps controls visible without consuming layout rows |
| Slide-in details panel does not permanently consume width |
| Health alert badges in top-right give instant status without overwhelming the layout |
| Clean enough to be embedded in a wall monitor / NOC display |
| Minimal cognitive load for experienced daily users |
| The bottom status strip is always visible without occupying vertical column space |

### Cons

| Weakness |
|----------|
| Floating/overlay elements can obscure nodes in dense topologies |
| Slide-in panel covers part of the topology when open — requires dismiss gesture |
| Settings are hidden behind ⚙ icon — discoverability is lower for new users |
| Table view requires a full layout transition (canvas becomes table, action bar reflows) |
| Less space for long filter dropdowns — may need a filter drawer/modal |
| Animations/overlays add implementation complexity vs current layout |

---

## Comparison Matrix

| Criterion | Current UI | Alt A: Command-Center | Alt B: Guided Workflow | Alt C: Minimal Focused |
|-----------|:----------:|:---------------------:|:---------------------:|:---------------------:|
| Logical flow / discoverability | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| Ease for new users | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| Topology canvas real estate | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Expert / power-user efficiency | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Mobile / tablet adaptability | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| Implementation delta (low = easy) | — | ⭐⭐ (high effort) | ⭐⭐⭐ (med effort) | ⭐⭐⭐⭐ (med-low effort) |
| Network health at-a-glance | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| Filter clarity | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |

---

## Recommended Next Steps

This proposal is for review only. **No code changes should be made until the plan is approved.**

Once approved, the following phased implementation approach is suggested:

### Phase 1 — Quick wins (improvements that require only HTML/CSS changes)
- [ ] Rename jargon-heavy button labels (Improvement 6)
- [ ] Add `<optgroup>` categories to dataset select (Improvement 2)
- [ ] Add explanatory tooltip to greyed-out Link filter in Table view (Improvement 5)
- [ ] Extend status bar with device count badges (Improvement 10)

### Phase 2 — Interaction improvements (HTML + CSS + JS)
- [ ] Reorganise toolbar into logical button groups (Improvement 1)
- [ ] Add onboarding banner with guided three-step flow (Improvement 3)
- [ ] Connect Fetch button visually to dataset workflow with last-fetched timestamp (Improvement 4)
- [ ] Improve toggle button states with icon or label-change feedback (Improvement 8)

### Phase 3 — Layout redesign (choose one alternative)
- [ ] Implement chosen alternative layout (A, B, or C — pending stakeholder decision)
- [ ] Collapsible details panel with expand/collapse affordance (Improvement 9)
- [ ] Filter option plain-English renaming and `ℹ` tooltips (Improvement 7)

### Stakeholder Decision Required

Before Phase 3 begins, the team should decide:

1. **Which alternative layout** to pursue — or a hybrid combining the best elements of each
2. **Target audience priority** — new users (favour Alt B) vs experienced power users (favour Alt C) vs NOC operators (favour Alt A)
3. **Scope of label changes** — internal/developer-facing terminology may need to be preserved for some options that map directly to CLI arguments
