# Local validation

## Repository preparation — 2026-09-22

- The source-only suite discovers 57 tests: 54 pass and 3 real-asset tests skip when `IB_GAME_ROOT` points to a missing installation. No game data is needed for those 54 tests.
- The latest local run with game assets passed all 57 tests. Cockpit camera markers, larger-ship socket presets and Blender/glTF custom imports are included in this source snapshot.
- Live in-game appearance, firing and module selection remain unverified. Historical validation details below refer to local fixtures, which are excluded from the repository.

## Local validation — 2026-09-09

## Mesh and texture write-back update

- 34 unit/real-asset tests passed, including different vertex/face counts, index-width overflow, invalid triangles/material IDs, socket preservation, RGBA/SRGB/SNORM encoding and mipmaps, texture installation/restoration, plus existing rollback and checksum checks.
- Hauler exported with the original render mesh, six LODs, collision and material/texture metadata. An unchanged blend staged **zero** changed files.
- `samples/Hauler-writeback-validation-3`: all eight mesh objects replaced by a larger test box through `REPLACE:` helpers, plus a replacement texture. Staging produced **10 files**: eight INSM meshes, one TXB, and expanded actor XML bounds. Triangulation, source material IDs, socket names, winding/normals, and decoded texture pixel values were checked.
- The staged mod installed into temporary copies and restored byte-exactly. Source game checksums were unchanged. The test box is only a round-trip fixture, not a finished ship design.
- Blender 5.0.1 was used. Worker scripts are isolated from the packaged app's Python libraries to prevent cross-version native-module collisions.
- The rebuilt windowed EXE staged the same Hauler replacement successfully (exit 0), with all 10 payload hashes matching the source-run output. Its staged mod also passed installation/restoration on temporary copies.
- Not verified: running the modified Hauler in the game, exact shader/runtime paint equivalence, all vertex declarations, performance of arbitrary new collision geometry, or animation. New shaders/material systems and automatic LOD/collision generation are not implemented.

## Earlier validation — 2026-09-05 (historical limitations below)

This is a working experimental first version, not completion of exact shader/effect conversion or unrestricted mod import.

- 18 unit/real-asset tests passed: name hashing, 16/32-bit triangle streams (including low-vertex-count 32-bit files), exact no-op binary round trips, bounds/socket patches, path containment, XML entity rejection, checksum conflicts, install/restore and simulated failure rollback.
- GUI instantiated successfully and listed 256 actor/module configurations. Packaged Windows EXE GUI self-test passed (exit 0).
- Actual packaged EXE exported `samples/PackagedAsteroid.blend` successfully, proving the bundled worker/dependencies can launch the installed Blender.
- `samples/FactoryModule-textured.blend`: render + collision + six declared LODs, four unique materials, 16 packed images. Inspected with a rendered preview. No-op import produced zero changed files.
- `samples/Interceptor-validated.blend`: exterior/cockpit meshes, declared LODs, collision, sockets/lights/thruster markers; no-op import produced zero changed files. See its report for missing material/texture references and unsupported particle-array texture.
- Fuel depot assembly loaded in Blender: 24 render instances, 24 collision instances, 78 LOD instances; inspected rendered hierarchy/placement. This early sample predates the improved shader preview.
- A factory vertex edit plus a light-energy edit produced exactly two staged replacements (INSM and XML). They installed into temporary copies, parsed successfully, and restored byte-exactly. The real game installation was not modified.
- Deliberately changed face connectivity was rejected, with no output mod directory created.

Not verified: loading a modified actor in the running game, exact runtime material/paint/effect appearance, every catalog entry, arbitrary topology, texture/shader editing, or dynamic loadout expansion.

The working package is `dist/ActorWorkbench/ActorWorkbench.exe` with `_internal` alongside. One-file packaging was rejected after this host's native Tcl loader could not read its temporary extraction path; the normal folder distribution passed instead. Earlier diagnostic packages are retained under `build/obsolete-packages`, not in the release folder.

No GitHub push or game installation write was performed.
# New actor / Principled profile — 2026-09-10

- Added `new-template` and `new-actor` app/CLI workflows; rebuilt the windowed executable with Tcl/Tk included.
- The packaged executable created `samples/CustomInterceptor_AppTemplate.blend` and staged `../Modfolder/CustomInterceptor.blend` into `../Modfolder/CustomInterceptor_Mod`.
- The dummy package contains 17 files: new render/collision meshes, three new material instances, nine new textures, one new actor XML, and two registry updates. No existing mesh, material, texture or actor XML is replaced.
- The render mesh round-trip has 96 exported vertices, 48 triangles, three material slots and 26 named sockets. Collision has 24 vertices and 12 triangles.
- `tools/validate_new_actor.py` resolved the new asset IDs and texture references, re-imported the actor through Workbench, and installed/restored the package on temporary game-data copies. Original game registry hashes remained unchanged.
- 42 unit tests pass, including additive installation/restore, conflict rejection, failed-install rollback, new material/group serialization, shader channel packing and asset registry collisions. Blender-side `tools/test_principled_validation.py` verifies rejection of transmission, alpha, coat, IOR changes and missing images.
- `tools/render_new_actor_check.py` compares authored and exported albedo using the actual staged TXB bytes; images are under `samples/new-actor-preview`.
- This verifies authoring, conversion and file/registry compatibility. New actor spawning and full game-shader rendering have **not** been tested in the running game. The first profile omits team skins, custom cockpits and generated LODs.
