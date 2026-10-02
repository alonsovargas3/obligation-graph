.PHONY: fetch ingest extract change eval mcp ui test lint
fetch:   ; uv run --locked python -m og.fetch
ingest:  ; uv run --locked python -m og.ingest
extract: ; uv run --locked python -m og.extract
change:  ; uv run --locked python -m og.change
eval:    ; @echo "not implemented yet (step 11)"; exit 2
mcp:     ; @echo "not implemented yet (step 9)"; exit 2
ui:      ; @echo "not implemented yet (step 10)"; exit 2
test:    ; uv run --locked pytest
lint:    ; uv run --locked ruff check . && uv run --locked ruff format --check .
