import Lean

open Lean

/-!
# Dump constant-to-module mapping

Print `module<TAB>constant` for every constant in the imported environment.
The statement dumper deliberately does not carry module provenance; this cheap
companion pass lets the Python builder record which module defined each
declaration, so leakage controls can exclude the target's own module.

    lake env lean --run NeuralProof/DumpModules.lean --import Mathlib \
      > /tmp/mathlib-modules.tsv
-/
private def parseImport (args : List String) : String :=
  let rec go : List String → String
    | "--import" :: value :: _ => value
    | _ :: rest => go rest
    | [] => "Mathlib"
  go args

private unsafe def run (args : List String) : IO Unit := do
  enableInitializersExecution
  let source := s!"import {parseImport args}\n"
  let inputCtx := Parser.mkInputContext source "<dump-modules>"
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
    throw <| IO.userError "the import failed to elaborate; refusing to dump a partial environment"
  let some state := Language.Lean.waitForFinalCmdState? snap
    | throw <| IO.userError "Lean did not produce a final command state"
  let env := state.env
  for h : i in *...env.header.moduleData.size do
    let moduleName := env.header.moduleNames[i]!
    let data := env.header.moduleData[i]!
    for h' : j in *...data.constNames.size do
      IO.println s!"{moduleName}\t{data.constNames[j]!}"

unsafe def main (args : List String) : IO Unit := run args
