"""Assigned Blender files keep their roles when reopened by the importer."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from ibworkbench.runner import blender_path,convert_custom_file,inspect_custom_file
from ibworkbench.import_plan import default_plan,validate_plan
folder=Path(__file__).resolve().parent.parent/'samples/import-ui-validation'
game='A:/Steam/steamapps/common/Infinity Battlescape'
recipe=json.loads((folder/'blend-recipe.json').read_text('utf8'))
output=folder/'ReopenAssigned.blend'
convert_custom_file(game,blender_path(),recipe,output,prepare=True)
scan=inspect_custom_file(game,output,blender_path())
plan=default_plan(scan)
errors,warnings=validate_plan(plan,scan)
assert not errors,errors
assert sum(a['role']=='socket' for a in plan['objects'])==26
assert next(a['role'] for a in plan['objects'] if a['name']=='unused_bolt')=='ignore'
assert next(a['role'] for a in plan['objects'] if a['name']=='bunda')=='collision'
assert next(a['role'] for a in plan['objects'] if a['name']=='mystery_nozzle')=='ignore'
print('PREPARED REOPEN PASSED: 26 unique sockets, collision mapping and ignored geometry preserved')
