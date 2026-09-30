from datetime import UTC, datetime
from decimal import Decimal

from rainstone.job_use import CPU_TIME, MEMORY_PEAKS, job_resource_use

START = datetime(2026, 9, 29, 1, 6, tzinfo=UTC)
FINISH = datetime(2026, 9, 29, 1, 16, tzinfo=UTC)
GIB = 1024**3
BATCH = "compute_insert_complete_to_delete_request"


def resource(**overrides) -> dict:
    return {
        "capacity_relationship": "dedicated", "timing_method": BATCH,
        "requested_vcpu": "8.000000000000", "requested_memory_mib": "32768.000000", **overrides,
    }


def use(metrics: dict, *, running=False, executions=None, resources=None) -> dict:
    return job_resource_use(
        {key: Decimal(value) for key, value in metrics.items()},
        running=running,
        executions=[(START, FINISH)] if executions is None else executions,
        resources=[resource()] if resources is None else resources,
    )


def ratio(value: str | None) -> Decimal:
    assert value is not None
    return Decimal(value)


class TestAverageCpu:
    def test_twenty_four_cpu_minutes_over_ten_minutes_on_eight_vcpus_is_thirty_percent(self) -> None:
        cpu = use({CPU_TIME: 24 * 60 * 1_000_000})["cpu"]
        assert cpu["status"] == "available"
        assert ratio(cpu["cpu_seconds"]) == 1440
        assert ratio(cpu["duration_seconds"]) == 600
        assert ratio(cpu["average_cores"]) == Decimal("2.4")
        assert ratio(cpu["request_fraction"]) == Decimal("0.3")

    def test_a_tiny_positive_use_stays_positive(self) -> None:
        cpu = use({CPU_TIME: 1})["cpu"]
        assert cpu["status"] == "available"
        assert 0 < ratio(cpu["request_fraction"]) < Decimal("0.0001")

    def test_use_above_the_request_is_not_clamped(self) -> None:
        cpu = use({CPU_TIME: 12 * 600 * 1_000_000})["cpu"]
        assert ratio(cpu["average_cores"]) == 12
        assert ratio(cpu["request_fraction"]) == Decimal("1.5")

    def test_an_exact_zero_is_a_measurement(self) -> None:
        cpu = use({CPU_TIME: 0})["cpu"]
        assert cpu["status"] == "available"
        assert ratio(cpu["request_fraction"]) == 0

    def test_missing_use_is_not_recorded_rather_than_zero(self) -> None:
        cpu = use({})["cpu"]
        assert cpu["status"] == "not_recorded"
        assert cpu["cpu_seconds"] is None and cpu["request_fraction"] is None

    def test_a_negative_counter_is_invalid(self) -> None:
        assert use({CPU_TIME: -5})["cpu"]["status"] == "invalid_value"

    def test_no_request_keeps_the_average_but_draws_no_ratio(self) -> None:
        cpu = use({CPU_TIME: 1_200_000_000}, resources=[resource(requested_vcpu=None)])["cpu"]
        assert cpu["status"] == "request_unavailable"
        assert cpu["reason"] == "request_missing"
        assert cpu["average_cores"] is not None and cpu["request_fraction"] is None

    def test_a_zero_request_is_never_a_denominator(self) -> None:
        cpu = use({CPU_TIME: 1_200_000_000}, resources=[resource(requested_vcpu="0.000000")])["cpu"]
        assert cpu["status"] == "request_unavailable"
        assert cpu["reason"] == "request_not_positive"

    def test_zero_or_reversed_elapsed_time_is_never_a_denominator(self) -> None:
        for executions in ([(START, START)], [(FINISH, START)], [(START, None)], [(None, FINISH)]):
            cpu = use({CPU_TIME: 1_200_000_000}, executions=executions)["cpu"]
            assert cpu["status"] == "duration_unavailable"
            assert cpu["average_cores"] is None and cpu["request_fraction"] is None

    def test_a_running_job_gets_no_average_from_a_counter_of_unknown_age(self) -> None:
        cpu = use({CPU_TIME: 1_200_000_000}, running=True, executions=[(START, None)])["cpu"]
        assert cpu["status"] == "unsupported_scope"
        assert cpu["reason"] == "running"
        assert cpu["average_cores"] is None

    def test_a_job_counter_is_not_matched_to_several_executions(self) -> None:
        cpu = use({CPU_TIME: 1_200_000_000}, executions=[(START, FINISH), (START, FINISH)])["cpu"]
        assert cpu["status"] == "unsupported_scope"
        assert cpu["reason"] == "several_executions"
        assert cpu["average_cores"] is None

    def test_several_resources_leave_the_request_ambiguous(self) -> None:
        cpu = use({CPU_TIME: 1_200_000_000}, resources=[resource(), resource()])["cpu"]
        assert cpu["status"] == "unsupported_scope"
        assert cpu["reason"] == "several_resources"
        assert cpu["requested_vcpu"] is None

    def test_a_galaxy_servers_counters_are_not_the_jobs(self) -> None:
        result = use({CPU_TIME: 1_200_000_000}, resources=[resource(capacity_relationship="existing")])
        assert result["measurement_scope"] == "unestablished"
        assert result["cpu"]["reason"] == "galaxy_server"
        assert result["cpu"]["cpu_seconds"] is None
        # The raw value stays available as evidence.
        assert [metric["name"] for metric in result["metrics"]] == ["cpu.stat.usage_usec"]

    def test_a_pod_request_that_may_include_init_containers_is_not_compared(self) -> None:
        cpu = use({CPU_TIME: 1_200_000_000}, resources=[resource(timing_method="kubernetes_pod_occupancy")])["cpu"]
        assert cpu["status"] == "unsupported_scope"
        assert cpu["reason"] == "request_scope_unverified"
        assert cpu["average_cores"] is not None and cpu["request_fraction"] is None


class TestPeakMemory:
    def test_eight_gib_of_thirty_two_is_twenty_five_percent(self) -> None:
        memory = use({MEMORY_PEAKS[0]: 8 * GIB})["memory"]
        assert memory["status"] == "available"
        assert memory["source"] == "memory.peak"
        assert ratio(memory["request_fraction"]) == Decimal("0.25")

    def test_the_older_cgroup_name_is_the_same_peak(self) -> None:
        memory = use({MEMORY_PEAKS[1]: 8 * GIB})["memory"]
        assert memory["source"] == "memory.max_usage_in_bytes"
        assert ratio(memory["request_fraction"]) == Decimal("0.25")

    def test_both_names_with_the_same_value_are_one_measurement(self) -> None:
        memory = use({MEMORY_PEAKS[0]: 8 * GIB, MEMORY_PEAKS[1]: 8 * GIB})["memory"]
        assert memory["status"] == "available"

    def test_conflicting_names_are_neither_summed_nor_chosen(self) -> None:
        memory = use({MEMORY_PEAKS[0]: 8 * GIB, MEMORY_PEAKS[1]: 16 * GIB})["memory"]
        assert memory["status"] == "unsupported_scope"
        assert memory["reason"] == "source_unresolved"
        assert memory["peak_bytes"] is None and memory["request_fraction"] is None

    def test_a_peak_above_the_request_keeps_its_true_ratio(self) -> None:
        memory = use({MEMORY_PEAKS[0]: 40 * GIB})["memory"]
        assert ratio(memory["request_fraction"]) == Decimal("1.25")

    def test_a_request_is_compared_in_bytes_not_in_mixed_units(self) -> None:
        memory = use({MEMORY_PEAKS[0]: 512 * 1024**2}, resources=[resource(requested_memory_mib="1024")])["memory"]
        assert ratio(memory["request_fraction"]) == Decimal("0.5")

    def test_missing_request_keeps_the_peak(self) -> None:
        memory = use({MEMORY_PEAKS[0]: GIB}, resources=[resource(requested_memory_mib=None)])["memory"]
        assert memory["status"] == "request_unavailable"
        assert ratio(memory["peak_bytes"]) == GIB

    def test_missing_use_is_not_recorded(self) -> None:
        assert use({CPU_TIME: 5})["memory"]["status"] == "not_recorded"

    def test_memory_does_not_need_a_duration(self) -> None:
        memory = use({MEMORY_PEAKS[0]: GIB}, executions=[(START, None)])["memory"]
        assert memory["status"] == "available"


class TestScopeAndEvidence:
    def test_one_finished_execution_on_one_resource_establishes_the_scope(self) -> None:
        result = use({})
        assert result["measurement_scope"] == "single_execution"
        assert result["scope_reason"] is None

    def test_a_job_with_no_execution_has_no_scope(self) -> None:
        assert use({}, executions=[])["scope_reason"] == "no_execution"

    def test_raw_metrics_carry_units_and_nothing_is_invented(self) -> None:
        result = use({("core", "galaxy_slots"): 2, CPU_TIME: 5, MEMORY_PEAKS[0]: 7})
        units = {metric["name"]: metric["unit"] for metric in result["metrics"]}
        assert units == {"galaxy_slots": "slots", "cpu.stat.usage_usec": "microseconds", "memory.peak": "bytes"}
        assert set(result["cpu"]) & {"peak_cores", "samples"} == set()
