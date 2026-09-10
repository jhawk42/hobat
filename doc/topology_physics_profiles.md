# Topology Physics Profiles

The Topology view uses a physics profile to arrange the Thread network. In
Auto mode, Hobat uses the selected dataset's default profile. A manually
selected profile overrides that default for the current browser preference.

Every profile preserves node identity and edge evidence. A border router is a
green square, a router is a blue hexagon, children are yellow dots, and unknown
nodes are gray dots. The profile changes their positions and whether diagnostic
links are allowed to influence placement.

## Choose a profile

| Profile | Best for | Result |
| --- | --- | --- |
| Mesh Compact | Default inspection of most datasets | Stable parent-local groups with separate FTD and other-child bands. |
| Hub Spoke | A broad live mesh overview | Readable router core/periphery; diagnostic child routes do not pull nodes together. |
| Mesh Ring | Comparing or presenting a snapshot | A deterministic, fixed ring with children around their selected parent. |
| Mesh Tree Horizontal | Wide displays and role review | Left-to-right bands show border routers, routers, FTDs, and other children. |
| Mesh Tree Vertical | Tall displays and role review | The same bands, arranged top to bottom. |
| Mesh Baseline | A neutral force-layout comparison | General Barnes-Hut layout with no specialized geometry. |
| Mesh Dense | Experimenting with a tighter force layout | Stronger separation and longer stabilization for dense graphs. |
| Mesh Sparse | Experimenting with a more center-oriented force layout | Shorter springs and stronger central pull. |

## How profiles display Thread nodes

### Mesh Compact

Compact is the usual choice for examining a populated network. Routers with
children form an outer ring, while other routers form an inner ring. Each child
is placed around one selected parent: FTD children occupy the nearer band and
MTD or other children the farther band. Collision resolution separates routers
and children before their coordinates are pinned.

This makes parent-child relationships easy to inspect without the view drifting
after it settles. Route-only router-to-child observations remain available as
edges but do not alter placement.

### Hub Spoke

Hub Spoke is a force-driven overview. Routers form the main network body while
longer router links keep border routers from collapsing into that center.
Explicit parent-child relationships pull FTD children closer than other
children. Non-parent router-child route observations are visible but exert no
spring force; secondary OTBR router-route observations are thin and dashed.

This reduces visual crowding in diagnostic-rich datasets while retaining the
evidence needed to investigate routes and parentage.

### Mesh Ring

Ring fixes routers on a circular path and places their selected children in
outward polar bands. FTD children are closer to their parent than MTD and other
children. Extra children use additional layers, and isolated or unassigned
nodes receive outer rings. Once built, every node is pinned.

Use Ring when repeatability matters. The same input has the same geometry, so
before/after screenshots and discussions of a specific topology stay legible.

### Mesh Tree Horizontal and Vertical

The Tree profiles classify nodes by role and by whether the selected parent is a
border router. Border routers occupy one band; non-border routers occupy a
separate band; FTDs and explicit non-FTD children occupy bands on the
corresponding side. An intentional empty band separates the two router groups.

Horizontal fixes the bands from left to right. Vertical fixes them from top to
bottom. Router and fallback positions are fixed; children can spread along the
other axis around their parent. These profiles are especially useful for
answering which children belong to which class of router.

### Mesh Baseline, Dense, and Sparse

These are force-only views. They do not create parent bands, rings, or role
zones, so routers, border routers, FTDs, MTDs, and unknown nodes arrange solely
through the graph's visible physical links and the profile's Barnes-Hut values.

Baseline is the neutral fallback. Dense increases repulsion and stabilization
time for a more separated force layout. Sparse applies a stronger central pull
and shorter springs for a tighter comparison. They are most useful when
evaluating how the raw graph behaves without specialized layout rules.

## Reading links and isolated nodes

Explicit parent-child links are structural. In specialized profiles they remain
physical, and their length accounts for whether the child is an FTD or a
different child type. The dashboard may show route-only links between a router
and child, but Compact, Tree, and Hub Spoke prevent them from competing with
the selected parent relationship.

The view also keeps isolated known and unknown nodes near an invisible layout
anchor. These anchors do not represent Thread links and do not appear in the
visible link count.

## Practical guidance

Start with the dataset's Auto profile, which is normally Mesh Compact. Switch
to Hub Spoke when router and route density makes the central area hard to read.
Use Ring for a fixed diagnostic picture, and use a Tree orientation to inspect
role and parent affinity. Baseline, Dense, and Sparse are comparison profiles
for studying force-layout behavior rather than authoritative hierarchy views.
