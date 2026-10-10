---
name: design-doc
description: Writes a design document with a fixed structure — requirements, high-level decisions with pros and cons and an architecture diagram, per-module deployment and performance contracts, low-level sequence flows mapped to critical use cases, optional epics only when the code is not yet written, and a conclusion with references. Use when asked to write, draft, revise, or review a design document, design doc, architecture design, or technical design.
---

# Design document

Write one markdown design document. Read the existing specifications, code, and prior design notes that govern the subject before drafting. Cite those sources. If a requirement, number, or component boundary is not established, state it as an assumption or stop and ask. Do not invent a requirement to fill a section.

Write to the path the user names. Otherwise write `docs/<kebab-case-topic>.md`.

A design document must be scope this way:

1. A clear cut level setting or requirements section.
2. High level design decisions and assumptions for chosing components. It should include a clear cut pro/cons of different approaches and where the current approach stands.
   1. Must include an architecture/design diagram clearly identifying different components
   2. optional deployment diagram - clearly stating different machine boundaries if need be (or pods/containers).
   3. address resilience and reliability etc..
3. Different modules involved and how they would interact - Low level abstraction between different modules. This must include for each of them
   1.  How will they be deployed.
   2.  Lifecycle/Protocol they will serve.
   3. Performance constraints/sla expected from each - correlating with the overall performance of the system.
   4. throughput
   5. configuration
   6. observability etc..
4. Low level design section must contain:
   1. A sequence diagram/flow chart of interaction between different components
   2. Take a critial use cases (one/two) and map it to the flows. Idea is to exemplify clearly the flow of information to/from different components.
5. (Optional) List of high level epics for the underlying task manager with appropriate AI and human touch points needed. Do this only if the code is yet to be written
6. Conclusion & References must list all the material that is relevant.
   1. Competing systems and evaluations
   2. Core design patterns etc.

## How to fill it

Use these headings, in this order: **Requirements**, **High-level design**, **Modules**, **Low-level design**, **Epics** (only when section 5 applies), **Conclusion & References**.

Draw the architecture diagram and the sequence or flow as Mermaid inside the document. Name every component on the diagram the same way it is named in the prose. Include a deployment diagram only when components cross machines, pods, or containers, and label those boundaries.

In High-level design, name the approaches that were not chosen. For each, give the concrete pros and cons that mattered, then state where the chosen approach stands among them and which assumptions that choice depends on. Cover how the design fails, what it retries or degrades, and what reliability it is expected to keep.

In Modules, give every module its own subsection and cover all six items. Relate each module's latency, throughput, and service level to the system requirement it serves. If a figure is not known, write the assumption and what would change it.

In Low-level design, walk one or two critical use cases through the sequence. For each step, say what information enters a component and what leaves it.

Include Epics only when the code for this design is not yet written. If the repository has a task tracker, list the epics in that tracker's format. In this repository that is `tasks/`: one markdown file per epic, checklist items, and a priority token such as `P0` when `tasks/schema.json` defines one. On each epic, mark what an agent can implement from this document and what needs a person (a decision, credentials, machine access, or review). Do not create those task files unless asked.

Conclusion & References lists the material the design actually used: competing systems and the evaluations that led to this choice, and the design patterns the design relies on. Link or name the specific sources. Omit a source you did not use.
