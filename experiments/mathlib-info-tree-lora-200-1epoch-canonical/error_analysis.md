# Error Analysis: 1-Epoch LoRA on InfoTree Corpus

**Eval file:** experiments/mathlib-info-tree-lora-200-1epoch-canonical/tactic-eval-full-heldout.json
**Examples file:** data/mathlib-info-tree-200/examples.jsonl

Loaded 6221 examples from examples.jsonl
Loaded eval with 342 sampled examples

Merged 342 examples

## Executive Summary

- **Base model:** 0/342 correct (0.0%), 157 silent predictions
- **LoRA adapter:** 21/342 correct (6.1%), 0 silent predictions
- **Gain:** +21 correct predictions (+6.1%)
- **Silence fix:** Adapter eliminated all 157 base silent predictions and produced 0 silent predictions of its own

## Silence vs Guessing Analysis

Cross-tabulation of base behavior vs LoRA outcome:

| | LoRA Correct | LoRA Wrong (non-silent) | LoRA Silent | Total |
| :-- | ---: | ---: | ---: | ---: |
| Base Silent | 7 | 150 | 0 | 157 |
| Base Non-Silent | 14 | 171 | 0 | 185 |
| **Total** | **21** | **321** | **0** | **342** |

- **From base-silent rows:** 7/157 became correct (4.5%), 150 became wrong guesses, 0 still silent
- **From base-non-silent rows:** 14/185 became correct (7.6%), mostly fixing the base's wrong guesses

## Tactic Family Breakdown

### Target tactic distribution (overall)

| Tactic Family | Count | % |
| :-- | ---: | ---: |
| `simp` | 55 | 16.1% |
| `rw` | 33 | 9.6% |
| `simpa` | 26 | 7.6% |
| `apply` | 19 | 5.6% |
| `exact` | 19 | 5.6% |
| `have` | 16 | 4.7% |
| `ext` | 12 | 3.5% |
| `obtain` | 11 | 3.2% |
| `intro` | 9 | 2.6% |
| `refine` | 8 | 2.3% |
| `induction` | 8 | 2.3% |
| `dsimp` | 7 | 2.0% |
| `rcases` | 7 | 2.0% |
| `simp_rw` | 7 | 2.0% |
| `rfl` | 6 | 1.8% |

### LoRA accuracy by tactic family

| Tactic Family | Total | Correct | Accuracy |
| :-- | ---: | ---: | ---: |
| `ext` | 12 | 5 | 41.7% |
| `rfl` | 6 | 2 | 33.3% |
| `simp` | 55 | 14 | 25.5% |
| `obtain` | 11 | 0 | 0.0% |
| `simpa` | 26 | 0 | 0.0% |
| `Set.preimage_union` | 2 | 0 | 0.0% |
| `apply` | 19 | 0 | 0.0% |
| `lift` | 3 | 0 | 0.0% |
| `conv` | 2 | 0 | 0.0% |
| `refine` | 8 | 0 | 0.0% |
| `dsimp` | 7 | 0 | 0.0% |
| `rw` | 33 | 0 | 0.0% |
| `have` | 16 | 0 | 0.0% |
| `letI` | 2 | 0 | 0.0% |
| `exact` | 19 | 0 | 0.0% |
| `change` | 4 | 0 | 0.0% |
| `rcases` | 7 | 0 | 0.0% |
| `suffices` | 2 | 0 | 0.0% |
| `resolventSet` | 2 | 0 | 0.0% |
| `assumption` | 4 | 0 | 0.0% |
| `induction` | 8 | 0 | 0.0% |
| `infer_instance` | 5 | 0 | 0.0% |
| `simp_rw` | 7 | 0 | 0.0% |
| `use` | 2 | 0 | 0.0% |
| `by_cases` | 3 | 0 | 0.0% |
| `algebraMap_apply` | 2 | 0 | 0.0% |
| `cases` | 2 | 0 | 0.0% |
| `let` | 6 | 0 | 0.0% |
| `ext1` | 3 | 0 | 0.0% |
| `intro` | 9 | 0 | 0.0% |
| `subst` | 2 | 0 | 0.0% |
| `forget₂` | 4 | 0 | 0.0% |
| `congr` | 2 | 0 | 0.0% |
| `compl_compl` | 2 | 0 | 0.0% |
| `abel` | 2 | 0 | 0.0% |
| `spectrum` | 2 | 0 | 0.0% |
| `Algebra.adjoin` | 2 | 0 | 0.0% |

### Base vs LoRA accuracy by family (families with >=3 occurrences)

| Tactic Family | Target Count | Base Correct | Base Acc | LoRA Correct | LoRA Acc | Gain |
| :-- | ---: | ---: | ---: | ---: | ---: | ---: |
| `obtain` | 11 | 0 | 0.0% | 0 | 0.0% | +0 |
| `rfl` | 6 | 0 | 0.0% | 2 | 33.3% | +2 |
| `simpa` | 26 | 0 | 0.0% | 0 | 0.0% | +0 |
| `apply` | 19 | 0 | 0.0% | 0 | 0.0% | +0 |
| `lift` | 3 | 0 | 0.0% | 0 | 0.0% | +0 |
| `simp` | 55 | 0 | 0.0% | 14 | 25.5% | +14 |
| `refine` | 8 | 0 | 0.0% | 0 | 0.0% | +0 |
| `dsimp` | 7 | 0 | 0.0% | 0 | 0.0% | +0 |
| `rw` | 33 | 0 | 0.0% | 0 | 0.0% | +0 |
| `have` | 16 | 0 | 0.0% | 0 | 0.0% | +0 |
| `ext` | 12 | 0 | 0.0% | 5 | 41.7% | +5 |
| `exact` | 19 | 0 | 0.0% | 0 | 0.0% | +0 |
| `change` | 4 | 0 | 0.0% | 0 | 0.0% | +0 |
| `rcases` | 7 | 0 | 0.0% | 0 | 0.0% | +0 |
| `assumption` | 4 | 0 | 0.0% | 0 | 0.0% | +0 |
| `induction` | 8 | 0 | 0.0% | 0 | 0.0% | +0 |
| `infer_instance` | 5 | 0 | 0.0% | 0 | 0.0% | +0 |
| `simp_rw` | 7 | 0 | 0.0% | 0 | 0.0% | +0 |
| `by_cases` | 3 | 0 | 0.0% | 0 | 0.0% | +0 |
| `let` | 6 | 0 | 0.0% | 0 | 0.0% | +0 |
| `ext1` | 3 | 0 | 0.0% | 0 | 0.0% | +0 |
| `intro` | 9 | 0 | 0.0% | 0 | 0.0% | +0 |
| `forget₂` | 4 | 0 | 0.0% | 0 | 0.0% | +0 |

## Goal Complexity Analysis

### Accuracy by hypothesis count

| Hypotheses | Total | Correct | Accuracy |
| :-- | ---: | ---: | ---: |
| 1-2 hypotheses | 6 | 0 | 0.0% |
| 3-4 hypotheses | 34 | 9 | 26.5% |
| 5-6 hypotheses | 80 | 7 | 8.8% |
| 7+ hypotheses | 222 | 5 | 2.3% |

### Accuracy by goal features

| Goal Feature | Total | Correct | Accuracy |
| :-- | ---: | ---: | ---: |
| Has equation | 185 | 17 | 9.2% |
| Has forall | 28 | 1 | 3.6% |
| Has exists | 6 | 0 | 0.0% |

## Source Distribution

### Files contributing to correct predictions

| Source File | Correct Predictions |
| :-- | ---: |
| `Mathlib/Algebra/Category/AlgCat/Basic.lean` | 6 |
| `Mathlib/Algebra/Algebra/Pi.lean` | 3 |
| `Mathlib/Algebra/Category/ModuleCat/Semi.lean` | 3 |
| `Mathlib/Algebra/Category/CommAlgCat/Basic.lean` | 3 |
| `Mathlib/Algebra/Category/HopfAlgCat/Monoidal.lean` | 1 |
| `Mathlib/Algebra/Category/AlgCat/TensorAlgebra.lean` | 1 |
| `Mathlib/Algebra/Algebra/Subalgebra/MulOpposite.lean` | 1 |
| `Mathlib/Algebra/Algebra/StrictPositivity.lean` | 1 |
| `Mathlib/Algebra/BigOperators/ModEq.lean` | 1 |
| `Mathlib/Algebra/Category/CoalgCat/Monoidal.lean` | 1 |

### Declarations with correct predictions

| Source Declaration | Correct Predictions |
| :-- | ---: |
| `HopfAlgCat.MonoidalCategory.inducingFunctorData` | 1 |
| `AlgCat.hom_ext_iff` | 1 |
| `AlgEquiv.sumArrowEquivProdArrow` | 1 |
| `SemimoduleCat.id_apply` | 1 |
| `SemimoduleCat.comp_apply` | 1 |
| `SemimoduleCat.hom_ext_iff` | 1 |
| `AlgCat.hom_inv_apply` | 1 |
| `CommAlgCat.hom_ext_iff` | 1 |
| `AlgEquiv.funUnique` | 1 |
| `CommAlgCat.algEquivOfIso` | 1 |
| `AlgCat.comp_apply` | 1 |
| `AlgCat.tensorAlgebraAdj` | 1 |
| `Subalgebra.unop_adjoin` | 1 |
| `IsStrictlyPositive.of_subsingleton` | 1 |
| `AlgCat.Hom.ext_iff` | 1 |

## Qualitative Examples

### All correct LoRA predictions

#### Correct #1: `Mathlib_Algebra_Category_HopfAlgCat_Monoidal_lean::HopfAlgCat_MonoidalCategory_inducingFunctorData::2181-2184`
- **Source:** `Mathlib/Algebra/Category/HopfAlgCat/Monoidal.lean` :: `HopfAlgCat.MonoidalCategory.inducingFunctorData`
- **Base:** `` (silent)
- **LoRA:** `rfl` ✓
- **Target:** `rfl`
- **Hypotheses:** 4, Goal has equation: False, Goal: `(((mk R x✝¹.carrier (MonoidalCategoryStruct.tensorUnit (HopfAlgCat R)).carrier).compr₂ₛₗ`
- **Context (first 150 chars):** `module
public import Mathlib.Algebra.Category.BialgCat.Monoidal
public import Mathlib.Algebra.Category.HopfAlgCat.Basic
public import Mathlib.RingTheo...`

#### Correct #2: `Mathlib_Algebra_Category_AlgCat_Basic_lean::AlgCat_hom_ext_iff::3299-3302`
- **Source:** `Mathlib/Algebra/Category/AlgCat/Basic.lean` :: `AlgCat.hom_ext_iff`
- **Base:** `case (R : Type u) [CommRing R]` (wrong)
- **LoRA:** `ext` ✓
- **Target:** `ext`
- **Hypotheses:** 4, Goal has equation: True, Goal: `Hom.hom f✝ = Hom.hom f✝`
- **Context (first 150 chars):** `module
public import Mathlib.Algebra.Category.ModuleCat.Basic
public import Mathlib.Algebra.Category.Ring.Basic
public import Mathlib.Algebra.FreeAlge...`

#### Correct #3: `Mathlib_Algebra_Algebra_Pi_lean::AlgEquiv_sumArrowEquivProdArrow::9224-9228`
- **Source:** `Mathlib/Algebra/Algebra/Pi.lean` :: `AlgEquiv.sumArrowEquivProdArrow`
- **Base:** `` (silent)
- **LoRA:** `simp` ✓
- **Target:** `simp`
- **Hypotheses:** 19, Goal has equation: True, Goal: `((RingEquiv.sumArrowEquivProdArrow α β S) ((algebraMap R (α ⊕ β → S)) x✝¹)).1 x✝ =`
- **Context (first 150 chars):** `module
public import Mathlib.Algebra.Algebra.Opposite
public import Mathlib.Algebra.Algebra.Prod
namespace AlgEquiv
variable {α β R ι : Type*} {A₁ A₂ ...`

#### Correct #4: `Mathlib_Algebra_Category_ModuleCat_Semi_lean::SemimoduleCat_id_apply::4825-4829`
- **Source:** `Mathlib/Algebra/Category/ModuleCat/Semi.lean` :: `SemimoduleCat.id_apply`
- **Base:** `` (silent)
- **LoRA:** `simp` ✓
- **Target:** `simp`
- **Hypotheses:** 4, Goal has equation: True, Goal: `(ConcreteCategory.hom (𝟙 M)) x = x`
- **Context (first 150 chars):** `module
public import Mathlib.Algebra.Algebra.Defs
public import Mathlib.Algebra.BigOperators.Group.Finset.Defs
public import Mathlib.Algebra.Category....`

#### Correct #5: `Mathlib_Algebra_Category_ModuleCat_Semi_lean::SemimoduleCat_comp_apply::5106-5110`
- **Source:** `Mathlib/Algebra/Category/ModuleCat/Semi.lean` :: `SemimoduleCat.comp_apply`
- **Base:** `M N O : SemimoduleCat R` (wrong)
- **LoRA:** `simp` ✓
- **Target:** `simp`
- **Hypotheses:** 6, Goal has equation: True, Goal: `(ConcreteCategory.hom (f ≫ g)) x = (ConcreteCategory.hom g) ((ConcreteCategory.hom f) x)`
- **Context (first 150 chars):** `module
public import Mathlib.Algebra.Algebra.Defs
public import Mathlib.Algebra.BigOperators.Group.Finset.Defs
public import Mathlib.Algebra.Category....`

#### Correct #6: `Mathlib_Algebra_Category_ModuleCat_Semi_lean::SemimoduleCat_hom_ext_iff::5114-5117`
- **Source:** `Mathlib/Algebra/Category/ModuleCat/Semi.lean` :: `SemimoduleCat.hom_ext_iff`
- **Base:** `case` (wrong)
- **LoRA:** `ext` ✓
- **Target:** `ext`
- **Hypotheses:** 4, Goal has equation: True, Goal: `Hom.hom f✝ = Hom.hom f✝`
- **Context (first 150 chars):** `module
public import Mathlib.Algebra.Algebra.Defs
public import Mathlib.Algebra.BigOperators.Group.Finset.Defs
public import Mathlib.Algebra.Category....`

#### Correct #7: `Mathlib_Algebra_Category_AlgCat_Basic_lean::AlgCat_hom_inv_apply::4331-4335`
- **Source:** `Mathlib/Algebra/Category/AlgCat/Basic.lean` :: `AlgCat.hom_inv_apply`
- **Base:** `A B : AlgCat R` (wrong)
- **LoRA:** `simp` ✓
- **Target:** `simp`
- **Hypotheses:** 5, Goal has equation: True, Goal: `(ConcreteCategory.hom e.hom) ((ConcreteCategory.hom e.inv) x) = x`
- **Context (first 150 chars):** `module
public import Mathlib.Algebra.Category.ModuleCat.Basic
public import Mathlib.Algebra.Category.Ring.Basic
public import Mathlib.Algebra.FreeAlge...`

#### Correct #8: `Mathlib_Algebra_Category_CommAlgCat_Basic_lean::CommAlgCat_hom_ext_iff::3367-3370`
- **Source:** `Mathlib/Algebra/Category/CommAlgCat/Basic.lean` :: `CommAlgCat.hom_ext_iff`
- **Base:** `case (A ⊢ B) in` (wrong)
- **LoRA:** `ext` ✓
- **Target:** `ext`
- **Hypotheses:** 4, Goal has equation: True, Goal: `Hom.hom f✝ = Hom.hom f✝`
- **Context (first 150 chars):** `module
public import Mathlib.Algebra.Category.AlgCat.Basic
public import Mathlib.Algebra.Category.Ring.Under.Basic
public import Mathlib.CategoryTheor...`

#### Correct #9: `Mathlib_Algebra_Algebra_Pi_lean::AlgEquiv_funUnique::8548-8552`
- **Source:** `Mathlib/Algebra/Algebra/Pi.lean` :: `AlgEquiv.funUnique`
- **Base:** `inst` (wrong)
- **LoRA:** `simp` ✓
- **Target:** `simp`
- **Hypotheses:** 18, Goal has equation: True, Goal: `∀ (x : R), (RingEquiv.piUnique fun i => S) ((algebraMap R (ι → S)) x) = (algebraMap R S) x`
- **Context (first 150 chars):** `module
public import Mathlib.Algebra.Algebra.Opposite
public import Mathlib.Algebra.Algebra.Prod
namespace AlgEquiv
variable {α β R ι : Type*} {A₁ A₂ ...`

#### Correct #10: `Mathlib_Algebra_Category_CommAlgCat_Basic_lean::CommAlgCat_algEquivOfIso::6294-6298`
- **Source:** `Mathlib/Algebra/Category/CommAlgCat/Basic.lean` :: `CommAlgCat.algEquivOfIso`
- **Base:** `variable {R : Type u} [CommRing R]` (wrong)
- **LoRA:** `simp` ✓
- **Target:** `simp`
- **Hypotheses:** 12, Goal has equation: True, Goal: `(ConcreteCategory.hom i.hom) ((ConcreteCategory.hom i.inv) x) = x`
- **Context (first 150 chars):** `module
public import Mathlib.Algebra.Category.AlgCat.Basic
public import Mathlib.Algebra.Category.Ring.Under.Basic
public import Mathlib.CategoryTheor...`

#### Correct #11: `Mathlib_Algebra_Category_AlgCat_Basic_lean::AlgCat_comp_apply::3291-3295`
- **Source:** `Mathlib/Algebra/Category/AlgCat/Basic.lean` :: `AlgCat.comp_apply`
- **Base:** `A B C : AlgCat R` (wrong)
- **LoRA:** `simp` ✓
- **Target:** `simp`
- **Hypotheses:** 6, Goal has equation: True, Goal: `(ConcreteCategory.hom (f ≫ g)) a = (ConcreteCategory.hom g) ((ConcreteCategory.hom f) a)`
- **Context (first 150 chars):** `module
public import Mathlib.Algebra.Category.ModuleCat.Basic
public import Mathlib.Algebra.Category.Ring.Basic
public import Mathlib.Algebra.FreeAlge...`

#### Correct #12: `Mathlib_Algebra_Category_AlgCat_TensorAlgebra_lean::AlgCat_tensorAlgebraAdj::1750-1754`
- **Source:** `Mathlib/Algebra/Category/AlgCat/TensorAlgebra.lean` :: `AlgCat.tensorAlgebraAdj`
- **Base:** `((TensorAlgebra.lift R) (TensorAlgebra.ι R ∘` (wrong)
- **LoRA:** `simp` ✓
- **Target:** `simp`
- **Hypotheses:** 4, Goal has equation: False, Goal: `((((TensorAlgebra.lift R) LinearMap.id).comp`
- **Context (first 150 chars):** `module
public import Mathlib.Algebra.Category.AlgCat.Basic
public import Mathlib.LinearAlgebra.TensorAlgebra.Basic
import Mathlib.Algebra.Category.Grp...`

#### Correct #13: `Mathlib_Algebra_Algebra_Subalgebra_MulOpposite_lean::Subalgebra_unop_adjoin::4959-4963`
- **Source:** `Mathlib/Algebra/Algebra/Subalgebra/MulOpposite.lean` :: `Subalgebra.unop_adjoin`
- **Base:** `` (silent)
- **LoRA:** `simp` ✓
- **Target:** `simp`
- **Hypotheses:** 7, Goal has equation: True, Goal: `x ∈ MulOpposite.op ⁻¹' Set.range ⇑(algebraMap R Aᵐᵒᵖ) ↔ x ∈ Set.range ⇑(algebraMap R A)`
- **Context (first 150 chars):** `module
public import Mathlib.Algebra.Algebra.Subalgebra.Lattice
public import Mathlib.Algebra.Ring.Subring.MulOpposite
namespace Subalgebra
section Se...`

#### Correct #14: `Mathlib_Algebra_Algebra_StrictPositivity_lean::IsStrictlyPositive_of_subsingleton::3028-3032`
- **Source:** `Mathlib/Algebra/Algebra/StrictPositivity.lean` :: `IsStrictlyPositive.of_subsingleton`
- **Base:** `` (silent)
- **LoRA:** `simp` ✓
- **Target:** `simp`
- **Hypotheses:** 6, Goal has equation: False, Goal: `0 ≤ a`
- **Context (first 150 chars):** `module
public import Mathlib.Algebra.Algebra.Spectrum.Quasispectrum
public import Mathlib.Algebra.Order.Star.Basic
variable {A : Type*}
namespace IsSt...`

#### Correct #15: `Mathlib_Algebra_Category_AlgCat_Basic_lean::AlgCat_Hom_ext_iff::1743-1746`
- **Source:** `Mathlib/Algebra/Category/AlgCat/Basic.lean` :: `AlgCat.Hom.ext_iff`
- **Base:** `case (x : Type u) in` (wrong)
- **LoRA:** `ext` ✓
- **Target:** `ext`
- **Hypotheses:** 4, Goal has equation: True, Goal: `x✝.hom' = x✝.hom'`
- **Context (first 150 chars):** `module
public import Mathlib.Algebra.Category.ModuleCat.Basic
public import Mathlib.Algebra.Category.Ring.Basic
public import Mathlib.Algebra.FreeAlge...`

#### Correct #16: `Mathlib_Algebra_Category_AlgCat_Basic_lean::AlgCat_inv_hom_apply::4232-4236`
- **Source:** `Mathlib/Algebra/Category/AlgCat/Basic.lean` :: `AlgCat.inv_hom_apply`
- **Base:** `A B : AlgCat R` (wrong)
- **LoRA:** `simp` ✓
- **Target:** `simp`
- **Hypotheses:** 5, Goal has equation: True, Goal: `(ConcreteCategory.hom e.inv) ((ConcreteCategory.hom e.hom) x) = x`
- **Context (first 150 chars):** `module
public import Mathlib.Algebra.Category.ModuleCat.Basic
public import Mathlib.Algebra.Category.Ring.Basic
public import Mathlib.Algebra.FreeAlge...`

#### Correct #17: `Mathlib_Algebra_BigOperators_ModEq_lean::Int_ModEq_listProd_map_one::4860-4864`
- **Source:** `Mathlib/Algebra/BigOperators/ModEq.lean` :: `Int.ModEq.listProd_map_one`
- **Base:** `` (silent)
- **LoRA:** `simp` ✓
- **Target:** `simp`
- **Hypotheses:** 5, Goal has equation: True, Goal: `(List.map (fun x => 1) l).prod ≡ 1 [ZMOD n]`
- **Context (first 150 chars):** `module
public import Mathlib.Data.ZMod.Basic
import Mathlib.Algebra.BigOperators.Ring.Finset
namespace Int
variable {α : Type*} {n : ℤ} {l : List α} {...`

#### Correct #18: `Mathlib_Algebra_Category_CommAlgCat_Basic_lean::CommAlgCat_Hom_ext_iff::1992-1995`
- **Source:** `Mathlib/Algebra/Category/CommAlgCat/Basic.lean` :: `CommAlgCat.Hom.ext_iff`
- **Base:** `case (R) in` (wrong)
- **LoRA:** `ext` ✓
- **Target:** `ext`
- **Hypotheses:** 4, Goal has equation: True, Goal: `x✝.hom' = x✝.hom'`
- **Context (first 150 chars):** `module
public import Mathlib.Algebra.Category.AlgCat.Basic
public import Mathlib.Algebra.Category.Ring.Under.Basic
public import Mathlib.CategoryTheor...`

#### Correct #19: `Mathlib_Algebra_Category_CoalgCat_Monoidal_lean::CoalgCat_MonoidalCategory_inducingFunctorData::2381-2384`
- **Source:** `Mathlib/Algebra/Category/CoalgCat/Monoidal.lean` :: `CoalgCat.MonoidalCategory.inducingFunctorData`
- **Base:** `` (silent)
- **LoRA:** `rfl` ✓
- **Target:** `rfl`
- **Hypotheses:** 4, Goal has equation: False, Goal: `(((TensorProduct.mk R ↑X.toModuleCat ↑(𝟙_ (CoalgCat R)).toModuleCat).compr₂ₛₗ`
- **Context (first 150 chars):** `module
public import Mathlib.Algebra.Category.CoalgCat.Basic
public import Mathlib.Algebra.Category.ModuleCat.Monoidal.Basic
public import Mathlib.Rin...`

#### Correct #20: `Mathlib_Algebra_Category_AlgCat_Basic_lean::CategoryTheory_Iso_toAlgEquiv::7288-7292`
- **Source:** `Mathlib/Algebra/Category/AlgCat/Basic.lean` :: `CategoryTheory.Iso.toAlgEquiv`
- **Base:** `X₁ X₂ : Type v` (wrong)
- **LoRA:** `simp` ✓
- **Target:** `simp`
- **Hypotheses:** 6, Goal has equation: True, Goal: `(ConcreteCategory.hom i.hom) ((ConcreteCategory.hom i.inv) x) = x`
- **Context (first 150 chars):** `module
public import Mathlib.Algebra.Category.ModuleCat.Basic
public import Mathlib.Algebra.Category.Ring.Basic
public import Mathlib.Algebra.FreeAlge...`

#### Correct #21: `Mathlib_Algebra_Algebra_Pi_lean::AlgEquiv_piCongrRight::5847-5851`
- **Source:** `Mathlib/Algebra/Algebra/Pi.lean` :: `AlgEquiv.piCongrRight`
- **Base:** `inst` (wrong)
- **LoRA:** `simp` ✓
- **Target:** `simp`
- **Hypotheses:** 17, Goal has equation: True, Goal: `(e i) ((algebraMap R ((i : ι) → A₁ i)) r i) = (algebraMap R ((i : ι) → A₂ i)) r i`
- **Context (first 150 chars):** `module
public import Mathlib.Algebra.Algebra.Opposite
public import Mathlib.Algebra.Algebra.Prod
namespace AlgEquiv
variable {α β R ι : Type*} {A₁ A₂ ...`

### Sample of incorrect LoRA predictions (10 examples)

#### Incorrect #1: `Mathlib_Algebra_Category_ModuleCat_Semi_lean::SemimoduleCat_Hom_ext::3459-3462`
- **Source:** `Mathlib/Algebra/Category/ModuleCat/Semi.lean`
- **Base:** `M✝ N✝ : SemimoduleCat R✝` 
- **LoRA:** `simp` (family: `simp`, target family: `ext`)
- **Target:** `ext`
- **Same family:** No
- **Hypotheses:** 5, Goal: `∀ {y : M✝.Hom N✝}, { hom' := hom'✝ }.hom' = y.hom' → { hom' := hom'✝ } = y`

#### Incorrect #2: `Mathlib_Algebra_AffineMonoid_Irreducible_lean::Submonoid_closure_irreducible::3964-3974`
- **Source:** `Mathlib/Algebra/AffineMonoid/Irreducible.lean`
- **Base:** `` (silent)
- **LoRA:** `rw [← ha, ⟨a, b⟩]` (family: `rw`, target family: `rw`)
- **Target:** `rw [hSgen]`
- **Same family:** Yes
- **Hypotheses:** 15, Goal: `a ∈ closure ↑?m.238`

#### Incorrect #3: `Mathlib_Algebra_AffineMonoid_Irreducible_lean::Submonoid_closure_irreducible::3995-4093`
- **Source:** `Mathlib/Algebra/AffineMonoid/Irreducible.lean`
- **Base:** `` (silent)
- **LoRA:** `rw [← hm, ⟨a, b⟩]` (family: `rw`, target family: `obtain`)
- **Target:** `obtain ⟨n, -, hn⟩ := Submonoid.mem_closure_finset (x := b).mp (by rw [hSgen]; exact mem_top _)`
- **Same family:** No
- **Hypotheses:** 17, Goal: `False`

#### Incorrect #4: `Mathlib_Algebra_Algebra_Subalgebra_MulOpposite_lean::Subalgebra_unop_adjoin::4944-4956`
- **Source:** `Mathlib/Algebra/Algebra/Subalgebra/MulOpposite.lean`
- **Base:** `` (silent)
- **LoRA:** `simp` (family: `simp`, target family: `congr`)
- **Target:** `congr with x`
- **Same family:** No
- **Hypotheses:** 6, Goal: `Subsemiring.closure (MulOpposite.op ⁻¹' Set.range ⇑(algebraMap R Aᵐᵒᵖ) ∪ MulOpposite.op ⁻¹' s) =`

#### Incorrect #5: `Mathlib_Algebra_AffineMonoid_Irreducible_lean::irreducible_mem_submonoidClosure_subset::1223-1231`
- **Source:** `Mathlib/Algebra/AffineMonoid/Irreducible.lean`
- **Base:** `` (silent)
- **LoRA:** `rw [Submonoid.closure_iff_iff, Submonoid.closure_iff]` (family: `rw`, target family: `simp_all`)
- **Target:** `simp_all`
- **Same family:** No
- **Hypotheses:** 12, Goal: `1 * b ∈ S`

#### Incorrect #6: `Mathlib_Algebra_Category_ModuleCat_Presheaf_Limits_lean::PresheafOfModules_evaluationJointlyReflectsLimits::1744-1750`
- **Source:** `Mathlib/Algebra/Category/ModuleCat/Presheaf/Limits.lean`
- **Base:** `` (silent)
- **LoRA:** `rw [← hm, hm.apply_apply]` (family: `rw`, target family: `ext1`)
- **Target:** `ext1 X`
- **Same family:** No
- **Hypotheses:** 12, Goal: `∀ (X : Cᵒᵖ), m.app X = { app := fun X => (hc X).lift ((evaluation R X).mapCone s), naturality := ⋯ }`

#### Incorrect #7: `Mathlib_Algebra_BigOperators_Module_lean::Finset_sum_Ico_by_parts::1517-1521`
- **Source:** `Mathlib/Algebra/BigOperators/Module.lean`
- **Base:** `module Finset.Finset.Finset.Finset.Finset.Finset.Finset.Finset.Finset.Finset.Finset.Finset.Finset.Finset.Finset.Finset` 
- **LoRA:** `rfl` (family: `rfl`, target family: `h₁`)
- **Target:** `h₁`
- **Same family:** No
- **Hypotheses:** 14, Goal: `f m • g m +`

#### Incorrect #8: `Mathlib_Algebra_Category_Grp_Zero_lean::GrpCat_isZero_of_subsingleton::666-763`
- **Source:** `Mathlib/Algebra/Category/Grp/Zero.lean`
- **Base:** `inst✝ :` 
- **LoRA:** `simp` (family: `simp`, target family: `refine`)
- **Target:** `refine ⟨fun X => ⟨⟨⟨1⟩, fun f => ?_⟩⟩, fun X => ⟨⟨⟨1⟩, fun f => ?_⟩⟩⟩`
- **Same family:** No
- **Hypotheses:** 2, Goal: `IsZero G`

#### Incorrect #9: `Mathlib_Algebra_Category_ModuleCat_Semi_lean::SemimoduleCat_hom_bijective::5381-5395`
- **Source:** `Mathlib/Algebra/Category/ModuleCat/Semi.lean`
- **Base:** `M N : SemimoduleCat R` 
- **LoRA:** `simp` (family: `simp`, target family: `simpa`)
- **Target:** `simpa using! h`
- **Same family:** No
- **Hypotheses:** 5, Goal: `{ hom' := hom'✝¹ } = { hom' := hom'✝ }`

#### Incorrect #10: `Mathlib_Algebra_BigOperators_Module_lean::Finset_sum_Ico_by_parts::1754-1811`
- **Source:** `Mathlib/Algebra/BigOperators/Module.lean`
- **Base:** `m n : �` 
- **LoRA:** `rfl` (family: `rfl`, target family: `simp_rw`)
- **Target:** `simp_rw [this, sum_neg_distrib, sum_range_succ, smul_add]`
- **Same family:** No
- **Hypotheses:** 18, Goal: `f m • g m +`

## Key Takeaways

1. **Silence fix:** The adapter went from producing tactics on 185/342 rows to 342/342 rows. Of the 21 correct predictions, 7 came from base-silent rows (33.3% of correct answers).
2. **Tactic selection:** 14 correct predictions came from base-non-silent rows where the base was guessing wrong, showing the adapter does learn better tactic selection in some cases.
3. **Best performing families:** `ext`, `rfl`, `simp`
4. **Complexity:** The model seems to work best on simpler goals with fewer hypotheses.

