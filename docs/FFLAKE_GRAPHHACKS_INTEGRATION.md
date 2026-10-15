# GraphHacks integration notes

## Intended loop
1. Trigger: choose a source principal and sensitive target.
2. Investigate: enumerate bounded paths from FalkorDB.
3. Score: combine relationship risk scores and path length.
4. Simulate: exclude a candidate relationship from path search.
5. Recommend: rank edges by how many paths they block.
6. Approve: require a human or policy gate before a real change.
7. Verify: rerun path analysis against the changed graph.
8. Remember: later store incident, action, and verification outcome as episodic memory.

This pack implements graph retrieval, scoring, candidate-cut simulation, and simulation-only verification. It does not perform live remediation.

## Selective reuse from Grok's repo
Keep the useful patterns: bounded multi-hop retrieval, explicit evidence/provenance, visible path exploration, and source traceability. Do not make the rail-specific seeded domain the core product story. FFlake's differentiator is capability-path investigation and verified remediation, with one graph that can later support persistent memory and company knowledge.

## Data model
Nodes: `(:FFAsset {id, name, kind, risk, description})`
Relationships: `[:FF_REL {id, kind, risk, name, reason}]`

One typed relationship with a `kind` property makes the first iteration easier to query safely. Migrate to real relationship types behind the engine API if needed.

## Next increments
- Persist finding, candidate, approval, action, and verification records.
- Add an approval gate and a remediation adapter for a sandbox-only environment.
- Expose `find_paths`, `simulate_change`, `diff_graphs`, `min_cut_fix`, and `verify` as MCP tools.
- Connect the existing UI to `/api/graph-hacks/analyze` and render path evidence and candidate-cut comparison.
- Add tenant/user isolation before multi-user deployment.
