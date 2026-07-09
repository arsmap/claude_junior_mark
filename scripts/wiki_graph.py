#!/usr/bin/env python3
"""wiki_graph.py - export the wiki relationship graph as a self-contained viewer.

Reuses wiki_cluster.py's graph analysis (3-signal edges + Louvain communities),
then writes wiki/graph.html: a standalone, offline-openable force-directed graph
viewer (vis-network from CDN, graph data inlined as JSON so file:// just works).

Node color toggles between Louvain community and page type; node size scales with
backlink count (sqrt); edge width scales with relationship weight. Read-only:
never modifies wiki content pages or overview.md.
"""
import os
import sys
import json
import math
from collections import defaultdict

import wiki_cluster

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WIKI_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "wiki"))
OUT_NAME = "graph.html"

# Dark categorical palette (dataviz reference, dark column). Validated set:
# worst adjacent CVD dE 10.3 - legal here because node labels give secondary
# encoding. Slot beyond the 8th folds into OTHER gray.
PALETTE = [
    "#3987e5", "#199e70", "#c98500", "#008300",
    "#9085e9", "#e66767", "#d55181", "#d95926",
]
OTHER_COLOR = "#7a7a75"

VIS_CDN = "https://cdn.jsdelivr.net/npm/vis-network@9.1.9/standalone/umd/vis-network.min.js"


def compute_backlinks(pages):
    """Return {slug: incoming [[link]] count} over content pages."""
    backlinks = defaultdict(int)
    for slug in pages:
        backlinks[slug] = 0
    for slug, p in pages.items():
        for target in p["links"]:
            backlinks[target] += 1
    return backlinks


def order_communities(slugs, membership):
    """Map raw Louvain labels to size-ordered integer indices (0 = largest)."""
    members = defaultdict(list)
    for n in slugs:
        members[membership[n]].append(n)
    ordered = sorted(members.items(), key=lambda kv: (-len(kv[1]), kv[1][0]))
    index_of = {}
    community_members = []
    for idx, (raw, ms) in enumerate(ordered):
        index_of[raw] = idx
        community_members.append(sorted(ms))
    return index_of, community_members


def community_labels(community_members, label_of, titles):
    """Human label per community = majority overview cluster title (fallback N)."""
    labels = []
    for idx, ms in enumerate(community_members, 1):
        counts = defaultdict(int)
        for m in ms:
            lab = label_of.get(m)
            if lab is not None:
                counts[lab] += 1
        if counts:
            dom = max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
            title = titles.get(dom, "")
            labels.append("%s. %s" % (dom, title) if title else dom)
        else:
            labels.append("community %d" % idx)
    return labels


def order_types(pages):
    """Ordered unique page types (by count desc), for a stable type->slot map."""
    counts = defaultdict(int)
    for p in pages.values():
        counts[p["type"] or "?"] += 1
    return [t for t, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def build_data(wiki_dir):
    pages = wiki_cluster.parse_pages(wiki_dir)
    if not pages:
        return None
    slugs, edges, signals = wiki_cluster.build_graph(pages)
    membership = wiki_cluster.louvain(slugs, edges)
    label_of, titles = wiki_cluster.parse_overview(wiki_dir)

    backlinks = compute_backlinks(pages)
    index_of, community_members = order_communities(slugs, membership)
    comm_labels = community_labels(community_members, label_of, titles)
    type_list = order_types(pages)

    nodes = []
    for slug in slugs:
        bl = backlinks[slug]
        ptype = pages[slug]["type"] or "?"
        ov = label_of.get(slug)
        ov_title = titles.get(ov, "") if ov else ""
        nodes.append({
            "id": slug,
            "label": slug,
            "size": round(8 + math.sqrt(bl) * 5, 1),
            "community": index_of[membership[slug]],
            "type": ptype,
            "backlinks": bl,
            "overview": ("%s. %s" % (ov, ov_title)) if ov else "",
        })

    # Display only direct [[link]] edges (Obsidian-like readable graph); the
    # dense source-overlap / Adamic-Adar edges still drive community detection
    # above but would hairball the canvas. Width uses the full relationship
    # weight so a directly-linked pair that also shares sources reads stronger.
    edge_list = []
    for (a, b), s in signals.items():
        if s["link"] > 0:
            w = s["link"] + s["source"] + s["adamic"]
            edge_list.append({"from": a, "to": b, "weight": round(w, 2)})

    return {
        "nodes": nodes,
        "edges": edge_list,
        "communityLabels": comm_labels,
        "typeList": type_list,
        "palette": PALETTE,
        "otherColor": OTHER_COLOR,
    }


def render_html(data):
    payload = json.dumps(data, ensure_ascii=False)
    return HTML_TEMPLATE.replace("__GRAPH_DATA__", payload).replace("__VIS_CDN__", VIS_CDN)


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JM wiki graph</title>
<script src="__VIS_CDN__"></script>
<style>
  :root {
    --surface: #1a1a19;
    --panel: #232321;
    --ink: #e8e8e3;
    --muted: #898781;
    --border: rgba(255,255,255,0.10);
  }
  html, body { margin: 0; height: 100%; background: var(--surface); color: var(--ink);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
  #graph { position: absolute; inset: 0; }
  #panel { position: absolute; top: 12px; left: 12px; z-index: 10; background: var(--panel);
    border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; max-width: 280px;
    box-shadow: 0 4px 18px rgba(0,0,0,0.4); }
  #panel h1 { font-size: 14px; margin: 0 0 2px; }
  #panel .sub { font-size: 11px; color: var(--muted); margin-bottom: 10px; }
  .toggle { display: inline-flex; border: 1px solid var(--border); border-radius: 7px; overflow: hidden; margin-bottom: 10px; }
  .toggle button { background: transparent; color: var(--muted); border: 0; padding: 5px 12px;
    font: inherit; font-size: 12px; cursor: pointer; }
  .toggle button.on { background: #34342f; color: var(--ink); }
  #legend { display: flex; flex-direction: column; gap: 5px; max-height: 46vh; overflow-y: auto; }
  .legend-row { display: flex; align-items: center; gap: 8px; font-size: 12px; line-height: 1.25; }
  .swatch { width: 12px; height: 12px; border-radius: 3px; flex: 0 0 auto; }
  #hint { position: absolute; bottom: 12px; left: 12px; z-index: 10; font-size: 11px; color: var(--muted); }
  .switch-row { display: flex; align-items: center; justify-content: space-between; font-size: 12px; margin-bottom: 10px; }
  .switch { position: relative; width: 34px; height: 18px; flex: 0 0 auto; }
  .switch input { opacity: 0; width: 0; height: 0; }
  .slider { position: absolute; inset: 0; background: #3a3a36; border-radius: 999px; transition: .15s; cursor: pointer; }
  .slider::before { content: ""; position: absolute; width: 14px; height: 14px; left: 2px; top: 2px; background: #e8e8e3; border-radius: 50%; transition: .15s; }
  .switch input:checked + .slider { background: #3987e5; }
  .switch input:checked + .slider::before { transform: translateX(16px); }
</style>
</head>
<body>
<div id="panel">
  <h1>JM wiki graph</h1>
  <div class="sub" id="stats"></div>
  <div class="toggle">
    <button id="btn-community" class="on">커뮤니티</button>
    <button id="btn-type">타입</button>
  </div>
  <label class="switch-row">
    <span>라벨 항상 표시</span>
    <span class="switch"><input type="checkbox" id="label-toggle"><span class="slider"></span></span>
  </label>
  <div id="legend"></div>
</div>
<div id="graph"></div>
<div id="hint">드래그로 이동 · 스크롤로 확대 · 노드에 마우스 올리면 정보</div>
<script>
const DATA = __GRAPH_DATA__;
const PALETTE = DATA.palette, OTHER = DATA.otherColor;

function colorForCommunity(i) { return i < PALETTE.length ? PALETTE[i] : OTHER; }
function colorForType(t) {
  const i = DATA.typeList.indexOf(t);
  return (i >= 0 && i < PALETTE.length) ? PALETTE[i] : OTHER;
}

let mode = "community";
let labelsAlways = false;  // false = hover-only labels; toggled by the switch

const nodes = new vis.DataSet(DATA.nodes.map(n => ({
  id: n.id,
  label: n.label,
  size: n.size,
  color: colorForCommunity(n.community),
  title: n.label + "\n타입: " + n.type + "\n백링크: " + n.backlinks +
         (n.overview ? "\n클러스터: " + n.overview : ""),
  _community: n.community,
  _type: n.type,
})));

const edges = new vis.DataSet(DATA.edges.map(e => ({
  from: e.from, to: e.to, value: e.weight,
})));

const container = document.getElementById("graph");
const network = new vis.Network(container, { nodes, edges }, {
  nodes: {
    shape: "dot",
    font: { color: "#e8e8e3", size: 13, face: "system-ui" },
    borderWidth: 0,
  },
  edges: {
    color: { color: "rgba(255,255,255,0.13)", highlight: "rgba(255,255,255,0.4)" },
    scaling: { min: 0.4, max: 4 },
    smooth: false,
  },
  physics: {
    solver: "forceAtlas2Based",
    forceAtlas2Based: { gravitationalConstant: -55, centralGravity: 0.012, springLength: 120, springConstant: 0.08 },
    stabilization: { iterations: 250 },
  },
  interaction: { hover: true, tooltipDelay: 120 },
});

function nodeColor(n) {
  return mode === "community" ? colorForCommunity(n.community) : colorForType(n.type);
}

// paint(null) = normal view; paint(nodeSet, edgeSet) = hover highlight (others dim).
function paint(nodeSet, edgeSet) {
  const hovering = !!nodeSet;
  nodes.update(DATA.nodes.map(n => {
    const active = !hovering || nodeSet.has(n.id);
    const showLabel = labelsAlways || (hovering && active);
    return {
      id: n.id,
      label: showLabel ? n.label : "",
      color: active ? nodeColor(n) : "rgba(120,120,115,0.12)",
      font: { color: active ? "#e8e8e3" : "rgba(232,232,227,0.13)", size: 13, face: "system-ui" },
    };
  }));
  edges.update(edges.get().map(e => {
    let c;
    if (!hovering) c = "rgba(255,255,255,0.13)";
    else if (edgeSet.has(e.id)) c = "rgba(255,255,255,0.5)";
    else c = "rgba(255,255,255,0.03)";
    return { id: e.id, color: { color: c, highlight: c } };
  }));
}

function recolor() { paint(null, null); }

network.on("hoverNode", params => {
  const id = params.node;
  const nb = new Set(network.getConnectedNodes(id));
  nb.add(id);
  paint(nb, new Set(network.getConnectedEdges(id)));
});
network.on("blurNode", () => paint(null, null));

function renderLegend() {
  const el = document.getElementById("legend");
  el.innerHTML = "";
  const rows = mode === "community"
    ? DATA.communityLabels.map((lab, i) => [colorForCommunity(i), lab])
    : DATA.typeList.map(t => [colorForType(t), t]);
  for (const [color, label] of rows) {
    const row = document.createElement("div");
    row.className = "legend-row";
    row.innerHTML = '<span class="swatch" style="background:' + color + '"></span><span>' + label + '</span>';
    el.appendChild(row);
  }
}

function setMode(m) {
  mode = m;
  document.getElementById("btn-community").classList.toggle("on", m === "community");
  document.getElementById("btn-type").classList.toggle("on", m === "type");
  recolor();
  renderLegend();
}

document.getElementById("btn-community").onclick = () => setMode("community");
document.getElementById("btn-type").onclick = () => setMode("type");

document.getElementById("stats").textContent =
  DATA.nodes.length + "개 노드 · " + DATA.edges.length + "개 링크 · " +
  DATA.communityLabels.length + "개 커뮤니티";

document.getElementById("label-toggle").addEventListener("change", e => {
  labelsAlways = e.target.checked;
  paint(null, null);
});

renderLegend();
paint(null, null);  // apply initial hover-only label state
</script>
</body>
</html>
"""


def main():
    wiki_dir = sys.argv[1] if len(sys.argv) > 1 else WIKI_DIR
    if not os.path.isdir(wiki_dir):
        sys.stderr.write("wiki dir not found: %s\n" % wiki_dir)
        return 1
    data = build_data(wiki_dir)
    if data is None:
        sys.stderr.write("no content pages found in %s\n" % wiki_dir)
        return 1
    html = render_html(data)
    out_path = os.path.join(wiki_dir, OUT_NAME)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    sys.stdout.write("wrote %s: %d nodes, %d edges, %d communities\n"
                     % (out_path, len(data["nodes"]), len(data["edges"]),
                        len(data["communityLabels"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
