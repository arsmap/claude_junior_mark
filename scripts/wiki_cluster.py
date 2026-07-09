#!/usr/bin/env python3
"""wiki_cluster.py - read-only wiki graph analysis.

Parses wiki content pages, builds a 3-signal relationship graph
(direct link x3.0 / source overlap x4.0 / Adamic-Adar x1.5; page type is a
descriptor label, deliberately not a clustering edge - see wiki-automation-boundary),
runs Louvain community detection, and writes a cluster / orphan / cohesion
report to wiki/_cluster_report.md. It also diffs the auto clusters against
overview.md's manual clustering (alignment / drift / uncharted / stale refs).

Read-only: never modifies wiki content pages or overview.md. Pure standard
library. Reclassification (overview.md) stays a human judgement step - this
only drafts the diff.
"""
import os
import re
import sys
import math
from collections import defaultdict
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WIKI_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "wiki"))
REPORT_NAME = "_cluster_report.md"

# Pages that are structure/meta, not content nodes.
EXCLUDE = {"purpose", "overview", "index", "log", "log_archive"}

# Relationship signal weights (Karpathy/nashsu llm_wiki original).
# Type affinity is intentionally excluded from clustering edges: type (form) and
# theme (cluster) are separate layers, so type only labels a page, it does not
# pull pages together. See wiki-automation-boundary.md.
W_LINK = 3.0
W_SOURCE = 4.0
W_ADAMIC = 1.5

# A drift page is a real reclassification candidate only if its overview label
# is "concentrated": at least this fraction of the label's pages share one auto
# cluster (a clear home). Below it, the label is scattered across the machine
# super-cluster (Louvain re-merges hand-split A/E/F/H/I), so its per-page drift
# is expected merge noise, not a signal. See wiki-automation-boundary.md.
LABEL_HOME_CUTOFF = 0.6

LINK_RE = re.compile(r"\[\[([^\]\[]+)\]\]")


# --- parsing -----------------------------------------------------------------
def parse_frontmatter(text):
    """Return (type, set(sources)) from YAML frontmatter."""
    ptype = ""
    sources = set()
    if not text.startswith("---"):
        return ptype, sources
    end = text.find("\n---", 3)
    if end == -1:
        return ptype, sources
    for line in text[3:end].splitlines():
        line = line.strip()
        if line.startswith("type:"):
            ptype = line[len("type:"):].strip()
        elif line.startswith("sources:"):
            inside = line[len("sources:"):].strip().strip("[]")
            for s in inside.split(","):
                s = s.strip()
                if s:
                    sources.add(s)
    return ptype, sources


def parse_pages(wiki_dir):
    """Return {slug: {"type", "sources", "links"}} for content pages only."""
    pages = {}
    for fn in sorted(os.listdir(wiki_dir)):
        if not fn.endswith(".md"):
            continue
        slug = fn[:-3]
        if slug in EXCLUDE or slug.startswith("_"):
            continue
        with open(os.path.join(wiki_dir, fn), encoding="utf-8") as fh:
            text = fh.read()
        ptype, sources = parse_frontmatter(text)
        links = set(LINK_RE.findall(text))
        pages[slug] = {"type": ptype, "sources": sources, "links": links}
    # Keep only links that point to a known content page (drop self / dangling).
    slugs = set(pages)
    for slug, p in pages.items():
        p["links"] = {l for l in p["links"] if l in slugs and l != slug}
    return pages


# Overview membership region: cluster labels live between these two headers.
OV_START_RE = re.compile(r"^##\s+주제 클러스터")
OV_END_RE = re.compile(r"^##\s+허브와 다리")
OV_LABEL_RE = re.compile(r"^###\s+([^.\s]+)\.\s*(.*)")
# Membership lives in bullet lines. Some clusters list one page per bullet
# ("- [[slug]] (type) — …"), others list several inline under a bold sub-group
# label ("- **flag·가드**: [[a]]·[[b]]"), so capture every [[slug]] in a bullet.
# Non-bullet prose ("묶이는 끈: [[…]]") carries cross-links, not membership.
OV_BULLET_RE = re.compile(r"^\s*-\s")


def parse_overview(wiki_dir):
    """Return (label_of, titles) from overview.md manual clustering.

    label_of: {slug: label} for pages listed under a cluster header.
    titles:   {label: header title} preserving declaration order.
    Only the membership region (주제 클러스터 ~ 허브와 다리) is read, so the
    cross-cluster '허브와 다리' links do not count as membership.
    """
    label_of = {}
    titles = {}
    path = os.path.join(wiki_dir, "overview.md")
    if not os.path.isfile(path):
        return label_of, titles
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    in_region = False
    label = None
    for line in text.splitlines():
        if not in_region:
            if OV_START_RE.match(line):
                in_region = True
            continue
        if OV_END_RE.match(line):
            break
        mh = OV_LABEL_RE.match(line)
        if mh:
            label = mh.group(1)
            titles[label] = mh.group(2).strip()
            continue
        if OV_BULLET_RE.match(line) and label is not None:
            for slug in LINK_RE.findall(line):
                label_of.setdefault(slug, label)
    return label_of, titles


# --- graph -------------------------------------------------------------------
def _key(a, b):
    return (a, b) if a < b else (b, a)


def build_graph(pages):
    """Build weighted edges and per-edge signal breakdown."""
    slugs = sorted(pages)
    # Direct-link adjacency (unweighted, undirected) - basis for Adamic-Adar.
    link_adj = defaultdict(set)
    for a in slugs:
        for b in pages[a]["links"]:
            link_adj[a].add(b)
            link_adj[b].add(a)

    signals = defaultdict(lambda: {"link": 0.0, "source": 0.0, "adamic": 0.0})
    # 1. direct link
    for a in slugs:
        for b in pages[a]["links"]:
            signals[_key(a, b)]["link"] = W_LINK
    # 2. source overlap (all pairs)
    for i, a in enumerate(slugs):
        for b in slugs[i + 1:]:
            if pages[a]["sources"] & pages[b]["sources"]:
                signals[_key(a, b)]["source"] = W_SOURCE
    # 3. Adamic-Adar over the link graph
    for i, a in enumerate(slugs):
        for b in slugs[i + 1:]:
            common = link_adj[a] & link_adj[b]
            if not common:
                continue
            aa = 0.0
            for z in common:
                deg = len(link_adj[z])
                if deg > 1:
                    aa += 1.0 / math.log(deg)
            if aa > 0:
                signals[_key(a, b)]["adamic"] = W_ADAMIC * aa

    edges = {}
    for k, s in signals.items():
        w = s["link"] + s["source"] + s["adamic"]
        if w > 0:
            edges[k] = w
    return slugs, edges, signals


# --- Louvain -----------------------------------------------------------------
def _one_level(nodes, adj, loops):
    """One Louvain pass. Returns (membership, improved)."""
    k = {n: sum(adj[n].values()) + 2 * loops[n] for n in nodes}
    m = sum(k.values()) / 2.0
    comm = {n: n for n in nodes}
    tot = {n: k[n] for n in nodes}
    if m == 0:
        return comm, False

    improved = False
    moved = True
    while moved:
        moved = False
        for n in nodes:
            c_old = comm[n]
            tot[c_old] -= k[n]
            neigh_w = defaultdict(float)
            for j, w in adj[n].items():
                if j != n:
                    neigh_w[comm[j]] += w
            best_c = c_old
            best_gain = neigh_w.get(c_old, 0.0) - tot[c_old] * k[n] / (2.0 * m)
            for c, wic in neigh_w.items():
                gain = wic - tot[c] * k[n] / (2.0 * m)
                if gain > best_gain + 1e-12:
                    best_gain = gain
                    best_c = c
            comm[n] = best_c
            tot[best_c] += k[n]
            if best_c != c_old:
                moved = True
                improved = True
    return comm, improved


def _aggregate(nodes, adj, loops, comm):
    """Collapse communities into super-nodes."""
    new_adj = defaultdict(lambda: defaultdict(float))
    new_loops = defaultdict(float)
    for n in nodes:
        new_loops[comm[n]] += loops[n]
    seen = set()
    for a in nodes:
        for b, w in adj[a].items():
            if b == a:
                continue
            pair = _key(a, b)
            if pair in seen:
                continue
            seen.add(pair)
            ca, cb = comm[a], comm[b]
            if ca == cb:
                new_loops[ca] += w
            else:
                new_adj[ca][cb] += w
                new_adj[cb][ca] += w
    new_nodes = sorted(set(comm.values()))
    for c in new_nodes:
        _ = new_adj[c]
    return new_nodes, new_adj, new_loops


def louvain(nodes, edges):
    """Return {original_node: community_label}."""
    adj = defaultdict(lambda: defaultdict(float))
    for (a, b), w in edges.items():
        adj[a][b] += w
        adj[b][a] += w
    loops = defaultdict(float)
    for n in nodes:
        _ = adj[n]

    orig_to_cur = {n: n for n in nodes}
    cur_nodes = list(nodes)
    for _level in range(100):
        comm, improved = _one_level(cur_nodes, adj, loops)
        for o in orig_to_cur:
            orig_to_cur[o] = comm[orig_to_cur[o]]
        if not improved:
            break
        cur_nodes, adj, loops = _aggregate(cur_nodes, adj, loops, comm)
    return orig_to_cur


def modularity(nodes, edges, membership):
    m = sum(edges.values())
    if m == 0:
        return 0.0
    k = defaultdict(float)
    for (a, b), w in edges.items():
        k[a] += w
        k[b] += w
    comm_in = defaultdict(float)
    comm_tot = defaultdict(float)
    for n in nodes:
        comm_tot[membership[n]] += k[n]
    for (a, b), w in edges.items():
        if membership[a] == membership[b]:
            comm_in[membership[a]] += 2 * w
    q = 0.0
    for c in comm_tot:
        q += comm_in[c] / (2 * m) - (comm_tot[c] / (2 * m)) ** 2
    return q


# --- analysis ----------------------------------------------------------------
def cluster_members(nodes, membership):
    clusters = defaultdict(list)
    for n in nodes:
        clusters[membership[n]].append(n)
    # Order clusters by size (desc), members alphabetical.
    ordered = sorted(clusters.values(), key=lambda ms: (-len(ms), ms[0]))
    for ms in ordered:
        ms.sort()
    return ordered


def cluster_cohesion(members, edges, membership):
    """internal / (internal + external) edge weight for one cluster."""
    mset = set(members)
    internal = external = 0.0
    for (a, b), w in edges.items():
        a_in, b_in = a in mset, b in mset
        if a_in and b_in:
            internal += w
        elif a_in or b_in:
            external += w
    denom = internal + external
    return (internal / denom) if denom > 0 else 0.0, internal, external


def cluster_modularity(internal, external, m):
    """Per-cluster modularity contribution: comm_in/(2m) - (comm_tot/(2m))^2.
    Positive = the cluster binds tighter internally than a random partition
    would; negative flags it as a reclassification candidate. Self-normalizing
    across graph density and cluster count, unlike an absolute cohesion cutoff.
    Derived from the cohesion internal/external weights (comm_in = 2*internal,
    comm_tot = 2*internal + external)."""
    if m <= 0:
        return 0.0
    comm_in = 2 * internal
    comm_tot = 2 * internal + external
    return comm_in / (2 * m) - (comm_tot / (2 * m)) ** 2


def strong_degree(node, signals):
    """Count edges of a node carrying a link or source signal."""
    n = 0
    for (a, b), s in signals.items():
        if node in (a, b) and (s["link"] > 0 or s["source"] > 0):
            n += 1
    return n


def classify_orphans(slugs, signals):
    """Return list of (slug, reason) for pages with no link/source edge."""
    out = []
    for n in slugs:
        if strong_degree(n, signals) > 0:
            continue
        has_adamic = any(n in (a, b) and s["adamic"] > 0
                         for (a, b), s in signals.items())
        if has_adamic:
            reason = "weak (Adamic-Adar common-neighbor only)"
        else:
            reason = "isolated (no edges)"
        out.append((n, reason))
    return out


def dominant_type(members, pages):
    counts = defaultdict(int)
    for m in members:
        counts[pages[m]["type"] or "?"] += 1
    return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]


# --- overview diff -----------------------------------------------------------
def overview_dominant_label(members, label_of):
    """Majority overview label among a cluster's members (None if none charted)."""
    counts = defaultdict(int)
    for m in members:
        lab = label_of.get(m)
        if lab is not None:
            counts[lab] += 1
    if not counts:
        return None, 0
    lab = max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
    return lab, counts[lab]


def build_overview_diff(clusters, slugs, label_of, titles):
    """Report lines comparing auto clusters against overview.md membership."""
    lines = ["## overview.md 대조", ""]
    if not label_of:
        lines.append("overview.md 멤버십을 읽지 못함 (파일 없음 또는 클러스터 미기재).")
        lines.append("")
        return lines

    lines.append("자동 클러스터(Louvain)를 overview.md 수동 클러스터와 대조. "
                 "읽기 전용 — overview.md는 수정하지 않고 재분류 후보만 제시.")
    lines.append("")

    # Per overview label: how its pages spread across auto clusters. A label
    # whose pages mostly share one auto cluster is "concentrated" (has a clear
    # home); one scattered across several is being torn by the machine
    # super-cluster (A/E/F/H/I merge), so its per-page drift is expected noise.
    label_dist = defaultdict(lambda: defaultdict(int))  # lab -> {cluster_i: n}
    for i, members in enumerate(clusters, 1):
        for m in members:
            lab = label_of.get(m)
            if lab is not None:
                label_dist[lab][i] += 1
    label_home = {}  # lab -> (home_cluster_i, home_fraction)
    for lab, dist in label_dist.items():
        total = sum(dist.values())
        home_i, home_n = max(dist.items(), key=lambda kv: (kv[1], -kv[0]))
        label_home[lab] = (home_i, home_n / total if total else 0.0)

    # 1. alignment + 2. drift
    lines.append("### 정렬 · 드리프트")
    lines.append("")
    drift_all = []
    for i, members in enumerate(clusters, 1):
        dom, hit = overview_dominant_label(members, label_of)
        charted = [m for m in members if m in label_of]
        if dom is None:
            lines.append("- 클러스터 %d (%d장): overview 라벨 없음 (전원 미수록)"
                         % (i, len(members)))
            continue
        title = titles.get(dom, "")
        lines.append("- 클러스터 %d (%d장) ↔ overview %s. %s — 겹침 %d/%d"
                     % (i, len(members), dom, title, hit, len(charted)))
        for m in members:
            lab = label_of.get(m)
            if lab is not None and lab != dom:
                drift_all.append((m, lab, dom, i))
    lines.append("")

    # Split drift into genuine reclassification candidates vs expected
    # super-cluster merge noise. A drift is genuine only when the page's label
    # is concentrated (clear home) AND the page left that home cluster.
    genuine, expected = [], []
    for m, lab, dom, i in sorted(drift_all):
        home_i, frac = label_home.get(lab, (i, 1.0))
        if frac < LABEL_HOME_CUTOFF:
            expected.append((m, lab, dom, i,
                             "라벨 %s 분산(홈집중 %.0f%%) — 슈퍼클러스터 병합"
                             % (lab, frac * 100)))
        elif i == home_i:
            expected.append((m, lab, dom, i,
                             "라벨 %s의 홈 클러스터 (지배 라벨만 %s로 다름)"
                             % (lab, dom)))
        else:
            genuine.append((m, lab, dom, i))

    lines.append("### 드리프트 — 진짜 재분류 후보")
    lines.append("")
    lines.append("집중된(홈 뚜렷한) overview 라벨의 페이지가 자기 홈을 떠나 다른 "
                 "클러스터에 안착 — 개별 재분류를 검토할 가치가 있는 신호.")
    lines.append("")
    if genuine:
        for m, lab, dom, i in genuine:
            lines.append("- [[%s]] — overview=%s 인데 클러스터 %d(주로 %s)에 묶임"
                         % (m, lab, i, dom))
    else:
        lines.append("없음 — 집중 라벨에서 홈을 벗어난 페이지 없음.")
    lines.append("")

    lines.append("### 드리프트 — 슈퍼클러스터 병합 (예상 노이즈, 억제)")
    lines.append("")
    lines.append("자동화(Louvain)가 손분할한 슈퍼클러스터를 재병합해 생기는 예상된 "
                 "드리프트. 재분류 신호 아님 — 참고용.")
    lines.append("")
    if expected:
        for m, lab, dom, i, why in expected:
            lines.append("- [[%s]] — overview=%s → 클러스터 %d(주로 %s): %s"
                         % (m, lab, i, dom, why))
    else:
        lines.append("없음.")
    lines.append("")

    # 3. uncharted / 4. stale
    present = set(slugs)
    overview_slugs = set(label_of)
    uncharted = sorted(present - overview_slugs)
    stale = sorted(overview_slugs - present)

    lines.append("### overview 미수록 (신규 — overview 갱신 대상)")
    lines.append("")
    if uncharted:
        for s in uncharted:
            lines.append("- [[%s]]" % s)
    else:
        lines.append("없음 — 모든 콘텐츠 페이지가 overview에 수록됨.")
    lines.append("")

    lines.append("### overview stale 참조 (실제 페이지 없음 — overview 정리 대상)")
    lines.append("")
    if stale:
        for s in stale:
            lines.append("- [[%s]]" % s)
    else:
        lines.append("없음 — overview 멤버십이 전부 실제 페이지와 일치.")
    lines.append("")
    return lines


# --- report ------------------------------------------------------------------
def build_report(pages, slugs, edges, signals, membership, label_of, titles):
    clusters = cluster_members(slugs, membership)
    q = modularity(slugs, edges, membership)
    orphans = classify_orphans(slugs, signals)

    lines = []
    lines.append("# _cluster_report - wiki graph analysis (auto-generated)")
    lines.append("")
    lines.append("생성: %s | 페이지 %d장 | 엣지 %d개 | 클러스터 %d개 | 모듈러리티 Q=%.3f"
                 % (datetime.now().strftime("%Y-%m-%d %H:%M"),
                    len(slugs), len(edges), len(clusters), q))
    lines.append("")
    lines.append("> 읽기 전용 자동 리포트(wiki_cluster.py 산출). 재분류 반영은 사람이 판단.")
    lines.append("> 클러스터 신호(관계 3신호): 직접링크 x3.0 / 자료중복 x4.0 / Adamic-Adar x1.5. 타입은 서술자(엣지 제외).")
    lines.append("")

    m_total = sum(edges.values())
    lines.append("## 클러스터 (%d개)" % len(clusters))
    lines.append("")
    sparse = []
    for i, members in enumerate(clusters, 1):
        coh, internal, external = cluster_cohesion(members, edges, membership)
        contrib = cluster_modularity(internal, external, m_total)
        dtype = dominant_type(members, pages)
        lines.append("### 클러스터 %d — 지배 타입: %s (%d장, 응집도 %.2f, Q기여 %+.3f)"
                     % (i, dtype, len(members), coh, contrib))
        for mslug in members:
            lines.append("- [[%s]] (%s)" % (mslug, pages[mslug]["type"] or "?"))
        lines.append("")
        if len(members) == 1 or contrib < 0:
            sparse.append((i, members, coh, internal, external, contrib))

    lines.append("## 고아 / 약결합")
    lines.append("")
    if orphans:
        lines.append("직접링크·자료중복 엣지가 0인 페이지 (억지 링크 금지 — 동료를 기다림):")
        for slug, reason in sorted(orphans):
            lines.append("- [[%s]] — %s" % (slug, reason))
    else:
        lines.append("없음 — 모든 페이지가 링크 또는 자료중복으로 결합됨.")
    lines.append("")

    lines.append("## 희박 영역 (재분류 후보)")
    lines.append("")
    lines.append("판정: 클러스터 modularity 기여 < 0 (랜덤 배치보다 내부 결합이 약함). "
                 "밀집 그래프에서 응집도 절대값이 과민한 문제를 피해 자기정규화된 기준.")
    lines.append("")
    if sparse:
        for i, members, coh, internal, external, contrib in sparse:
            note = "단독 클러스터" if len(members) == 1 else "Q기여 음수(랜덤 이하)"
            lines.append("- 클러스터 %d (%d장): Q기여 %+.3f, 응집도 %.2f, 내부 %.1f / 외부 %.1f — %s"
                         % (i, len(members), contrib, coh, internal, external, note))
    else:
        lines.append("없음 — 모든 클러스터 modularity 기여 > 0 (랜덤 대비 양호).")
    lines.append("")

    lines.extend(build_overview_diff(clusters, slugs, label_of, titles))

    lines.append("---")
    lines.append("※ v2 범위: 클러스터·고아·응집도 + overview.md 대조(정렬·드리프트·미수록·stale). "
                 "재분류 반영은 사람이 판단.")
    lines.append("")
    return "\n".join(lines)


def main():
    wiki_dir = sys.argv[1] if len(sys.argv) > 1 else WIKI_DIR
    if not os.path.isdir(wiki_dir):
        sys.stderr.write("wiki dir not found: %s\n" % wiki_dir)
        return 1
    pages = parse_pages(wiki_dir)
    if not pages:
        sys.stderr.write("no content pages found in %s\n" % wiki_dir)
        return 1
    slugs, edges, signals = build_graph(pages)
    membership = louvain(slugs, edges)
    label_of, titles = parse_overview(wiki_dir)
    report = build_report(pages, slugs, edges, signals, membership,
                          label_of, titles)

    out_path = os.path.join(wiki_dir, REPORT_NAME)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(report)
    n_clusters = len(set(membership.values()))
    sys.stdout.write("wrote %s: %d pages, %d edges, %d clusters\n"
                     % (out_path, len(slugs), len(edges), n_clusters))
    return 0


if __name__ == "__main__":
    sys.exit(main())
