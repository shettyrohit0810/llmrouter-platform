"""Generates the small synthetic dataset the sample router configs train on.

Three imaginary models (small / mid / large) answer a set of easy and hard
prompts. A model's `performance` on a prompt is its answer quality (drawn from
a skill table, plus noise) minus a penalty proportional to its price, i.e. a
cost-adjusted score. Cheap models are nearly as good on easy prompts and much
worse on hard ones, so after the price penalty the small model wins easy
prompts and the large model wins hard ones. That is the structure that makes
routing worthwhile, and it gives the Elo and KNN routers something real to learn.

Prompt embeddings are produced by the routing library's own text encoder, so
the saved vectors have the same dimensionality the routers use at inference.

Run from the project root:  python scripts/generate_sample_data.py
Output is deterministic (fixed seed) apart from encoder numerics.
"""

import json
import random
from pathlib import Path

import torch

SEED = 7
OUT = Path("data/sample")

MODELS = {
    "small-model": {"size": "7B", "price": 0.1, "skill": {"easy": 0.88, "hard": 0.25}},
    "mid-model": {"size": "34B", "price": 0.6, "skill": {"easy": 0.86, "hard": 0.55}},
    "large-model": {"size": "180B", "price": 2.5, "skill": {"easy": 0.91, "hard": 0.86}},
}
PRICE_PENALTY = 0.04  # score lost per unit of price

EASY = {
    "math": [
        "What is {a} plus {b}?",
        "What is {a} times {b}?",
        "Round {a}.{b} to the nearest whole number.",
    ],
    "code": [
        "Write a Python expression that reverses the string '{w}'.",
        "How do I print '{w}' in Python?",
        "What does len('{w}') return in Python?",
    ],
    "qa": [
        "What is the capital of {c}?",
        "In which continent is {c}?",
        "Name the official language of {c}.",
    ],
}
HARD = {
    "math": [
        "Solve {a}x^2 + {b}x - {a} = 0 and justify each algebraic step, including the discriminant.",
        "Prove that the sum of the first {a} odd numbers is a perfect square, using induction.",
        "A bag holds {a} red and {b} blue marbles. Derive the probability of drawing exactly two red in three draws without replacement.",
    ],
    "code": [
        "Implement an LRU cache with O(1) get and put for capacity {a} in Python and analyse its complexity.",
        "Design a thread-safe rate limiter for {a} requests per second and explain the race conditions you avoid.",
        "Write a function that finds the longest palindromic substring of a {a}-character string in O(n^2) and discuss a faster alternative.",
    ],
    "qa": [
        "Compare the economic causes of the 1929 crash and the 2008 crisis, and argue which was more preventable.",
        "Explain how {c}'s political history shaped its present trade policy, citing at least three events.",
        "Evaluate the trade-offs between nuclear and solar power for a country like {c} over a thirty-year horizon.",
    ],
}
COUNTRIES = [
    "Norway",
    "Peru",
    "Kenya",
    "Japan",
    "Chile",
    "Egypt",
    "Canada",
    "India",
    "Poland",
    "Vietnam",
]
WORDS = ["router", "gateway", "lantern", "orbit", "harbor", "cipher", "meadow", "pylon"]


def make_prompts(rng: random.Random, n: int):
    prompts = []
    for _ in range(n):
        difficulty = rng.choice(["easy", "hard"])
        task = rng.choice(["math", "code", "qa"])
        template = rng.choice((EASY if difficulty == "easy" else HARD)[task])
        text = template.format(
            a=rng.randint(2, 40), b=rng.randint(2, 40), c=rng.choice(COUNTRIES), w=rng.choice(WORDS)
        )
        prompts.append({"task_name": task, "query": text, "difficulty": difficulty})
    # Deduplicate while keeping order so every prompt is a distinct routing instance.
    seen, unique = set(), []
    for p in prompts:
        if p["query"] not in seen:
            seen.add(p["query"])
            unique.append(p)
    return unique


def routing_rows(rng: random.Random, prompts, start_id: int):
    rows = []
    for offset, p in enumerate(prompts):
        for name, spec in MODELS.items():
            quality = spec["skill"][p["difficulty"]] + rng.gauss(0, 0.02)
            score = quality - PRICE_PENALTY * spec["price"]
            tokens = rng.randint(40, 400)
            rows.append(
                {
                    "task_name": p["task_name"],
                    "query": p["query"],
                    "model_name": name,
                    "performance": round(min(1.0, max(0.0, score)), 4),
                    "embedding_id": start_id + offset,
                    "response_time": round(rng.uniform(0.3, 1.0) * (1 + MODELS[name]["price"]), 3),
                    "token_num": tokens,
                    "input_tokens": tokens // 4,
                    "output_tokens": tokens - tokens // 4,
                }
            )
    return rows


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def main() -> None:
    rng = random.Random(SEED)
    train = make_prompts(rng, 90)
    test = [p for p in make_prompts(rng, 40) if p["query"] not in {t["query"] for t in train}]

    from llmrouter.utils import get_longformer_embedding

    all_prompts = train + test
    embeddings = torch.stack(
        [get_longformer_embedding(p["query"]).reshape(-1) for p in all_prompts]
    ).float()

    write_jsonl(
        OUT / "queries/train.jsonl",
        [{k: v for k, v in p.items() if k != "difficulty"} for p in train],
    )
    write_jsonl(
        OUT / "queries/test.jsonl",
        [{k: v for k, v in p.items() if k != "difficulty"} for p in test],
    )
    write_jsonl(OUT / "routing/train.jsonl", routing_rows(rng, train, 0))
    write_jsonl(OUT / "routing/test.jsonl", routing_rows(rng, test, len(train)))
    torch.save(embeddings, OUT / "routing/query_embeddings.pt")

    candidates = {
        name: {
            "size": spec["size"],
            "feature": f"Synthetic {name} used only by the sample dataset.",
            "input_price": spec["price"],
            "output_price": spec["price"],
            "model": name,
            "service": "sample",
            "api_endpoint": "http://localhost:11434/v1",
        }
        for name, spec in MODELS.items()
    }
    (OUT / "llm_candidates.json").write_text(json.dumps(candidates, indent=2) + "\n")
    print(
        f"train prompts={len(train)} test prompts={len(test)} embedding shape={tuple(embeddings.shape)}"
    )


if __name__ == "__main__":
    main()
