# ADR-004 — Bitemporal Increment Fact & As-Of Reproducibility

**Status:** Accepted
**Context layer:** Storage backbone (how binned counts are recorded so that the past stays reproducible under late data and corrections)
**Depends on:** ADR-002 (Bin Derivation Method) and ADR-003 (Bin Schema Provenance & Lifecycle) — every count recorded here is tagged with the `bin_schema_id` that produced it.
**Project:** BinMoments — Real-Time Distribution Fingerprinting and Anomaly Detection for IoT Streams

---

## Context

A core promise of the system is that a metric is **reproducible as it stood at a past
moment**. If someone made a business decision yesterday based on an instrument's
distribution, the system must be able to show what that distribution *was* when the
decision was made — even though, since then, late-arriving data and corrections may have
changed it. And it must show the *current* value alongside, and make clear that the two
differ and why. Without this, a metric is just "the latest number," with no defensible
record of what was actually known when.

Two things make this hard. **Late data:** readings for a past hour can arrive after that
hour has closed — a sensor reconnects, a backfill runs — so an hour's counts are not final
when the hour ends. **Corrections:** a previously reported value can turn out to be wrong
and need restating. A naive store that *mutates* counts in place handles both by
overwriting — and in doing so destroys the very history the reproducibility promise depends
on. Once yesterday's count is overwritten, "what did I see yesterday" is unanswerable.

The root cause is that a single timestamp conflates two different questions: *which hour is
this measurement about?* and *when did the system learn it?* These are independent. A
reading about 14:00 can be learned at 14:01 (on time), at 23:00 (late), or restated at noon
the next day (correction). Reproducibility requires keeping both axes.

An earlier design considered organizing this as several physical tables bucketed by how late
data arrived (within 1h, 24h, 7d, older). That was reconsidered and rejected — see
alternatives — because those buckets are defined *relative to now*, so a row would have to
migrate from one table to the next as wall-clock time passes, with shifting boundaries and
constant recompute. The cleaner formulation keeps one table and makes lateness a *query*, not
a *location*.

## Decision

**1. Every count carries two explicit time axes — bitemporal modeling.**
   - **Valid time — `event_hour`:** the hour the measurement is *about*.
   - **Transaction time — `arrival_time`:** the instant the system *recorded* the increment.

   "What did I see as of yesterday 17:00" is then an `arrival_time ≤` filter; "how late was
   this data" is `arrival_time − event_hour`. Both axes are first-class, never collapsed into
   one timestamp.

**2. Counts live in a single append-only increment fact. It is never mutated or deleted.**
Each row is a signed delta to one bin:
`(instrument_id, channel, bin_schema_id, bin, event_hour, arrival_time, delta, entry_type)`.
On-time data, late data, and corrections are all **new appended rows** — never updates to
existing ones. The append-only rule is what makes every past state permanently
reconstructible.

**3. Corrections are handled by compensating deltas, not by mutation.** A new or late
measurement appends `delta = +1` to its bin. A correction appends a `delta = −1` to the bin
that was wrong and `delta = +1` to the bin that is right, both stamped with the correction's
`arrival_time` and `entry_type = 'correction'`. The net count at any bin, as of any instant,
is the sum of deltas with `arrival_time ≤` that instant. Corrections are thus **kept separate
and visible** (their own flagged rows) while still folding correctly into the aggregate — the
audit trail is complete because nothing is ever erased.

**4. The fact carries no lateness/horizon column. Lateness is a filter, not a partition.**
"Arrived within 1 hour," "within 24 hours," "final" are all expressed as predicates on
`(arrival_time − event_hour)` over the one fact. There is a single source of truth; no row
ever changes table or bucket as time passes.

**5. Fixed-horizon statistics are derived materializations over the fact, with the horizon as
a column on the *derived* table.** The common questions (1h / 24h / 7d / final) are
precomputed: each materialized row is the statistics for an `(instrument, channel,
event_hour)` computed from only the increments whose `arrival_time` falls within that horizon
of `event_hour`. The horizon label lives here, on the derived projection — not on the fact.

**6. Arbitrary as-of queries are computed on demand from the fact.** Any business instant —
"as of yesterday 17:00," not just the fixed horizons — is answered by summing deltas with
`arrival_time ≤` that instant. Unlimited as-of points, no precomputation; the fixed horizons
are an optimization for the frequent cases, not a limit on what can be asked.

**7. Change visibility is a first-class output.** Because the fact is append-only and
bitemporal, the system can present, together: the value **as of** a chosen past instant, the
**current** value, and the fact that they differ — attributable to the specific late or
correction rows (with their `arrival_time`) that account for the difference. "You knew X when
you decided; it is now Y because a correction arrived at T" is a supported query, not a
reconstruction after the fact.

## Alternatives considered

**Mutate counts in place (uni-temporal, latest-only).** Smallest storage, simplest writes.
Rejected outright: overwriting destroys the past, making reproducibility — the system's core
promise — impossible. There is no recovery from a mutated count.

**Several physical tables bucketed by lateness relative to now** (within 1h / 24h / 7d /
older). The original sketch. Rejected because the buckets are wall-clock-relative: a row must
migrate from the 1h table to the 24h table to the 7d table as time passes, the boundaries
move continuously, and every passing hour triggers reclassification churn. Replaced by one
append-only fact where lateness is a *filter* — same questions answerable, no migration. *(The
derived fixed-horizon materializations in decision (5) preserve what was useful about the
original idea — fast answers for the common horizons — without making the raw store carry the
buckets.)*

**Valid time only (no transaction time).** Knows which hour data is about, but not when it was
learned — so "what did I see yesterday" is unanswerable and corrections are indistinguishable
from originals. Rejected; transaction time is the axis the reproducibility promise actually
needs.

**Rely on Delta Lake time travel for history.** Delta's table-version history is genuinely
useful and complements this design for cheap recent rollback. Rejected as the *mechanism* for
as-of reproducibility, on two grounds: it is **table-version granularity**, not
measurement-level valid/transaction separation, so it cannot express "as of this business
instant" cleanly; and its history is **vacuumed**, so it is not a permanent record over the
long horizons a decision audit may need. Explicit bitemporal columns are kept as the source of
truth; Delta time travel is an operational convenience layered on top, not a substitute.

**SCD-style separate history table (overwrite current, archive prior versions).** A classic
pattern and a valid alternative. Rejected as heavier than needed here: the histogram is already
an *additive delta* structure, so append-only signed deltas express corrections and late data
natively, without a separate current/history split to keep in sync.

## Consequences

**What this buys us.** Full as-of reproducibility; a complete, tamper-evident audit trail;
corrections and late data absorbed without losing what was previously known; first-class change
visibility for decision defensibility; one source of truth; and unlimited as-of points with
fast paths for the common horizons.

**What it costs.** An append-only fact grows monotonically, and as-of queries sum a range of
deltas rather than reading a single current value — so storage and read cost are higher than a
mutate-in-place store. This is mitigated because deltas are **sparse** (only touched bins, per
instrument-hour) and because the fixed-horizon materializations bound the cost of the frequent
queries. **Archival to cold storage is the deferred answer to unbounded growth:** once an
`event_hour` is far enough past that its transaction-time history is effectively final
(no further late data or corrections expected), its detailed delta rows can be rolled up and
moved to a cheap cold tier, leaving the hot fact to recent, still-mutating history. This is a
real eventual concern but **deliberately not built now** — at Free Edition demo scale it is never
reached, and a retention/cold-tier policy is straightforward to add when volume warrants. Kept
simple on purpose: a one-line policy, not a tiering framework.

**Scope discipline (over-engineering guards).**
- The slice builds the append-only fact, the fixed-horizon materializations, and on-demand
  as-of querying. That is the complete minimal mechanism.
- Signed-delta correction handling is in the model **from the start** — it is cheap (a sign and
  a type column) and central to the value proposition — but the *presentation* of "this changed
  since you saw it" beyond the query itself (dashboards, alerts) is a later concern.
- No SCD framework, no separate current/history tables, no per-measurement identity tracking in
  the count fact: the append-only signed-delta fact is the minimal complete structure, and the
  cleverness is in the two time axes, not in machinery around them.

**Coupling to other decisions.** Every delta carries its `bin_schema_id` (ADR-003); a schema
change is a boundary, and as-of sums are always within a single schema version. The
moments/entropy computation (its own ADR) reads the fixed-horizon materializations. The drift
metric (Wasserstein, its own ADR) compares as-of-consistent snapshots, so that "is it drifting"
is always asked against a defensible, reproducible pair of distributions rather than against
counts that may have silently shifted.

---

*Authorship: architecture and all design decisions by the author. Implementation is AI-assisted
— code generated against the documented architecture and decisions. This ADR records the
reasoning; the code is the proof.*
