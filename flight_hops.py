#!/usr/bin/env python3
"""
Compute shortest-path hops from an airport to all others and visualize
with a color-coded graph. Uses OpenFlights route data.
"""

import collections
import csv
import io
import json
import re
import ssl
import sys
from typing import Optional, Set
import urllib.request
from pathlib import Path

import matplotlib
if "--show" not in sys.argv:
    matplotlib.use("Agg")  # Non-interactive backend when saving to file
import matplotlib.pyplot as plt
import networkx as nx

ROUTES_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat"
AIRPORTS_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"
CAPITALS_URL = "https://raw.githubusercontent.com/icyrockcom/country-capitals/master/data/country-list.json"
DATA_DIR = Path(__file__).resolve().parent / "data"

# Manual overrides: capital city name variants and known capital airport codes
# (OpenFlights city may differ from official capital name)
CAPITAL_OVERRIDES = {
    ("Sri Lanka", "Colombo"),   # Commercial capital / main airport
    ("United States", "Washington"),
    ("China", "Beijing"),
    ("Republic of China (Taiwan)", "Taipei"),
    ("South Africa", "Pretoria"),
    ("Bolivia", "La Paz"),      # Administrative capital with main airport
    ("Netherlands", "Amsterdam"),
    ("United Kingdom; England", "London"),
    ("Switzerland", "Bern"),
    ("Japan", "Tokyo"),
    ("South Korea", "Seoul"),
    ("India", "New Delhi"),
    ("Vietnam", "Hanoi"),
    ("Turkey", "Ankara"),
    ("United Arab Emirates", "Abu Dhabi"),
    ("Kazakhstan", "Nur-Sultan"),  # Former Astana
    ("Kazakhstan", "Astana"),
    ("Myanmar", "Naypyidaw"),
    ("Myanmar", "Yangon"),  # Main airport
    ("Ivory Coast", "Abidjan"),   # Main airport not in Yamoussoukro
    ("Côte d'Ivoire", "Abidjan"),
    ("Australia", "Canberra"),
    ("New Zealand", "Wellington"),
}


def _fetch(url: str) -> str:
    """Fetch URL content, using SSL context that works on macOS."""
    ctx = ssl.create_default_context()
    try:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    except Exception:
        pass
    req = urllib.request.Request(url, headers={"User-Agent": "flight-graph/1.0"})
    with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
        return resp.read().decode("utf-8", errors="replace")


def load_routes() -> set[tuple[str, str]]:
    """Load flight routes from OpenFlights. Returns set of (origin, dest) IATA pairs."""
    local = DATA_DIR / "routes.dat"
    if local.exists():
        print("Using cached routes data...")
        content = local.read_text(encoding="utf-8", errors="replace")
    else:
        print("Downloading routes data...")
        content = _fetch(ROUTES_URL)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        local.write_text(content, encoding="utf-8")

    routes = set()
    for line in csv.reader(io.StringIO(content)):
        if len(line) >= 6:
            origin, dest = line[2].strip(), line[4].strip()
            if origin and dest and origin != "\\N" and dest != "\\N" and len(origin) == 3 and len(dest) == 3:
                routes.add((origin.upper(), dest.upper()))
    return routes


def _norm(s: str) -> str:
    """Normalize for matching: lowercase, strip, remove accents-ish."""
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r",?\s*d\.?c\.?", "", s)  # Washington, D.C. -> washington
    s = re.sub(r"\s+", " ", s)
    return s


def load_airports() -> dict[str, dict]:
    """Load airport info: IATA -> {name, lat, lon, city, country}."""
    local = DATA_DIR / "airports.dat"
    if local.exists():
        print("Using cached airports data...")
        content = local.read_text(encoding="utf-8", errors="replace")
    else:
        print("Downloading airports data...")
        content = _fetch(AIRPORTS_URL)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        local.write_text(content, encoding="utf-8")

    airports = {}
    for line in csv.reader(io.StringIO(content)):
        if len(line) >= 8:
            iata = line[4].strip().upper() if line[4] != "\\N" else None
            if iata and len(iata) == 3:
                try:
                    airports[iata] = {
                        "name": line[1],
                        "lat": float(line[6]),
                        "lon": float(line[7]),
                        "city": line[2].strip() if len(line) > 2 else "",
                        "country": line[3].strip() if len(line) > 3 else "",
                    }
                except (ValueError, IndexError):
                    pass
    return airports


def load_capital_airports(airports: dict[str, dict]) -> set[str]:
    """Return set of IATA codes for airports in national capitals."""
    local = DATA_DIR / "country-list.json"
    if local.exists():
        content = local.read_text(encoding="utf-8", errors="replace")
    else:
        print("Downloading capitals data...")
        content = _fetch(CAPITALS_URL)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        local.write_text(content, encoding="utf-8")

    capitals_data = json.loads(content)
    capital_pairs: set[tuple[str, str]] = set()
    for row in capitals_data:
        country = row.get("country", "")
        capital = row.get("capital", "")
        if country and capital:
            capital_pairs.add((_norm(country), _norm(capital)))
            if ";" in country:
                # "United Kingdom; England" -> also add "United Kingdom"
                base = country.split(";")[0].strip()
                capital_pairs.add((_norm(base), _norm(capital)))
    for country, city in CAPITAL_OVERRIDES:
        capital_pairs.add((_norm(country), _norm(city)))

    result = set()
    for iata, info in airports.items():
        city = info.get("city", "")
        country = info.get("country", "")
        if (_norm(country), _norm(city)) in capital_pairs:
            result.add(iata)
        # Also match if airport city contains capital (e.g. "Port of Spain" in city)
        for (c_norm, cap_norm) in capital_pairs:
            if c_norm == _norm(country) and cap_norm in _norm(city):
                result.add(iata)
                break
    return result


def build_graph(routes: set[tuple[str, str]]) -> nx.DiGraph:
    """Build directed graph from routes (unweighted; each edge = 1 hop)."""
    G = nx.DiGraph()
    for origin, dest in routes:
        G.add_edge(origin, dest)
    return G


def shortest_path_hops(G: nx.DiGraph, source: str) -> dict[str, int]:
    """
    BFS from source to compute shortest hop count to every reachable airport.
    Returns dict: airport_iata -> min number of flights (0 = source itself).
    """
    hops = {source: 0}
    queue = collections.deque([source])
    while queue:
        node = queue.popleft()
        for neighbor in G.neighbors(node):
            if neighbor not in hops:
                hops[neighbor] = hops[node] + 1
                queue.append(neighbor)
    return hops


def plot_hop_graph(
    G: nx.DiGraph,
    airports: dict[str, dict],
    hop_dist: dict[str, int],
    source: str,
    output_path: str = "flight_hops_graph.png",
    max_airports: int = 500,
    capitals_only: bool = False,
    show: bool = False,
    capital_airports: Optional[Set[str]] = None,
    use_world_map: bool = True,
) -> None:
    """
    Draw a color-coded graph of airports by shortest-path hop count.
    Uses lat/lon for layout; colors by hop distance.
    """
    reachable = set(hop_dist.keys())
    if capitals_only and capital_airports:
        reachable = {source} | (reachable & capital_airports)
    elif len(reachable) > max_airports:
        sorted_by_hops = sorted(hop_dist.items(), key=lambda x: (x[1], x[0]))
        keep = {a for a, _ in sorted_by_hops[:max_airports]}
        reachable = keep

    nodes = [n for n in reachable if n in G and n in airports]
    sub = G.subgraph(nodes).copy()
    sub_undirected = sub.to_undirected()

    pos = {}
    for node in sub_undirected.nodes():
        if node in airports:
            a = airports[node]
            pos[node] = (a["lon"], a["lat"])

    # Use max from displayed nodes so colors reflect actual range (e.g. capitals 0–3)
    displayed_hops = [hop_dist.get(n, 0) for n in sub_undirected.nodes()]
    max_hops = max(displayed_hops) if displayed_hops else 1
    cmap = plt.cm.viridis
    node_colors = []
    for node in sub_undirected.nodes():
        h = hop_dist.get(node, -1)
        if h < 0:
            node_colors.append((0.5, 0.5, 0.5, 0.5))
        else:
            norm = h / max(max_hops, 1)
            node_colors.append(cmap(norm))

    # Use cartopy for world map background
    proj = None
    if use_world_map:
        try:
            # Patch SSL for systems with cert verification issues (e.g. macOS Python)
            _orig_urlopen = urllib.request.urlopen
            _ssl_ctx = ssl.create_default_context()
            _ssl_ctx.check_hostname = False
            _ssl_ctx.verify_mode = ssl.CERT_NONE
            def _patched_urlopen(*a, **k):
                k.setdefault("context", _ssl_ctx)
                return _orig_urlopen(*a, **k)
            urllib.request.urlopen = _patched_urlopen
            import cartopy.crs as ccrs
            import cartopy.feature as cfeature
            proj = ccrs.PlateCarree()
            fig = plt.figure(figsize=(18, 10))
            ax = fig.add_subplot(1, 1, 1, projection=proj)
            ax.set_global()
            ax.add_feature(cfeature.LAND, facecolor="#f0f0e8")
            ax.add_feature(cfeature.OCEAN, facecolor="#e8f4fc")
            ax.add_feature(cfeature.COASTLINE, linewidth=0.5, edgecolor="#666")
            ax.add_feature(cfeature.BORDERS, linestyle=":", linewidth=0.3, edgecolor="#999")
        except (ImportError, Exception) as e:
            print(f"Note: World map unavailable ({e}), using simple background")
            use_world_map = False
            proj = None
            fig, ax = plt.subplots(figsize=(16, 10))
    if not use_world_map:
        fig, ax = plt.subplots(figsize=(16, 10))

    lons = [pos[n][0] for n in sub_undirected.nodes()]
    lats = [pos[n][1] for n in sub_undirected.nodes()]
    ax.scatter(lons, lats, c=node_colors, s=40 if capitals_only else 15, zorder=4, transform=proj)

    for u, v in sub_undirected.edges():
        lon_u, lat_u = pos[u]
        lon_v, lat_v = pos[v]
        ax.plot([lon_u, lon_v], [lat_u, lat_v], "gray", alpha=0.2, linewidth=0.5, transform=proj)

    label_nodes = {source}
    for n in list(hop_dist.keys())[:30]:
        if n in sub_undirected and n in airports:
            label_nodes.add(n)
    if capitals_only:
        label_nodes = {n for n in sub_undirected.nodes()}
    labels = {n: n for n in label_nodes if n in pos}
    for n, (lon, lat) in pos.items():
        if n in labels:
            ax.text(lon, lat, f" {n}", fontsize=7, fontweight="bold", transform=proj)

    if source in pos:
        lon_s, lat_s = pos[source]
        ax.scatter([lon_s], [lat_s], s=250, c="red", marker="*", zorder=5, label=f"Source: {source}", transform=proj)

    if use_world_map:
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=0, vmax=max_hops))
        sm.set_array([])
        cbar = plt.colorbar(sm, ax=ax, shrink=0.5, pad=0.02)
    else:
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=0, vmax=max_hops))
        sm.set_array([])
        cbar = plt.colorbar(sm, ax=ax, shrink=0.6)
    cbar.set_label("Shortest-path hops from source", fontsize=12)

    title = f"Airport connectivity from {source}"
    if capitals_only:
        title += " (national capitals only)"
    title += ": color = minimum connecting flights"
    ax.set_title(title, fontsize=14)
    ax.legend(loc="upper left")
    plt.tight_layout()
    if show:
        plt.show()
    else:
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"Saved: {output_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Flight hop analysis from an airport")
    parser.add_argument(
        "--source", "-s", default="SFO", help="Source airport IATA code (default: SFO)"
    )
    parser.add_argument(
        "--output", "-o", default="flight_hops_graph.png", help="Output image path"
    )
    parser.add_argument(
        "--max-airports", type=int, default=500,
        help="Max airports to show on graph (default: 500)",
    )
    parser.add_argument(
        "--all-airports", action="store_true",
        help="Show all reachable airports (default: capitals only)",
    )
    parser.add_argument(
        "--no-map", action="store_true", help="Skip world map background",
    )
    parser.add_argument(
        "--show", action="store_true", help="Display plot with plt.show() instead of saving",
    )
    parser.add_argument("--list", action="store_true", help="Print hop counts to stdout")
    args = parser.parse_args()
    source = args.source.upper()

    routes = load_routes()
    airports = load_airports()
    G = build_graph(routes)

    if source not in G:
        print(f"Airport {source} not found in route data.")
        candidates = [a for a in airports if a in G][:20]
        print(f"Available airports include: {', '.join(candidates)}")
        return 1

    hop_dist = shortest_path_hops(G, source)
    print(f"\nFrom {source}: reachable airports = {len(hop_dist)}")

    capitals_only = not args.all_airports
    capital_airports = None
    if capitals_only:
        capital_airports = load_capital_airports(airports)
        reachable_capitals = {a for a in hop_dist if a in capital_airports or a == source}
        print(f"  Reachable national capitals: {len(reachable_capitals)}")

    by_hops = collections.defaultdict(list)
    for a, h in hop_dist.items():
        by_hops[h].append(a)
    for h in sorted(by_hops.keys()):
        print(f"  {h} hop(s): {len(by_hops[h])} airports")

    if args.list:
        print("\nHop counts (sample):")
        items = sorted(hop_dist.items(), key=lambda x: (x[1], x[0]))
        if capitals_only and capital_airports:
            items = [(a, h) for a, h in items if a in capital_airports or a == source]
        for a, h in items[:50]:
            name = airports.get(a, {}).get("name", "")[:40]
            print(f"  {a}: {h} hops - {name}")

    plot_hop_graph(
        G, airports, hop_dist, source, args.output, args.max_airports,
        capitals_only=capitals_only,
        capital_airports=capital_airports,
        use_world_map=not args.no_map,
        show=args.show,
    )
    return 0


if __name__ == "__main__":
    exit(main())
