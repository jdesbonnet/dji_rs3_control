# Things To Do

## Improve `state --watch` reliability and behavior

### Problem summary

`python3 -m rs3.cli.ctl state --watch --seconds 10` is currently hit-and-miss.
It can print repeated timeout lines even though one-shot state retrieval works.

Observed behavior:

- One-shot active state often succeeds:
  - `python3 -m rs3.cli.ctl state --timeout 5 --raw`
- Watch mode can emit repeated:
  - `state pose=unavailable timeout`
- A more tolerant runtime invocation is currently more reliable:
  - `python3 -m rs3.cli.ctl state --watch --seconds 20 --timeout 8 --poll-interval 0.5`

### Current implementation context

Relevant files:

- `python/rs3/cli/ctl.py`
- `python/rs3/client.py`
- `python/rs3/models.py`
- `python/rs3/protocol/telemetry.py`

Current flow:

1. `ctl.py` watch mode loops and repeatedly calls `RS3Client.request_state(...)`.
2. `request_state(...)` in `client.py` returns only when a *fresh* pose sample
   arrives after the function call start time.
3. If no new pose sample arrives before timeout, `request_state(...)` raises
   `TimeoutError`.
4. `ctl.py` currently prints `state pose=unavailable timeout` on each timeout.

Important implementation detail:

- `TelemetrySnapshot.pose_timestamp` was added so fresh-pose detection can be
  done independently of other telemetry updates.

### Suspected root cause

Watch mode is too strict for intermittent pose cadence. It treats "no new pose
sample during this window" as total failure instead of returning last-known
pose with freshness metadata.

### Desired behavior

- Watch mode should degrade gracefully when pose updates are sparse.
- If at least one pose has been seen this session, continue reporting pose with
  age/freshness instead of frequent timeout errors.
- Keep hard timeout behavior for startup cases where no pose has ever been
  observed.

### Proposed implementation approach

1. In `RS3Client.request_state(...)`, add an optional fallback mode:
   - return last-known pose when timeout expires and `allow_stale=True`.
2. In `ctl.py` watch mode:
   - during startup, require first fresh pose (or timeout message).
   - after first successful pose, allow stale fallback and print pose age.
3. Add explicit freshness marker in output:
   - example: `fresh=true|false` or `stale=true|false`.
4. Keep active polling defaults, but avoid timeout spam once baseline pose is
   established.

### Acceptance criteria

1. `state --watch` runs for 20s without repeated timeout spam after initial
   pose lock.
2. Output still indicates freshness/age clearly.
3. One-shot behavior remains unchanged unless explicitly configured.
4. Passive mode (`--passive`) behavior remains correct.
