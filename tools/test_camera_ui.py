"""Check camera picker assignment, singleton replacement, and recipe persistence."""
import json
import sys
from pathlib import Path
from unittest.mock import patch
from PIL import ImageGrab
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from main import App,DEFAULT_GAME
from ibworkbench.import_ui import ImportDialog
from ibworkbench.runner import blender_path
from ibworkbench.socket_types import COCKPIT_CAMERA
folder=Path(__file__).resolve().parent.parent/'samples/camera-validation'
scan=json.loads((folder/'inspection.json').read_text('utf8'));plan=json.loads((folder/'recipe.json').read_text('utf8'))
app=App();app.update();dialog=ImportDialog(app,DEFAULT_GAME,blender_path());dialog.geometry('1280x850+60+60')
try:
    dialog.pending_recipe=plan;dialog.load_inspection(scan);dialog.tabs.select(dialog.socket_tab);dialog.update()
    def assign(name):
        key=next(k for k,v in dialog.socket_rows.items() if v==name)
        dialog.socket_objects.selection_set(key);dialog.socket_objects.see(key);dialog.update()
        dialog.socket_kind.set('Cameras');dialog.filter_presets();dialog.apply_preset();dialog.update()
    assign('Alternate pilot eye')
    assert dialog.assignment('Pilot eye')['role']=='ignore'
    assert dialog.assignment('Alternate pilot eye')['socket_preset']==COCKPIT_CAMERA
    assign('Pilot eye')
    assert dialog.assignment('Alternate pilot eye')['role']=='ignore'
    assert dialog.validate(select_tab=False)
    with patch('ibworkbench.import_ui.messagebox.showinfo') as info:
        assign('Hull');info.assert_called_once()
    assert dialog.assignment('Hull')['role']=='render'
    with patch('ibworkbench.import_ui.filedialog.asksaveasfilename',return_value=str(folder/'ui-recipe.json')):dialog.save_recipe()
    saved=json.loads((folder/'ui-recipe.json').read_text('utf8'))
    dialog.pending_recipe=saved;dialog.load_inspection(scan);dialog.update()
    assert dialog.validate(select_tab=False)
    key=next(k for k,v in dialog.socket_rows.items() if v=='Pilot eye')
    dialog.socket_objects.selection_set(key);dialog.socket_objects.see(key);dialog.update()
    dialog.attributes('-topmost',True);dialog.deiconify();dialog.lift();dialog.update()
    dialog.after(350,dialog.quit);dialog.mainloop()
    x,y=dialog.winfo_rootx(),dialog.winfo_rooty()
    ImageGrab.grab(bbox=(x,y,x+dialog.winfo_width(),y+dialog.winfo_height())).save(folder/'camera-picker.png')
    print('CAMERA UI PASSED: named Cameras preset, Empty-only assignment, singleton replacement, recipe reload')
finally:
    dialog.close();app.destroy()
