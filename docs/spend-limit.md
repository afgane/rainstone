# Batch spend limits

On a single-user AnVIL Galaxy, Rainstone can pause new GCP Batch dispatch
when estimated Batch compute approaches a limit the user sets. It can
also ask Galaxy to stop outstanding Batch jobs. The limit is optional
and inactive on a new installation until the user saves one.

## What the user sets

Open **Set a Batch spend limit** in Rainstone's masthead. The amount is a
ceiling over the deployment's recorded Batch history, including spending
before activation. It is not an extra allowance. With $3.00 recorded, a
$5.00 ceiling leaves $2.00 before the nominal limit. The server rejects a
ceiling at or below the latest recorded amount.

The slider and amount field stay synchronized. The switch for stopping
running jobs is off initially: existing Batch jobs finish and keep adding
costs. Turning it on requests cancellation when the guard triggers.
Stopped jobs are not restarted, and workflow runs containing them remain
failed. Jobs that fit on the already-running Galaxy server keep running.

The limit covers estimated Batch compute only. It excludes the Galaxy
server, disks, network, discounts, credits and taxes. Earlier Batch work
that Rainstone cannot reconstruct is also excluded; Spending details
shows the data start, observation time and missing cost data. An unknown
cost is never presented as zero.

The guard is best effort. Collection and shutdown take time, and final
spending can exceed the ceiling. This is particularly important when
existing jobs are allowed to finish: their continued spending has no
upper bound from the guard. The Galaxy server keeps running. Shutting it
down while retaining its persistent disk is not implemented.

## Supported deployment

Use chart `0.4.0` / Rainstone `2.0.0b2` or later with:

- The `anvil-workspace` identity mode and one fixed Galaxy account. People
  admitted by the workspace's existing route may change the shared limit.
- Galaxy 26.2 or later, with fair dispatch past deferred ready jobs.
  Deployments adding resubmission rules also need the correction below.
- GCP Batch observations and prices for this deployment's Galaxy jobs.
- One existing Rainstone collector; no additional process or pod.
- A shared dispatch-state Secret and a collector-only Galaxy API key
  belonging to an administrator account.

The default AnVIL job configuration and shared TPV database do not define
resubmission rules, so the default guard does not require a Galaxy patch.
Before adding such rules, use a Galaxy image that catches
`JobNotReadyException` while recovering a resubmission's mapped
destination. Without that generic correction a waiting retry interrupts
the poll and prevents other ready jobs from running. The correction and
regression test are prepared as Galaxy commit `284a6a6dbd`, pending review
and publication. Keep that prerequisite explicit for custom deployments;
a live ConfigMap override is not a release substitute.

## Configuration

The default reporting chart leaves `spendGuard.enabled` false. AnVIL's
k8s-boot playbook enables it when Batch and Galaxy's single-user mode are
on, provisions the Secrets, installs the TPV helper and rule, and enables
Galaxy notifications. None of these steps sets a spending ceiling.

For another compatible deployment, provide the equivalent wiring:

```yaml
spendGuard:
  enabled: true
  stateSecret: rainstone-dispatch
  stateSecretKey: token
  galaxyUrl: http://galaxy-nginx:8000/galaxy
  galaxySecret: rainstone-galaxy-control
  galaxySecretKey: api-key
  reactionSeconds: 600
  staleSeconds: 600
  controlBudgetSeconds: 10
```

The Secrets must already exist in Rainstone's namespace. The dispatch
Secret contains a random shared credential. Mount the same credential
into the Galaxy handler for its TPV helper. The control Secret holds an
ordinary Galaxy administrator API key; the bootstrap admin key is not
Rainstone's long-lived credential. Do not put either value in Helm values
or source control.

The chart values map to the application's environment settings:

- `enabled` → `RAINSTONE_GUARD_ENABLED`: expose the policy and evaluate it.
- `stateSecret` / `stateSecretKey` → `RAINSTONE_GUARD_TOKEN`: authenticate
  TPV's state requests.
- `galaxyUrl` → `RAINSTONE_GUARD_GALAXY_URL`: Galaxy's internal base URL.
- `galaxySecret` / `galaxySecretKey` → `RAINSTONE_GUARD_GALAXY_API_KEY`:
  collector-only notification and job control.
- `reactionSeconds` → `RAINSTONE_GUARD_REACTION_SECONDS`: reaction
  allowance; default 600 seconds.
- `staleSeconds` → `RAINSTONE_GUARD_STALE_SECONDS`: notify at this data
  age; default 600 seconds.
- `controlBudgetSeconds` → `RAINSTONE_GUARD_CONTROL_BUDGET_SECONDS`:
  control-pass budget; default 10 seconds.

The page URL in a broadcast is recorded when the browser saves a policy.
This is a full URL because Galaxy routes path-only links inside its own
client. `RAINSTONE_GUARD_PAGE_URL`, derived from the chart's `basePath`, is
the fallback for policies created without a browser URL.

The web process holds the dispatch token but not the Galaxy control key.
Only the collector gets that key, alongside its existing read-only cloud
observation access. Rainstone never deletes provider resources directly:
Galaxy's Batch runner performs deletion. No new cloud write permission is
needed. Regenerating the shared user's API key breaks notifications and
cancellation until k8s-boot is rerun to refresh the Secret; failures appear
on the limit page and retry.

The TPV rule belongs on the `gcp_batch` destination and raises
`TryNextDestinationOrWait` when Rainstone returns `paused: true`. A job
that fits a later server destination falls back to it; otherwise it waits.
The helper caches state for five seconds, times out after two seconds,
and admits jobs if the state service is unavailable or malformed. Allow
Galaxy handlers to reach the Rainstone service if network policies are on.
The internal endpoint exposes only the pause boolean and requires the
shared Bearer credential.

## Evaluation and recovery

The ceiling includes failed Batch jobs and chargeable retries, counting
each attributable VM lifetime once. Closed lifetimes use the same stored
cost lines as reports. Active lifetimes accrue through their own last
observation; reading the page does not advance that observation.

The margin is the larger of $0.25 and the sum, over running VMs, of:

```text
VM hourly price × (reaction allowance + age of that VM's observation)
```

The guard triggers when the known Batch subtotal plus this margin reaches
the ceiling, comparing unrounded decimal values. A valid ceiling can be
within the margin already and therefore trigger immediately. The UI makes
this visible. One stale VM widens the margin by its own rate, without
holding back accrual for other VMs.

The ten-minute default allowance follows measurements on a test AnVIL
deployment: a running VM's cleanup was verified after about 107 seconds,
while stopping a VM still provisioning took roughly seven minutes for
provider removal and nearly ten minutes including verification backoff.
These measurements are not a bound on future cloud behavior. Adjust the
allowance deliberately for the deployment's observed delay.

The collector evaluates after new facts and while waiting for sources.
Control calls run at most once per collection interval, or immediately
on a new trigger. The control budget is checked between calls; a request
already underway can finish within its own timeout. Stops are sent before
cleanup verification, so a slow provider read does not delay other stops.
Missing observations alone do not pause jobs or request cancellation.

A trigger is durable across browser, collector and Galaxy restarts. Cost
corrections do not clear it. Raise the ceiling to resume, or turn it off.
Changing the stop choice on a triggered limit can request stops without
reopening Batch dispatch. Already-sent stops cannot be undone; their
cleanup checks continue after the limit is turned off. Unsent stops from
a resumed trigger are discarded.

Galaxy acceptance, provider VM removal and final cost reconciliation are
separate facts. The UI keeps failures and pending cleanup visible. A job
cancelled before its VM lifetime was observed can retain unavailable cost
data even after cleanup is verified. No zero or completed cost is invented
for that missing evidence.

The collector posts and withdraws Galaxy broadcasts for a trigger, cost
data older than the stale threshold, and unpriced running Batch resources.
Broadcast identity and retry state survive restarts. If the collector
itself is down it cannot evaluate or notify; the observation time remains
the last known time. Monitoring that process from outside Rainstone is
outside this capability.

## Upgrades, source changes and release order

Keep Rainstone's database and instance slug across upgrades. Activation,
report filters, calendar boundaries and Galaxy VM restarts do not reset
accumulated cost or the guard. Source replacement is refused while the old
source has an active limit; explicitly turn it off before re-enrolling.
A fresh database starts with no limit and cannot inherit an old database's
policy or reconstruct all missing history automatically.

Use linked Rainstone and k8s-boot PRs. The Rainstone PR must be merged,
tested, and publish its image followed by its immutable chart package
before the playbook PR selecting that chart is merged. For a deployment enabling resubmissions, the Galaxy image correction
must also be available first. Validate the published package
on a fresh installation, with no source or static-file overlays, and
verify that all active Kubernetes CPU requests remain below three cores.
