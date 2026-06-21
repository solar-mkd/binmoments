# ADR-007 — Instrument Registry & Geodetic Metadata

**Status:** Accepted
**Context layer:** Reference data (how instruments are identified, located, and classified — the dimension the measurement stream and all reporting join against)
**Depends on:** ADR-004 (reuses the bitemporal/validity-interval pattern for registry history).
**Referenced by:** ingestion (ADR-009), reporting/drill-down, configuration (ADR-011).
**Project:** BinMoments — Real-Time Distribution Fingerprinting and Anomaly Detection for IoT Streams

---

## Context

Measurements are meaningless without knowing *which* instrument produced them, *where* it is,
and *what class* it belongs to. Three needs follow (original requirement point 3): a stable
unique identity per instrument; a position precise and unambiguous enough to support
geographic reporting and drill-down; and a classification scheme rich enough to group and
filter instruments by purpose, importance, or category.

Position is the subtle one. A bare latitude/longitude pair is **ambiguous at the precision
geodetic sensors actually report**. The same physical point has different coordinates in
different reference frames (datums), and — because tectonic plates move on the order of
centimetres per year — even within one modern frame a coordinate is only meaningful *at a
stated epoch*. A coordinate without its datum and epoch cannot be correctly joined to other
spatial data, compared across sources, or trusted over time. Treating location as
"lat, long" would be the amateur choice; treating it as a geodetic quantity is the correct one.

Instruments also change: they get relocated, recalibrated, relabelled. Reporting on a past
measurement must interpret it against the metadata that was valid *then*, not against today's.

## Decision

**1. A separate instrument registry (a dimension), keyed by a stable unique `instrument_id`.**
The measurement stream carries only `instrument_id`; all descriptive attributes live in the
registry. This keeps the stream and the increment fact (ADR-004) lean, exactly as ADR-001 keeps
channel direction out of the scalar statistical path.

**2. Location is stored geodetically, not as bare coordinates:** latitude, longitude, ellipsoidal
height, **plus the datum / reference-frame identifier** (e.g. WGS84, ETRS89, an ITRF realization)
**plus the epoch**. A position is never recorded without the frame and epoch it is expressed in.

**3. The registry is bitemporal / validity-interval versioned.** Relocation, recalibration, and
relabelling are recorded as new validity intervals, not overwrites — reusing the valid-time /
transaction-time thinking of ADR-004. A measurement is interpreted against the instrument metadata
valid at its `event_hour`, so historical reports stay faithful to what was true then.

**4. Classification is a many-to-many label set.** An instrument carries one or more labels
(purpose, importance, class, category) rather than a single category enum, because these
classifications are orthogonal and an instrument legitimately belongs to several at once. Reports
filter and drill down by label.

**5. Geographic region is derived from the geodetic position** (spatial join to region polygons,
hierarchical: country → region → …) and stored resolved for drill-down, recomputed if the
instrument is relocated.

## Alternatives considered

**Bare latitude/longitude, no datum or epoch.** Simpler. Rejected: ambiguous at survey precision,
silently wrong when joined across frames, and ignores plate motion — a correctness flaw, not a
convenience trade.

**A single category enum per instrument.** Rejected: instruments have multiple independent
classifications; a label set is the honest model and supports richer drill-down.

**Embedding metadata in each measurement.** Rejected: denormalizes, bloats the stream, and makes
metadata change-tracking impossible. The registry-as-dimension keeps the fact lean and the
metadata governed.

**Mutable registry (overwrite on change).** Rejected: loses the ability to interpret historical
measurements against then-current metadata, breaking reproducibility for any report that crosses a
relocation or recalibration.

## Consequences

**What this buys us.** Correct, unambiguous geospatial joins; faithful historical reporting;
flexible region-and-label drill-down; a lean measurement stream. Storing datum + epoch is a strong
data-architecture signal precisely because it is the detail most designs get wrong.

**What it costs.** Registry lifecycle management (validity intervals, region re-resolution on
relocation).

**Scope discipline (over-engineering guard).** Store the datum and epoch and validity intervals —
cheap and correct. A full coordinate-reference-system **transformation engine** (converting between
datums/epochs on the fly) is **designed-for, not built**: store the frame faithfully, and transform
only when a specific report actually needs cross-frame comparison.

**Coupling.** Measurements reference `instrument_id`; ingestion (ADR-009) joins the registry in
silver; configuration (ADR-011) links instruments to their channels and drift rules; the bitemporal
pattern mirrors ADR-004.

---

*Authorship: architecture and all design decisions by the author. Implementation is AI-assisted.
This ADR records the reasoning; the code is the proof.*
