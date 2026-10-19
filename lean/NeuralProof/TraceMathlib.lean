import Lean

open Lean

private unsafe def run (fileName : String) : IO Unit := do
  enableInitializersExecution
  let source ← IO.FS.readFile fileName
  let inputCtx := Parser.mkInputContext source fileName
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
  if hasErrors then throw <| IO.userError "Lean reported source elaboration errors; refusing to export a partial trace"
  let some _state := Language.Lean.waitForFinalCmdState? snap
    | throw <| IO.userError "Lean did not produce a final command state"
  let mut tactics : Array Json := #[]
  let mut commands : Array Json := #[]
  for snapshot in (Language.toSnapshotTree snap).getAll do
    if let some tree := snapshot.infoTree? then
      let (newTactics, newCommands) ← tree.foldInfoM (fun ctx info (tacc, cacc) => do
        match info with
        | .ofTacticInfo tactic =>
          let text := tactic.stx.reprint.getD ""
          let beforeCtx := { ctx with mctx := tactic.mctxBefore }
          let afterCtx := { ctx with mctx := tactic.mctxAfter }
          let before := (← beforeCtx.ppGoals tactic.goalsBefore).pretty
          let after := (← afterCtx.ppGoals tactic.goalsAfter).pretty
          pure ((tacc.push <| Json.mkObj [
            ("declaration", toJson (ctx.parentDecl?.map toString |>.getD "")),
            ("syntax_kind", toJson (tactic.stx.getKind.toString)),
            ("source_start", toJson (tactic.stx.getPos?.map toString |>.getD "")),
            ("source_end", toJson (tactic.stx.getTailPos?.map toString |>.getD "")),
            ("tactic", toJson text),
            ("goal_state", toJson before),
            ("result_state", toJson after),
            ("completed", toJson tactic.goalsAfter.isEmpty)
          ]), cacc)
        | .ofCommandInfo command =>
          let stx := command.toElabInfo.stx
          pure (tacc, cacc.push <| Json.mkObj [
            ("declaration", toJson (ctx.parentDecl?.map toString |>.getD "")),
            ("syntax_kind", toJson (stx.getKind.toString)),
            ("source_start", toJson (stx.getPos?.map toString |>.getD "")),
            ("source_end", toJson (stx.getTailPos?.map toString |>.getD "")),
            ("source_text", toJson (stx.reprint.getD ""))
          ])
        | _ => pure (tacc, cacc)) (tactics, commands)
      tactics := newTactics
      commands := newCommands
  IO.println <| Json.mkObj [
    ("tactics", Json.arr tactics),
    ("commands", Json.arr commands)
  ] |>.compress

unsafe def main (args : List String) : IO Unit := do
  match args with
  | [fileName] => run fileName
  | _ => throw <| IO.userError "usage: lake env lean --run NeuralProof/TraceMathlib.lean -- <file.lean>"
