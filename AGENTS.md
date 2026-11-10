# AGENTS.md (ds_ingestion)
Common rules, repo map, rebuild procedure: `/home/vector/projects/ds/AGENTS.md` — read it first. Status log: `CURRENT_STATUS.md`.
RAG indexing.

- Own repo Ssazurov/ds_ingestion, default branch `main`, nested and gitignored in `ds`.
- Service `ds-ingestion`, code baked into image: `bash -l ~/projects/deploy/scripts/rebuild.sh ds-ingestion > ~/build.log 2>&1` (see hub «Rebuild»).
