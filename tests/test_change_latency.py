"""Wave 4 rev 2.3: the stored run latency is the recorded latency, not replay wall time.

C10 found `change_run.latency_ms` holding this invocation's wall time, which on a replay
is milliseconds, while the aggregate and README label it "recorded latency". Per rev 2
W4-4 the stored run latency is recorded_latency_ms (check outcomes plus classifier-tier
gate decisions); replay wall time lives only in the log's replay_wall_ms.
"""

import sqlite3

from test_replay import change_live, extract_live, records, workdir  # noqa: F401

from og.change.__main__ import main as change_main


def _stored(mode):
    con = sqlite3.connect("data/graph.db")
    try:
        return con.execute("SELECT latency_ms FROM change_run WHERE mode = ?", (mode,)).fetchone()[
            0
        ]
    finally:
        con.close()


def test_stored_run_latency_is_the_recorded_latency_live_and_on_replay(workdir):  # noqa: F811
    extract_live()
    change_live()
    live_ungated, live_gated = records()
    assert _stored("ungated") == live_ungated["recorded_latency_ms"]
    assert _stored("gated") == live_gated["recorded_latency_ms"]
    assert change_main(["--mode", "both"]) == 0
    replay_ungated, replay_gated = records()[-2:]
    assert (
        _stored("ungated")
        == replay_ungated["recorded_latency_ms"]
        == live_ungated["recorded_latency_ms"]
    )
    assert (
        _stored("gated") == replay_gated["recorded_latency_ms"] == live_gated["recorded_latency_ms"]
    )
