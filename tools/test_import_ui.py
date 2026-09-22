"""Exercise actual Tk widgets and capture the importer tabs for visual review."""
import json
import sys
from pathlib import Path
from unittest.mock import patch
from PIL import ImageGrab
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from main import App,DEFAULT_GAME
from ibworkbench.runner import blender_path
from ibworkbench.import_ui import ImportDialog
from ibworkbench.import_plan import ROLES,MODES

folder=Path(__file__).resolve().parent.parent/'samples/import-ui-validation'
scan=json.loads((folder/('packaged-inspection.json' if (folder/'packaged-inspection.json').exists() else 'blend-inspection.json')).read_text('utf8'))
recipe=json.loads((folder/'blend-recipe.json').read_text('utf8'))
app=App();app.geometry('1120x820+20+20');app.update()
dialog=ImportDialog(app,DEFAULT_GAME,blender_path());dialog.geometry('1280x850+60+60')
try:
    dialog.load_inspection(scan);dialog.update()
    assert len(dialog.objects.get_children())==len(scan['objects'])
    key=next(k for k,v in dialog.object_rows.items() if v=='bunda')
    dialog.objects.selection_set(key);dialog.objects.see(key);dialog.update()
    dialog.role.set(ROLES['collision']);dialog.apply_role()
    assert dialog.assignment('bunda')['role']=='collision'
    dialog.pending_recipe=recipe;dialog.load_inspection(scan);dialog.update()
    assert dialog.validate(select_tab=False)
    dialog.resolution.set('256');dialog.apply_resolution()
    assert {m['resolution'] for m in dialog.plan['materials']}=={256}
    dialog.objects.selection_set(key);dialog.objects.see(key);dialog.tabs.select(0);dialog.update()
    def capture(name):
        dialog.attributes('-topmost',True);dialog.deiconify();dialog.lift();dialog.update()
        # Allow the desktop compositor to paint the window before capture.
        dialog.after(350,dialog.quit);dialog.mainloop()
        x,y=dialog.winfo_rootx(),dialog.winfo_rooty()
        ImageGrab.grab(bbox=(x,y,x+dialog.winfo_width(),y+dialog.winfo_height())).save(folder/name)
    capture('ui-meshes.png')
    rows=[k for k,i in dialog.material_rows.items() if dialog.plan['materials'][i]['object'] in ('Left wing','Right wing')]
    dialog.materials.selection_set(rows);dialog.tabs.select(dialog.material_tab);dialog.update()
    dialog.material.set('Trim - Principled');dialog.mode.set(MODES['principled']);dialog.material_resolution.set('128')
    dialog.apply_material()
    assert all(m['resolution']==128 for m in dialog.plan['materials'] if m['object'] in ('Left wing','Right wing'))
    row=next(k for k,i in dialog.material_rows.items() if dialog.plan['materials'][i]['object']=='Hull')
    dialog.materials.selection_set(row);dialog.update();capture('ui-materials.png')
    with patch('ibworkbench.import_ui.filedialog.asksaveasfilename',return_value=str(folder/'ui-saved-recipe.json')):
        dialog.save_recipe()
    saved=json.loads((folder/'ui-saved-recipe.json').read_text('utf8'))
    assert saved['objects']==recipe['objects']
    assert dialog.validate();dialog.update();capture('ui-review.png')
    dialog.work(lambda:'test complete','converted')
    assert dialog.busy
    for _ in range(30):
        dialog.update()
        if not dialog.events.empty():break
    dialog.poll();assert not dialog.busy
    print('UI PASSED: role assignment, recipe loading/saving, multi-slot material mapping, sizes, validation, worker completion, screenshots')
finally:
    dialog.close();app.destroy()
