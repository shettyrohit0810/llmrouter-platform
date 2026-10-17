"""Named cache instances -- each is a CacheNamespace with a prefix and a TTL
chosen for what it holds. None of these are wired into a hot path yet
(Milestone 5's scope is the caching infrastructure itself); consumers land
in later milestones:

- session_cache: session-scoped lookups for Milestone 6's rate limiting and
  Milestone 13's dashboard ("who's logged in") -- not the JWT/refresh-token
  system itself (that's Postgres-backed and stays that way, see
  docs/backend/authentication.md).
- job_cache: short-TTL job-status lookups, to reduce Postgres load once
  Milestone 7 wires jobs to persist there.
- embedding_cache: query embeddings keyed by (query, model) -- long TTL,
  since an embedding for identical input never changes.
- prediction_cache: routing decisions keyed by (router, config_path, query)
  -- short-to-medium TTL, since retraining changes what a router predicts
  for the same query.
"""

from backend.cache.namespace import CacheNamespace

session_cache = CacheNamespace("session", default_ttl_seconds=15 * 60)
job_cache = CacheNamespace("job", default_ttl_seconds=30)
embedding_cache = CacheNamespace("embedding", default_ttl_seconds=24 * 60 * 60)
prediction_cache = CacheNamespace("prediction", default_ttl_seconds=5 * 60)
