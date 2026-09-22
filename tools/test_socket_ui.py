"""Exercise and capture the socket type picker using real inspection data."""
import json
import sys
from pathlib import Path
from unittest.mock import patch
from PIL import ImageGrab
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from main import App,DEFAULT_GAME
from ibworkbench.runner import blender_path
from ibworkbench.import_ui import ImportDialog
from ibworkbench.socket_types import socket_catalog

folder=Path(__file__).resolve().parent.parent/'samples/socket-validation'
scan=json.loads((folder/'blend-inspection.json').read_text('utf8'))
scan['socket_catalog']=socket_catalog(Path(DEFAULT_GAME))
recipe=json.loads((folder/'blend-recipe.json').read_text('utf8'))
app=App();app.geometry('1120x820+20+20');app.update()
dialog=ImportDialog(app,DEFAULT_GAME,blender_path());dialog.geometry('1280x850+60+60')
try:
    dialog.pending_recipe=recipe;dialog.load_inspection(scan);dialog.tabs.select(dialog.socket_tab);dialog.update()
    assert len(dialog.presets)==111
    assert len({p['label'] for p in dialog.presets.values()})==len(dialog.presets)
    assert dialog.validate(select_tab=False)
    def select(names):
        keys=[k for k,v in dialog.socket_rows.items() if v in names]
        dialog.socket_objects.selection_set(keys);dialog.socket_objects.see(keys[0]);dialog.update()
    def preset(ident,ship,category):
        dialog.socket_kind.set(category);dialog.socket_ship.set(ship);dialog.filter_presets()
        dialog.socket_type.set(dialog.presets[ident]['label']);dialog.preset_selected()
    select(['s_main_bottom_left','s_main_bottom_right'])
    preset('thruster:Carrier:2','Carrier','Thrusters');dialog.apply_preset()
    for name in ('s_main_bottom_left','s_main_bottom_right'):
        assert dialog.assignment(name)['socket']==name
        assert dialog.assignment(name)['socket_preset']=='thruster:Carrier:2'
    def capture(name):
        dialog.attributes('-topmost',True);dialog.deiconify();dialog.lift();dialog.update()
        dialog.after(350,dialog.quit);dialog.mainloop()
        x,y=dialog.winfo_rootx(),dialog.winfo_rooty()
        ImageGrab.grab(bbox=(x,y,x+dialog.winfo_width(),y+dialog.winfo_height())).save(folder/name)
    select(['mystery_nozzle']);preset('thruster:Cruiser:0','Cruiser','Thrusters');capture('socket-thrusters.png')
    select(['unused_bolt']);preset('weapon:TurretGunMK7:MK7','Cruiser','Weapons')
    dialog.weapon_group.set('5');dialog.apply_preset()
    assert dialog.assignment('unused_bolt')['socket_group']==4
    select(['unused_bolt']);preset('weapon:TurretGunMK7:MK7','Cruiser','Weapons');capture('socket-weapons.png')
    select(['far_away_shape']);preset('module:Shields:MK6','Carrier','Modules');capture('socket-modules.png')
    with patch('ibworkbench.import_ui.filedialog.asksaveasfilename',return_value=str(folder/'ui-recipe.json')):dialog.save_recipe()
    saved=json.loads((folder/'ui-recipe.json').read_text('utf8'))
    assert next(a for a in saved['objects'] if a['name']=='unused_bolt')['socket_group']==4
    dialog.pending_recipe=saved;dialog.load_inspection(scan);dialog.update()
    assert dialog.validate(select_tab=False)
    row=dialog.assignment('unused_bolt');old=row['socket_preset'];row['socket_preset']='missing'
    assert not dialog.validate(select_tab=False);row['socket_preset']=old
    dialog.validate();dialog.update();capture('socket-review.png')
    print('SOCKET UI PASSED: 111 unique readable presets; ship/category filters; multi-object assignment; weapon groups; recipe replay; validation')
finally:
    dialog.close();app.destroy()
