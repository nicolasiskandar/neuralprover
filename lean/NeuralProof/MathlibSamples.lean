module

import Mathlib

theorem np_mathlib_add_zero (n : Nat) : n + 0 = n := by
  simp

theorem np_mathlib_norm_num : (37 : Nat) + 5 = 42 := by
  norm_num

theorem np_mathlib_and_intro (p q : Prop) (hp : p) (hq : q) : p ∧ q := by
  exact ⟨hp, hq⟩
