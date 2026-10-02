# Recorded API responses (C1)

Real `claude-sonnet-5-5` responses recorded once by the coordinator on 2026-10-02 with `prompt_version` `extract_v1@6de99191`, using `effort` high and the server-side fallback beta.

- `*.json`: the response body (`message.to_dict()`): content, stop_reason, model, and usage. No request headers and no credentials.
- `*.chunk.txt`: the exact user-message text (the chunk) that produced it.

Tests replay these offline. Re-record only through the coordinator, and record the change in `docs/reviews/test-changes.md`.
