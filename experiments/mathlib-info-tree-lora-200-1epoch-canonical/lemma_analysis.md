# Lemma Usage Analysis

Loaded 2044 unique lemmas from training data

## Executive Summary

- **`rw`**: 0/33 correct (0.0%), 33 total attempts
- **`apply`**: 0/19 correct (0.0%), 19 total attempts
- **`exact`**: 0/19 correct (0.0%), 19 total attempts
- **`simpa`**: 0/26 correct (0.0%), 26 total attempts
- **`simp`**: 14/55 correct (25.5%), 55 total attempts

## Analysis: `rw`

**Breakdown:** 0 correct, 15 wrong (same family), 18 wrong (different family)

### Wrong `rw` predictions (same family - lemma selection issue)

| Example | Target Lemmas | Predicted Lemmas | Target in Ctx? | Pred in Ctx? | Pred in Train? |
| :-- | :-- | :-- | :-- | :-- | :-- |
| Mathlib_Algebra_AffineMonoid_Irreducible | `hSgen` | `ha` | ✓ | ✓ | ✓ |
| Mathlib_Algebra_Category_ModuleCat_Semi_ | `smul_assoc`, `smul_eq_mul`, `Algebra.commutes`, `mul_smul` | `algebraMap_eq_smul`, `algebrasum_smul`, `algebrasum_smul_eq` | ✗ | ✗ | ✗ |
| Mathlib_Algebra_Category_ModuleCat_Presh | `cancel_mono`, `assoc`, `Iso.inv_hom_id`, `comp_id` | `apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_` | ✗ | ✗ | ✗ |
| Mathlib_Algebra_Category_AlgCat_TensorAl | `Functor.isRightAdjoint_comp_iff_right` | `forget₂` | ✗ | ✓ | ✗ |
| Mathlib_Algebra_Category_ModuleCat_Semi_ | `LinearMap.id_apply`, `SemimoduleCat.hom_id` | `h` | ✗ | ✓ | ✓ |
| Mathlib_Algebra_Category_ModuleCat_Semi_ | `Subsingleton.elim` | `Hom.hom_eq_iff` | ✗ | ✗ | ✗ |
| Mathlib_Algebra_AffineMonoid_Irreducible | `hn`, `Finset.sdiff_singleton_eq_erase`, `Finset.mul_prod_erase` | `hm`, `hs` | ✓ | ✓ | ✓ |
| Mathlib_Algebra_Category_ModuleCat_Presh | `hm`, `comp_app` | `hm`, `hm.app_apply` | ✓ | ✓ | ✓ |
| Mathlib_Algebra_AffineMonoid_Irreducible | `hm`, `Finset.sdiff_singleton_eq_erase`, `Finset.mul_prod_erase` | `hm` | ✓ | ✓ | ✓ |
| Mathlib_Algebra_AffineMonoid_Irreducible | `hr'`, `Set.singleton_subset_iff` | `hm` | ✗ | ✓ | ✓ |
| Mathlib_Algebra_Category_ModuleCat_Presh | `ModuleCat.mono_iff_injective` | `Hom.injective_apply_injective` | ✗ | ✗ | ✗ |
| Mathlib_Algebra_Category_ModuleCat_Presh | `h₁`, `Hom.naturality` | `h₁`, `h₂` | ✓ | ✓ | ✓ |
| Mathlib_Algebra_AffineMonoid_Irreducible | `hSgen` | `hm` | ✓ | ✓ | ✓ |
| Mathlib_Algebra_AffineMonoid_Irreducible | `hr'` | `hs` | ✗ | ✓ | ✓ |
| Mathlib_Algebra_Category_ModuleCat_Presh | `ModuleCat.epi_iff_surjective` | `Hom.fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun` | ✗ | ✗ | ✗ |

## Analysis: `apply`

**Breakdown:** 0 correct, 0 wrong (same family), 19 wrong (different family)

## Analysis: `exact`

**Breakdown:** 0 correct, 0 wrong (same family), 19 wrong (different family)

## Analysis: `simpa`

**Breakdown:** 0 correct, 0 wrong (same family), 26 wrong (different family)

## Analysis: `simp`

**Breakdown:** 14 correct, 13 wrong (same family), 28 wrong (different family)

### Correct `simp` predictions

| Example | Target Lemmas | In Context? | In Training? |
| :-- | :-- | :-- | :-- |
| Mathlib_Algebra_Algebra_Pi_lean::AlgEquiv_sumArrow | (no lemmas) | - | - |
| Mathlib_Algebra_Category_ModuleCat_Semi_lean::Semi | (no lemmas) | - | - |
| Mathlib_Algebra_Category_ModuleCat_Semi_lean::Semi | (no lemmas) | - | - |
| Mathlib_Algebra_Category_AlgCat_Basic_lean::AlgCat | (no lemmas) | - | - |
| Mathlib_Algebra_Algebra_Pi_lean::AlgEquiv_funUniqu | (no lemmas) | - | - |
| Mathlib_Algebra_Category_CommAlgCat_Basic_lean::Co | (no lemmas) | - | - |
| Mathlib_Algebra_Category_AlgCat_Basic_lean::AlgCat | (no lemmas) | - | - |
| Mathlib_Algebra_Category_AlgCat_TensorAlgebra_lean | (no lemmas) | - | - |
| Mathlib_Algebra_Algebra_Subalgebra_MulOpposite_lea | (no lemmas) | - | - |
| Mathlib_Algebra_Algebra_StrictPositivity_lean::IsS | (no lemmas) | - | - |
| Mathlib_Algebra_Category_AlgCat_Basic_lean::AlgCat | (no lemmas) | - | - |
| Mathlib_Algebra_BigOperators_ModEq_lean::Int_ModEq | (no lemmas) | - | - |
| Mathlib_Algebra_Category_AlgCat_Basic_lean::Catego | (no lemmas) | - | - |
| Mathlib_Algebra_Algebra_Pi_lean::AlgEquiv_piCongrR | (no lemmas) | - | - |

### Wrong `simp` predictions (same family - lemma selection issue)

| Example | Target Lemmas | Predicted Lemmas | Target in Ctx? | Pred in Ctx? | Pred in Train? |
| :-- | :-- | :-- | :-- | :-- | :-- |
| Mathlib_Algebra_BigOperators_Module_lean | `Nat.add_sub_cancel` | (none) | ✗ | ✗ | ✗ |
| Mathlib_Algebra_BigOperators_Module_lean | `range_eq_Ico` | (none) | ✗ | ✗ | ✗ |
| Mathlib_Algebra_BigOperators_Module_lean | `range_eq_Ico` | `mul_add_add_mul_add_mul_add_mul_add_mul_add_mul_add_mul_add_mul_add_mul_add_mul_add_mul_add_mul_add_mul_add_mul_add_mul` | ✗ | ✗ | ✗ |
| Mathlib_Algebra_BigOperators_ModEq_lean: | `modEq_natAbs`, `ZMod.intCast_eq_intCast_iff`, `cast_zero`, `cast_sum` | `hf` | ✗ | ✓ | ✓ |
| Mathlib_Algebra_Algebra_Spectrum_Pi_lean | `isQuasiregular_iff'`, `isUnit_map_iff`, `Pi.isUnit_iff` | `IsQuasiregular_iff_isQuasiregular_iff` | ✗ | ✗ | ✗ |
| Mathlib_Algebra_Algebra_Spectrum_Pi_lean | `isQuasiregular_iff'`, `isUnit_map_iff`, `Prod.isUnit_iff` | (none) | ✗ | ✗ | ✗ |
| Mathlib_Algebra_BigOperators_ModEq_lean: | `ZMod.natCast_eq_natCast_iff`, `cast_one`, `cast_prod`, `apply_ite` | `hf` | ✗ | ✓ | ✓ |
| Mathlib_Algebra_BigOperators_ModEq_lean: | `modEq_natAbs`, `ZMod.intCast_eq_intCast_iff`, `cast_one`, `cast_prod` | `f_eq_iff_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq` | ✗ | ✗ | ✗ |
| Mathlib_Algebra_BigOperators_ModEq_lean: | `ZMod.natCast_eq_natCast_iff`, `cast_zero`, `cast_sum`, `apply_ite` | `hf` | ✗ | ✓ | ✓ |
| Mathlib_Algebra_Algebra_Pi_lean::Pi_alge | `Algebra.smul_def` | (none) | ✗ | ✗ | ✗ |
| Mathlib_Algebra_BigOperators_ModEq_lean: | `ModEq.refl` | (none) | ✗ | ✗ | ✗ |
| Mathlib_Algebra_BigOperators_ModEq_lean: | `ZMod.natCast_eq_natCast_iff`, `cast_one`, `cast_prod` | `f_eq_iff_eq` | ✗ | ✗ | ✗ |
| Mathlib_Algebra_Algebra_Pi_lean::Pi_alge | `Algebra.smul_def` | (none) | ✗ | ✗ | ✗ |

## Hallucination Statistics

**For wrong predictions in same tactic family (lemma selection errors):**

- Copied from context: 14/27 (51.9%)
- Not in context, but seen in training: 1/27 (3.7%)
- Not in context and not in training (hallucinated): 12/27 (44.4%)

### Hallucinated lemmas (not in context, not in training)

- `algebraMap_eq_smul` (from Mathlib_Algebra_Category_ModuleCat_Semi_lean::SemimoduleCat_)
- `algebrasum_smul` (from Mathlib_Algebra_Category_ModuleCat_Semi_lean::SemimoduleCat_)
- `algebrasum_smul_eq` (from Mathlib_Algebra_Category_ModuleCat_Semi_lean::SemimoduleCat_)
- `apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_` (from Mathlib_Algebra_Category_ModuleCat_Presheaf_Limits_lean::Pre)
- `Hom.hom_eq_iff` (from Mathlib_Algebra_Category_ModuleCat_Semi_lean::SemimoduleCat_)
- `hm.app_apply` (from Mathlib_Algebra_Category_ModuleCat_Presheaf_Limits_lean::Pre)
- `Hom.injective_apply_injective` (from Mathlib_Algebra_Category_ModuleCat_Presheaf_EpiMono_lean::Pr)
- `Hom.fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun_fun` (from Mathlib_Algebra_Category_ModuleCat_Presheaf_EpiMono_lean::Pr)
- `mul_add_add_mul_add_mul_add_mul_add_mul_add_mul_add_mul_add_mul_add_mul_add_mul_add_mul_add_mul_add_mul_add_mul_add_mul` (from Mathlib_Algebra_BigOperators_Module_lean::Finset_sum_range_b)
- `IsQuasiregular_iff_isQuasiregular_iff` (from Mathlib_Algebra_Algebra_Spectrum_Pi_lean::isQuasiregular_pi_)
- `f_eq_iff_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq_eq` (from Mathlib_Algebra_BigOperators_ModEq_lean::Int_prod_modEq_sing)
- `f_eq_iff_eq` (from Mathlib_Algebra_BigOperators_ModEq_lean::Nat_prod_modEq_sing)

## Search Trace Analysis (n=100, w=8)

Search trace not found

## Recommendations

Based on this analysis, and on the retrieval-feasibility measurement:

1. **Retrieval is not yet a solution.** Lexical BM25 over theorem names and
   pretty-printed statements recalled a gold lemma in the top 20 for only
   34.5% of the 84 applicable held-out rows (name-only: 10.7%). Excluding
   the target's own module drops that to 9.5%, so the positive result is
   also partly explained by near-duplicate declarations. See
   `experiments/retrieval-feasibility/README.md`; do not present these
   recall numbers as proof-solving performance.
2. **Constrained decoding is already covered by the pre-filter.** It refuses
   names that cannot resolve in the current environment and state, but it
   cannot choose the right lemma. The filter is opt-in and is a budget
   heuristic, not a correctness check.
3. **Two-stage prediction is still a candidate, conditional on better
   retrieval.** The model is comparatively good at lemma-free tactics
   (`simp`, `ext`, `rfl`), so predicting a skeleton and filling lemma
   arguments is plausible. The next measurement should be embedding/hybrid
   retrieval (or a model reranker) on the same 84 rows before any prompt or
   training change.
4. **Change the evaluation target too.** Exact match on a source tactic is
   only a diagnostic. A retrieval or two-stage method should be judged by
   kernel-verified next-tactic acceptance or bounded proof search, never by
   retrieval recall alone.

