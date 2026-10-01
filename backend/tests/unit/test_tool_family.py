from rainstone.reporting import tool_family_key

SHED = "toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc"


def test_a_tool_shed_version_is_removed_when_the_job_confirms_it() -> None:
    assert tool_family_key(f"{SHED}/0.74+galaxy1", "0.74+galaxy1") == SHED
    assert tool_family_key(f"{SHED}/0.73", None) == SHED


def test_a_version_the_job_contradicts_is_kept() -> None:
    assert tool_family_key(f"{SHED}/0.73", "0.72") == f"{SHED}/0.73"


def test_other_ids_keep_their_exact_identity() -> None:
    for tool_id in ("upload1", "cat1", "local/tools/fastqc", f"{SHED}", "a/repos/b/c/d/e/f"):
        assert tool_family_key(tool_id, "1.0") == tool_id
    assert tool_family_key("host/notrepos/o/r/t/1.0", "1.0") == "host/notrepos/o/r/t/1.0"
