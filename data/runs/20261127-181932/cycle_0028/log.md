# Cycle 28: mission (productive)

- Planner: Nemotron (NVIDIA, nvidia/nemotron-3-ultra-550b-a55b)
- Worker: Gemini (Google, gemini-3.8-flash)
- Reviewer: Nemotron (NVIDIA, nvidia/nemotron-3-ultra-550b-a55b)
- Time: 2026-11-27T18:35:07+00:00 to 2026-11-27T18:41:47+00:00
- Rules: constitution v3, core fingerprint 935dd7bb3ef827a9
- Models that replied: gemini-3.5-flash-lite, gemini-3.6-flash, nvidia/nemotron-3-ultra-550b-a55b
- Usage: 12 API calls (6 failed attempts), 245729 input tokens, 18507 output tokens, $0.0000

**Task:** Catalogue and verify the NPA hierarchy, almost-quantum correlations, and device-independent self-testing: Formulate verifiable claims with precise mathematical statements, exact domain boundaries, refutation conditions, and citations for: (1) The Navascués-Pironio-Acín (NPA) hierarchy of semidefinite programming relaxations characterizing the quantum correlation set; (2) The Q₁ (almost-quantum) correlation set as the first level of the NPA hierarchy, its properties, and how it strictly contains the quantum set while being contained in the non-signaling polytope; (3) Device-independent self-testing protocols that certify quantum states and measurements (e.g., Mayers-Yao, CHSH self-testing, parallel self-testing) based on Bell inequality violations reaching Tsirelson's bound; (4) The relationship between self-testing rigidity and the boundary of the quantum set.

**Why this allocation:** -

**What was done:** Completed T20: Catalogued and verified the NPA hierarchy of semidefinite programming relaxations, the almost-quantum correlation set Q₁, device-independent self-testing protocols (CHSH, Mayers-Yao, and parallel self-testing), and the relationship between self-testing rigidity and the boundary of the quantum correlation set. All 6 claims are verifiable, grounded in literature, and include precise domain boundaries and refutation conditions.

**Results (new findings):**
- F0105 (supported): The Navascués-Pironio-Acín (NPA) hierarchy is an infinite sequence of semidefinite programming (SDP) relaxations Q₁ ⊇ Q₂ ⊇ ... ⊇ Q_k ⊇ ... ⊇ Q_c that provides outer bounds on the set of quantum correlations. Each level k is defined by the positive semidefinite constraint M⁽ᵏ⁾ ≥ 0 on the moment matrix of products of local measurement operators up to length k. The sequence converges asymptotically (k → ∞) to the set Q_c of quantum commuting correlations (where measurement operators of separate parties commute on a Hilbert space). Following the resolution of Tsirelson's problem (Ji et al., 2020, MIP* = RE), Q_c is strictly larger than the closure of the tensor-product quantum correlation set cl(Q_q), establishing that the NPA hierarchy converges to the commuting-operator quantum correlation set Q_c.
- F0106 (supported): The almost-quantum correlation set Q₁ (also denoted Q_{1+AB} or Q̃) is a semidefinite relaxation level of the NPA hierarchy situated strictly between the quantum correlation set Q and the non-signaling polytope NS (Q ⊊ Q₁ ⊊ NS). Defined by positive semidefiniteness of the moment matrix constructed from operator set S = {I, A_x, B_y, A_x B_y}, Q₁ satisfies all major physical principles proposed to characterize quantum correlations—including No Advantage for Nonlocal Computation (NANLC), Information Causality (IC), Macroscopic Locality (ML), Local Orthogonality (LO), and Non-Trivial Communication Complexity (NTCC)—yet strictly contains supra-quantum correlations and violates the no-restriction hypothesis.
- F0107 (supported): The CHSH self-testing theorem establishes that maximal violation of the CHSH inequality (⟨C⟩ = 2√2) uniquely certifies, up to local isometries, the presence of a maximally entangled two-qubit state |Φ⁺⟩ = (1/√2)(|00⟩+|11⟩) and anti-commuting measurement observables. Specifically, for any state |ψ⟩ ∈ H_A ⊗ H_B and dichotomic observables A₀, A₁ on H_A and B₀, B₁ on H_B achieving ⟨ψ|A₀B₀ + A₀B₁ + A₁B₀ - A₁B₁|ψ⟩ = 2√2, there exist local isometries Φ_A: H_A → H_A' ⊗ H_A_bar and Φ_B: H_B → H_B' ⊗ H_B_bar such that (Φ_A ⊗ Φ_B)|ψ⟩ = |junk⟩ ⊗ |Φ⁺⟩, and under which A₀, A₁ and B₀, B₁ act on the target qubits as Pauli σ_z, σ_x and (σ_z + σ_x)/√2, (σ_z - σ_x)/√2.
- F0108 (supported): The Mayers-Yao self-testing protocol (Mayers & Yao, 2004) device-independently certifies a maximally entangled state |Φ⁺⟩ and reference measurement choices using 3 measurement settings per party (x,y ∈ {0,1,2}). In robust self-testing, if observed correlation statistics P(ab|xy) deviate by ε in trace distance or L₁ norm from ideal target statistics, the physical state |ψ⟩ satisfies ||(Φ_A ⊗ Φ_B)|ψ⟩ - |junk⟩ ⊗ |Φ⁺⟩||₂ = O(√ε) (with O(ε) achieved under optimized robust self-testing bounds), guaranteeing quantitative state certification under experimental noise.
- F0109 (supported): Parallel self-testing protocols establish device-independent certification of N-copy tensor product states |Φ⁺⟩^{⊗N} and high-dimensional quantum systems (C^{2^N} ⊗ C^{2^N}) using parallelized Bell tests. Specifically, testing N maximally entangled qubit pairs simultaneously under parallel CHSH inequalities certifies that the shared state is locally isometric to |junk⟩ ⊗ (|Φ⁺⟩)^{⊗N} with a number of measurement choices per party that remains fixed at 2 (independent of N) or scales polynomial in N, enabling efficient high-dimensional quantum hardware verification.
- F0110 (supported): Self-testing rigidity characterizes the boundary ∂Q of the quantum correlation set: a correlation point P* ∈ ∂Q is rigid if and only if all physical quantum realizations (H_A, H_B, |ψ⟩, {A_a^x}, {B_b^y}) yielding P* are unique up to a local isometry Φ = Φ_A ⊗ Φ_B. Exposed vector extremal points of Q that maximize linear Bell inequalities (e.g., CHSH, tilted CHSH, and CGLMP inequalities) are rigid self-tests, and every pure bipartite entangled state can be self-tested by maximal violation of an appropriate Bell inequality.

**Rejected claims:**
- none

**Status changes:**
- none

**Flagged for review (depend on refuted findings):**
- none

**Resource proposals:**
- none

**Published updates:**
- none

**Disagreements:**
- Minor imprecision in Claim 4's robust self-testing statement regarding the metric for statistical deviation (trace distance vs L₁ norm on probabilities), addressed by lowering confidence to 0.95.

**Roadmap changes:**
- added task T20 under M3: Catalogue and verify the NPA hierarchy, almost-quantum correlations, and device-independent self-testing
- T20 proposed -> active: chosen by the planner: M3 has completed quantum speed limits (T15), Holevo/Maassen-Uffink (T16), EUR-QM (T17/T18), and CHSH/Tsirelson/Kochen-Specker (T19). The natural structural continuation is mapping the correlation hierarchy (NPA, almost-quantum) and the device-independent certification protocols (self-testing) that make Tsirelson's bound operational. This deepens the physical information bounds catalogue into the geometry of quantum correlations and their device-independent verification.
- T20 active -> done: worker and reviewer agree the goal was met

**Appeal check:** No claim appears shaped to impress rather than to be true. All statements are technical, precise, include appropriate caveats (strict inclusions, asymptotic convergence, 'up to local isometries'), and cite primary literature. The confidence levels are high but justified by the maturity of these results.

**Next step:** Proceed to the suggested next task on network nonlocality and network-assisted self-testing protocols (e.g., triangle networks, network-assisted entanglement certification).

**Problems:**
- failed attempt: gemini-3.8-flash (work): Transient: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please 
- failed attempt: gemini-3.8-flash (work): Transient: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please 
- failed attempt: gemini-3.6-flash (work): Transient: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please 
- failed attempt: gemini-3.6-flash (work): Transient: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please 
- failed attempt: gemini-3.6-flash (work): Transient: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please 
- failed attempt: gemini-3.6-flash (work): Transient: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please 
