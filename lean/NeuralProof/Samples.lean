import Lean

theorem np_true : True := by
  trivial

theorem np_add_zero (n : Nat) : n + 0 = n := by
  rfl

theorem np_pair (p q : Prop) (hp : p) (hq : q) : p ∧ q := by
  constructor
  · exact hp
  · exact hq
