#!/usr/bin/env python3
"""Generate `fixtures/runs-demo.json`: about 150 workflow runs over two months.

The output holds observations only: jobs, their attempts and the resource
lifetimes they used. Every cost is then produced by the real ingestion and
costing path, against the same price entries `phase1.json` carries, so nothing
here states an amount. The generator is deterministic; regenerating must leave
the committed file unchanged.

Run it from the repository root:

    python scripts/generate_run_demo.py
"""

import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE_FIXTURE = ROOT / "fixtures" / "phase1.json"
OUTPUT = ROOT / "fixtures" / "runs-demo.json"

SEED = 20260929
OBSERVED_AT = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
PERIOD_START = datetime(2026, 8, 1, tzinfo=UTC)
PERIOD_END = datetime(2026, 9, 28, 23, tzinfo=UTC)
FIRST_JOB_NUMBER = 1000

# Shapes the bundled price catalog covers, and one it does not.
PRICED = ("n2-standard-2", "n2-highcpu-2", "n2-highmem-4")
UNPRICED_SHAPE = "c3-standard-8"
EXISTING_SHAPE = "t2d-standard-4"


@dataclass(frozen=True)
class Step:
    name: str
    tool: str
    minutes: tuple[int, int]
    shape: str | None = PRICED[0]  # None runs on the existing Galaxy server
    fanout: int = 1


@dataclass(frozen=True)
class Workflow:
    slug: str
    name: str
    runs: int
    steps: tuple[Step, ...]
    # Runs of the same stored workflow made under a different saved version.
    saved_versions: int = 1


TOOLSHED = "toolshed.g2.bx.psu.edu/repos"

WORKFLOWS = (
    Workflow("variant-calling", "Variant calling, one sample", 55, (
        Step("quality", f"{TOOLSHED}/devteam/fastqc/fastqc/0.74+galaxy1", (2, 5), "n2-standard-2"),
        Step("align", f"{TOOLSHED}/devteam/bwa/bwa_mem/0.7.17.2", (12, 30), "n2-highmem-4"),
        Step("call", f"{TOOLSHED}/iuc/lofreq_call/lofreq_call/2.1.5+galaxy0", (8, 22), "n2-highmem-4"),
    ), saved_versions=2),
    Workflow("qc-trimming", "Quality control and trimming", 22, (
        Step("quality", f"{TOOLSHED}/devteam/fastqc/fastqc/0.74+galaxy1", (1, 3), None),
        Step("trim", f"{TOOLSHED}/pjbriggs/trimmomatic/trimmomatic/0.39+galaxy2", (3, 9), "n2-highcpu-2"),
    )),
    Workflow("rna-seq", "RNA-seq differential expression", 18, (
        Step("trim", f"{TOOLSHED}/pjbriggs/trimmomatic/trimmomatic/0.39+galaxy2", (4, 8), "n2-highcpu-2"),
        Step("map", f"{TOOLSHED}/iuc/rgrnastar/rna_star/2.7.11a+galaxy0", (25, 55), "n2-highmem-4", 3),
        Step("count", f"{TOOLSHED}/iuc/featurecounts/featurecounts/2.0.3+galaxy2", (6, 14), "n2-standard-2"),
        Step("differential", f"{TOOLSHED}/iuc/deseq2/deseq2/2.11.40.8+galaxy0", (5, 12), "n2-standard-2"),
    ), saved_versions=3),
    Workflow("chip-seq", "ChIP-seq peak calling", 14, (
        Step("align", f"{TOOLSHED}/devteam/bowtie2/bowtie2/2.5.3+galaxy0", (15, 40), "n2-highmem-4"),
        Step("filter", f"{TOOLSHED}/devteam/samtools_view/samtools_view/1.15.1+galaxy0", (3, 8), None),
        Step("peaks", f"{TOOLSHED}/iuc/macs2/macs2_callpeak/2.2.9.1+galaxy0", (6, 18), "n2-standard-2"),
    )),
    Workflow("single-cell", "Single-cell clustering", 12, (
        Step("filter", f"{TOOLSHED}/iuc/scanpy_filter_cells/scanpy_filter_cells/1.8.1+galaxy9", (5, 12), "n2-standard-2"),
        Step("normalize", f"{TOOLSHED}/iuc/scanpy_normalize_data/scanpy_normalize_data/1.8.1+galaxy9", (4, 10), "n2-standard-2"),
        Step("cluster", f"{TOOLSHED}/iuc/scanpy_cluster_reduce_dimension/scanpy_cluster_reduce_dimension/1.8.1+galaxy9", (30, 80), "n2-highmem-4"),
        Step("plot", f"{TOOLSHED}/iuc/scanpy_plot/scanpy_plot/1.8.1+galaxy9", (3, 6), None),
    )),
    Workflow("amplicon", "Amplicon analysis, batch of samples", 10, (
        Step("trim", f"{TOOLSHED}/pjbriggs/trimmomatic/trimmomatic/0.39+galaxy2", (3, 7), "n2-highcpu-2", 4),
        Step("denoise", f"{TOOLSHED}/iuc/dada2_denoiseSingle/dada2_denoiseSingle/1.28+galaxy0", (20, 45), "n2-highmem-4"),
    )),
    Workflow("metagenomics", "Metagenomic profiling", 10, (
        Step("host-removal", f"{TOOLSHED}/devteam/bowtie2/bowtie2/2.5.3+galaxy0", (45, 90), "n2-highmem-4"),
        Step("classify", f"{TOOLSHED}/iuc/kraken2/kraken2/2.1.3+galaxy1", (90, 240), "n2-highmem-4"),
        Step("summarize", f"{TOOLSHED}/iuc/taxonomy_krona_chart/taxonomy_krona_chart/2.7.1+galaxy0", (4, 9), "n2-standard-2"),
    )),
    Workflow("assembly", "Genome assembly", 7, (
        Step("correct", f"{TOOLSHED}/iuc/flye/flye/2.9.5+galaxy0", (120, 300), "n2-highmem-4"),
        Step("polish", f"{TOOLSHED}/iuc/medaka_consensus_pipeline/medaka_consensus_pipeline/1.7.2+galaxy0", (60, 200), "n2-highmem-4"),
        Step("report", f"{TOOLSHED}/iuc/quast/quast/5.3.0+galaxy0", (6, 14), "n2-standard-2"),
    )),
)

OWNER_WEIGHTS = (("alice", 60), ("bob", 35), ("admin", 5))


def iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Builder:
    def __init__(self) -> None:
        self.random = random.Random(SEED)
        self.jobs: list[dict] = []
        self.invocations: list[dict] = []
        self.next_job = FIRST_JOB_NUMBER
        self.next_vm = 1

    def owner(self) -> str:
        names, weights = zip(*OWNER_WEIGHTS, strict=True)
        return self.random.choices(names, weights)[0]

    def job(
        self, owner: str, step: Step, created: datetime, *, shape: str | None,
        state: str = "ok", minutes: float | None = None, running: bool = False,
        evidence: bool = True,
    ) -> tuple[dict, datetime]:
        """One job with one attempt; returns it and when its resources were released."""
        number = self.next_job
        self.next_job += 1
        source_id = str(number)
        duration = timedelta(minutes=minutes if minutes is not None else self.random.uniform(*step.minutes))
        outcome = {"ok": "ok", "error": "error", "running": "running", "deleted": "error"}[state]
        if shape is None:
            begin = created + timedelta(seconds=self.random.randint(5, 40))
            resource_start = begin - timedelta(seconds=self.random.randint(1, 4))
            lifetime = {
                "resource_uid": "baseline-vm-demo", "provider": "gcp", "region": "us-central1",
                "machine_type": EXISTING_SHAPE, "purchase_model": "on_demand",
                "capacity_relationship": "existing",
                "timing_method": "kubernetes_pod_occupancy", "requested_vcpu": 1,
                "requested_memory_mib": 3891.2, "facts": {"isolation": "pod_request"},
                "resource_key": f"pod-runs-demo-{number}",
            }
            runner, destination = "kubernetes", "k8s"
        else:
            wait = self.random.randint(35, 110)
            resource_start = created + timedelta(seconds=wait)
            begin = resource_start + timedelta(seconds=self.random.randint(25, 75))
            vm = self.next_vm
            self.next_vm += 1
            lifetime = {
                "resource_uid": f"batch-vm-runs-demo-{vm}", "provider": "gcp",
                "region": "us-central1", "machine_type": shape, "purchase_model": "on_demand",
                "capacity_relationship": "dedicated",
                "timing_method": "compute_insert_complete_to_delete_request",
                "requested_vcpu": 2, "requested_memory_mib": 8192,
                "facts": {"actual_vcpu": 4, "actual_memory_mib": 32768, "disk_excluded": True},
                "resource_key": f"vm-runs-demo-{vm}",
            }
            runner, destination = "gcp_batch", "batch-jobs"
        finish = begin + duration
        release = finish + timedelta(seconds=self.random.randint(4, 40))
        attempt = {
            "source_attempt_id": "galaxy-0" if shape is None else "batch-task-0-attempt-0",
            "runner": runner, "external_id": f"runs-demo-{number}", "outcome": outcome,
            "tool_started_at": iso(begin),
            "tool_finished_at": None if running else iso(finish),
        }
        if evidence:
            attempt["lifetimes"] = [{
                **lifetime, "observed_start": iso(resource_start),
                "observed_end": None if running else iso(release),
            }]
        else:
            # Galaxy recorded the run but no evidence of where it ran survives.
            attempt["runner"], attempt["source_attempt_id"] = "legacy", "galaxy-0"
            attempt["lifetimes"] = []
            runner, destination = "legacy", "legacy"
        job = {
            "source_id": source_id, "owner_source_id": owner, "tool_id": step.tool,
            "tool_version": step.tool.rsplit("/", 1)[-1], "state": state, "runner": runner,
            "destination": destination, "created_at": iso(created),
            "updated_at": iso(created if running else release), "copied_from_source_id": None,
            "attempts": [attempt],
        }
        self.jobs.append(job)
        return job, release

    def run(
        self, workflow: Workflow, index: int, owner: str, started: datetime, *,
        outcome: str = "completed", unpriced: bool = False, missing_evidence: bool = False,
        nested: bool = False,
    ) -> dict:
        """One workflow run: steps in sequence, each starting when the last ended."""
        slug = workflow.slug
        version = 1 + index % workflow.saved_versions
        memberships: list[dict] = []
        cursor = started
        failed_at = self.random.randrange(len(workflow.steps)) if outcome == "failed" else None
        # The second step is the one still running, so it began after the run did.
        running_at = 1 if outcome == "running" else None
        stop_at = failed_at if failed_at is not None else running_at
        cancelled_at = 1 if outcome == "cancelled" else None
        for position, step in enumerate(workflow.steps):
            if stop_at is not None and position > stop_at:
                break
            if cancelled_at is not None and position > cancelled_at:
                break
            shape = step.shape
            if unpriced and position == 0 and shape is not None:
                shape = UNPRICED_SHAPE
            ends = []
            for element in range(step.fanout):
                state, minutes, running = "ok", None, False
                if position == failed_at:
                    state, minutes = "error", self.random.uniform(0.5, 4)
                if position == running_at:
                    state, running = "running", True
                if position == cancelled_at:
                    state, minutes = "deleted", self.random.uniform(0.5, 3)
                created = cursor + timedelta(seconds=self.random.randint(4, 30) + element * 3)
                job, release = self.job(
                    owner, step, created, shape=shape, state=state, minutes=minutes,
                    running=running,
                    evidence=not (missing_evidence and position == len(workflow.steps) - 1),
                )
                ends.append(release)
                key = f"{step.name}/element-{element}" if step.fanout > 1 else step.name
                memberships.append({
                    "job_source_id": job["source_id"], "step_key": key,
                    "relationship": "collection" if step.fanout > 1 else "direct",
                })
            cursor = max(ends) + timedelta(seconds=self.random.randint(10, 60))
        run_id = f"run-demo-{len(self.invocations) + 1:04d}"
        family = f"wf-family-{slug}"
        invocation = {
            "source_id": run_id, "owner_source_id": owner, "parent_source_id": None,
            "workflow_id": f"wf-{slug}-v{version}", "workflow_family_id": family,
            "workflow_name": workflow.name, "workflow_version": f"wf-{slug}-v{version}",
            "state": "cancelled" if outcome == "cancelled" else "scheduled",
            "created_at": iso(started), "jobs": memberships,
        }
        self.invocations.append(invocation)
        if nested:
            self.nest(invocation, workflow)
        return invocation

    def nest(self, root: dict, workflow: Workflow) -> None:
        """Move a run's collection steps into a child workflow, as Galaxy nests them."""
        moved = [m for m in root["jobs"] if m["relationship"] == "collection"]
        if not moved:
            return
        child_id = f"{root['source_id']}-child"
        self.invocations.append({
            "source_id": child_id, "owner_source_id": root["owner_source_id"],
            "parent_source_id": root["source_id"], "workflow_id": f"{root['workflow_id']}-sub",
            "workflow_family_id": f"{root['workflow_family_id']}-sub",
            "workflow_name": f"{workflow.name}, collection step", "workflow_version": "1",
            "state": root["state"], "created_at": root["created_at"],
            "jobs": [{**m, "step_key": m["step_key"].split("/", 1)[-1]} for m in moved],
        })
        # The root also reaches those jobs through the child, so the same job
        # is a member of both and must be counted once for the root.
        root["jobs"] = [
            *[m for m in root["jobs"] if m["relationship"] != "collection"],
            *[{**m, "relationship": "descendant_collection"} for m in moved],
        ]

    def standalone(self, count: int) -> None:
        """Individual tool runs outside any workflow, which only Overview counts."""
        tools = (
            ("fastp", f"{TOOLSHED}/iuc/fastp/fastp/0.23.4+galaxy0", (2, 12), PRICED[0]),
            ("multiqc", f"{TOOLSHED}/iuc/multiqc/multiqc/1.27+galaxy1", (1, 4), None),
            ("samtools", f"{TOOLSHED}/devteam/samtools_sort/samtools_sort/2.0.5", (3, 20), PRICED[1]),
            ("blast", f"{TOOLSHED}/devteam/ncbi_blast_plus/ncbi_blastn_wrapper/2.14.1+galaxy2", (10, 60), PRICED[2]),
        )
        span = (PERIOD_END - PERIOD_START).total_seconds()
        for _ in range(count):
            _, tool, minutes, shape = self.random.choice(tools)
            created = PERIOD_START + timedelta(seconds=self.random.uniform(0, span))
            self.job(
                self.owner(), Step("single", tool, minutes, shape), created, shape=shape,
            )

    def share_jobs(self) -> None:
        """Let a later run of the same owner reach a job an earlier run made.

        Galaxy can reuse an earlier job's outputs, so one job can belong to more
        than one run. Two pairs are shared: one inside a workflow, one across.
        """
        by_owner: dict[str, list[dict]] = {}
        for invocation in self.invocations:
            if invocation["parent_source_id"] is None and invocation["jobs"]:
                by_owner.setdefault(invocation["owner_source_id"], []).append(invocation)
        alice = by_owner["alice"]
        same = [i for i in alice if i["workflow_name"] == WORKFLOWS[0].name]
        middle = same[len(same) // 2]
        other = [
            i for i in alice
            if i["workflow_name"] == WORKFLOWS[2].name and i["created_at"] > middle["created_at"]
        ]
        quarter = len(same) // 4
        for earlier, later in ((same[quarter], same[quarter + 1]), (middle, other[0])):
            reused = earlier["jobs"][0]
            later["jobs"].append({
                "job_source_id": reused["job_source_id"], "step_key": "reused-input",
                "relationship": "reused",
            })


def start_times(builder: Builder, workflow: Workflow) -> list[datetime]:
    """Spread runs over the period, in bursts of one owner's samples."""
    span = (PERIOD_END - PERIOD_START).total_seconds()
    starts: list[datetime] = []
    while len(starts) < workflow.runs:
        remaining = workflow.runs - len(starts)
        if remaining >= 6 and builder.random.random() < 0.45:
            anchor = PERIOD_START + timedelta(seconds=builder.random.uniform(0, span))
            burst = min(remaining, builder.random.randint(6, 12))
            starts += [anchor + timedelta(seconds=90 * n) for n in range(burst)]
        else:
            starts.append(PERIOD_START + timedelta(seconds=builder.random.uniform(0, span)))
    return sorted(starts)


def build() -> dict:
    base = json.loads(BASE_FIXTURE.read_text())
    builder = Builder()
    special = {
        # Runs that cross the month edge, so a period boundary splits their cost.
        "month_edge": [datetime(2026, 8, 31, 22, 40, tzinfo=UTC) + timedelta(minutes=17 * n) for n in range(5)],
        # Still running when the data was observed.
        "running": [OBSERVED_AT - timedelta(minutes=m) for m in (95, 60, 25)],
    }
    plan: list[tuple[Workflow, int, datetime, dict]] = []
    for workflow in WORKFLOWS:
        starts = start_times(builder, workflow)
        for index, started in enumerate(starts):
            plan.append((workflow, index, started, {}))
    # Assign the special outcomes to distinct existing plan entries.
    order = list(range(len(plan)))
    builder.random.shuffle(order)
    failed, cancelled, unpriced = order[:13], order[13:14], order[14:18]
    finished = [i for i in order[18:] if not plan[i][3]]
    missing = finished[:3]
    nested = [i for i in finished[3:] if plan[i][0].steps[1].fanout > 1][:3]
    for i in failed:
        plan[i][3]["outcome"] = "failed"
    for i in cancelled:
        plan[i][3]["outcome"] = "cancelled"
    for i in unpriced:
        plan[i][3]["unpriced"] = True
    for i in missing:
        plan[i][3]["missing_evidence"] = True
    for i in nested:
        plan[i][3]["nested"] = True
    # Month-edge and running runs replace the last runs of a busy workflow, so
    # the total stays near 150 while their timing is exactly as intended.
    edge_slots = [i for i, (w, *_rest) in enumerate(plan) if w.slug == "rna-seq"][:5]
    running_slots = [i for i, (w, *_rest) in enumerate(plan) if w.slug == "variant-calling"][-3:]
    for slot, when in zip(edge_slots, special["month_edge"], strict=True):
        workflow, index, _, options = plan[slot]
        plan[slot] = (workflow, index, when, {k: v for k, v in options.items() if k != "outcome"})
    for slot, when in zip(running_slots, special["running"], strict=True):
        workflow, index, _, _options = plan[slot]
        plan[slot] = (workflow, index, when, {"outcome": "running"})
    # Runs started close together by one workflow are one person's batch.
    last: dict[str, tuple[str, datetime]] = {}
    for workflow, index, started, options in sorted(plan, key=lambda item: item[2]):
        owner, previous = last.get(workflow.slug, (None, None))
        if owner is None or started - previous > timedelta(minutes=30):
            owner = builder.owner()
        last[workflow.slug] = (owner, started)
        builder.run(workflow, index, owner, started, **options)
    builder.standalone(40)
    builder.share_jobs()
    return {
        "schema_version": base["schema_version"],
        "fixture_id": "runs-demo-2026-09-29-v1",
        "observed_at": iso(OBSERVED_AT),
        "tenant": base["tenant"],
        "owners": base["owners"],
        "policies": base["policies"],
        "prices": base["prices"],
        "jobs": builder.jobs,
        "invocations": builder.invocations,
        "infrastructure_intervals": [],
    }


def render(data: dict) -> str:
    """One job or run per line: a reviewable file that diffs sensibly."""
    lines = ["{"]
    keys = list(data)
    for position, key in enumerate(keys):
        value = data[key]
        tail = "," if position < len(keys) - 1 else ""
        if isinstance(value, list) and value and isinstance(value[0], dict) and key in {"jobs", "invocations"}:
            lines.append(f'  "{key}": [')
            lines += [
                f"    {json.dumps(item, separators=(',', ':'))}{',' if n < len(value) - 1 else ''}"
                for n, item in enumerate(value)
            ]
            lines.append(f"  ]{tail}")
        else:
            lines.append(f'  "{key}": {json.dumps(value, separators=(",", ":"))}{tail}')
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> None:
    data = build()
    OUTPUT.write_text(render(data))
    print(f"{OUTPUT.relative_to(ROOT)}: {len(data['invocations'])} invocations, {len(data['jobs'])} jobs")


if __name__ == "__main__":
    main()
