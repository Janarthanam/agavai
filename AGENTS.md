# AGENTS.md — working discipline for coding agents

This file governs how any coding agent (or human, for that matter) works in this
repository. It exists because unmanaged agents default to two failure modes: **scope
creep** (fixing/rewriting things nobody asked for) and **slop** (code that works but
that no human would have written — over-abstracted, duplicated, unreadable, or quietly
wrong on edge cases). Both are addressed below. Follow this before writing any code, not
after.

## 0. Assume you are not alone

**Other agents — in other sessions, other machines, other tools you cannot see — may be
working on this same repository concurrently, right now.** This is the default assumption,
not an edge case to occasionally consider. Never assume you have exclusive ownership of
the working tree for the duration of your task.

- Before starting work, check current state (`git status`, `git log -1`, re-read any file
  you're about to change) — don't work from a stale mental snapshot taken at the start of
  a long session.
- Before writing a change, re-read the specific file/section you're about to touch, even
  if you read it earlier this session. It may have changed under you.
- Prefer small, frequent, atomic commits over one large batched change — this shrinks the
  window in which your work and someone else's can collide, and makes a collision easy to
  see and resolve instead of silently overwritten.
- If you find the file already changed in a way that conflicts with your plan, stop and
  reconcile — read what changed, understand why, and adapt, rather than overwriting it or
  proceeding as if you're still working from the old version.
- Never assume a lock, a "nobody else touches this file" convention, or a coordination
  mechanism exists unless the repo explicitly documents one. If you need one and it
  doesn't exist, that's a gap to flag, not a risk to ignore.

### 00. Task management and bookkeeping

Use the repository's task tracker when the work is substantial enough that another agent
or human would benefit from seeing its owner, current state, decisions, or handoff notes.
If the user explicitly asks for task bookkeeping, always use it. If no tracker exists and
bookkeeping is required, create a simple `tasks/` directory that follows any task format
already documented in the repository.

A task update is **not required** for:

- read-only investigation, explanation, or review that does not change the repository;
- a trivial, self-contained edit completed in the same session with no meaningful handoff
  risk, unless the user asks for tracking;
- routine validation or follow-up work already represented accurately by an existing task;
- updating the task tracker itself or making a minor correction to these instructions.

When uncertain, update the tracker if the work spans multiple steps, files, sessions, or
agents; can become blocked; changes behavior or architecture; or needs a durable record of
why a decision was made. Do not create a task merely to record that you are updating tasks.

When tracking is warranted:

1. Reuse the relevant task file. Create a new one only when no existing task accurately
   represents the work.
2. Before implementation, mark the task `in progress` and append the date, agent identity,
   scope, and starting context.
3. Append meaningful progress, decisions, validation results, blockers, and handoff notes.
   Do not rewrite or remove earlier history.
4. If waiting for user input, mark the task `blocked` or `waiting for input` and state the
   exact decision or information needed near the top so it is easy to find.
5. Mark the task complete only after the work is finished, validated, and committed to the
   local repository. Record the commit hash and validation performed.
6. If committing is not authorized or is not possible, leave the task in progress and note
   that implementation is complete but awaiting commit.

For each task also add the changed files and possibly diffs so that if needed we can inspect the changes done and other agent can take over in progress tasks that are abandoned. write a timestamp and session name as well.

Keep task updates concise and factual. Do not change unrelated task statuses, duplicate an
existing task, or report planned work as completed.

## 1. Consult before you construct

**Before writing any new logic, function, type, or module, search the existing codebase
for something that already does this or something close to it.** A human engineer joining
a codebase reads around before adding code; an agent must do the same, every time, not
just on the first task of a session.

Concretely, before writing:
- Grep/search for existing functions, utilities, types, or patterns that solve the same or
  an adjacent problem. Search by concept, not just by the exact name you're about to give
  your new thing — the existing one may be named differently.
- Check for an existing abstraction (a base class, interface, shared helper, config
  pattern) that your new code should extend or use, rather than duplicating its shape
  next to it.
- If you find something close but not quite right, prefer extending or generalizing it
  slightly over forking a parallel implementation — but only if the generalization is
  small and obviously correct. Don't force an awkward abstraction just to avoid a second
  small function; two similar-looking small pieces of code are often clearer than one
  wrong abstraction (see §3).
- Check how similar problems are solved elsewhere in the repo (error handling style,
  logging conventions, naming, file layout) and match it. Consistency with the existing
  codebase beats your own personal preference or a "better" pattern from elsewhere.
- If reuse would require a nontrivial refactor of existing code, don't silently do the
  refactor as a side effect of your task — call it out (see §4) and let it be a deliberate,
  reviewable decision.
- Before implementation, inspect the repository's documentation and identify every current
  specification that governs the task. Consider product behavior, user experience,
  architecture, component design, interfaces, data contracts, deployment, operations, and
  acceptance criteria as applicable; do not assume one document contains the whole contract.
- Follow the documentation hierarchy, conventions, and formats already established in the
  repository. Treat superseded or archived material as context rather than current guidance.
- If applicable specifications are missing, ambiguous, or contradictory, stop and surface
  the gap or conflict instead of inventing a requirement or silently choosing one source.

Skipping this step is the single most common source of duplicated logic, inconsistent
patterns, and code that "works" but doesn't belong in the codebase it landed in.

## 2. Write for the human who reads it next

Code is read far more often than it's written. Every line should be as clear to a human
reviewer as it is correct to a compiler.

- Name things for what they mean, not for how they're implemented. A reader shouldn't need
  to open the function to guess what it does from its name.
- Prefer straightforward control flow over clever one-liners. If you have to pause to
  parse your own code, rewrite it plainer.
- Keep functions doing one thing. If you're narrating "and then it also..." while writing
  a function, that's a second function.
- Match the file's existing formatting, structure, and idioms even if you'd personally
  choose differently — a codebase that reads as one voice is more valuable than any single
  local improvement.
- Comments explain **why**, never **what** — the code already says what. Write a comment
  only when there's a non-obvious constraint, a subtle invariant, a workaround for a
  specific bug, or a reason a reader would otherwise be surprised by. If deleting a comment
  wouldn't confuse anyone, don't write it.
- If a piece of logic is inherently complex (an algorithm, a tricky concurrency invariant,
  a business rule with real exceptions), make the complexity visible and named, not buried
  — a well-named helper function documents intent better than a comment above tangled
  inline code.

## 3. No slop: concrete anti-patterns to refuse

Treat all of the following as defects to avoid introducing, not stylistic preferences:

- **Speculative generality.** Don't build a plugin system, config flag, or abstract base
  class for a use case that doesn't exist yet. Solve the problem you have. Three similar
  concrete lines are better than one premature abstraction covering imagined future cases.
- **Duplicated logic introduced by you.** If your change needs the same logic twice in the
  same task, factor it out immediately — don't leave two near-identical blocks for someone
  else to notice.
- **Dead code.** Don't leave unused functions, commented-out blocks, unused imports,
  feature flags with only one live branch, or "just in case" fallback paths for scenarios
  that can't occur given the code's actual callers.
- **Silent failure.** Don't swallow exceptions, ignore error return values, or add a
  fallback/default that hides a real failure instead of surfacing it. Only handle an error
  where you can do something meaningful with it; otherwise let it propagate.
- **Unrequested scope.** Don't rename unrelated variables, reformat untouched code,
  "improve" adjacent functions, or refactor something you happened to walk past while
  doing your actual task. If you notice something that should change, flag it (§4) —
  don't fold it into your diff.
- **Backwards-compatibility theater for code with no external consumers.** Don't add
  shims, deprecated-but-kept branches, or compatibility layers for internal code you can
  simply update at all call sites, unless you were explicitly told compatibility matters
  here.
- **Validation/error-handling for impossible inputs.** Don't defensively check conditions
  that the type system, a caller contract, or an upstream invariant already rules out.
  Validate at real boundaries (user input, external APIs, network/file I/O) — not
  everywhere, out of habit.
- **Copy-adapted code without understanding it.** If you're adapting an existing pattern,
  understand why it's shaped that way before reusing it — don't cargo-cult a pattern into
  a context where its original reasoning doesn't apply.

## 4. Scope discipline

- Do the task you were given. If you discover something else that's broken, risky, or
  worth fixing, **report it, don't fix it** — unless it's a one-line, unambiguous
  correction directly required to complete your actual task correctly.
  - If you're an agent capable of flagging follow-up work for a separate task/session, do
    that rather than expanding your own diff.
  - If you can only report in text, say so plainly at the end of your work rather than
    silently folding the fix in.
- If a task's instructions only cover part of a file, service, or module, don't take that
  as license to "improve" the rest of it. Touch only what the task requires.
- If completing your task well genuinely requires touching a file outside your assigned
  scope, say so explicitly before doing it (or flag it clearly in your output if you're
  running unattended) — don't quietly expand your own mandate because it seemed like the
  right call in the moment. An agent that unilaterally decides to rewrite something
  adjacent — even correctly — has made a decision that belongs to whoever assigned the
  task, not to itself.

## 5. Definition of done

A change is done when:
1. It satisfies the specific task/requirement/test it was assigned — cite which one.
2. It reuses existing abstractions where they exist (§1), rather than duplicating them.
3. A human reading the diff cold, with no other context, can understand what it does and
   why, without needing you to explain it afterward.
4. It contains nothing beyond what the task asked for — no drive-by fixes, no speculative
   extensibility, no unrelated cleanup (§3, §4).
5. Existing tests pass, and new logic has tests covering its real behavior and edge cases
   — not just its happy path.
6. You've reviewed your own diff once, as if reviewing someone else's PR, before calling
   it finished.



If a task's requirements are ambiguous or contradictory, don't guess broadly and ship your
best interpretation as if it were settled — surface the ambiguity and the specific
question it raises, the same way you'd stop and ask a human teammate rather than silently
picking an answer that might be wrong in a way nobody notices until much later.

When a step doesn't need my input, keep going. Put status notes in the
same message as your next action.
Stop and ask only when you can't continue without me, or before anything
destructive: deleting data, force-pushing, or changing anything outside
this repository.
