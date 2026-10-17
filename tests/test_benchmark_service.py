import pandas as pd
import pytest

from backend.api.services.benchmark import run_benchmark


class _FakeRouter:
    def __init__(self, routing_data_test):
        self.routing_data_test = routing_data_test

    def route_single(self, query_input):
        # Deterministic fake: always route to "model_a"
        return {"model_name": "model_a"}


def test_run_benchmark_scores_against_existing_routing_data(monkeypatch):
    df = pd.DataFrame(
        [
            {
                "query": "q1",
                "model_name": "model_a",
                "performance": 1.0,
                "response_time": 0.5,
                "token_num": 100,
                "task_name": "default",
            },
            {
                "query": "q2",
                "model_name": "model_a",
                "performance": 0.0,
                "response_time": 0.3,
                "token_num": 80,
                "task_name": "default",
            },
        ]
    )
    fake_router = _FakeRouter(df)

    import backend.api.services.benchmark as benchmark_module

    monkeypatch.setattr(
        benchmark_module, "_load_router_for_benchmark", lambda name, cfg: fake_router
    )

    result = run_benchmark("fake_router", "unused_config.yaml")

    assert result.num_queries == 2
    assert result.accuracy == pytest.approx(0.5)
    assert result.routing_distribution == {"model_a": 2}
    assert result.failures == 0
