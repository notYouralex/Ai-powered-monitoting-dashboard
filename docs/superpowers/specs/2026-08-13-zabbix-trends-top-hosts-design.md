# Zabbix Trends and Top Affected Hosts Design

**Date:** 2026-08-13
**Branch:** `feature/zabbix-hosts`
**Owner boundary:** Intern B / `app/integrations/zabbix/`
**Commit policy:** Keep this spec and implementation uncommitted until the user explicitly requests the combined feature commit.

## 1. Goal

Extend the authenticated Zabbix dashboard with a bounded 24-hour CPU/memory/disk trend for the most affected enabled hosts and a deterministic top-affected-host ranking, while preserving the existing host availability, active problems, and current resource-pressure behavior.

The repository roadmap lists the Zabbix infrastructure sequence as host availability, active problems, CPU/memory/disk pressure, trend, top affected hosts, caching/staleness, Grafana provisioning, and AI infrastructure summary. This slice implements only trend and top affected hosts.

## 2. Scope

In scope:

- deterministic ranking of at most 10 enabled hosts;
- current host/problem/interface/resource facts as ranking inputs;
- fixed last-24-completed-UTC-hours resource trend;
- read-only `trend.get` historical retrieval;
- bounded trend item discovery for only the ranked host IDs;
- hourly average CPU, memory, and one selected disk filesystem per host;
- additive `top_affected_hosts` and `resource_trends` response fields;
- safe malformed-source handling and strict bounds;
- route serialization tests.

Out of scope:

- user-selectable time ranges;
- `history.get` raw sample retrieval;
- `event.get` historical problem-event analysis;
- warning/critical utilization thresholds;
- AI-derived or weighted risk scores;
- caching/staleness;
- Grafana provisioning;
- Executive aggregation;
- migrations or shared contracts;
- any Zabbix write method.

## 3. Source API Choice

Use Zabbix 7.4 `trend.get` for resource history. Zabbix trend objects represent hourly aggregates and expose `itemid`, hourly `clock`, and `value_avg`. `trend.get` accepts `itemids`, `time_from`, `time_till`, `output`, and `limit`.

Do not use `history.get` because this dashboard needs an hourly operational trend rather than raw high-volume samples. Do not use `event.get` because this slice trends resource pressure rather than historical problem-event counts.

The production JSON-RPC method literal set becomes exactly:

```text
host.get
problem.get
trigger.get
item.get
trend.get
```

## 4. Dashboard Execution Flow

`ZabbixDashboardService.get_dashboard()` keeps the existing first-stage concurrency:

```text
list_hosts()
list_active_problems()
list_resource_pressure()
```

After those three complete:

1. build the deterministic top-affected-host list from normalized current data;
2. extract at most 10 ranked host IDs;
3. call `list_resource_trends(top_host_ids)`;
4. compose the existing response plus `top_affected_hosts` and `resource_trends`.

If there are no ranked hosts, `list_resource_trends([])` returns `[]` without any Zabbix item or trend request.

If trend retrieval fails with `IntegrationError`, the Zabbix source request fails through the existing safe integration error path. Partial trend snapshots are not returned in this pre-caching slice.

## 5. Top Affected Host Ranking

Only enabled hosts are eligible.

A host becomes a candidate when at least one of the following is true:

- it has an active mapped problem;
- at least one host interface is currently `unavailable`;
- it has at least one normalized current CPU, memory, or disk metric.

For every candidate compute:

- `highest_problem_severity` or `None`;
- `active_problem_count`;
- `unavailable_interface_count`;
- `peak_resource_percent` across current CPU, memory, and all current disks, or `None`;
- `peak_resource` as `cpu`, `memory`, `disk`, or `None`;
- `peak_filesystem` only when the peak resource is disk.

Sort descending by this tuple, with host ID as the final ascending stable tie-break:

1. highest active-problem severity rank;
2. unavailable-interface count;
3. active-problem count;
4. peak current resource utilization.

Severity rank is:

```text
unknown = 7
disaster = 6
high = 5
average = 4
warning = 3
information = 2
not_classified = 1
no active problem = 0
```

`unknown` is deliberately surfaced above known severities so a future/unrecognized source severity cannot be silently deprioritized.

Return at most 10 records.

## 6. Top Host Model

```python
class ZabbixTopAffectedHost(BaseModel):
    host_id: str
    technical_name: str
    name: str
    highest_problem_severity: ZabbixProblemSeverity | None
    active_problem_count: int
    unavailable_interface_count: int
    peak_resource_percent: float | None
    peak_resource: Literal["cpu", "memory", "disk"] | None
    peak_filesystem: str | None
```

Bounds follow the existing host/resource models. Counts are nonnegative and percentages stay within `0..100`.

## 7. Trend Window

The trend window is fixed to the last 24 **completed UTC hours**.

For a current UTC time `now`:

```text
current_hour = floor now to HH:00:00 UTC
time_from = current_hour - 24 hours
time_till = current_hour - 1 second
```

Example: at `2026-08-13T08:44:00Z`, retrieve trend rows whose hourly clocks range from `2026-08-12T08:00:00Z` through `2026-08-13T07:00:00Z`.

There is no route query parameter for the range in this slice.

## 8. Trend Item Discovery

`ZabbixClient.list_resource_trends(host_ids)` accepts at most 10 unique, nonblank host IDs. Duplicate IDs are deduplicated in first-seen order. More than 10 unique IDs or an ID longer than 64 characters maps to `SOURCE_BAD_RESPONSE`.

For nonempty host IDs, run three concurrent bounded `item.get` requests for the same prefixes and current-value semantics already used by resource pressure:

```text
system.cpu.util
vm.memory.size
vfs.fs.size
```

Each request adds:

```python
"hostids": host_ids
```

and otherwise uses the current resource-pressure item contract:

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

Each result accepts at most 10,000 rows; 10,001 maps to `SOURCE_BAD_RESPONSE`.

Reuse the current resource selection rules to choose one CPU item and one memory item per host. For disk, choose the currently hottest normalized filesystem for each host; ties choose filesystem name lexically. The selected source item for that filesystem continues to prefer `pused` over `pfree`.

At most 30 item IDs can therefore be selected: 10 hosts × 3 metric classes.

## 9. Exact `trend.get` Request

If no metric items are selected, return `[]` without calling `trend.get`.

Otherwise issue one read-only request:

```python
{
    "output": ["itemid", "clock", "value_avg"],
    "itemids": selected_item_ids,
    "time_from": time_from,
    "time_till": time_till,
    "limit": 721,
}
```

The maximum legitimate payload is 720 rows: 10 hosts × 3 items × 24 completed hours. A 721-row result maps to `SOURCE_BAD_RESPONSE`.

Because `trend.get` does not provide a required sort contract for this slice, normalization sorts output locally.

## 10. Trend Normalization

For every recognized trend row:

- `itemid` must be one of the selected item IDs;
- duplicate `(itemid, clock)` rows are invalid;
- `clock` must be an integer Unix timestamp inside the fixed request window and aligned to a UTC hour boundary;
- `value_avg` must be a finite decimal percentage in `0..100`;
- CPU idle, memory `pavailable`, and disk `pfree` values are inverted with `100 - value_avg`;
- direct memory/disk used percentages are kept as-is;
- normalized values remain in `0..100`.

Missing expected hourly rows are valid no-data gaps and do not fail the source.

Unknown/unrequested item IDs, duplicate rows, malformed timestamps, malformed percentages, or out-of-window rows map to `SOURCE_BAD_RESPONSE`.

## 11. Trend Models

```python
ResourceTrendMetric = Literal["cpu", "memory", "disk"]

class ZabbixResourceTrendPoint(BaseModel):
    observed_at: datetime
    average_used_percent: float

class ZabbixResourceTrend(BaseModel):
    host_id: str
    metric: ResourceTrendMetric
    filesystem: str | None
    points: list[ZabbixResourceTrendPoint]
```

Bounds:

- `points`: maximum 24;
- `resource_trends`: maximum 30 series;
- percentages: `0..100`;
- filesystem: required only for `disk`, omitted/`None` for CPU and memory.

Series ordering is stable by top-host rank first, then metric order `cpu`, `memory`, `disk`. Points are sorted oldest-to-newest.

A selected metric item with no historical rows may be omitted from `resource_trends`; no empty series is required.

## 12. Response Contract

`GET /api/dashboard/zabbix` remains authenticated and keeps all existing fields. Add:

```text
top_affected_hosts[]
resource_trends[]
```

No new summary counters are required for this slice.

## 13. Security and Bounds

- All source access remains read-only.
- No public generic JSON-RPC request/call API is added.
- No credentials, authorization headers, raw response bodies, source stack traces, or production connection strings are logged or serialized.
- Production method literals must be exactly `host.get`, `problem.get`, `trigger.get`, `item.get`, and `trend.get`.
- No `history.get`, `event.get`, or mutation method is allowed.

## 14. Definition of Done

The slice is complete when `/api/dashboard/zabbix` returns deterministic top affected enabled hosts plus bounded hourly CPU/memory/disk trend series for those hosts over the last 24 completed UTC hours; all calls remain read-only; malformed or oversized source data fails safely; focused and full tests pass; and the feature remains uncommitted until explicitly requested.
