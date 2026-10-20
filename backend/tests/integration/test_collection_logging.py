import logging
import uuid
from datetime import UTC, datetime

from rainstone.adapters.contracts import ObservationBatch
from rainstone.collector import Collector, ScheduledSource
from rainstone.config import Settings
from rainstone.db import engine
from rainstone.ingestion import stable_id
from rainstone.models import Job, Owner, Tenant
from sqlalchemy import delete
from sqlalchemy.orm import Session


def test_progress_aggregates_pages_and_reports_scoped_missing_resources(caplog, monkeypatch):
    slug = f"logging-{uuid.uuid4()}"
    tenant_id, owner_id = stable_id("tenant", slug), uuid.uuid4()
    stamp = datetime.now(UTC)
    with Session(engine) as session:
        session.add(Tenant(id=tenant_id, slug=slug, display_name="Logging", capabilities={}))
        session.flush()
        session.add(Owner(id=owner_id, tenant_id=tenant_id, source_id="private-owner", label="Owner"))
        session.flush()
        session.add(Job(id=uuid.uuid4(), tenant_id=tenant_id, owner_id=owner_id, source_id="private-job",
                        tool_id="private-tool", state="ok", runner="gcp_batch", created_at=stamp, updated_at=stamp))
        session.commit()

    class Adapter:
        source_name = "gcp_batch"

        def collect(self, cursor):
            return ObservationBatch(source=self.source_name, observed_at=stamp, metrics={
                "targets": 100, "observed": 25, "terminal_offset": 50,
                "private_field": "not for logs",
            })

    logger = logging.getLogger("rainstone.collector")
    monkeypatch.setattr(logger, "propagate", False)
    logger.addHandler(caplog.handler)
    now = [0]
    process = Collector(Settings(tenant_slug=slug, auth_mode="development", demo_data=True),
                        [ScheduledSource(Adapter(), 1)], engine=engine, clock=lambda: now[0])
    try:
        with caplog.at_level(logging.INFO, logger="rainstone.collector"):
            process.collect_source(process._sources[0])
            now[0] = 30
            process.collect_source(process._sources[0])
            process.log_progress()
            assert not caplog.records
            now[0] = 60
            process.log_progress()
            fields = caplog.records[-1].fields
            assert fields["sources"]["gcp_batch"]["pages"] == 2
            assert fields["sources"]["gcp_batch"]["observed"] == 25
            assert fields["finished_batch_jobs_without_resources"] == 1
            assert "private" not in str(fields)
            assert "not for logs" not in str(fields)
            now[0] = 120
            process.collect_source(process._sources[0])
            process.log_progress()
            assert len(caplog.records) == 1
            now[0] = 360
            process.log_progress()
            assert len(caplog.records) == 2
            assert caplog.records[-1].fields["active"] is False
    finally:
        logger.removeHandler(caplog.handler)
        with Session(engine) as session:
            session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            session.commit()
