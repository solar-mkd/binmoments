# ADR-020: Materialized current-state histogram (serving read model)

**Status:** Accepted

**Context layer:** Serving / read model over the bitemporal increment fact (ADR-004)

**Depends on:** ADR-004 (bitemporal increment fact), ADR-002/003 (bins & schemas), ADR-010 (platform)

---

## Context

The increment fact (ADR-004) is append-only: every reading and every correction is recorded as a
signed delta keyed by (instrument, bin_schema, event_hour, bin), carrying both valid time
(event_hour) and transaction time (arrival_time). This is the source of truth and the basis of the
project's bitemporal guarantees — any past state is reconstructable as-of any transaction time.

Reading the *current* histogram from the fact, however, means summing every signed delta for each
(instrument, schema, event_hour, bin) key. For a single key that may be many rows (one per reading
that fell in that bin that hour, plus any corrections). At production scale — millions of inserts —
recomputing this sum on every read is wasteful, given that the overwhelmingly common query is simply
"what is the current histogram for this instrument?"

The need is a fast path for the latest state, without weakening the append-only fact or the
point-in-time reconstruction it provides.

## Decision

Maintain a **materialized current-state histogram** table, `histogram_current`, keyed by
(instrument_id, bin_schema_id, event_hour, bin_index) with a net `count`. It is the increment fact
with **transaction time collapsed**: the sum of all signed deltas known so far for each key.

Four points define the decision:

1. **The fact stays the source of truth; this table is a derived cache.** The append-only fact is
   unchanged. `histogram_current` is a projection of it and may be discarded and rebuilt at any
   time. Point-in-time / as-of queries continue to replay the fact; only "current" reads use the
   materialized table.

2. **Maintained incrementally by upsert (`MERGE`), not by recompute.** Each arriving batch of
   increments is aggregated by key and `MERGE`d into the table: matched bins have the batch delta
   added to their count; unmatched bins are inserted. This is an O(batch) write, not an O(history)
   recompute.

3. **Corrections are included (option A).** Because corrections are themselves signed deltas in the
   fact, they `MERGE` into the affected bins exactly like original readings (retract = negative
   delta on the old bin, assert = positive delta on the new bin). The current-state table therefore
   reflects *all known deltas*, so a fast "current" read and a full as-of-now reconstruction always
   agree. The alternative — forward-only, ignoring late corrections in the materialized table — was
   rejected because it lets the fast table silently disagree with the truth.

4. **Rebuildable, and the rebuild is asserted to match.** A rebuild path recomputes the whole table
   directly from the fact (`GROUP BY key → SUM(delta)`, dropping zeroed bins). The
   incrementally-maintained table must equal this rebuild; a consistency check asserts it. This is
   both the disaster-recovery path (if maintenance ever drifts, rebuild and you are correct again)
   and the guarantee that keeps the cache trustworthy.

The correctness of (2) vs (4) — that maintaining incrementally equals rebuilding from scratch — is
not an accident of implementation. Bin counts are additive, and addition is associative and
commutative (a commutative monoid; see the mathematical companion). Applying deltas batch by batch
and applying them all at once are the same sum in a different order, so they are equal by
construction. The same additive property that underpins bitemporal reconstruction and distributed
aggregation underpins this read model.

The analytical logic stays storage-agnostic: the fold/merge/rebuild semantics live in pure,
tested Python (`binmoments.serving.current_state`); the Delta `MERGE` is confined to a thin
notebook.

## Alternatives considered

**Query the fact (or a view) on every read.** Correct and always consistent, with no second write
path — the simplest option. Rejected as the *default* read path at scale: it pays the
sum-over-all-deltas cost on every read. (It remains exactly the rebuild path, used to seed and to
verify the materialized table.)

**Forward-only materialization (ignore late corrections in the table).** Simpler writes, but the
fast table drifts from the as-of-now truth whenever a correction arrives, undermining trust in the
table. Rejected in favour of option A.

**Hand-coded read-modify-write increments (no MERGE).** Maintaining counts by reading a row, adding,
and writing it back outside a transaction invites race conditions and lost updates at the very scale
this optimisation targets. Rejected in favour of Delta `MERGE`, which is atomic and idempotent-
friendly.

**Treat the materialized table as the source of truth (drop or demote the fact).** This would gain
nothing and would forfeit the bitemporal reconstruction, audit trail, and rebuildability that are
the project's spine. Explicitly rejected: the table is a cache, never the truth.

## Consequences

- **Fast current reads.** The latest histogram for an instrument is a single keyed read, no delta
  replay. Arbitrary-window totals remain cheap (sum the relevant event-hours).
- **No weakening of the fact.** Append-only, bitemporality, and as-of reconstruction are untouched;
  this is purely additive (a read model alongside the write model — an event-sourcing / CQRS shape).
- **A second, derived write path to keep honest.** The materialized table must be kept in step with
  the fact. This is mitigated by the rebuild path and the asserted consistency check; the table is
  never authoritative, so the worst case is "rebuild it".
- **Zeroed bins are dropped** to keep the projection sparse and rebuild-equivalent; reads filter to
  non-zero counts.
- **Power-sum current state is the same pattern, deferred.** A materialized current state for the
  power sums (fast exact moments without replay) follows the identical additive `MERGE`-and-rebuild
  design. It is recorded here as a designed-for extension rather than built, to keep this change
  scoped to the histogram as motivated.
