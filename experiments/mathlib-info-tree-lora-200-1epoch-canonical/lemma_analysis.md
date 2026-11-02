# Lemma Usage Analysis

Loaded 1694 unique lemmas from training data

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
| Mathlib_Algebra_Category_ModuleCat_Presh | `assoc`, `Iso.inv_hom_id`, `comp_id` | `apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_` | ✗ | ✗ | ✗ |
| Mathlib_Algebra_Category_AlgCat_TensorAl | (none) | (none) | ✗ | ✗ | ✗ |
| Mathlib_Algebra_Category_ModuleCat_Semi_ | `SemimoduleCat.hom_id` | `h` | ✗ | ✓ | ✓ |
| Mathlib_Algebra_Category_ModuleCat_Semi_ | (none) | `Hom.hom_eq_iff` | ✗ | ✗ | ✗ |
| Mathlib_Algebra_AffineMonoid_Irreducible | `hn`, `Finset.sdiff_singleton_eq_erase` | `hm`, `hs` | ✓ | ✓ | ✓ |
| Mathlib_Algebra_Category_ModuleCat_Presh | `hm`, `comp_app` | `hm`, `hm.app_apply` | ✓ | ✓ | ✓ |
| Mathlib_Algebra_AffineMonoid_Irreducible | `hm`, `Finset.sdiff_singleton_eq_erase` | `hm` | ✓ | ✓ | ✓ |
| Mathlib_Algebra_AffineMonoid_Irreducible | `Set.singleton_subset_iff` | `hm` | ✗ | ✓ | ✓ |
| Mathlib_Algebra_Category_ModuleCat_Presh | `ModuleCat.mono_iff_injective` | `Hom.injective_apply_injective` | ✗ | ✗ | ✗ |
| Mathlib_Algebra_Category_ModuleCat_Presh | `Hom.naturality` | (none) | ✗ | ✗ | ✗ |
| Mathlib_Algebra_AffineMonoid_Irreducible | `hSgen` | `hm` | ✓ | ✓ | ✓ |
| Mathlib_Algebra_AffineMonoid_Irreducible | (none) | `hs` | ✗ | ✓ | ✓ |
| Mathlib_Algebra_Category_ModuleCat_Presh | `ModuleCat.epi_iff_surjective` | (none) | ✗ | ✗ | ✗ |

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
| Mathlib_Algebra_BigOperators_Module_lean | `range_eq_Ico` | (none) | ✗ | ✗ | ✗ |
| Mathlib_Algebra_BigOperators_ModEq_lean: | `modEq_natAbs`, `ZMod.intCast_eq_intCast_iff`, `cast_zero`, `cast_sum` | (none) | ✗ | ✗ | ✗ |
| Mathlib_Algebra_Algebra_Spectrum_Pi_lean | `isUnit_map_iff`, `Pi.isUnit_iff` | `IsQuasiregular_iff_isQuasiregular_iff` | ✗ | ✗ | ✗ |
| Mathlib_Algebra_Algebra_Spectrum_Pi_lean | `isUnit_map_iff`, `Prod.isUnit_iff` | (none) | ✗ | ✗ | ✗ |
| Mathlib_Algebra_BigOperators_ModEq_lean: | `ZMod.natCast_eq_natCast_iff`, `cast_one`, `cast_prod`, `apply_ite`, `Nat.cast` | (none) | ✗ | ✗ | ✗ |
| Mathlib_Algebra_BigOperators_ModEq_lean: | `modEq_natAbs`, `ZMod.intCast_eq_intCast_iff`, `cast_one`, `cast_prod` | (none) | ✗ | ✗ | ✗ |
| Mathlib_Algebra_BigOperators_ModEq_lean: | `ZMod.natCast_eq_natCast_iff`, `cast_zero`, `cast_sum`, `apply_ite`, `Nat.cast` | (none) | ✗ | ✗ | ✗ |
| Mathlib_Algebra_Algebra_Pi_lean::Pi_alge | `Algebra.smul_def` | (none) | ✗ | ✗ | ✗ |
| Mathlib_Algebra_BigOperators_ModEq_lean: | `ModEq.refl` | (none) | ✗ | ✗ | ✗ |
| Mathlib_Algebra_BigOperators_ModEq_lean: | `ZMod.natCast_eq_natCast_iff`, `cast_one`, `cast_prod` | `f_eq_iff_eq` | ✗ | ✗ | ✗ |
| Mathlib_Algebra_Algebra_Pi_lean::Pi_alge | `Algebra.smul_def` | (none) | ✗ | ✗ | ✗ |

## Hallucination Statistics

**For wrong predictions in same tactic family (lemma selection errors):**

- Copied from context: 8/18 (44.4%)
- Not in context, but seen in training: 1/18 (5.6%)
- Not in context and not in training (hallucinated): 9/18 (50.0%)

### Hallucinated lemmas (not in context, not in training)

- `algebraMap_eq_smul` (from Mathlib_Algebra_Category_ModuleCat_Semi_lean::SemimoduleCat_)
- `algebrasum_smul` (from Mathlib_Algebra_Category_ModuleCat_Semi_lean::SemimoduleCat_)
- `algebrasum_smul_eq` (from Mathlib_Algebra_Category_ModuleCat_Semi_lean::SemimoduleCat_)
- `apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_apply_` (from Mathlib_Algebra_Category_ModuleCat_Presheaf_Limits_lean::Pre)
- `Hom.hom_eq_iff` (from Mathlib_Algebra_Category_ModuleCat_Semi_lean::SemimoduleCat_)
- `hm.app_apply` (from Mathlib_Algebra_Category_ModuleCat_Presheaf_Limits_lean::Pre)
- `Hom.injective_apply_injective` (from Mathlib_Algebra_Category_ModuleCat_Presheaf_EpiMono_lean::Pr)
- `IsQuasiregular_iff_isQuasiregular_iff` (from Mathlib_Algebra_Algebra_Spectrum_Pi_lean::isQuasiregular_pi_)
- `f_eq_iff_eq` (from Mathlib_Algebra_BigOperators_ModEq_lean::Nat_prod_modEq_sing)

## Search Trace Analysis (n=100, w=8)

### Theorem: np_mined_Mathlib_Algebra_BigOperators_ModEq_Nat_ModEq_listSum_map

- Solved: False
- Expanded: 2, Tactic calls: 16, Invalid: 14, Timeouts: 4

**Root-level suggestions (7):**

- ✗ `rw [List.map f l, BigOperators.sum_sum]` - lemmas: `BigOperators.sum_sum`
- ✓ `simp only [List.sum]` - lemmas: `List.sum`
- ✗ `rw [List.mul_sum]` - lemmas: `List.mul_sum`
- ✗ `simpa [List.map_l => l]` - lemmas: (none)
- ✗ `rw [List.fromList, List.prod_sum_mul]` - lemmas: `List.fromList`, `List.prod_sum_mul`
- ✗ `simp only [List.map_smul_map_smul]` - lemmas: `List.map_smul_map_smul`
- ✗ `rw [SumRing.prod_add_mul]` - lemmas: `SumRing.prod_add_mul`

### Theorem: np_mined_Mathlib_Algebra_BigOperators_ModEq_Int_ModEq_listSum_map

- Solved: False
- Expanded: 1, Tactic calls: 8, Invalid: 8, Timeouts: 0

**Root-level suggestions (5):**

- ✗ `rw [List.map_smul, List.map_smul_eq, List.iff_smul]` - lemmas: `List.map_smul`, `List.map_smul_eq`, `List.iff_smul`
- ✗ `simp [List.add_of_one][List.one]` - lemmas: `List.add_of_one`
- ✗ `rw [simplify_sum_eq_zero_one, map_empty_zero_one]` - lemmas: `simplify_sum_eq_zero_one`, `map_empty_zero_one`
- ✗ `simp [List.map_of_map]` - lemmas: `List.map_of_map`
- ✗ `simp` - lemmas: (none)

## Recommendations

Based on this analysis:

1. **Retrieval-Augmented Generation (RAG)** - Most promising. The model doesn't reliably copy lemmas from context and hallucinates. We need to retrieve relevant lemmas from Mathlib based on goal state and inject them into context or use them for constrained decoding.
2. **Constrained Decoding** - Filter model predictions to only use lemmas that exist in a Mathlib index. This would prevent hallucinations even if the model suggests them.
3. **Two-Stage Prediction** - First predict tactic family (model is decent at this), then separately predict/retrieve lemma arguments. The tactic family prediction seems more learnable than lemma selection.
4. **Better Training Data** - Focus on examples where lemmas are in context or where lemma selection is clear. Oversample `rw`/`apply` examples with lemmas that appear in context.

