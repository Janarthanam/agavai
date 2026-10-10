---
name: task-dashboard
description: Show a live, Linear-style local dashboard for Markdown checklists in a project's tasks/ folder. Use when someone wants to browse task status, filter by schema priority or tag, archive finished task files, create a task schema, and see file edits appear automatically.
---

# Task dashboard

From this skill's directory, run the bundled server for the requested project:

```bash
python3 scripts/serve.py --project /absolute/path/to/project
```

The project must have a `tasks/` directory. The server prints a local URL; open it for the user when a browser is available. Leave the server running while the dashboard is needed. The page polls the source files once per second and updates after edits, additions, and deletions. List and Kanban board views share the same task data and filters.

The dashboard treats Markdown checkboxes as tasks: `[ ]` todo, `[~]` in progress, `[!]` blocked, and `[x]` done. It groups each task under its nearest heading and source file. `README.md` files are excluded because they commonly explain tracker conventions rather than hold tasks. If a project uses another task format, inspect that format and adapt the parser only for the requested project; do not silently infer statuses from prose.

Create the project's task schema before priority and tag mean anything. From this skill's directory:

```bash
python3 scripts/schema.py --project /absolute/path/to/project --priority P0,P1,P2 --tag mvp,reliability
```

That writes `tasks/schema.json`. It refuses to replace an existing schema unless `--force` is passed. `priority` and `tag` are lists of tokens. A token starts with a letter and then uses letters, digits, `_`, or `-`. The same token cannot be both a priority and a tag.

The dashboard gives each checklist item one priority and any number of tags when that item's text, including wrapped lines, contains a schema token as a whole word. The canonical spelling comes from the schema. Without `tasks/schema.json`, every item has no priority and no tags. A file-level prose summary is not applied to its items.

Open a file whose items are all done and use **Move to archive** to place that file in `tasks/archive/`. Archived files stay out of the current list. The server writes task files only for that move. Creating the schema is a separate command.

The script uses only Python's standard library. It is independent of the project's language, framework, and existing dashboard.
