# Cross-Camera Correlation

Decides whether two per-camera (local) tracks belong to the same real-world
movement, and stitches them into a **global track**.

## Gates (hard requirements)
1. **Topology** — a `camera_edge` must exist from A's camera to B's camera.
2. **Temporal window** — the transit gap `B.start − A.end` must fall within the
   edge's `[walk_seconds_min, walk_seconds_max]`.

Failing either gate rejects the pair outright (no score computed).

## Score
```
score = w_t · s_time + w_m · s_motion + w_a · s_appearance
```
- `s_time`      — triangular, peak at the middle of the walk window.
- `s_motion`    — velocity-angle continuity between A's exit and B's entry.
- `s_appearance`— cosine similarity of mean OSNet track embeddings (pgvector).

Defaults (config, tunable): `w_t=0.34, w_m=0.16, w_a=0.50`, merge threshold `τ=0.62`.

## Merge
Pairs scoring ≥ τ are unioned (union-find) into connected global tracks. Each
`global_track_member` stores its `join_score` and a `method` string with the
component sub-scores (e.g. `time=0.83 motion=1.00 appearance=0.98 gap=6.0s`) so
operators can see exactly **why** two observations were linked.

## Explainability & privacy
Appearance is a *similarity* signal only — no identity, no PII, no facial or
gait recognition. All merges are transparent and reviewable by a human operator.
