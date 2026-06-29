# ADR-020: Materialized current-state histogram (serving read model)

**Status:** Accepted

**Context layer:** Serving / read model over the bitemporal increment fact (ADR-004)

**Depends on:** ADR-004 (bitemporal increment fact), ADR-002/003 (bins & schemas), ADR-009 (medallion), ADR-010 (platform)

---

## Context

The increment fact (ADR-004) is append-only: every reading and every correction is a signed delta
keyed by (instrument, bin_schema, event_hour, bin), carrying valid time (event_hour) and transaction
time (arrival_time). It is the source of truth and the basis of the bitemporal guarantees — any past
state is reconstructable as-of any transaction time.

Two common read needs are expensive against the raw fact at scale:

1. **"What is this instrument's distribution right now?"** — summing every signed delta for the
   instrument across all hours and all arrival times, on every read.
2. **"What did the distribution look like in a given past hour?"** — answerable per-hour, but only
   after the gold per-hour histogram is materialized.

Recomputing these from the log on every read is wasteful when they are the overwhelmingly common
queries. The need is fast read models for the common cases, without weakening the append-only fact
or the point-in-time reconstruction it still provides for the rare "what did we know as-of T"
question.

## Decision

Materialize two complementary read models off the fact, at two deliberately different grains:

**Gold `histogram` (per-hour).** Keyed (instrument, bin_schema, **event_hour**, bin) with net
count. The time-resolved analytical view: to see a past hour's distribution you index straight to
its rows — no replay. This is also the basis of the plottable `histogram_plot` view (joined to the
persisted bin edges, with empty bins zero-filled).

**`histogram_current` (collapsed).** Keyed (instrument, bin_schema, **bin**) with net count — the
hour dimension summed away. The instrument's whole current distribution as a single fast read,
including all known corrections. This is the materialized "latest state".

Five points define the current-state model:

1. **The fact stays the source of truth; both tables are derived caches.** The append-only fact is
   unchanged. These projections may be discarded and rebuilt at any time. Point-in-time / as-of
   queries continue to replay the fact; only "current" and "per-hour" reads use the materialized
   tables.

2. **Collapsed grain for the current state.** `histogram_current` drops the hour dimension on
   purpose, so it answers "the distribution now" in one keyed read and stays distinct from the
   per-hour `histogram`. Windowed reads ("the distribution over the last N days") remain cheap from
   the per-hour `histogram` (sum the relevant hours); a trailing-window current state is a recorded
   variant, not built.

3. **Maintained incrementally by upsert (`MERGE`).** Each arriving batch of increments is aggregated
   to the collapsed grain and `MERGE`d in (matched bins add the batch delta; unmatched bins insert).
   An O(batch) write, not an O(history) recompute.

4. **Corrections are included (option A).** Corrections are signed deltas in the fact, so they
   `MERGE` into the affected bins exactly like original readings (retract = negative delta, assert =
   positive delta). The current-state table therefore reflects all known deltas, so a fast "current"
   read and a full as-of-now reconstruction always agree. The forward-only alternative — ignoring
   late corrections in the materialized table — was rejected because it lets the fast table silently
   disagree with the truth.

5. **Rebuildable, and the rebuild is asserted to match.** A rebuild path recomputes the whole table
   from the fact (`GROUP BY (instrument, schema, bin) → SUM(delta)`, dropping zeroed bins). The
   incrementally-maintained table must equal this rebuild; a consistency check asserts it. This is
   both the disaster-recovery path and the guarantee that keeps the cache trustworthy.

The correctness of (3) vs (5) — that maintaining incrementally equals rebuilding from scratch — is
not accidental. Bin counts are additive, and addition is associative and commutative (a commutative
monoid; see the mathematical companion). Applying deltas batch by batch and applying them all at
once are the same sum in a different order, so they are equal by construction. The same additive
property that underpins bitemporal reconstruction and distributed aggregation underpins this read
model.

The fold/merge/rebuild semantics live in pure, tested Python
(`binmoments.serving.current_state`); the schema-edge export for plotting lives in
`binmoments.serving.schema_export`; the Delta `MERGE`, the schema table, and the plottable view are
confined to thin notebooks.

## Alternatives considered

**Query the fact (or a view) on every read.** Correct and always consistent, no second write path.
Rejected as the *default* read path at scale: it pays the sum-over-all-deltas cost on every read. It
remains the rebuild path used to seed and verify the materialized tables.

**One table at a single grain.** A single per-hour table could serve "current" by summing hours on
read, or a single collapsed table could lose per-hour history. Two grains were chosen because the
two questions ("now" vs "each hour") are both common and want different keys; the cost is one extra
small, derived table.

**Forward-only materialization (ignore late corrections).** Simpler writes, but the fast table
drifts from the as-of-now truth whenever a correction arrives. Rejected in favour of option A.

**Hand-coded read-modify-write increments (no `MERGE`).** Invites race conditions and lost updates
at the scale this optimisation targets. Rejected in favour of atomic Delta `MERGE`.

**Treat a materialized table as the source of truth.** Would forfeit bitemporal reconstruction, the
audit trail, and rebuildability. Explicitly rejected: these tables are caches, never the truth.

## Consequences

- **Fast common reads.** Current distribution = one keyed read of `histogram_current`; a past hour's
  distribution = a direct read of `histogram`. Neither replays the log.
- **Plottable histograms.** The persisted bin edges plus the zero-filled `histogram_plot` view make
  any (instrument, hour) histogram directly plottable.
- **No weakening of the fact.** Append-only, bitemporality, and as-of reconstruction are untouched;
  this is purely additive (read models alongside the write model — an event-sourcing / CQRS shape).
  The rare "what did we know as-of T" query still replays the fact, by design.
- **Derived write paths to keep honest.** The materialized tables must stay in step with the fact;
  mitigated by the rebuild path and the asserted consistency check. The worst case is "rebuild it".
- **Zeroed bins are dropped** to keep the projection sparse and rebuild-equivalent; reads filter to
  non-zero counts.
- **Power-sum current state is the same pattern, deferred.** A materialized current state for the
  power sums (fast exact moments without replay) follows the identical additive `MERGE`-and-rebuild
  design, recorded as a designed-for extension rather than built.
