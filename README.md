# Flight Hop Graph

Compute the minimum number of connecting flights from any airport to all others, and visualize on a **world map** as a color-coded graph.

Uses [OpenFlights](https://openflights.org/) route data. Each edge represents a direct flight; the shortest path (BFS) gives the hop count.

**Default**: Shows only **national capital airports** (plus source) on an actual world map.

## Quick start

```bash
# Create virtual env and install
python3 -m venv .venv
source .venv/bin/activate  # or: .venv\Scripts\activate on Windows
pip install -r requirements.txt

# Run from SFO: capitals only on world map
python flight_hops.py

# Show all reachable airports instead of just capitals
python flight_hops.py --all-airports

# Run from another airport
python flight_hops.py --source LAX --output lax_graph.png

# Simple plot without map background (if cartopy has issues)
python flight_hops.py --no-map
```

## Options

| Flag | Description |
|------|-------------|
| `--source`, `-s` | Source airport IATA code (default: SFO) |
| `--output`, `-o` | Output image path (default: flight_hops_graph.png) |
| `--all-airports` | Show all reachable airports (default: capitals only) |
| `--no-map` | Skip world map background |
| `--max-airports` | Max airports when using --all-airports (default: 500) |
| `--list` | Print hop counts to stdout |

## Output

- **Terminal**: Summary of reachable airports by hop count; with capitals mode, shows reachable national capitals
- **Graph**: World map with airports color-coded by minimum connecting flights (purple = farther, yellow = closer). Source airport is highlighted with a red star.

## Example (SFO, capitals only)

From San Francisco:
- **176 national capitals** reachable
- Direct flights (1 hop) to capitals like Tokyo (HND), London (LHR), Mexico City (MEX)
- Farthest capitals within 5–6 hops

Data is cached in `data/` after first run.
