from datetime import timedelta
from decimal import Decimal

import pytest
from rainstone.costing import calculate_lifetime
from rainstone.models import CapacityRelationship, ExecutionAttempt

from .test_costing import START, lifetime, price


def attempt(start, end):
    return ExecutionAttempt(
        tool_started_at=START + timedelta(seconds=start) if start is not None else None,
        tool_finished_at=START + timedelta(seconds=end) if end is not None else None,
    )


def phases_for(seconds, attempts, prices=None):
    return calculate_lifetime(lifetime(CapacityRelationship.dedicated, str(seconds)), [],
                              prices or price("0.12"), attempts=attempts)[0]


def test_phase_costs_reconcile_with_minimum_billing():
    line = phases_for(30, [attempt(5, 20)])
    phases = {item["phase"]: item for item in line.phases}
    assert set(phases) == {"provisioning", "execution", "teardown"}
    assert sum(Decimal(item["amount"]) for item in line.phases) == line.amount == Decimal("0.002")
    assert sum(Decimal(item["charged_seconds"]) for item in line.phases) == 60
    assert Decimal(phases["execution"]["observed_seconds"]) == 15
    assert Decimal(phases["execution"]["charged_seconds"]) == 30
    assert all(allocation["phase"] in phases for allocation in line.allocations)


def test_price_change_splits_execution_without_repeating_the_minimum():
    second = price("0.24")
    second.effective_from = START + timedelta(seconds=15)
    line = phases_for(40, [attempt(10, 30)], [price("0.12"), second])
    assert sum(Decimal(item["amount"]) for item in line.phases) == line.amount
    assert sum(Decimal(item["charged_seconds"]) for item in line.phases) == 60
    execution = [allocation for allocation in line.allocations if allocation["phase"] == "execution"]
    assert len(execution) == 2
    assert [Decimal(item["hourly_rate"]) for item in execution] == [Decimal("0.12"), Decimal("0.24")]


def test_retries_on_one_vm_include_idle_and_overlapping_execution_is_not_double_counted():
    line = phases_for(60, [attempt(5, 20), attempt(30, 45), attempt(35, 50)])
    phases = {item["phase"]: item for item in line.phases}
    assert Decimal(phases["execution"]["observed_seconds"]) == 35
    assert Decimal(phases["idle"]["observed_seconds"]) == 10
    assert Decimal(phases["provisioning"]["observed_seconds"]) == 5
    assert Decimal(phases["teardown"]["observed_seconds"]) == 10
    assert sum(Decimal(item["amount"]) for item in line.phases) == line.amount


@pytest.mark.parametrize("attempts", [[], [attempt(None, 20)], [attempt(5, None)],
                                      [attempt(-1, 20)], [attempt(5, 31)], [attempt(20, 5)],
                                      [attempt(5, 10), attempt(None, 20)]])
def test_unknown_or_invalid_timing_is_wholly_unattributed(attempts):
    line = phases_for(30, attempts)
    [phase] = line.phases
    assert phase["phase"] == "unattributed"
    assert phase["reason"]
    assert Decimal(phase["amount"]) == line.amount
    assert Decimal(phase["observed_seconds"]) == 30
    assert Decimal(phase["charged_seconds"]) == 60


def test_server_jobs_have_no_phases_and_unpriced_costs_stay_null():
    lines = calculate_lifetime(lifetime(CapacityRelationship.existing), [], price(), attempts=[attempt(5, 20)])
    assert all(not line.phases for line in lines)
    lines = calculate_lifetime(lifetime(CapacityRelationship.dedicated), [], None, attempts=[attempt(5, 20)])
    assert all(phase["amount"] is None and phase["charged_seconds"] is None
               for line in lines for phase in line.phases)


def test_incomplete_resource_does_not_invent_a_finish_or_a_zero_cost():
    item = lifetime(CapacityRelationship.dedicated)
    item.observed_end = None
    [phase] = calculate_lifetime(item, [], price(), attempts=[attempt(5, 20)])[0].phases
    assert phase["phase"] == "unattributed"
    assert phase["finished_at"] is None
    assert phase["observed_seconds"] is None
    assert phase["amount"] is None


def test_rounding_preserves_the_stored_amount_without_negative_tiny_phases():
    from rainstone.costing import _stored_allocations

    allocations = [{"amount": "0.0000000000004"} for _ in range(5)]
    stored = _stored_allocations(allocations, Decimal("0.000000000002"))
    assert sum(Decimal(item["amount"]) for item in stored) == Decimal("0.000000000002")
    assert all(Decimal(item["amount"]) >= 0 for item in stored)
    assert allocations[0]["amount"] == "0.0000000000004"


def test_phase_amounts_are_already_rounded_to_the_stored_resource_total():
    line = phases_for(30, [attempt(5, 20)], price("0.262028"))
    assert line.amount == Decimal("0.004367133333")
    assert sum(Decimal(phase["amount"]) for phase in line.phases) == line.amount
    assert sum(Decimal(allocation["amount"]) for allocation in line.allocations) == line.amount
