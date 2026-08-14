# Zabbix Resource Pressure Integration Design

**Date:** 2026-08-13
**Branch:** `feature/zabbix-hosts`
**Owner boundary:** Intern B / `app/integrations/zabbix/`
**Commit policy:** Keep this spec and its implementation uncommitted until the user requests the combined feature commit.

## 1. Goal

Extend the authenticated Zabbix dashboard response with current CPU, memory, and filesystem utilization percentages while preserving the existing host-availability and active-problem behavior.

This is the third Zabbix capability in the platform sequence: host availability, active problems, CPU/memory/disk pressure, trends, top affected hosts, caching/staleness, Grafana provisioning, and AI infrastructure summary.

## 2. Scope

In scope:

- read-only current resource metrics;
- per-host CPU used percentage;
- per-host memory used percentage;
- per-filesystem disk used percentage;
- source observation timestamps from Zabbix item `lastclock`;
- additive dashboard summary coverage counts;
- bounded warnings for enabled hosts missing current metric coverage;
- authenticated route serialization;
- strict source bounds and safe error mapping.

Out of scope:

- historical `history.get` or `trend.get`;
- trend calculations;
- alert thresholds or trigger creation;
- top affected host ranking;
- caching/staleness policy;
- Grafana provisioning;
- Executive aggregation;
- any Zabbix write method.

## 3. Source API Choice

Use Zabbix 7.4 `item.get`. The item object exposes `lastvalue` and `lastclock`; `item.get` can restrict results to monitored items and search item keys by prefix.

Use three concurrent `item.get` calls because the API search parameter takes one string value per searched field and cannot express an OR across three different `key_` prefixes in one criterion without retrieving unrelated items.

The only new production JSON-RPC method literal is `item.get`. The complete allowed set becomes:

```text
host.get
problem.get
trigger.get
item.get
```

## 4. Public Client Interface

```python
class ZabbixClient:
    async def list_hosts(self) -> list[ZabbixHost]: ...
    async def list_active_problems(self) -> list[ZabbixProblem]: ...
    async def list_resource_pressure(self) -> list[ZabbixResourcePressure]: ...
```

`list_resource_pressure()` executes the CPU, memory, and disk item queries concurrently and returns one normalized record per host that has at least one supported current metric.

## 5. Exact `item.get` Requests

Each request uses:

```python
{
    "output": ["itemid", "hostid", "key_", "lastvalue", "lastclock"],
    "monitored": True,
    "filter": {"state": "0"},
    "search": {"key_": PREFIX},
    "startSearch": True,
    "sortfield": "itemid",
    "limit": 10001,
}
```

Prefixes:

```text
system.cpu.util
vm.memory.size
vfs.fs.size
```

Each result is independently bounded to 10,000 records. A sentinel result of 10,001 maps to `SOURCE_BAD_RESPONSE`.

## 6. Supported Metric Semantics

### CPU

Zabbix `system.cpu.util` reports a percentage for a selected CPU state. Total CPU used percentage is derived from aggregate idle percentage:

```text
cpu_used_percent = 100 - idle_percent
```

Accept aggregate CPU idle items where:

- CPU parameter is empty or `all`;
- state/type is `idle`;
- averaging mode is empty or `avg1`;
- optional AIX logical/physical parameter is empty or `logical`.

Per-core items, non-idle states, avg5/avg15 items, and unrelated keys are ignored.

If more than one supported aggregate-idle candidate exists for one host, choose the candidate with the newest `lastclock`; ties choose the numerically smallest `itemid`. This keeps behavior deterministic across inherited/direct template duplication.

### Memory

Preferred key:

```text
vm.memory.size[pused]
```

Fallback:

```text
vm.memory.size[pavailable]
```

For `pavailable`:

```text
memory_used_percent = 100 - available_percent
```

A direct `pused` candidate takes precedence over `pavailable`. Within the same mode, newest `lastclock` wins; ties choose the numerically smallest `itemid`.

### Disk

Supported keys:

```text
vfs.fs.size[<filesystem>,pused]
vfs.fs.size[<filesystem>,pfree]
```

For `pfree`:

```text
disk_used_percent = 100 - free_percent
```

Normalize one record per filesystem. `pused` takes precedence over `pfree`; within the same mode newest `lastclock` wins and ties choose the numerically smallest `itemid`.

A host may expose at most 64 normalized filesystems. More maps to `SOURCE_BAD_RESPONSE`.

## 7. Value Validation

For recognized metric items:

- `itemid` and `hostid` must be nonblank IDs of at most 64 characters;
- `lastclock` must be a positive Unix timestamp;
- `lastvalue` must parse as a finite decimal number;
- source percentages must be within `0..100` inclusive;
- normalized percentages remain within `0..100` inclusive;
- timestamps normalize to UTC-aware datetimes.

An item with blank `lastvalue` or `lastclock == "0"` is treated as having no current value and is skipped. This is not an integration failure.

Malformed recognized current values map to `SOURCE_BAD_RESPONSE`. Unrecognized keys returned by prefix search are ignored.

## 8. Normalized Models

```python
class ZabbixDiskPressure(BaseModel):
    filesystem: str
    used_percent: float
    observed_at: datetime

class ZabbixResourcePressure(BaseModel):
    host_id: str
    cpu_used_percent: float | None
    cpu_observed_at: datetime | None
    memory_used_percent: float | None
    memory_observed_at: datetime | None
    disks: list[ZabbixDiskPressure]
```

Bounds:

- `host_id`: 1..64 characters;
- `filesystem`: 1..512 characters;
- percentages: `0..100`;
- disks: maximum 64 per host;
- dashboard `resource_pressure`: maximum 5,000 hosts.

Resource-pressure output is sorted by `host_id` using numeric ordering when IDs are numeric, lexical ordering otherwise. Disk rows are sorted by filesystem for stable serialization.

## 9. Dashboard Summary

Add coverage counts:

```text
resource_hosts_total
resource_hosts_with_cpu
resource_hosts_with_memory
resource_hosts_with_disk
```

`resource_hosts_total` counts normalized resource-pressure host records with at least one metric. The other fields count records that expose the corresponding metric class.

No warning/critical thresholds or aggregate averages are introduced in this slice.

## 10. Service Concurrency

The dashboard service concurrently retrieves:

```text
list_hosts()
list_active_problems()
list_resource_pressure()
```

The three internal resource `item.get` calls also run concurrently.

If any client call raises `IntegrationError`, the existing integration error handling fails the Zabbix source safely. Partial source snapshots are not returned.

## 11. Warnings

Existing unmapped-problem warnings remain unchanged.

For enabled dashboard hosts only, add at most three resource coverage warnings:

```text
1 enabled Zabbix host has no current CPU utilization metric.
{n} enabled Zabbix hosts have no current CPU utilization metric.

1 enabled Zabbix host has no current memory utilization metric.
{n} enabled Zabbix hosts have no current memory utilization metric.

1 enabled Zabbix host has no current disk utilization metric.
{n} enabled Zabbix hosts have no current disk utilization metric.
```

Disabled hosts do not create missing-resource warnings. Missing metrics do not degrade `health.status`; they remain top-level dashboard warnings.

## 12. Route Contract

`GET /api/dashboard/zabbix` remains unchanged and authenticated. It serializes the additive fields:

```text
summary.resource_hosts_total
summary.resource_hosts_with_cpu
summary.resource_hosts_with_memory
summary.resource_hosts_with_disk
resource_pressure[]
```

No router production change is expected.

## 13. Security and Bounds

- All calls are read-only.
- No generic public JSON-RPC call surface is added.
- No credentials, authorization headers, raw response bodies, or source error text are logged or returned.
- Result limits are enforced before normalization.
- Existing retry/TLS/error behavior is reused through `_read_jsonrpc`.

## 14. Definition of Done

The slice is complete when authenticated `/api/dashboard/zabbix` returns existing host/problem data plus bounded normalized current CPU, memory, and filesystem utilization percentages; the service and resource subqueries are concurrent; missing metric coverage produces bounded safe warnings; production Zabbix code exposes only `host.get`, `problem.get`, `trigger.get`, and `item.get`; and focused/full validation is green.
