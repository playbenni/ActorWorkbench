# Development tools

These are optional developer diagnostics and integration fixtures, not part of the app's runtime. Run the portable automated suite with `python -m unittest discover -s tests -v` from the repository root.

Several tools assume the original developer's game path or locally generated files under `samples/`. Review each script's paths and arguments before running it, and use temporary copies for install/restore experiments. Those game assets and generated fixtures are intentionally not distributed. Scripts that import `bpy` run inside Blender; the `.mjs` package inspection tools require Node.js.
