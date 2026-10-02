# C10: Fresh-clone reproducibility (2026-10-02)

**Result: pass. The aggregate projection was equal: `SEMANTIC_EQUAL True`.**

On the devbox, I cloned the GitHub repository at `65bd9e3` into an empty temp directory and set one value in `.env`, `OG_EDGAR_USER_AGENT`, which SEC policy requires. There was no API key in the environment, and `OG_REPLAY=strict` was set, so any missing recording would have failed.

Then I ran `make fetch ingest extract eval`:

1. **fetch:** downloaded the seven filings from SEC EDGAR and accepted them against their pinned SHA-256s.
2. **ingest:** rebuilt the TextDocs.
3. **extract:** replayed all 72 recorded extraction responses.
4. **change:** replayed 12 checks and 9 gate samples.
5. **eval:** wrote the aggregate.

The fresh aggregate's semantic projection (`og.eval.all.semantic_projection`, which drops dates, run ids, wall times and incremental spend) equals the committed `eval/results/2026-10-02-aggregate.json`. Every incremental cost was $0.
