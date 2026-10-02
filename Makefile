.PHONY: fetch ingest extract change eval mcp ui readme test lint
fetch:   ; uv run --locked python -m og.fetch
ingest:  ; uv run --locked python -m og.ingest
extract: ; uv run --locked python -m og.extract
change:  ; uv run --locked python -m og.change
eval: change ; uv run --locked python -m og.eval all
mcp:     ; uv run --locked python -m og.mcp
ui:      ; uv run --locked python -m og.ui
readme:  ; uv run --locked python -m og.eval readme-tables --check README.md
test:    ; uv run --locked pytest
lint:    ; uv run --locked ruff check . && uv run --locked ruff format --check .
