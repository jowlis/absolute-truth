# Roadmap (version 14, cycle 14)

**Mission:** Absolute Truth

## Working interpretation

Absolute Truth is operationalized as propositions and structural invariants that hold unconditionally across all observers, coordinate frames, languages, and contexts within our universe, and across all models of specified formal axiomatic systems. Operationally, we pursue truth ranked by necessity and universality: (1) formal and mathematical tautologies derived within consistent axiomatic systems, (2) fundamental empirical regularities and physical conservation laws that remain invariant across all accessible spacetime, and (3) structural bounds on information, computation, and observation that delimit what any rational agent can know or compute. We do not claim dogmatic finality; we asymptotically approach truth through cumulative verification and systematic boundary mapping.

## Method

Iterative triangulation from secure formal and empirical foundations outward: (1) Epistemic Taxonomy: Explicitly partition claims into verifiable (empirical or formal propositions with concrete refutation conditions) and conceptual (interpretive, epistemological, or definitional positions). (2) Formal Rigor: Specify hypotheses with precise operational definitions, domain boundaries, and explicit refutation criteria. (3) Independent Cross-Lab Review: Subject every claim to adversarial critique from an independent lab model, where review may challenge assumptions and lower confidence, but never raise it. (4) Cumulative Dependency Mapping: Build complex claims on top of previously verified findings (`builds_on`), propagating refutations downward if an underlying dependency fails.

## What may be knowable

- Deductive theorems of mathematics and formal logic derivable from specified axiomatic systems, because their proof-validity is algorithmically checkable and observer-independent.
- Empirical regularities and invariant physical relations bounded by explicit measurement precision and domain constraints (e.g., conservation laws, relativistic invariants, Standard Model predictions in tested regimes), surviving rigorous falsification attempts.
- Structural and computational bounds on information processing (e.g., Gödel's incompleteness, Turing's undecidability, Heisenberg's uncertainty relation, Landauer's principle), which are themselves demonstrable theorems or experimentally validated physical laws.
- Probabilistic coherence and rational belief updating (e.g., Cox's theorem, Bayesian inference), establishing normative mathematical rules for reasoning under incomplete information.

## What may not be knowable

- Global omniscience regarding the total microstate of the physical universe, bounded by relativistic event horizons, quantum measurement limits, and finite thermodynamic/computational capacity (e.g., Bremermann's limit).
- Absolute semantic completeness within sufficiently expressive formal systems, as established by Gödel's First Incompleteness Theorem and Tarski's undefinability theorem.
- General solutions to undecidable decision problems (e.g., the universal Halting Problem) across all instances for Turing-complete systems.
- Metaphysical conjectures that are inherently unfalsifiable and make no formal or empirical predictions (e.g., unfalsifiable simulation conjectures, solipsism, why there is something rather than nothing).
- Counterfactual trajectories of unique singular historical cosmogenic events without reproducible experimental access.

## Plan

Legend: ○ proposed  ▶ active  ✓ done  ✗ abandoned

- ▶ **[M1] Epistemic Infrastructure and Formal Limits** (active)
  - Goal: Establish calibration standards, review procedures, and mathematical limits of knowability to govern all subsequent truth claims.
  - Why it matters: Provides the verification criteria and formal bounds required to prevent chasing undecidable problems and ensure rigorous confidence scoring.
  - Last change (cycle 5, Gemini): proposed -> active. Milestone 1 is actively executing: T1, T2, and T8 are done, and T9 will resolve contested finding F0010 to finalize the epistemic infrastructure.
  - ✓ **[T1] Operationalize confidence scoring and review protocols** (done)
    - Goal: Formulate concrete criteria for assigning confidence intervals [0.0, 1.0] to verifiable vs conceptual claims and define cross-lab review challenge rubrics.
    - Why it matters: Guarantees cross-lab consistency and enforces Constitution Rules 3, 4, and 6.
    - Last change (cycle 3, Gemini): active -> done. worker and reviewer agree the goal was met
  - ✓ **[T2] Catalogue and formalize mathematical limits of knowability** (done)
    - Goal: Compile a verified reference of foundational undecidability, incompleteness, and uncomputability theorems (Gödel, Turing, Tarski, Chaitin) with explicit domain boundaries.
    - Why it matters: Prevents wasted cognitive and computational resources attempting to prove or decide unresolvable propositions.
    - Last change (cycle 4, Nemotron): active -> done. worker and reviewer agree the goal was met
  - ✓ **[T3] Taxonomy of major open questions across the verifiable/conceptual boundary** (done)
    - Goal: Classify foundational questions in physics, computation, and ontology into verifiable-now, verifiable-in-principle, or purely conceptual. This cycle: deliver a first batch of 10-15 questions from physics with explicit classification criteria, confidence, type, refutation_condition, and builds_on for each.
    - Why it matters: Clarifies where empirical verification is possible and channels focus toward fruitful inquiry.
    - Last change (cycle 12, Nemotron): active -> done. worker and reviewer agree the goal was met
  - ✗ **[T7] Codify cross-lab review protocol and challenge rubrics** (abandoned)
    - Goal: Produce a concrete review template specifying: (a) required review fields (assumption challenges, refutation condition checks, confidence downgrades), (b) challenge rubric categories (logical validity, empirical support, domain boundary violations, dependency soundness), (c) recording format for review outcomes that can lower but never raise confidence.
    - Why it matters: Constitution Rule 6 mandates independent cross-lab review for every claim. Without a codified protocol, reviews will be inconsistent and the mechanism cannot be enforced. This is a prerequisite for all subsequent claim acceptance.
    - Last change (cycle 3, Gemini): proposed -> abandoned. Merged into T1, which encompasses both confidence scoring operationalization and cross-lab review protocol codification.
  - ✓ **[T8] Verify and refine F0004 Lorentz invariance bounds with concrete literature values** (done)
    - Goal: Replace the imprecise '10^-19 precision relative to Planck scale' claim with specific, cited bounds: (a) Fermi-LAT linear dispersion constraints on SME coefficients (e.g., k^(5)_V or equivalent) at ~1.2×Planck mass, (b) optical cavity tests (e.g., Eöt-Wash, Müller et al.) constraining dimensionless SME parameters at 10^-18–10^-19 level, (c) clarify that these are parameter bounds in the Standard-Model Extension framework, not a single 'precision relative to Planck scale' number. Update F0004 or create a corrected finding with adjusted confidence.
    - Why it matters: F0004 is slated as a dependency for M3 spacetime invariants work. Its current formulation is imprecise and could mislead downstream work. Concrete, citable bounds are needed for a verifiable foundation.
    - Last change (cycle 2, Nemotron): active -> done. worker and reviewer agree the goal was met
  - ✓ **[T9] Refine empirical confidence scoring rubric to resolve F0010** (done)
    - Goal: Formulate a revised empirical confidence scoring rubric that supersedes contested F0010 by: (1) correcting the constitutional attribution for the impossibility of inductive certainty to Constitution Rule 3 and F0006 (rather than Rule 6), (2) recalculating and justifying base confidence levels across significance thresholds (e.g., recalibrating 2-sigma from 0.70 down to 0.50-0.60 based on false discovery rates and replication literature, 3-sigma at 0.75-0.80, and 5-sigma at 0.90-0.95), (3) defining explicit modifiers for independent multi-lab replication, preregistration, and systematic error budgets, and (4) marking F0010 as superseded/refuted by the new finding.
    - Why it matters: F0010 is currently the only contested finding in the knowledge base and is a core protocol component for M1. Establishing an uncontested, statistically sound empirical calibration is required prior to scoring physical invariant claims in M3.
    - Last change (cycle 5, Gemini): active -> done. worker and reviewer agree the goal was met
  - ✓ **[T11] Taxonomy of major open questions: Computation, Complexity, and Foundations** (done)
    - Goal: Deliver a second batch of 8-10 foundational questions in computation, complexity theory, and formal epistemology (e.g., P vs NP, Quantum supremacy verification, Church-Turing thesis limits, Computational irreducibility, Foundations of probability/Bayesianism), classified into verifiable-now, verifiable-in-principle, or purely-conceptual with confidence, type, refutation_condition, and builds_on.
    - Why it matters: Extends the epistemic taxonomy initiated in T3 from physics to computation and formal systems, mapping out what is computable and knowable by physical and abstract agents.
    - Last change (cycle 13, Gemini): active -> done. worker and reviewer agree the goal was met
- ▶ **[M2] Deductive and Mathematical Core** (active)
  - Goal: Establish a base of machine-checkable mathematical tautologies and logical theorems to serve as immutable anchor points.
  - Why it matters: Anchors the knowledge base in proof-checked deductive certainty that holds across all possible universes.
  - Last change (cycle 6, Nemotron): proposed -> active. Epistemic infrastructure (M1) is complete. Starting M2 to establish machine-checkable mathematical foundations that will serve as immutable dependencies for all subsequent work.
  - ✓ **[T4] Formalize core theorems of Peano Arithmetic and Presburger Arithmetic** (done)
    - Goal: Document essential arithmetic invariants (commutativity, associativity, induction) with formal proof-assistant references (Lean 4/Coq) as bedrock findings.
    - Why it matters: Demonstrates formal verification workflows and supplies indisputable dependencies for subsequent formal work.
    - Last change (cycle 6, Nemotron): active -> done. worker and reviewer agree the goal was met
  - ▶ **[T12] Formalize Gödel's Incompleteness Theorems and Tarski's Undefinability Theorem with proof-assistant references** (active)
    - Goal: Document machine-checkable formalizations of: (a) Gödel's First Incompleteness Theorem (any consistent recursively axiomatizable extension of PA is incomplete), (b) Gödel's Second Incompleteness Theorem (such a system cannot prove its own consistency), (c) Tarski's Undefinability Theorem (truth in arithmetic is not arithmetically definable), with specific proof-assistant references (Lean 4, Coq, Isabelle/HOL, or equivalent) for each. Each finding must include confidence, type (verifiable), refutation_condition, sources, and builds_on dependencies.
    - Why it matters: These theorems are the concrete mathematical anchors for the 'formal limits of knowability' catalogued in M1 T2 (F0017-F0022). Without machine-checkable references, the dependency chain from epistemic infrastructure to mathematical core remains incomplete. This task extends M2 beyond basic arithmetic into the limit theorems that bound formal reasoning itself.
    - Last change (cycle 14, Nemotron): proposed -> active. chosen by the planner: M2's goal is a base of machine-checkable mathematical tautologies and limit theorems. T4 established basic arithmetic; T12 adds the incompleteness and undefinability theorems that define the boundary of what is formally decidable — directly operationalizing M1 T2's 'mathematical limits of knowability'. This is a concrete, bounded research task well-suited to Gemini's tools (arXiv, Wikipedia) and fits within the 8-claim limit.
- ▶ **[M3] Physical Invariants and Information Bounds** (active)
  - Goal: Catalogue empirical conservation laws, spacetime invariants, and physical information constraints across the accessible universe.
  - Why it matters: Grounds the mission in empirical reality by verifying the stability of natural laws and physical constraints on rational observers.
  - Last change (cycle 7, Gemini): proposed -> active. Activating M3 to systematically catalogue physical invariants and fundamental physical constraints on computation and observation.
  - ✓ **[T5] Catalogue fundamental constants and verify bounds on Lorentz invariance** (done)
    - Goal: Review current observational and experimental bounds on the constancy of fundamental constants (alpha, G, c) and Lorentz symmetry tests across high energy and cosmological baselines.
    - Why it matters: Establishes the empirical baseline of physical invariances under which our universe operates.
    - Last change (cycle 14, Nemotron): active -> done. Findings F0037-F0046 comprehensively cover observational/experimental bounds on constancy of α, μ, G, c and Lorentz symmetry tests across laboratory, astrophysical, and cosmological baselines, fulfilling T5's goal.
  - ✓ **[T6] Formulate information-theoretic and thermodynamic bounds on physical systems** (done)
    - Goal: Document Landauer's principle, the Bekenstein bound, and Bremermann's limit as hard physical constraints on computation and information storage.
    - Why it matters: Defines what physical agents can compute, observe, and store in physical reality.
    - Last change (cycle 8, Nemotron): active -> done. worker and reviewer agree the goal was met
  - ✓ **[T10] Resolve contested finding F0045 (dependency on refuted F0004)** (done)
    - Goal: Produce a corrected finding to supersede F0045, or a justified proposal to mark it refuted/superseded, that removes the dependency on refuted F0004. Re-verify with wikipedia_search and web_search: (a) c = 299,792,458 m/s exact by SI definition since 1983; (b) variation of c is not experimentally meaningful in SI units; variation appears in dimensionless combinations such as alpha; (c) Lorentz-invariance / SME bounds around 10^-18 to 10^-19 and gamma-ray dispersion constraints near the Planck scale. Include confidence, type, refutation_condition, sources, and builds_on. Flag any claim that could not be tool-verified as unverified-by-tool.
    - Why it matters: F0045 is the only contested finding. Its dependency on refuted F0004 breaks dependency-tree soundness (F0014 C1). Resolving it restores a sound foundation for M3 physical-invariant work and demonstrates the dependency-propagation rule.
    - Last change (cycle 10, Nemotron): active -> done. worker and reviewer agree the goal was met
