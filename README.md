# Actor Workbench

A separate Windows application for exporting Infinity Battlescape actors and modules to Blender and staging supported edits for local modding. 

## Run

Open `dist/ActorWorkbench/ActorWorkbench.exe`. Keep its `_internal` dependency folder alongside the EXE (copy the whole ActorWorkbench folder when moving it). Select the game installation folder (containing `Dev`) and an installed `blender.exe`. Blender 5.0 and 5.2 have been tested; Blender itself is not bundled. Click **Scan actors**, filter/select an actor, then **Export selected → .blend**. Large stations can take several minutes and produce large files. Progress appears in the log.

Files are exported with meter units, Z-up coordinates, the original triangle connectivity, declared material groups, UV layers and mesh normals. Textures that can be decoded are packed into the `.blend`; it can be viewed without the source installation. Read the companion `.report.json` for actor-specific omissions.

Collections separate Render, each declared LOD, Collision, internal Cockpit, and Sockets and effects. Collision/LODs/Cockpit start hidden. Toggle each collection in the Blender Outliner; avoid displaying all LODs at once. Named sockets and statically configured lights follow the module hierarchy. Linked instances share mesh data.

Ship previews now apply the configured Team 0 default skin: material-instance overrides (Interceptor) and runtime hull ColorMap bindings (Bomber). The report records the selected skin. Color parameters including `T_ColourSkin`, `Color_Roughness` and `Bcol_Rough` are recognized, and texture nodes explicitly use UV0. Preview overrides do not rewrite the original INSM material IDs on an unchanged round-trip. Shader-specific paint masks/tints are still approximate; this is not an exact reproduction of team paint.

## Current limits — not a complete engine asset editor

- Compiled game shaders are **not translated exactly**. Materials retain source hashes, texture associations and original parameters, with an approximate Principled preview. Recognized color, color/roughness and normal maps are connected. Shader-specific packed channels, paint masks, runtime material overrides, procedural projection and lighting behavior are not fully reproduced.
- Unsupported/missing textures and materials are reported. Only supported 2D textures are decoded; cube/array textures are not yet expanded.
- Particles are named, positioned markers with original settings, not reconstructed game effects. Thruster lights are static previews. Dynamic loadout/weapon attachments, animation and procedural planet generation are not expanded.
- Runtime XML conditions beyond client/server branching are not evaluated. The browser lists configs containing scene meshes/links, not every possible runtime actor type.
- Source formats are reverse-engineered from this installed game version. Unsupported layouts stop conversion rather than guessing triangles.

## Mission Editor collision package

Use **Mission Editor collision package…** for the selected actor, or check **All actors/modules**. This exports directly from the game without Blender. Only full-resolution explicit `CollisionFile`/`HitMesh` geometry and assembly transforms are included; no render LODs, materials, textures or effects are loaded. Actor HitMesh takes precedence over internal cockpit collision. Shared meshes are deduplicated.

The output is the editor's `IBE1` AES-256-GCM envelope containing an `IBS1` catalog, with the same key and coordinate conventions. Bounding boxes are omitted because the Mission Editor already bundles bounds-only metadata for stock actors/modules; it derives updated/custom boxes from imported positions. Module view works without this package. The editor ships no detailed/collision/LOD geometry: select this file when activating detailed view. Save packages outside the Mission Editor project; this option does not install them there. The embedded key discourages casual extraction, but cannot prevent extraction by someone with the application.

CLI: `python main.py package output/collisions.ibmesh Dev/Config/Ships/Interceptor.xml` (omit config paths to package all). Configs without explicit collision geometry are logged as skipped during multi-actor export; all-catalog mode also logs and skips incomplete configs referencing missing files. Nonuniform/mirrored transforms are baked into mesh variants because IBS1 supports only uniform instance scale. Unsupported binary formats stop the export. Output must be a new filename.

## Edit and stage a mod

### Import your own Blender or glTF file

Click **Import custom meshes…** and open `.blend`, `.glb` or `.gltf`. The new actor does not require original Workbench object names or metadata. The source is inspected by Blender in a separate process.

1. In **Meshes & sockets**, select one or several objects and apply their role: visible mesh (LOD 0), collision/hit mesh, LOD 1–6, exterior cockpit, interior cockpit, cockpit collision, attachment socket, or Ignore. For example, select `bunda` and apply **Collision / hit mesh**. A rotatable wireframe and object details help identify each mesh. Set the scale to convert source coordinates into meters.
2. For an existing attachment socket, select one object and a readable target from the Interceptor socket list, then **Assign socket**. For larger-ship effects, weapons or module slots, use **Socket types** (details below). The object's origin and rotation determine placement; its geometry is not rendered. Unassigned baseline sockets can retain Interceptor positions, or disable that option to require every baseline socket explicitly. Adjust sockets to fit the new model.
3. In **Materials**, choose a source Blender material, conversion mode and texture resolution for each visible mesh slot. Multiple selected slots can be changed together. **Principled + linked textures** bakes the supported shader inputs; **Diffuse color only** explicitly discards shader/texture links and uses the material's viewport color (or default grey). Collision and ignored meshes need no material conversion. **Apply size to all slots** sets every slot's resolution; individual slots can then override it.
4. **Validate assignments** reports missing collision/render meshes, unsupported materials, incomplete LOD sequences, invalid/duplicate sockets and source-file changes. **Save recipe…** retains assignments for later use; **Load recipe…** inspects the source again. Recipes reference the source file and do not embed it. Keep glTF sidecar buffers/textures together with the `.gltf`.
5. **Save assigned .blend…** creates an independent, packed Blender authoring file with the normalized collections. **Convert → new mod folder…** bakes and stages separate game meshes, textures, materials, actor configuration and registry changes. Both outputs include a companion import recipe. Install through **Install staged mod…** only after reviewing the staged package.

The target is currently the verified Interceptor opaque hull shader. Supported Principled inputs include base color, roughness, metallic, normals and emission, including linked images/procedurals. Unsupported shading is reported; there is no universal shader translator. LOD and cockpit meshes must be supplied; the importer does not generate them. Cockpit cameras and flight behavior are inherited from the Interceptor. Attachment presets can supply independent thruster and weapon/module configurations. Animated/skinned geometry is outside this static actor profile. Team skin/paint overrides are disabled.

### Choose larger-ship socket types

In **Import custom meshes… → Socket types**, select one or more source objects, choose **Category** and **Source ship**, then choose a named preset and click **Assign type to selected**. The picker reads the installed game's definitions for Interceptor, Bomber, Corvette, Hauler, Destroyer, Cruiser and Carrier. The tested installation provides 110 stock attachment presets plus the cockpit camera marker:

- **Thrusters:** 20 flame/light variants, including Cruiser small/medium/large engines, Carrier main and pod/retro engines, and each ship's manoeuvring jets. The stock particle group settings—including size, length, light and offsets—are copied into an independent thruster configuration.
- **Weapons:** 46 fitted stock weapon variants, labelled with mount size, localized game name and compatible source ships. Normal and defence variants are distinguished. Select a **Weapon group** (1–10) to choose the control group in the generated default loadout.
- **Modules:** 41 empty slot types, labelled by category and size, such as **Shield module slot · MK6 · Carrier**. These provide compatible hardpoints for modules fitted through the game's loadout editor. They do not automatically install a shield/reactor/other module.
- **Lights:** the stock socket spotlights from Interceptor, Bomber and Corvette, with their original color, intensity, cone and offset settings.
- **Cameras → Cockpit_Camera_Position:** assign one Empty at the pilot's eye position. Workbench converts its world position (including parents and **Scale to meters**) into both the internal camera's `ViewPosition` and the custom cockpit's `ViewPosition` when an interior cockpit is assigned. Camera direction and external/chase cameras stay unchanged. Selecting another Empty for this type replaces the previous marker; multiple camera markers in a recipe are rejected. The choice survives saved recipes and assigned `.blend` files. A camera-only assignment does not create equipment configurations or equipment registry edits.

Assigning a type to an existing socket retains its target name and replaces that attachment's configuration. Assigning an unassigned object creates a unique socket; the same preset can be used on several objects. **Ignore selected** excludes attachments. Original target names are still available with readable descriptions on **Meshes & sockets**. Empty rotation controls attachment direction; stock effect and weapon sizes are retained, independently of Empty scaling.

When presets are used, Workbench creates a separate INSM socket table, thruster XML, hardpoint layout and default loadout for the new actor. It updates the actor's references and extends stock weapon/system actor eligibility only where required for the new actor. Those eligibility changes are staged as checksum-checked edits to `Weapons.xml` / `ShipSystems.xml`, and participate in normal install backup/restore. Stock ships and their existing eligibility entries are preserved. Game configuration changes during conversion stop staging.

Socket types and weapon groups are stored in import recipes and in **Save assigned .blend…** outputs. Reopening or staging that assigned Blender file preserves them. A generated actor can use its new default loadout with `Loadout="Default"` in a mission. Large equipment retains its stock requirements, mass and size; the inherited Interceptor flight/energy settings need tuning. Hangar launch bays require additional carrier gameplay components and are not included in this picker. Runtime mounting, firing, effects and module selection still require an in-game test.

CLI: `python main.py inspect-custom source.blend inspection.json`, then `python main.py convert-custom actor.import.json new-mod-folder`. Add `--prepare-blend` to save the assigned scene instead. The GUI creates import recipes; `inspection.json` is the inspection report, not a conversion recipe.

### Create a new actor from Principled materials

Use **New actor template…** to create an independent, editable dummy ship based on the Interceptor's vertex format, sockets, collision format and gameplay configuration. Give it a unique actor name. The original Interceptor is retained.

Edit meshes in the Blender **Render** collection and the hull in **Collision**. Render materials must have a Principled BSDF directly connected to Material Output. Base Color, Metallic, Roughness, Normal (including Normal Map/Bump), Emission Color and Emission Strength can use linked images or procedural networks. Workbench bakes them with Cycles into a separate automatically generated UV layout. Named socket empties control weapon/thruster attachment locations. Scene properties `IB_actor_name` and `IB_bake_resolution` set the actor name and per-material texture size (128, 256, 512, 1024 or 2048).

Save the file, then choose **New actor .blend → mod folder**. Workbench creates independent INSM meshes, CMTI material instances, TXB textures and actor XML, plus updated copies of `Dev/toc.xml` and `Dev/Config/ActorsList.xml`. Stage first; installation remains a separate action. Existing registry changes or asset-name conflicts are rejected. Restore removes unmodified added files and restores the original registries. A newly registered actor still needs a mission/spawn reference and in-game validation; it is not automatically added to the ship-selection UI.

The first profile uses verified Interceptor hull shader `d819ce37`, with team skin/paint overrides disabled. `T_Skin` stores base color RGB and roughness A; `T_Data` stores AO R, metallic G and emission mask B. The shader's normal texture binding receives signed tangent-space normals with DirectX Y orientation. Detail color/roughness are disabled and tiling is one. Emission follows albedo in this game shader, so luminous albedo texels are adapted to retain glow color. Source Blender files are never modified by staging.

This profile supports opaque metallic/roughness surfaces with default IOR/specular response. Transparency, transmission, coat, sheen, anisotropy, subsurface, thin film and displacement are rejected. AO defaults to one; AO multiplied into source base color is baked into that color. It inherits Interceptor flight/loadout behavior and sockets. The custom importer can assign supplied cockpit and LOD meshes; it does not generate them. New meshes automatically use 32-bit indices when needed. Shader fingerprint checks stop conversion if the game's shader changes. New actor spawning/rendering has not yet been validated in-game.

CLI: `python main.py new-template CustomInterceptor.blend --name CustomInterceptor`, then `python main.py new-actor CustomInterceptor.blend CustomInterceptor-mod`. Use global `--game`, `--blender`, and `--log` options before the subcommand.

### Edit an existing actor export

1. Keep the original export as a backup. Open a copy in Blender.
2. Replace/edit geometry in **Edit Mode** (new topology and UV seams supported), or use the `REPLACE:` helper workflow below. Retain the original game material slots and object hierarchy. Use assembly Empty transforms for placements; retain Quaternion rotation mode. Socket Empty position/rotation, XML light position/color/energy/cones, and material `IB_param_*` scalar/vector properties remain supported.
3. Save the edited `.blend`. Choose **Edited .blend → mod folder** and name a **new** output directory. This does not touch the game installation.
4. Inspect `mod.json` and its file list. An unchanged project must produce zero changed files. Unsupported edits are rejected. Editing shared module XML requires consistent edits across its instances. Moving an individual assembly Link changes only that occurrence.
5. Close the game. **Install staged mod…** explicitly confirms replacements. Matching source hashes and all replacement hashes are checked before writing. Originals are backed up under `%LOCALAPPDATA%/IBActorWorkbench/Backups`. Use **Restore backup…** to revert; conflicting newer edits are not overwritten.

Static mesh replacement rebuilds vertices, triangle/material groups, bounds, normals/tangents, hard-edge and UV-seam splits. Modifiers are evaluated. Existing vertex layouts/material IDs and socket data are retained; unsupported channels stop staging. Replacements exceeding 65,536 vertices use 32-bit indices; smaller replacements retain the original index width. Faces may be reassigned among the existing material slots. The old lossless path still handles unchanged exports without rewriting assets. Animation, shape keys, arbitrary new shader graphs/materials, and arbitrary added/deleted scene objects remain unsupported. Do not modify internal `IB_*` metadata or original XML text blocks.

### Replace the whole Hauler (or another actor)

1. Export Hauler, then open a copy of the `.blend`. Keep the exported objects as targets.
2. Import/model your ship as a new mesh object. Name it `REPLACE:` followed by the **exact name** of the exported render object, e.g. `REPLACE:Render: SM_SFC_Hauler_2_Lod0`. Position and scale it in the same world-space location as the target (meters). Its transform is baked into target-local geometry during import; the original hierarchy and sockets survive. Alternatively delete all vertices of the original mesh in Edit Mode and build replacement geometry there.
3. Reuse the original game materials and provide a UV map. A helper with no material slots uses the target's original slot 0. Additional game UV channels fall back to UV0/your active UV map if absent. Missing vertex colors default to white. Shader-specific multi-UV/paint details may therefore need explicit UV1/UV2 authoring.
4. Repeat for the exported **LOD** objects and **Collision** object, using their exact target names. Prefer simplified shapes for collision and distant LODs; they are not automatically generated. Unchanged LOD/collision objects are reported in `mod.json`, because they would retain the old shape. Edit sockets/effect positions if the new ship shape requires it. Existing actor `WorldBoxSize` is expanded to enclose replacement geometry when needed; gameplay tuning is not changed.
5. Paint and **pack** original texture images before saving, or select your replacement image in the existing game texture node. Preserve its color space, node name and shader links. This overwrites the original referenced TXB asset, not a new arbitrary material. Supported ordinary 2D images may be resized up to 8192×8192. Edited textures are encoded as uncompressed RGBA8 (UNORM/SRGB/SNORM as appropriate), with regenerated mipmaps when the original uses them; disk/VRAM cost can increase. Unsupported HDR/cubemap/array formats stop staging. Two conflicting edits of a shared texture are rejected.
6. Save the blend, stage a new mod folder, inspect its warnings/files, close the game, and install through the guarded installer. **Mesh/texture import help…** in the app summarizes this workflow.

The existing executable must be replaced with the updated build to use these features. Previously exported blends remain supported; no exporter re-export is required unless game source checksums have changed. Existing missing/unresolved texture bindings cannot be replaced through a node that was never exported.

The replacement workflow changes existing assets; use **Import custom meshes…** or the new actor template to create a separately registered actor. A shared mesh/material/config can affect many actors. Keep a separate game copy for experiments. Checksums/round-trip tests verify binary integrity, **not game compatibility**; the generated mods have not been tested in a running game. Game updates can invalidate existing exports. Do not distribute game-owned source assets without permission.

Installation is file-by-file atomic, with prewritten backups and rollback on ordinary errors. An operating-system crash/power loss can still interrupt a multi-file transaction: retain the backup folder for recovery. Administrative rights may be needed for protected game folders; the application does not self-elevate.

## Develop and test

This experimental Windows app requires Python 3.12 with Tcl/Tk, a separately installed Blender, and your own Infinity Battlescape installation for game asset operations. The repository contains source and development tools; game assets, sample models and built executables are not included.

```powershell
git clone https://github.com/playbenni/ActorWorkbench.git
cd ActorWorkbench
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Select your game and Blender locations in the app. Run `./build.ps1` to test and package `dist/ActorWorkbench/ActorWorkbench.exe`. Keep its `_internal` folder alongside the executable. Only app code/dependencies are bundled, not extracted assets.

CLI examples (run from this directory):

```powershell
.venv/Scripts/python.exe main.py list
.venv/Scripts/python.exe main.py export Dev/Config/Ships/Interceptor.xml output/Interceptor.blend
.venv/Scripts/python.exe main.py stage output/Interceptor-edited.blend output/Interceptor-mod
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

Use `--game` / `--blender` before the subcommand to override paths. Tests use temporary copies for install/restore. Optional real-asset tests use `IB_GAME_ROOT` or the local default installation and are read-only. `tools/verify_blend.py` runs within Blender to inspect an export and optionally create a test edit/render.

For CLI use of the windowed EXE, add `--log new-log-file.txt` before the subcommand to capture progress/errors. `tools/test_full_replacement.py` runs in headless Blender and tests full Hauler replacement, texture staging and install/restore on temporary copies only.
