import Lean

open Lean

/-- Print every constant name in the imported Mathlib environment, one per line.

Using the frontend (rather than a plain `import Mathlib` + `getEnv`) keeps this
file itself cheap to elaborate and runs the import inside `IO`.  Run from the
pinned `lean/` project:

    lake env lean --run NeuralProof/DumpDeclarations.lean > /tmp/mathlib-declarations.txt

The Python builder sorts and deduplicates the output, writes the index, and
records the Mathlib revision and toolchain in a metadata file.
-/
private unsafe def run : IO Unit := do
  enableInitializersExecution
  let source := "import Mathlib\n"
  let inputCtx := Parser.mkInputContext source "<dump-declarations>"
  let setup (header : Elab.HeaderSyntax) : Language.ProcessingT IO
      (Except Language.Lean.HeaderProcessedSnapshot Language.Lean.SetupImportsResult) := do
    return .ok {
      mainModuleName := Name.anonymous
      isModule := header.isModule
      imports := header.imports
      opts := {}
    }
  let snap ← (Language.Lean.process setup none) { inputCtx with }
  let hasErrors ← (Language.toSnapshotTree snap).runAndReport {} false
  if hasErrors then
    throw <| IO.userError "Mathlib failed to elaborate; refusing to dump a partial environment"
  let some state := Language.Lean.waitForFinalCmdState? snap
    | throw <| IO.userError "Lean did not produce a final command state"
  for (name, _) in state.env.constants.toList do
    IO.println name

unsafe def main (_args : List String) : IO Unit := run
