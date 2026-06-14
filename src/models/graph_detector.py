"""
Graph-based anomaly detection utilities.

Builds a heterogeneous user interaction graph from processed event tables
and exposes per-user anomaly scores plus focused user subgraphs for the API.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple
import pandas as pd

try:
    import networkx as nx
except ImportError:  # pragma: no cover - fallback keeps the app usable until dependency install
    nx = None


@dataclass
class GraphMetric:
    user: str
    graph_score: float
    graph_connections_count: int
    centrality: float
    interaction_weight: float


class _SimpleGraph:
    """Small undirected graph fallback when networkx is not installed."""

    def __init__(self):
        self._nodes = {}
        self._adj = defaultdict(dict)

    def add_node(self, node_id, **attrs):
        self._nodes.setdefault(node_id, {}).update(attrs)

    def add_edge(self, source, target, **attrs):
        self.add_node(source)
        self.add_node(target)
        payload = self._adj[source].get(target, {}).copy()
        payload.update(attrs)
        self._adj[source][target] = payload
        self._adj[target][source] = payload

    def has_node(self, node_id):
        return node_id in self._nodes

    def neighbors(self, node_id):
        return list(self._adj.get(node_id, {}).keys())

    def degree(self, node_id):
        return len(self._adj.get(node_id, {}))

    def number_of_nodes(self):
        return len(self._nodes)

    def get_edge_data(self, source, target, default=None):
        return self._adj.get(source, {}).get(target, default)

    def nodes(self, data=False):
        return list(self._nodes.items()) if data else list(self._nodes.keys())

    def edges(self, data=False):
        seen = set()
        rows = []
        for source, neighbors in self._adj.items():
            for target, attrs in neighbors.items():
                key = tuple(sorted((source, target)))
                if key in seen:
                    continue
                seen.add(key)
                rows.append((source, target, attrs) if data else (source, target))
        return rows

    def subgraph(self, node_ids):
        subset = set(node_ids)
        g = _SimpleGraph()
        for node_id in subset:
            if node_id in self._nodes:
                g.add_node(node_id, **self._nodes[node_id])
        for source, target, attrs in self.edges(data=True):
            if source in subset and target in subset:
                g.add_edge(source, target, **attrs)
        return g


class GraphAnomalyDetector:
    def __init__(
        self,
        device_df: Optional[pd.DataFrame] = None,
        file_df: Optional[pd.DataFrame] = None,
        email_df: Optional[pd.DataFrame] = None,
        max_file_edges_per_user: int = 20,
        max_email_edges_per_user: int = 20,
    ):
        self.device_df = device_df.copy() if device_df is not None else pd.DataFrame()
        self.file_df = file_df.copy() if file_df is not None else pd.DataFrame()
        self.email_df = email_df.copy() if email_df is not None else pd.DataFrame()
        self.max_file_edges_per_user = max_file_edges_per_user
        self.max_email_edges_per_user = max_email_edges_per_user

        self.graph = None
        self.user_metrics: Dict[str, GraphMetric] = {}
        self._graph_payload_cache: Dict[str, Dict] = {}

    def build_graph(self):
        if self.graph is not None:
            return self.graph

        graph = nx.Graph() if nx is not None else _SimpleGraph()

        for user, pc, weight in self._group_edges(self.device_df, "pc"):
            self._add_weighted_edge(graph, self._user_id(user), self._device_id(pc), "device", weight)

        for user, filename, weight in self._group_edges(
            self.file_df, "filename", per_user_limit=self.max_file_edges_per_user
        ):
            self._add_weighted_edge(graph, self._user_id(user), self._file_id(filename), "file", weight)

        for user, target, weight in self._group_edges(
            self.email_df, "to", per_user_limit=self.max_email_edges_per_user
        ):
            self._add_weighted_edge(graph, self._user_id(user), self._email_id(target), "email", weight)

        self.graph = graph
        return graph

    def get_user_metrics_df(self) -> pd.DataFrame:
        if self.user_metrics:
            return pd.DataFrame([vars(metric) for metric in self.user_metrics.values()])

        graph = self.build_graph()
        user_nodes = [node_id for node_id, attrs in graph.nodes(data=True) if attrs.get("type") == "user"]
        if not user_nodes:
            return pd.DataFrame(columns=["user", "graph_score", "graph_connections_count"])

        centrality_map = self._degree_centrality(graph, user_nodes)
        interaction_map = {}
        connection_map = {}
        diversity_map = {}

        for user_node in user_nodes:
            neighbors = list(graph.neighbors(user_node))
            weights = [float(graph.get_edge_data(user_node, neighbor, {}).get("weight", 1.0)) for neighbor in neighbors]
            attrs = self._node_attrs(graph, user_node)
            user = attrs.get("key") or user_node.replace("user_", "", 1)
            connection_map[user] = len(neighbors)
            interaction_map[user] = float(sum(weights))
            diversity_map[user] = len({self._node_attrs(graph, n).get("type") for n in neighbors})

        centrality_scores = self._normalize_series(
            pd.Series({user: centrality_map[self._user_id(user)] for user in connection_map})
        )
        interaction_scores = self._normalize_series(pd.Series(interaction_map))
        diversity_scores = self._normalize_series(pd.Series(diversity_map))
        combined_scores = (0.55 * centrality_scores) + (0.35 * interaction_scores) + (0.10 * diversity_scores)

        self.user_metrics = {
            user: GraphMetric(
                user=user,
                graph_score=round(float(combined_scores.get(user, 0.0)), 2),
                graph_connections_count=int(connection_map.get(user, 0)),
                centrality=round(float(centrality_scores.get(user, 0.0)), 2),
                interaction_weight=round(float(interaction_map.get(user, 0.0)), 2),
            )
            for user in connection_map
        }
        return pd.DataFrame([vars(metric) for metric in self.user_metrics.values()])

    def get_user_subgraph(self, user_id: str, max_neighbors: int = 30) -> Dict:
        if user_id in self._graph_payload_cache:
            return self._graph_payload_cache[user_id]

        graph = self.build_graph()
        user_node = self._user_id(user_id)
        if not graph.has_node(user_node):
            return {"nodes": [], "edges": []}

        neighbors = []
        for neighbor in graph.neighbors(user_node):
            edge_data = graph.get_edge_data(user_node, neighbor, {})
            neighbor_type = self._node_attrs(graph, neighbor).get("type")
            neighbors.append(
                (
                    float(edge_data.get("weight", 1.0)),
                    self._type_priority(neighbor_type),
                    neighbor,
                )
            )

        selected_neighbors = [node for _, _, node in sorted(neighbors, reverse=True)[:max_neighbors]]
        subgraph = graph.subgraph([user_node, *selected_neighbors])
        metrics = self.get_user_metrics_df().set_index("user").to_dict("index")
        user_metric = metrics.get(user_id, {})
        max_weight = max(
            [float(attrs.get("weight", 1.0)) for _, _, attrs in subgraph.edges(data=True)] or [1.0]
        )

        nodes = []
        for node_id, attrs in subgraph.nodes(data=True):
            node_weight = self._node_weight(subgraph, node_id)
            activity_score = min(100.0, (node_weight / max_weight) * 100.0) if max_weight else 0.0
            if attrs.get("type") == "user":
                activity_score = float(user_metric.get("graph_score", activity_score))
            nodes.append(
                {
                    "id": node_id,
                    "type": attrs.get("type"),
                    "label": attrs.get("label"),
                    "key": attrs.get("key"),
                    "activity_score": round(activity_score, 2),
                    "connections": int(subgraph.degree(node_id)),
                    "metadata": {
                        "graph_score": round(float(user_metric.get("graph_score", 0.0)), 2) if attrs.get("type") == "user" else None,
                        "centrality": round(float(user_metric.get("centrality", 0.0)), 2) if attrs.get("type") == "user" else None,
                        "interaction_weight": round(float(user_metric.get("interaction_weight", 0.0)), 2) if attrs.get("type") == "user" else round(node_weight, 2),
                    },
                }
            )

        edges = [
            {
                "source": source,
                "target": target,
                "weight": round(float(attrs.get("weight", 1.0)), 2),
                "type": attrs.get("type"),
            }
            for source, target, attrs in subgraph.edges(data=True)
        ]

        payload = {
            "nodes": nodes,
            "edges": edges,
            "graph_score": round(float(user_metric.get("graph_score", 0.0)), 2),
            "graph_connections_count": int(user_metric.get("graph_connections_count", len(selected_neighbors))),
        }
        self._graph_payload_cache[user_id] = payload
        return payload

    def _group_edges(self, df: pd.DataFrame, value_col: str, per_user_limit: Optional[int] = None) -> Iterable[Tuple[str, str, int]]:
        if df.empty or "user" not in df.columns or value_col not in df.columns:
            return []

        rows = df[["user", value_col]].copy()
        rows["user"] = rows["user"].astype(str).str.strip()
        rows[value_col] = rows[value_col].astype(str).str.strip()
        rows = rows[(rows["user"] != "") & (rows[value_col] != "")]
        if rows.empty:
            return []

        grouped = rows.groupby(["user", value_col]).size().reset_index(name="weight")
        if per_user_limit:
            grouped = (
                grouped.sort_values(["user", "weight"], ascending=[True, False])
                .groupby("user", group_keys=False)
                .head(per_user_limit)
            )
        return grouped.itertuples(index=False, name=None)

    def _add_weighted_edge(self, graph, user_id: str, entity_id: str, entity_type: str, weight: int):
        user_label = user_id.replace("user_", "", 1)
        graph.add_node(user_id, type="user", label=user_label, key=user_label)
        graph.add_node(entity_id, type=entity_type, label=entity_id.split("_", 1)[1], key=entity_id.split("_", 1)[1])
        graph.add_edge(user_id, entity_id, weight=int(weight), type=entity_type)

    def _degree_centrality(self, graph, user_nodes: List[str]) -> Dict[str, float]:
        if nx is not None and hasattr(nx, "degree_centrality"):
            centrality = nx.degree_centrality(graph)
            return {node: float(centrality.get(node, 0.0)) for node in user_nodes}

        denom = max(graph.number_of_nodes() - 1, 1)
        return {node: float(graph.degree(node)) / denom for node in user_nodes}

    def _normalize_series(self, series: pd.Series) -> pd.Series:
        if series.empty:
            return pd.Series(dtype=float)
        min_val = float(series.min())
        max_val = float(series.max())
        if max_val == min_val:
            return pd.Series(50.0, index=series.index, dtype=float)
        return ((series - min_val) / (max_val - min_val) * 100.0).astype(float)

    def _node_weight(self, graph, node_id: str) -> float:
        return float(
            sum(float(graph.get_edge_data(node_id, neighbor, {}).get("weight", 1.0)) for neighbor in graph.neighbors(node_id))
        )

    def _node_attrs(self, graph, node_id: str) -> Dict:
        if hasattr(graph, "_nodes"):
            return dict(graph._nodes.get(node_id, {}))
        if nx is not None and hasattr(graph, "nodes"):
            return dict(graph.nodes[node_id])
        for existing_node, attrs in graph.nodes(data=True):
            if existing_node == node_id:
                return dict(attrs)
        return {}

    def _type_priority(self, node_type: Optional[str]) -> int:
        order = {"device": 3, "file": 2, "email": 1}
        return order.get(node_type, 0)

    def _user_id(self, value: str) -> str:
        return f"user_{str(value).strip()}"

    def _device_id(self, value: str) -> str:
        return f"device_{str(value).strip()}"

    def _file_id(self, value: str) -> str:
        return f"file_{str(value).strip()}"

    def _email_id(self, value: str) -> str:
        return f"email_{str(value).strip()}"
