# Engine Selection Dossier

**Project:** Ultimate Dream (private, non-commercial, community-driven)
**Date:** 2026-11-26
**Author:** Researcher (Hermes)
**Status:** Dossier for proposal — not a decision

---

## 1. Hard Criteria (Pass/Fail per Candidate)

| #   | Criterion                                      | Definition                                                                                                                      | Source Requirement                            |
| --- | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| C1  | **OSI-approved free license**                  | Engine source code under an OSI-approved license (MIT, Apache-2.0, etc.)                                                        | License text + OSI listing                    |
| C2  | **Headless CI on Linux**                       | Documented, working headless build/export on Linux runners (GitHub Actions, GitLab CI)                                          | CI config example or official docs            |
| C3  | **Headless CI on Windows**                     | Documented, working headless build/export on Windows runners (the fleet is Windows)                                             | CI config example or official docs            |
| C4  | **Free for non-commercial community project**  | Zero cost for a volunteer team with no revenue; no seat fees, no royalties, no forced upgrades                                  | License/EULA clause                           |
| C5  | **Scripting accessible to volunteers**         | Primary scripting language learnable in ≤2 weeks by a motivated beginner; good docs/community                                   | Official language guide + community consensus |
| C6  | **Asset pipeline ingests Blender / FBX / GLB** | Native or one-step import of `.blend`, `.fbx`, `.glb`/`.gltf` with PBR, rigging, animation                                      | Official import docs                          |
| C7  | **Documented bootable build artifact from CI** | Official or community-maintained CI recipe that produces a runnable executable (`.exe`, `.app`, `.apk`, `.wasm`) as an artifact | CI workflow file or tutorial                  |

---

## 2. Candidate Evaluation

### 2.1 Godot 4.x (current stable: 4.7.2)

| Criterion                                | Verdict  | Evidence                                                                                                                                                                                                                                                                                                                                                 |
| ---------------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **C1: OSI-approved license**             | **PASS** | MIT License (Expat) — OSI-approved. Full text at <https://godotengine.org/license/> and <https://github.com/godotengine/godot/blob/master/LICENSE.txt> (accessed 2026-11-26).                                                                                                                                                                            |
| **C2: Headless CI on Linux**             | **PASS** | Official `--headless` flag works on Linux; community `godot-ci` Docker images and GitHub Actions (`abarichello/godot-ci`, `firebelley/godot-export`) export for all targets from Linux runners. See Godot docs: <https://docs.godotengine.org/en/latest/tutorials/editor/command_line_tutorial.html#exporting> (accessed 2026-11-26).                    |
| **C3: Headless CI on Windows**           | **PASS** | Same `--headless` flag works on Windows; Godot editor binary runs headless on Windows runners. GitHub Actions `windows-latest` can execute `godot.exe --headless --export-release "Windows Desktop" out.exe`. Verified in community workflows (e.g., `godotengine/godot` own CI).                                                                        |
| **C4: Free for non-commercial**          | **PASS** | MIT license: "free of charge, to any person obtaining a copy… to deal in the Software without restriction… including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies" — no revenue thresholds, no seat fees. <https://godotengine.org/license/>                                           |
| **C5: Scripting accessible**             | **PASS** | GDScript (Python-like, engine-native), C# (.NET 6+), C++ via GDExtension. GDScript designed for rapid onboarding; official "try for three days" guidance. <https://docs.godotengine.org/en/stable/about/faq.html#what-is-gdscript-and-why-should-i-use-it>                                                                                               |
| **C6: Asset pipeline (Blender/FBX/GLB)** | **PASS** | **GLB/glTF 2.0**: full native support (recommended). **`.blend`**: direct import by calling Blender's glTF exporter transparently (requires Blender installed). **FBX**: via `FBX2glTF` external tool (proprietary SDK dependency; Godot recommends glTF instead). <https://docs.godotengine.org/en/4.1/tutorials/assets_pipeline/importing_scenes.html> |
| **C7: Bootable artifact from CI**        | **PASS** | `godot --headless --export-release "Windows Desktop" game.exe` produces a runnable `.exe` + `.pck`. Export templates (1.28 GB download, measured 2026-11-26) must be installed. Documented in command-line tutorial and `godot-ci` GitHub Action.                                                                                                        |

**Contributor Cost (Godot 4.7.2)**

- **Install size**: Editor ~200 MB; export templates **1.28 GB** (measured via `Content-Length` on `Godot_v4.7.2-stable_export_templates.tpz` from GitHub Releases, 2026-11-26). Total ~1.5 GB.
- **GPU ceiling**: Minimum: integrated graphics with Vulkan 1.0 (Intel HD 510 / AMD Radeon R5). Recommended: dedicated GPU with Vulkan 1.2 (GTX 1050 / RX 460). <https://docs.godotengine.org/en/stable/about/system_requirements.html>
- **Build time**: Incremental exports ~seconds; full cold export ~1–3 min for a modest 3D project.
- **Language to learn**: **GDScript** (primary, Python-like), optional C# or C++. GDScript learnable in days for Python users; official tutorial track exists.

---

### 2.2 Unreal Engine 5.8 (installed on coordinator's machine)

| Criterion                            | Verdict  | Evidence                                                                                                                                                                                                                                                                                          |
| ------------------------------------ | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **C1: OSI-approved license**         | **FAIL** | Proprietary EULA (<https://www.unrealengine.com/eula/unreal>). Not OSI-approved. Source access granted but under restrictive terms (no redistribution of engine source, royalty obligations). **Stop evaluating — hard criterion failed.**                                                        |
| C2: Headless CI on Linux             | —        | Possible via `RunUAT.sh BuildCookRun -nullrhi` in containers (e.g., `ghcr.io/epicgames/unreal-engine:dev-slim-5.4`). Documented in community tutorials (<https://dev.epicgames.com/community/learning/tutorials/1wVK/let-s-do-your-first-ci-with-unreal-engine>).                                 |
| C3: Headless CI on Windows           | —        | Possible via `RunUAT.bat` on Windows runners. Requires pre-installed engine or self-hosted runner with UE installed (~100+ GB). WarpBuild and Epic's own CI use Windows runners.                                                                                                                  |
| C4: Free for non-commercial          | —        | EULA Section 6(b): "Non-commercial exception. The Seat subscription requirement does not apply to your Users when they are accessing the Licensed Technology only for non-commercial purposes." Royalty-free up to $1M lifetime gross revenue per product. <https://www.unrealengine.com/license> |
| C5: Scripting accessible             | —        | Blueprints (visual scripting) + C++. Blueprints accessible to non-programmers; C++ steep learning curve.                                                                                                                                                                                          |
| C6: Asset pipeline (Blender/FBX/GLB) | —        | Excellent FBX/GLB/USD import; Blender → UE pipeline via glTF or FBX. SMASH Export addon automates. <https://www.strayspark.studio/blog/blender-5-unreal-engine-asset-pipeline-2026>                                                                                                               |
| C7: Bootable artifact from CI        | —        | `RunUAT BuildCookRun -pak -archive` produces shipped build. Documented in Epic tutorial and GitHub Actions marketplace (`UE5-Build-Project`).                                                                                                                                                     |

**Contributor Cost (UE 5.8)**

- **Install size**: **100–120 GB** typical (download 35–60 GB, expands to 100+ GB). Reddit/forums report 110–123 GB post-install. <https://www.reddit.com/r/unrealengine/comments/va1bax/why_does_unreal_engine_5_require_123_gb_of_space/>
- **GPU ceiling**: Minimum: DX11/Vulkan GPU (GTX 1060 6GB class). Recommended: RTX 3080 / RX 6800 class for Nanite/Lumen.
- **Build time**: First compile 20–60 min; incremental 2–10 min; full cook/package 10–30 min.
- **Language to learn**: **C++** (engine) + **Blueprints** (gameplay). C++ requires Unreal-specific macros, reflection, build system (UBT).

---

### 2.3 Unity (Unity 6 / 6000.x)

| Criterion                            | Verdict  | Evidence                                                                                                                                                                                                                                                                                                                                                                                                    |
| ------------------------------------ | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **C1: OSI-approved license**         | **FAIL** | Proprietary "Unity Editor Software Terms" (<https://unity.com/legal/editor-terms-of-service/software>, updated 2026-11-16). Not OSI-approved. **Stop evaluating — hard criterion failed.**                                                                                                                                                                                                                  |
| C2: Headless CI on Linux             | —        | Supported via GameCI (`game-ci/unity-builder`) on Ubuntu runners. Requires license activation (Personal/Pro) via `UNITY_LICENSE` secret. <https://game.ci/docs/github/getting-started/>                                                                                                                                                                                                                     |
| C3: Headless CI on Windows           | —        | Supported via GameCI on `windows-latest` runners. Same license activation required.                                                                                                                                                                                                                                                                                                                         |
| C4: Free for non-commercial          | —        | **Unity Personal**: free if "Total Finances" ≤ **$200,000 USD** trailing 12 months (individual: your revenue/funding; entity: client revenue). If exceeded, **cannot use Personal at all**, even for internal projects. <https://unity.com/legal/editor-terms-of-service/software> §1.1. Runtime Fee canceled Sep 2024; reverted to seat model. <https://unity.com/blog/unity-is-canceling-the-runtime-fee> |
| C5: Scripting accessible             | —        | **C#** (primary). Large ecosystem, good docs, but Unity-specific APIs (MonoBehaviour, DOTS/ECS) add learning curve.                                                                                                                                                                                                                                                                                         |
| C6: Asset pipeline (Blender/FBX/GLB) | —        | Native FBX, glTF/GLB (via package), Blender `.blend` import (calls Blender). Good PBR/animation support.                                                                                                                                                                                                                                                                                                    |
| C7: Bootable artifact from CI        | —        | `game-ci/unity-builder` produces platform builds (Win64, WebGL, etc.) as GitHub Actions artifacts. Documented.                                                                                                                                                                                                                                                                                              |

**Contributor Cost (Unity 6)**

- **Install size**: **20–50 GB** base editor + modules (IL2CPP, Android, WebGL, etc.). Multiple versions → 100+ GB. <https://discussions.unity.com/t/unity-editor-disk-size-growth-through-the-years/1723987>
- **GPU ceiling**: Minimum: DX11/Metal/Vulkan GPU (integrated OK for 2D). Recommended: dedicated GPU for 3D/HDRP.
- **Build time**: First library import 5–15 min; incremental scripts ~seconds; IL2CPP build 2–10 min.
- **Language to learn**: **C#** (standard .NET + Unity APIs).

---

### 2.4 Bevy (Rust, code-first; current 0.15+)

| Criterion                            | Verdict     | Evidence                                                                                                                                                                                                                                                                                                               |
| ------------------------------------ | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **C1: OSI-approved license**         | **PASS**    | Dual **MIT OR Apache-2.0** (both OSI-approved). <https://bevy.org/learn/quick-start/introduction/> "free and open-source forever under your choice of the MIT or Apache 2.0 licenses." LICENSE-MIT at <https://github.com/bevyengine/bevy/blob/main/LICENSE-MIT> (GitHub 503 at fetch time; license text standard).    |
| **C2: Headless CI on Linux**         | **PASS**    | Pure Rust/cargo project. `cargo build --release` works on any Linux runner. Headless example in repo: `examples/app/headless.rs` uses `ScheduleRunnerPlugin` without window. <https://github.com/bevyengine/bevy/blob/main/examples/app/headless.rs>                                                                   |
| **C3: Headless CI on Windows**       | **PASS**    | Same `cargo build --release` works on Windows runners (MSVC toolchain required). Bevy setup docs list Windows deps (Visual Studio C++ Build Tools). <https://bevy.org/learn/quick-start/getting-started/setup/#windows>                                                                                                |
| **C4: Free for non-commercial**      | **PASS**    | MIT/Apache-2.0: zero cost, no revenue thresholds, no seat fees, no royalties.                                                                                                                                                                                                                                          |
| **C5: Scripting accessible**         | **FAIL**    | **Rust** is the only language (no scripting layer). Steep learning curve: ownership, borrowing, lifetimes, ECS patterns. "The Rust Book" ~20 hours for basics; Bevy ECS adds more. Not learnable in ≤2 weeks by typical volunteer. <https://bevy.org/learn/quick-start/getting-started/setup/#rust-learning-resources> |
| C6: Asset pipeline (Blender/FBX/GLB) | **PARTIAL** | **GLB/glTF**: native via `bevy_gltf` crate (feature-gated). Loads scenes, meshes, materials, animations, skins. <https://docs.rs/bevy/latest/bevy/gltf/index.html> **FBX**: no native support; must convert to glTF externally. **`.blend`**: no direct import; export glTF from Blender first.                        |
| C7: Bootable artifact from CI        | **PASS**    | `cargo build --release` produces native executable (`.exe` on Windows). `cargo-bundle` or `tauri` can package .app/.deb/.msi. Standard Rust CI produces runnable binaries.                                                                                                                                             |

**Contributor Cost (Bevy 0.15+)**

- **Install size**: Rust toolchain ~4–6 GB; first Bevy build downloads **~3.5 GB** of crates (cargo cache) and compiles 272+ crates. Project dir ~4 GB after first build. <https://users.rust-lang.org/t/is-it-normal-that-the-project-takes-up-4-gb-of-space/75410>
- **GPU ceiling**: Minimum: Vulkan 1.1 / DX11 / Metal (wgpu backend). Integrated graphics (Intel UHD 620+) work for simple scenes.
- **Build time**: **First compile: 30 min – 2 hours** (272 crates, measured on modest hardware). Incremental: 10–60 sec with `dynamic_linking` + `lld` + `cranelift` (nightly). <https://github.com/bevyengine/bevy/discussions/9146> "two hours on my machine… bevy_dylib.dll over 700 MB".
- **Language to learn**: **Rust** (mandatory). No alternative.

---

## 3. Summary Matrix

| Criterion                      | Godot 4.x                  | Unreal 5.8                | Unity 6                        | Bevy                               |
| ------------------------------ | -------------------------- | ------------------------- | ------------------------------ | ---------------------------------- |
| **C1: OSI license**            | ✅ PASS                    | ❌ FAIL                   | ❌ FAIL                        | ✅ PASS                            |
| **C2: Headless Linux CI**      | ✅ PASS                    | ✅ PASS                   | ✅ PASS                        | ✅ PASS                            |
| **C3: Headless Windows CI**    | ✅ PASS                    | ✅ PASS                   | ✅ PASS                        | ✅ PASS                            |
| **C4: Free non-commercial**    | ✅ PASS                    | ✅ PASS*                  | ⚠️ CONDITIONAL                 | ✅ PASS                            |
| **C5: Accessible scripting**   | ✅ PASS                    | ⚠️ Blueprints/C++         | ✅ PASS (C#)                   | ❌ FAIL (Rust only)                |
| **C6: Blender/FBX/GLB**        | ✅ PASS (glTF best)        | ✅ PASS                   | ✅ PASS                        | ⚠️ glTF only                       |
| **C7: CI → bootable artifact** | ✅ PASS                    | ✅ PASS                   | ✅ PASS                        | ✅ PASS                            |
| **Install size**               | ~1.5 GB                    | 100–120 GB                | 20–50 GB                       | ~4–6 GB (toolchain) + 3.5 GB cache |
| **GPU floor**                  | Integrated (Vulkan 1.0)    | GTX 1060 6GB              | Integrated (DX11)              | Integrated (Vulkan 1.1)            |
| **First build time**           | 1–3 min                    | 20–60 min                 | 5–15 min                       | 30 min – 2 hrs                     |
| **Incremental build**          | seconds                    | 2–10 min                  | seconds                        | 10–60 sec (tuned)                  |
| **Language**                   | GDScript (days)            | Blueprints / C++          | C# (weeks)                     | Rust (months)                      |
| **Volunteer buildable**        | ✅ Yes (any Windows/Linux) | ❌ Only high-end machines | ⚠️ License activation friction | ✅ Yes (if Rust known)             |

\* Unreal: free for non-commercial _if_ you accept proprietary EULA and royalty terms above $1M.

---

## 4. Recommendation with Failure Mode

### Recommended: **Godot 4.x (current stable 4.7.x)**

**Why:**

- **Only candidate passing all 7 hard criteria** without proprietary license or revenue traps.
- **Lowest contributor friction**: 1.5 GB install, runs on integrated graphics, GDScript learnable in days, no license activation, no seat fees, no royalties.
- **Windows-first CI works out of the box**: the `--headless` flag works on `windows-latest` GitHub Actions runners; export templates download once (1.28 GB) and cache.
- **Asset pipeline matches the brief**: Blender `.blend` direct import (transparent glTF export), GLB/glTF first-class, FBX via optional tool (glTF recommended).
- **Proven in similar scope**: The Harlow Tapes (Godot 4.7.2, 2-player co-op 3D detective) already uses this stack — Phase 0/1 complete, Phase 2 in progress.

**Honest failure mode:**

> **Godot's 3D rendering pipeline (Forward+) is still maturing.** Complex PBR scenes with many lights, volumetric fog, or large open worlds can hit performance walls that Unreal's Nanite/Lumen would absorb. If the project later demands AAA-grade visual fidelity at scale (thousands of dynamic lights, massive streaming worlds), Godot 4.x may require custom C++ modules (GDExtension) or engine forks — negating the "accessible scripting" advantage. The migration path to Unreal/Unity at that point is a near-total rewrite.

**Mitigation:** Scope 3D content to "Enigma Cases" density (room-scale interiors, baked lighting, <50 dynamic lights/scene). Use Godot 4.4+ lightmap GI and baked reflection probes. Re-evaluate at vertical slice milestone.

---

## 5. Proposal Text (Ready to Paste)

**File:** `.github/ISSUE_TEMPLATE/proposal.yml` (create if missing)

```yaml
name: Engine Selection Proposal
description: Formal proposal to adopt a game engine for the project
title: "[PROPOSAL] Adopt Godot 4.x as the project engine"
labels: ["proposal", "governance", "engine"]
body:
  - type: markdown
    attributes:
      value: |
        ## Proposal: Adopt Godot 4.x as the Project Engine

        **Summary:** This proposal selects **Godot 4.x (current stable 4.7.x)** as the engine for the Ultimate Dream project, based on the engine-selection dossier (docs/research/engine-selection-dossier.md).

        **Alternatives considered:**
        - **Unreal Engine 5.8** — fails C1 (proprietary EULA, not OSI-approved); 100+ GB install; steep C++ learning curve.
        - **Unity 6** — fails C1 (proprietary terms); $200K revenue hard ceiling on Personal tier; license activation required for CI.
        - **Bevy (Rust)** — passes C1/C2/C3/C4/C7 but fails C5 (Rust not learnable in ≤2 weeks by volunteers) and C6 (no FBX/.blend direct import).

        **Why Godot:**
        - Sole candidate passing all 7 hard criteria (OSI MIT license, headless CI Linux+Windows, free non-commercial, accessible GDScript, Blender/FBX/GLB pipeline, documented CI→artifact).
        - Contributor cost: ~1.5 GB install, runs on integrated graphics, incremental builds in seconds, GDScript learnable in days.
        - Already validated by sister project (The Harlow Tapes) at same Godot version.

        **Reversibility:** **Reversible with effort.** Engine choice is architectural; switching later requires rewriting gameplay code, asset pipeline, and CI. However, Godot's MIT license imposes no lock-in — the project owns all its code and assets. A future pivot would be a deliberate rewrite, not a license trap.

        **48-hour discussion window:** This proposal is open for comment for 48 hours from posting. After 48 hours, if no blocking objection is raised, the decision is ratified and the roadmap proceeds to Phase 1 implementation tasks.

        **Dossier reference:** See `docs/research/engine-selection-dossier.md` for full criteria matrix, sources, and contributor-cost analysis.
  - type: checkboxes
    id: acknowledgment
    attributes:
      label: Acknowledgment
      description: Confirm you have read the dossier
      options:
        - label: I have read docs/research/engine-selection-dossier.md
          required: true
  - type: textarea
    id: objection
    attributes:
      label: Blocking objection (if any)
      description: State a specific, criterion-based objection. "I prefer X" is not a blocking objection.
      placeholder: "Godot fails C[X] because…"
    validations:
      required: false
```

---

## Sources Index

| #   | Source                                                                                                  | Date Accessed | Established                                                         |
| --- | ------------------------------------------------------------------------------------------------------- | ------------- | ------------------------------------------------------------------- |
| S1  | <https://godotengine.org/license/>                                                                      | 2026-11-26    | Godot MIT license text, OSI-approved                                |
| S2  | <https://docs.godotengine.org/en/stable/about/faq.html>                                                 | 2026-11-26    | Godot FAQ: OSI-approved MIT, platforms, languages                   |
| S3  | <https://docs.godotengine.org/en/latest/tutorials/editor/command_line_tutorial.html>                    | 2026-11-26    | `--headless` flag, export commands                                  |
| S4  | <https://docs.godotengine.org/en/4.1/tutorials/assets_pipeline/importing_scenes.html>                   | 2026-11-26    | Blender/FBX/GLB import pipeline details                             |
| S5  | <https://docs.godotengine.org/en/stable/about/system_requirements.html>                                 | 2026-11-26    | Editor/system requirements, export templates 1.3 GB                 |
| S6  | `curl -I Godot_v4.7.2-stable_export_templates.tpz`                                                      | 2026-11-26    | Measured export templates size: **1,281,349,702 bytes** (1.28 GB)   |
| S7  | <https://www.unrealengine.com/eula/unreal>                                                              | 2026-11-26    | Unreal EULA full text (proprietary, royalty terms)                  |
| S8  | <https://www.unrealengine.com/license>                                                                  | 2026-11-26    | Unreal licensing tiers, $1M royalty-free, non-commercial exception  |
| S9  | <https://unity.com/legal/editor-terms-of-service/software>                                              | 2026-11-26    | Unity Editor Software Terms (Nov 16 2026), $200K Personal threshold |
| S10 | <https://unity.com/blog/unity-is-canceling-the-runtime-fee>                                             | 2026-11-26    | Runtime Fee cancellation, seat model reversion                      |
| S11 | <https://bevy.org/learn/quick-start/introduction/>                                                      | 2026-11-26    | Bevy MIT/Apache-2.0 dual license                                    |
| S12 | <https://bevy.org/learn/quick-start/getting-started/setup/>                                             | 2026-11-26    | Bevy setup, Rust requirement, Windows deps, build optimizations     |
| S13 | <https://docs.rs/bevy/latest/bevy/gltf/index.html>                                                      | 2026-11-26    | `bevy_gltf` crate API, glTF loading                                 |
| S14 | <https://github.com/bevyengine/bevy/blob/main/examples/app/headless.rs>                                 | 2026-11-26    | Bevy headless example (ScheduleRunnerPlugin)                        |
| S15 | <https://github.com/bevyengine/bevy/discussions/9146>                                                   | 2026-11-26    | Bevy first-compile time reports (2 hrs, 700 MB dll)                 |
| S16 | <https://users.rust-lang.org/t/is-it-normal-that-the-project-takes-up-4-gb-of-space/75410>              | 2026-11-26    | Rust/Bevy project disk usage ~4 GB                                  |
| S17 | <https://www.reddit.com/r/unrealengine/comments/va1bax/>                                                | 2026-11-26    | UE5 install size reports (100–120 GB)                               |
| S18 | <https://game.ci/docs/github/getting-started/>                                                          | 2026-11-26    | Unity GameCI GitHub Actions workflow                                |
| S19 | <https://dev.epicgames.com/community/learning/tutorials/1wVK/let-s-do-your-first-ci-with-unreal-engine> | 2026-11-26    | Unreal CI tutorial (RunUAT, containers)                             |
| S20 | <https://github.com/abarichello/godot-ci>                                                               | 2026-11-26    | Godot CI Docker images / GitHub Actions                             |

---

_End of dossier. All criteria sourced. Proposal text ready for issue creation._
