# ADR-001 — Measurement & Channel Model

**Status:** Accepted
**Context layer:** Ingestion / data model (foundational — every downstream decision depends on this)
**Project:** BinMoments — Real-Time Distribution Fingerprinting and Anomaly Detection for IoT Streams

---

## Context

IoT instruments do not emit only scalars. A temperature reading is a single
number, but a wind reading has speed *and* direction (a vector), and a property
like electrical conductivity in an anisotropic medium is a tensor — it has a
different magnitude along each principal axis, plus an orientation in space. A
measurement model that assumes "one reading = one number" cannot represent these
without flattening away information that is operationally meaningful: an
anemometer whose bearing seizes while its speed reads normally is a fault that a
scalar-only model is structurally blind to.

At the same time, the statistical core of this system — streaming histograms,
moments, entropy, percentiles, and distribution-distance drift detection — is
defined on **scalar** random variables. The "variance" of a vector is a
covariance matrix; the higher co-moments of a vector or tensor are themselves
higher-rank objects. A statistical engine that tried to operate directly on
vectors and tensors would have to special-case every rank, and concepts like a
one-dimensional histogram or a skewness would have no single well-defined meaning.

The model must therefore be **rich enough at ingest** to preserve vector and
tensor structure, while presenting the statistical engine with a **uniform
scalar interface**. It must also avoid the opposite failure: a fully general
rank-N tensor abstraction that is versatile in principle and never finished in
practice. No instrument in scope produces anything above rank-2.

A second subtlety: not all scalar quantities are linear. A compass bearing is
**circular** — the arithmetic mean of 350° and 10° is 0°, not 180°, and naive
binning breaks at the 0°/360° wraparound. The model must distinguish linear from
circular quantities so the statistical engine can apply the correct treatment.

## Decision

**1. Every measurement is modeled as a tensor of rank 0, 1, or 2, and is
decomposed at ingest into a magnitude and a direction.**

- **Rank-0 (scalar):** the value itself is the magnitude; there is no direction.
- **Rank-1 (vector, e.g. wind):** magnitude is the vector length; direction is a
  unit vector (equivalently, the polar/spherical angles).
- **Rank-2 (symmetric tensor, e.g. conductivity):** the decomposition is the
  **eigendecomposition** — magnitude is a frame-independent **invariant** (the
  Frobenius norm, or the dominant eigenvalue where it is the physically
  meaningful quantity); direction is the eigenbasis (eigenvalues + eigenvectors,
  i.e. the orientation of the principal axes).

**2. The magnitude is stored exactly as a scalar would be, and is the primary
input to the statistical engine.** Direction is stored alongside it as a
structured overflow field (JSON) — a unit vector for rank-1, an eigenbasis for
rank-2 — and is *not*, by default, fed to the statistical engine.

**3. A measurement decomposes into one or more named scalar *channels*. The
statistical engine operates per channel, never on the raw rank-1/2 object.** The
magnitude is always a channel. Direction is promoted to its own channel **only
for quantities where directional drift is explicitly in scope**; otherwise it
remains in the overflow field as retained-but-unaggregated provenance.

**4. Every channel carries a `linear | circular` flag.** Linear channels use the
standard histogram/moment treatment; circular channels (e.g. wind bearing) use
circular statistics and wrap-around bins. The flag is a property of the channel
definition, set in instrument configuration.

**5. Rank scope for the build: rank-0 and rank-1 are implemented; rank-2
(eigendecomposition) is designed-for but not built in the initial vertical
slice. Rank ≥ 3 is an explicit non-goal.**

## Alternatives considered

**Scalar-only model (store just the number).** Simplest, and adequate for
temperature. Rejected because it cannot represent wind direction or conductivity
anisotropy, and is structurally blind to an entire class of faults (direction
drifts while magnitude looks healthy). The cost of losing those is permanent and
unrecoverable; the cost of the channel model is a bounded decomposition step.

**Fully general rank-N tensor model.** Maximally versatile. Rejected as
over-engineering with no in-scope justification: no instrument under
consideration emits above rank-2, the storage and math for arbitrary rank are
substantial, and the abstraction would delay a working system indefinitely —
versatility at the price of never finishing. The model is capped at rank-2 *on
purpose*, and the cap is documented rather than left implicit.

**Compute statistics directly on the raw vector/tensor.** Rejected because the
statistical core is univariate by definition. Operating on raw rank-1/2 objects
would force the engine to special-case every rank (covariance matrices, higher-
rank co-moments), and one-dimensional concepts like a histogram bin or a skewness
would lose a single well-defined meaning. The magnitude/channel decomposition
keeps the engine uniformly scalar, so a new instrument type adds channels, not
engine code.

**Decompose rank-2 as "one magnitude + one direction vector" (by analogy to
rank-1).** Tempting, and wrong. A symmetric rank-2 tensor does not reduce to a
single magnitude and a single direction: its natural decomposition is the
eigendecomposition, with *several* magnitudes (the eigenvalues) and an
orientation (the eigenvectors). Collapsing it to one magnitude + one direction
would silently discard the anisotropy that is the entire reason the quantity is a
tensor. Rejected in favor of the eigendecomposition, with a named scalar
invariant as the channel.

**Treat every scalar channel as linear.** Rejected because circular quantities
(bearing) break linear binning and moment computation at the 0°/360° wraparound,
producing nonsensical means and false drift. The `linear | circular` flag is the
minimal mechanism that prevents this.

## Consequences

**What this buys us.** A single statistical engine that is uniformly scalar and
never needs to know a channel's originating rank. Instrument richness lives at
the ingest boundary; everything downstream — bins, moments, entropy, drift —
sees only named scalar channels. New instrument types are onboarded by declaring
channels and their `linear | circular` nature in configuration, not by changing
engine code. Tensor structure is preserved (in the overflow field) for any future
analysis that wants it, without polluting the statistical path.

**What it costs.** A decomposition step per measurement (trivial for rank-0/1, an
eigendecomposition for rank-2), and per-channel metadata to carry. Magnitude and
direction are stored separately, so reconstructing the original tensor requires
both columns — an accepted trade for keeping the statistical column scalar and
mergeable.

**Deliberate scope discipline (over-engineering guard).**

- Rank-2 is *designed* here but *not built* in the slice. The eigendecomposition
  design is recorded so the extension point is real, not improvised later — but
  the code is deferred until a rank-2 instrument is actually onboarded.
- The `linear | circular` flag is *defined* in the model now (it is one cheap
  field), but the **circular-statistics implementation is deferred** until the
  first circular channel — wind bearing — is built. The temperature-only initial
  slice has no circular channel, so it ships with the flag present and the linear
  path only. This keeps the model complete without building code the slice does
  not exercise.

**Coupling to later decisions.** Because the statistical engine consumes only
scalar channels, the bin-schema decisions (ADR on bin derivation), the drift
metric (Wasserstein over channel histograms), and the moment/entropy computation
all operate per channel and inherit this model unchanged. The `linear | circular`
flag is the one piece of channel metadata those layers must respect.

---

*Authorship: architecture and all design decisions by the author. Implementation
is AI-assisted — code generated against the documented architecture and
decisions. This ADR records the reasoning; the code is the proof.*
