"""Thin read-only wrapper over the existing CLI registries -- no new
router-discovery logic, just formatting for the API."""

from typing import List

from backend.api.schemas.routers import ModelInfo, RouterInfo


def list_routers() -> List[RouterInfo]:
    from llmrouter.cli.router_inference import ROUTER_REGISTRY
    from llmrouter.cli.router_train import ROUTER_TRAINER_REGISTRY, UNSUPPORTED_ROUTERS

    infos = []
    seen = set()
    for name, cls in ROUTER_REGISTRY.items():
        if name in seen:
            continue
        seen.add(name)
        infos.append(
            RouterInfo(
                name=name,
                class_name=cls.__name__,
                trainable=name in ROUTER_TRAINER_REGISTRY,
                unsupported_reason=UNSUPPORTED_ROUTERS.get(name),
            )
        )
    return sorted(infos, key=lambda r: r.name)


def list_models(llm_data_path: str) -> List[ModelInfo]:
    """Reads the candidate LLM list the same way routers do (llm_data JSON)."""
    import json

    from backend.api.services.config_resolver import locate_config

    with open(locate_config(llm_data_path)) as f:
        data = json.load(f)
    return [
        ModelInfo(name=name, size=info.get("size"), service=info.get("service"))
        for name, info in data.items()
    ]
