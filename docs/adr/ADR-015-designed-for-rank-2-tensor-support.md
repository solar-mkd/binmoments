# ADR-015 — Designed-For: Rank-2 Tensor Support

**Status:** Designed-for (not built)
**Context layer:** Future extension (tensor-valued measurements such as conductivity, stress, strain)
**Depends on:** ADR-001 (which capped the build at rank-0/1 and worked out the rank-2 design).
**Project:** BinMoments — Real-Time Distribution Fingerprinting and Anomaly Detection for IoT Streams

---

## Context

ADR-001 modelled measurements as tensors of rank 0, 1, or 2, but deliberately **built only rank-0 and rank-1** and recorded rank-2 (conductivity, stress, strain, diffusion tensors) as designed-for. This ADR holds that deferred design and its trigger, so the deferral is a reasoned choice rather than a gap.

## Decision (deferred)

When a real rank-2 instrument is onboarded, the decomposition from ADR-001 applies: the **magnitude** fed to the scalar channel engine is a named **invariant** (Frobenius norm, or the dominant eigenvalue where it is the physically meaningful quantity); the **direction** is the **eigendecomposition** (eigenvalues + eigenvectors), retained in the overflow field.

Three questions are deliberately left to be answered **with real data**, because answering them on synthetic data would risk committing to the wrong abstraction:
- *Which invariant* is the right channel for the specific physical quantity and its notion of "drifting."
- How to handle a **non-symmetric** tensor (the eigendecomposition assumes symmetry).
- How to **normalize eigenvector sign and ordering** so the stored direction is stable across readings.

**Trigger to build:** a real rank-2 instrument and its data in hand — so the invariant choice and normalization are validated against reality, not guessed.

## Alternatives noted

Building now on synthetic data is rejected — it would guess the invariant and normalization wrong and bake in the error (precisely the over-engineering trap). A fully general rank-N model is rejected (ADR-001).

## Consequences

Deferred; ADR-001's worked-out design makes onboarding a bounded task rather than a research project. Fence: not built until a real rank-2 instrument requires it. Understanding rank-2 correctly while choosing not to build it speculatively is the intended signal.

---

*Authorship: architecture by the author; implementation AI-assisted. This ADR records a deferred decision.*
