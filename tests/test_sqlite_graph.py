"""Tests for SqliteGraphAdapter."""

from __future__ import annotations

import sqlite3

import pytest

from codelattice.graph.sqlite_graph import SqliteGraphAdapter


class FakeDataPoint:
    """Minimal DataPoint-like object for testing."""

    def __init__(self, id: str, name: str, type: str, **kwargs):
        self._id = id
        self._name = name
        self._type = type
        self._extra = kwargs

    def model_dump(self):
        d = {"id": self._id, "name": self._name, "type": self._type}
        d.update(self._extra)
        return d


@pytest.fixture
def adapter(tmp_path):
    a = SqliteGraphAdapter(db_path=str(tmp_path / "test_graph.db"))
    yield a
    a.close()


@pytest.mark.asyncio
async def test_add_and_get_node(adapter):
    node = FakeDataPoint(
        id="node-1",
        name="my_func",
        type="CodeFunction",
        file_path="src/main.py",
        start_line=10,
        end_line=20,
        signature="def my_func(x: int) -> str",
    )
    await adapter.add_nodes([node])
    result = await adapter.get_node("node-1")
    assert result is not None
    assert result["name"] == "my_func"
    assert result["file_path"] == "src/main.py"
    assert result["start_line"] == 10
    assert result["signature"] == "def my_func(x: int) -> str"


@pytest.mark.asyncio
async def test_get_node_not_found(adapter):
    result = await adapter.get_node("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_upsert_node(adapter):
    node_v1 = FakeDataPoint(id="n1", name="old_name", type="CodeFunction")
    await adapter.add_nodes([node_v1])

    node_v2 = FakeDataPoint(id="n1", name="new_name", type="CodeFunction")
    await adapter.add_nodes([node_v2])

    result = await adapter.get_node("n1")
    assert result["name"] == "new_name"


@pytest.mark.asyncio
async def test_add_and_get_edges(adapter):
    n1 = FakeDataPoint(id="n1", name="file", type="CodeFile")
    n2 = FakeDataPoint(id="n2", name="func", type="CodeFunction")
    await adapter.add_nodes([n1, n2])

    await adapter.add_edges([("n1", "n2", "contains_symbols", {})])

    edges = await adapter.get_edges("n1")
    assert len(edges) == 1
    source, rel, target = edges[0]
    assert rel == "contains_symbols"
    assert source["id"] == "n1"
    assert target["id"] == "n2"

    # Also visible from the other direction
    edges2 = await adapter.get_edges("n2")
    assert len(edges2) == 1


@pytest.mark.asyncio
async def test_edge_upsert(adapter):
    n1 = FakeDataPoint(id="n1", name="a", type="X")
    n2 = FakeDataPoint(id="n2", name="b", type="Y")
    await adapter.add_nodes([n1, n2])

    await adapter.add_edges([("n1", "n2", "calls", {"weight": 1})])
    await adapter.add_edges([("n1", "n2", "calls", {"weight": 2})])

    edges = await adapter.get_edges("n1")
    assert len(edges) == 1  # Upserted, not duplicated


@pytest.mark.asyncio
async def test_batch_nodes(adapter):
    nodes = [
        FakeDataPoint(id=f"n{i}", name=f"func_{i}", type="CodeFunction")
        for i in range(100)
    ]
    await adapter.add_nodes(nodes)

    for i in range(100):
        result = await adapter.get_node(f"n{i}")
        assert result is not None
        assert result["name"] == f"func_{i}"


@pytest.mark.asyncio
async def test_empty_inputs(adapter):
    """add_nodes and add_edges should handle empty lists gracefully."""
    await adapter.add_nodes([])
    await adapter.add_edges([])
    result = await adapter.get_node("anything")
    assert result is None


@pytest.mark.asyncio
async def test_no_edges(adapter):
    """get_edges returns empty list when node has no edges."""
    n1 = FakeDataPoint(id="n1", name="lonely", type="CodeFunction")
    await adapter.add_nodes([n1])
    edges = await adapter.get_edges("n1")
    assert edges == []


@pytest.mark.asyncio
async def test_wal_mode(tmp_path):
    db_path = str(tmp_path / "wal_test.db")
    adapter = SqliteGraphAdapter(db_path=db_path)

    conn = sqlite3.connect(db_path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
    conn.close()
    adapter.close()


@pytest.mark.asyncio
async def test_concurrent_readers(tmp_path):
    """Multiple adapters can read the same DB concurrently."""
    db_path = str(tmp_path / "concurrent.db")

    writer = SqliteGraphAdapter(db_path=db_path)
    node = FakeDataPoint(id="n1", name="test", type="T")
    await writer.add_nodes([node])

    reader1 = SqliteGraphAdapter(db_path=db_path)
    reader2 = SqliteGraphAdapter(db_path=db_path)

    r1 = await reader1.get_node("n1")
    r2 = await reader2.get_node("n1")

    assert r1 is not None
    assert r2 is not None
    assert r1["name"] == "test"
    assert r2["name"] == "test"

    reader1.close()
    reader2.close()
    writer.close()


@pytest.mark.asyncio
async def test_multiple_edges_same_node(adapter):
    """A node can have edges to multiple targets."""
    nodes = [
        FakeDataPoint(id=f"n{i}", name=f"node_{i}", type="T")
        for i in range(4)
    ]
    await adapter.add_nodes(nodes)

    await adapter.add_edges([
        ("n0", "n1", "calls", {}),
        ("n0", "n2", "calls", {}),
        ("n3", "n0", "defined_in", {}),
    ])

    edges = await adapter.get_edges("n0")
    assert len(edges) == 3  # 2 outgoing + 1 incoming


@pytest.mark.asyncio
async def test_initialize_is_noop(adapter):
    """initialize() should succeed without error."""
    await adapter.initialize()
