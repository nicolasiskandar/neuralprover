import Lean
import Lean.Data.Json
import Mathlib.Lean.FoldEnvironment

open Lean

/-!
# Dump declaration statements as JSON lines

Print `{"name": ..., "kind": ..., "type": ...}` for selected Mathlib constants.
The type is pretty-printed with the delaborator, so it reads like the source
signature.  This is the Lean half of the lemma-statement corpus builder; the
Python script sorts the records, writes the compressed artifact and records
provenance.

Run from the pinned `lean/` project:

    lake env lean --run NeuralProof/DumpStatements.lean \
      --import Mathlib --kinds theorem,def > /tmp/mathlib-statements.jsonl

Using the frontend (rather than a plain `import Mathlib` + `getEnv`) keeps this
file itself cheap to elaborate and gives the final imported environment.  The
fold is parallel, so the record order is stable only after the Python builder
sorts by name.
-/

private def kindOf : ConstantInfo → String
  | .axiomInfo _ => "axiom"
  | .defnInfo _ => "def"
  | .thmInfo _ => "theorem"
  | .opaqueInfo _ => "opaque"
  | .quotInfo _ => "quot"
  | .inductInfo _ => "inductive"
  | .ctorInfo _ => "constructor"
  | .recInfo _ => "recursor"

private structure DumpOptions where
  importModule : String := "Mathlib"
  kinds : List String := ["theorem"]
  limit : Nat := 0

private def parseArgs (args : List String) : DumpOptions :=
  let rec go (args : List String) (opts : DumpOptions) : DumpOptions :=
    match args with
    | "--import" :: value :: rest => go rest { opts with importModule := value }
    | "--kinds" :: value :: rest => go rest { opts with kinds := value.splitOn "," }
    | "--limit" :: value :: rest => go rest { opts with limit := (value.toNat?).getD 0 }
    | _ :: rest => go rest opts
    | [] => opts
  go args {}

private unsafe def run (args : List String) : IO Unit := do
  enableInitializersExecution
  let opts := parseArgs args
  let source := s!"import {opts.importModule}\n"
  let inputCtx := Parser.mkInputContext source "<dump-statements>"
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

  let act (acc : Array String) (name : Name) (info : ConstantInfo) : MetaM (Array String) := do
    let kind := kindOf info
    if opts.kinds.contains kind then
      let fmt ← Lean.PrettyPrinter.ppExpr info.toConstantVal.type
      let line := Json.compress <| Json.mkObj [
        ("name", .str name.toString),
        ("kind", .str kind),
        ("type", .str fmt.pretty)]
      return acc.push line
    else
      return acc

  let coreCtx : Core.Context := { fileName := "<dump-statements>", fileMap := default }
  let coreState : Core.State := { env := state.env }
  let ((tasks, errorRef), _) ←
    (Lean.Meta.foldImportedDecls #[] {} act).toIO coreCtx coreState
  let mut emitted := 0
  for task in tasks do
    match ← IO.wait task with
    | .ok lines =>
      for line in lines do
        if opts.limit == 0 || emitted < opts.limit then
          IO.println line
          emitted := emitted + 1
    | .error exception =>
      throw <| IO.userError (← exception.toMessageData.toString)
  let errors ← errorRef.get
  unless errors.isEmpty do
    IO.eprintln s!"{errors.length} declaration(s) failed to pretty-print"

unsafe def main (args : List String) : IO Unit := run args
