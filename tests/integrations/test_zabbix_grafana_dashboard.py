import base64
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "grafana" / "dashboards" / "zabbix-infrastructure.json"


EXPECTED_POSITIONS = {
    "2": [860, 610],
    "3": [1140, 610],
    "4": [1000, 700],
    "5": [1000, 900],
    "6": [1160, 780],
    "7": [860, 1080],
    "8": [1030, 1100],
    "9": [1280, 900],
    "10": [900, 170],
    "11": [720, 760],
    "12": [720, 1000],
    "13": [1100, 170],
    "14": [1580, 350],
    "15": [1440, 310],
    "16": [1830, 820],
    "17": [1700, 760],
    "18": [1630, 1360],
    "19": [1500, 1310],
    "20": [480, 315],
    "21": [360, 240],
    "22": [350, 400],
    "23": [510, 415],
    "24": [300, 830],
    "25": [230, 730],
    "26": [230, 930],
    "27": [420, 1340],
    "28": [930, 1570],
    "29": [1080, 1630],
}

EXPECTED_LINKS = [
    ("4", "2"),
    ("3", "4"),
    ("5", "4"),
    ("4", "6"),
    ("5", "8"),
    ("5", "7"),
    ("12", "5"),
    ("12", "6"),
    ("5", "11"),
    ("5", "9"),
    ("10", "9"),
    ("10", "13"),
    ("15", "9"),
    ("15", "14"),
    ("9", "17"),
    ("17", "16"),
    ("19", "9"),
    ("18", "19"),
    ("11", "21"),
    ("20", "21"),
    ("22", "20"),
    ("25", "20"),
    ("25", "24"),
    ("26", "24"),
    ("23", "22"),
    ("27", "12"),
    ("29", "28"),
    ("9", "28"),
]

EXPECTED_GRID = {
    13: {"x": 0, "y": 4, "w": 24, "h": 39},
    7: {"x": 0, "y": 43, "w": 8, "h": 8},
    8: {"x": 8, "y": 43, "w": 8, "h": 8},
    9: {"x": 16, "y": 43, "w": 8, "h": 8},
    11: {"x": 0, "y": 51, "w": 24, "h": 5},
    16: {"x": 0, "y": 56, "w": 12, "h": 8},
    17: {"x": 12, "y": 56, "w": 12, "h": 8},
}


def _dashboard() -> dict:
    return json.loads(DASHBOARD.read_text(encoding="utf-8"))


def _topology_panel() -> dict:
    dashboard = _dashboard()
    return next(panel for panel in dashboard["panels"] if panel.get("id") == 13)


def test_zabbix_topology_uses_admin_centered_radial_layout() -> None:
    dashboard = _dashboard()
    panels = {panel["id"]: panel for panel in dashboard["panels"]}

    for panel_id, grid_pos in EXPECTED_GRID.items():
        assert panels[panel_id]["gridPos"] == grid_pos

    panel = panels[13]
    weathermap = panel["options"]["weathermap"]
    assert panel["type"] == "tamirsuliman-weathermap-panel"
    assert weathermap["settings"]["panel"]["panelSize"] == {"height": 1800, "width": 2000}

    background = weathermap["settings"]["panel"]["backgroundImage"]
    assert background["fit"] == "contain"
    assert background["attachToCanvas"] is True
    assert background["url"].startswith("data:image/svg+xml;base64,")

    svg = base64.b64decode(background["url"].split(",", 1)[1]).decode("utf-8")
    for label in [
        "ADMIN",
        "PH1",
        "PH2",
        "COOP C",
        "HSF",
        "TOWER 2 / TOURIST CENTER",
        "LANIKAI",
        "WAREHOUSE",
        "STAFFHOUSE",
    ]:
        assert label in svg
    assert 'width="2000" height="1800"' in svg
    assert "<ellipse" not in svg
    assert 'id="site-ring"' not in svg
    assert 'id="admin-zone" x="640" y="520" width="720" height="660" stroke-width="8"' in svg
    assert 'id="ph1-zone" x="760" y="60" width="480" height="240"' in svg
    assert 'id="ph2-zone" x="1280" y="180" width="440" height="280"' in svg
    assert 'id="coop-c-zone" x="1540" y="650" width="440" height="260"' in svg
    assert 'id="hsf-zone" x="1370" y="1210" width="420" height="240"' in svg
    assert 'id="staffhouse-zone" x="800" y="1490" width="400" height="230"' in svg
    assert 'id="warehouse-zone" x="240" y="1230" width="360" height="240"' in svg
    assert 'id="lanikai-zone" x="80" y="660" width="420" height="340"' in svg
    assert 'id="tower-tourist-zone" x="140" y="150" width="520" height="320"' in svg

    nodes = {node["id"]: node for node in weathermap["nodes"]}
    assert set(nodes) == set(EXPECTED_POSITIONS)
    assert {node_id: node["position"] for node_id, node in nodes.items()} == EXPECTED_POSITIONS
    assert nodes["27"]["label"] == "warehouse_switch"
    assert nodes["27"]["nodeIcon"]["name"] == "networking/switch"
    assert nodes["28"]["label"] == "staffhouse_p2p"
    assert nodes["28"]["nodeIcon"]["name"] == "networking/radio-tower"
    assert nodes["29"]["label"] == "staffhouse_switch"
    assert nodes["29"]["nodeIcon"]["name"] == "networking/switch"


def test_zabbix_reconstructed_layout_preserves_live_topology_graph() -> None:
    panel = _topology_panel()
    weathermap = panel["options"]["weathermap"]

    links = [tuple(endpoint["id"] for endpoint in link["nodes"]) for link in weathermap["links"]]
    assert links == EXPECTED_LINKS
    assert len(weathermap["links"]) == 28
    assert [link["statusQuery"] for link in weathermap["links"]] == [
        *(f"edge_{index}_up" for index in range(1, 10)),
        *(f"edge_{index}_up" for index in range(11, 30)),
    ]
    assert all(link["stroke"] == 5 for link in weathermap["links"])
    radial_links = {link["id"]: link for link in weathermap["links"]}
    assert "waypoints" not in radial_links["edge-27"]
    assert "waypoints" not in radial_links["edge-29"]

    nodes = {node["id"]: node for node in weathermap["nodes"]}
    assert all(node["statusQuery"] == f"node_{node_id}_status" for node_id, node in nodes.items())

    target = panel["targets"][0]
    selectors = {column["selector"] for column in target["columns"]}
    for node_id in ("27", "28", "29"):
        assert f"node_{node_id}_status" in selectors
        assert f"node_{node_id}_problems" in selectors
    for edge_id in ("27", "28", "29"):
        assert f"edge_{edge_id}_up" in selectors
    assert "$n27 := $nodes[node_id='27'][0]" in target["root_selector"]
    assert "$n28 := $nodes[node_id='28'][0]" in target["root_selector"]
    assert "$n29 := $nodes[node_id='29'][0]" in target["root_selector"]
