import networkx as nx
import pandas as pd
import pytest

from enforcement_toolkit.detection import run_detection
from enforcement_toolkit.graph import GraphConfig, run_graph, write_graph_report
from enforcement_toolkit.graph.build import build_graph, describe_path, social_view
from enforcement_toolkit.validation import run_validation
from enforcement_toolkit.validation.sample_data import make_sample_data


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    paths = make_sample_data(tmp_path_factory.mktemp("data"))
    frames = run_validation(paths).frames()
    return run_graph(frames, run_detection(frames))


def status(result, account):
    return result.accounts.set_index("account_id").loc[account]


def test_tipping_chains_found(result):
    kevin = status(result, "ACC-1043")
    assert kevin["status"] == "Linked to insider" and kevin["linked_insider"] == "Dana Whitfield"
    assert kevin["hops"] == 2  # account -> Kevin -> Dana
    assert "spouse of" in kevin["connection"] and "KYC" in kevin["evidence"]
    assert status(result, "ACC-2210")["linked_insider"] == "Marc Olsen"
    assert status(result, "ACC-3307")["linked_insider"] == "Leo Tremblay"


def test_unlinked_and_contrary_trades(result):
    assert status(result, "ACC-5150")["status"] == "No known link"
    assert status(result, "ACC-6020")["status"] == "Traded against the news"
    assert "ACC-7781" not in set(result.accounts["account_id"])  # traded months before: out of window


def test_insiders_linked_through_shared_board(result):
    links = result.insider_links
    row = links[(links["insider_a"] == "Dana Whitfield") & (links["insider_b"] == "Marc Olsen")].iloc[0]
    assert "Pinecrest Capital" in row["connection"]


def test_unsourced_relationship_is_rejected(result):
    # "Sam Reid friend_of Marc Olsen" has no evidence_source, so Module 1 quarantines it
    assert not result.graph.has_edge("person:Sam Reid", "person:Marc Olsen")


def test_company_is_not_a_connection():
    frames = {
        "insider_trades": pd.DataFrame(
            {"insider_name": ["A", "B"], "insider_role": ["CEO", "CFO"], "ticker": ["XYZ", "XYZ"]}
        ),  # fmt: skip
        "account_trades": pd.DataFrame(),
        "relationships": pd.DataFrame(),
    }
    g = build_graph(frames)
    assert nx.has_path(g, "person:A", "person:B")  # via the company node...
    assert not nx.has_path(social_view(g), "person:A", "person:B")  # ...which doesn't count as a link


def test_path_text_keeps_direction():
    g = nx.Graph()
    g.add_edge("person:Marc", "entity:Trust", relation="trustee_of", src="person:Marc", evidence="x")
    assert describe_path(g, ["entity:Trust", "person:Marc"]) == "Trust ←[trustee of]— Marc"
    assert describe_path(g, ["person:Marc", "entity:Trust"]) == "Marc —[trustee of]→ Trust"


def test_outputs_written(result, tmp_path):
    write_graph_report(result, tmp_path)
    assert (tmp_path / "graph.graphml").exists()
    assert (tmp_path / "charts" / "E001_network.png").exists()
    text = (tmp_path / "network_report.md").read_text()
    assert "Kevin Whitfield" in text and "not proof" in text


def test_max_hops_respected(tmp_path):
    paths = make_sample_data(tmp_path)
    frames = run_validation(paths).frames()
    res = run_graph(frames, run_detection(frames), GraphConfig(max_hops=1))
    assert (res.accounts["status"] == "Linked to insider").sum() == 0  # every chain needs 2 links
