import base64
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "grafana" / "dashboards" / "zabbix-infrastructure.json"


EXPECTED_POSITIONS = {
    "2": [650, 560],
    "3": [900, 560],
    "4": [800, 720],
    "5": [1050, 800],
    "6": [700, 940],
    "7": [1100, 1040],
    "8": [1300, 1040],
    "9": [1350, 590],
    "10": [650, 160],
    "11": [1100, 560],
    "12": [900, 1160],
    "13": [850, 160],
    "14": [1350, 160],
    "15": [1150, 160],
    "16": [1900, 570],
    "17": [1700, 570],
    "18": [1900, 1020],
    "19": [1700, 1020],
    "20": [100, 220],
    "21": [350, 220],
    "22": [100, 100],
    "23": [350, 100],
    "24": [260, 1010],
    "25": [120, 900],
    "26": [120, 1120],
    "27": [590, 1620],
    "28": [1260, 1620],
    "29": [1540, 1620],
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


def test_zabbix_topology_uses_clean_grouped_network_layout() -> None:
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
    assert 'id="admin-zone" x="475" y="410" width="1050" height="970" stroke-width="8"' in svg
    assert 'id="tower-tourist-zone" x="20" y="20" width="430" height="270"' in svg
    assert 'id="ph1-zone" x="570" y="20" width="360" height="270"' in svg
    assert 'id="ph2-zone" x="1070" y="20" width="360" height="270"' in svg
    assert 'id="coop-c-zone" x="1645" y="410" width="335" height="330"' in svg
    assert 'id="hsf-zone" x="1645" y="860" width="335" height="330"' in svg
    assert 'id="staffhouse-zone" x="1110" y="1500" width="600" height="280"' in svg
    assert 'id="warehouse-zone" x="290" y="1500" width="600" height="280"' in svg
    assert 'id="lanikai-zone" x="20" y="810" width="335" height="400"' in svg
    assert '<text x="1000" y="455" font-size="40">ADMIN</text>' in svg
    assert '<text x="750" y="60" font-size="28">PH1</text>' in svg
    assert '<text x="1250" y="60" font-size="28">PH2</text>' in svg
    assert '<text x="1812" y="455" font-size="28">COOP C</text>' in svg
    assert '<text x="1812" y="905" font-size="28">HSF</text>' in svg
    assert '<text x="1410" y="1545" font-size="28">STAFFHOUSE</text>' in svg
    assert '<text x="590" y="1545" font-size="28">WAREHOUSE</text>' in svg
    assert '<text x="187" y="855" font-size="28">LANIKAI</text>' in svg
    assert '<text x="235" y="60" font-size="26">TOWER 2 / TOURIST CENTER</text>' in svg

    nodes = {node["id"]: node for node in weathermap["nodes"]}
    assert set(nodes) == set(EXPECTED_POSITIONS)
    assert {node_id: node["position"] for node_id, node in nodes.items()} == EXPECTED_POSITIONS
    assert nodes["3"]["label"] == "DC TECH"
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
    expected_waypoints = {
        "edge-12": [{"x": 650, "y": 350}, {"x": 1300, "y": 350}, {"x": 1300, "y": 590}],
        "edge-14": [{"x": 1150, "y": 320}, {"x": 1350, "y": 320}],
        "edge-16": [{"x": 1580, "y": 590}, {"x": 1580, "y": 570}],
        "edge-18": [{"x": 1580, "y": 1020}, {"x": 1580, "y": 590}],
        "edge-20": [{"x": 1100, "y": 380}, {"x": 500, "y": 380}, {"x": 500, "y": 220}],
        "edge-23": [{"x": 80, "y": 900}, {"x": 80, "y": 350}, {"x": 100, "y": 350}],
        "edge-27": [{"x": 590, "y": 1440}, {"x": 900, "y": 1440}],
        "edge-29": [
            {"x": 1580, "y": 590},
            {"x": 1550, "y": 640},
            {"x": 1550, "y": 1440},
            {"x": 1260, "y": 1440},
        ],
    }
    assert {link_id for link_id, link in radial_links.items() if "waypoints" in link} == set(
        expected_waypoints
    )
    for link_id, waypoints in expected_waypoints.items():
        assert radial_links[link_id]["waypoints"] == waypoints

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
