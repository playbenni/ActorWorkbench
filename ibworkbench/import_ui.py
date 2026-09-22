"""Interactive object-role and material assignment for Blender/glTF imports."""
import copy
import json
import math
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from .import_plan import ROLES, VISUAL_ROLES, MODES, RESOLUTIONS, default_plan, validate_plan, recipe_structure_errors
from .runner import inspect_custom_file, convert_custom_file
from .socket_types import socket_label, new_socket_name, COCKPIT_CAMERA


class ImportDialog(tk.Toplevel):
    def __init__(self,parent,game,blender):
        super().__init__(parent)
        self.title('Import custom meshes — Actor Workbench')
        self.geometry('1280x850');self.minsize(1050,720)
        self.transient(parent)
        self.game,self.blender=game,blender
        self.inspection=None;self.plan=None;self.busy=False;self.pending_recipe=None
        self.events=queue.Queue();self.object_rows={};self.material_rows={}
        self.source=tk.StringVar();self.name=tk.StringVar(value='CustomActor')
        self.scale=tk.StringVar(value='1');self.resolution=tk.StringVar(value='512')
        self.defaults=tk.BooleanVar(value=True);self.status=tk.StringVar(value='Open a Blender or glTF file to inspect its objects and materials.')
        self.role=tk.StringVar(value=ROLES['render']);self.socket=tk.StringVar()
        self.socket_kind=tk.StringVar(value='Thrusters');self.socket_ship=tk.StringVar(value='All ships')
        self.socket_type=tk.StringVar();self.weapon_group=tk.StringVar(value='1');self.socket_rows={};self.presets={}
        self.material=tk.StringVar();self.mode=tk.StringVar(value=MODES['principled']);self.material_resolution=tk.StringVar(value='512')
        self.yaw=.6;self.pitch=.4;self.drag=None;self.preview=None
        outer=ttk.Frame(self,padding=16);outer.pack(fill='both',expand=True)
        ttk.Label(outer,text='IMPORT CUSTOM ASSETS',font=('Segoe UI',17,'bold')).pack(anchor='w')
        ttk.Label(outer,text='Assign source objects to game roles, then choose the material conversion for each visible slot.').pack(anchor='w',pady=(3,12))
        filebar=ttk.Frame(outer);filebar.pack(fill='x')
        ttk.Entry(filebar,textvariable=self.source,state='readonly').pack(side='left',fill='x',expand=True)
        ttk.Button(filebar,text='Open .blend / glTF…',command=self.browse).pack(side='left',padx=6)
        ttk.Button(filebar,text='Load recipe…',command=self.load_recipe).pack(side='left')
        options=ttk.Frame(outer);options.pack(fill='x',pady=12)
        for label,var,width in [('New actor name',self.name,25),('Scale to meters',self.scale,10)]:
            ttk.Label(options,text=label).pack(side='left',padx=(0,5))
            ttk.Entry(options,textvariable=var,width=width).pack(side='left',padx=(0,18))
        ttk.Label(options,text='Texture size').pack(side='left',padx=(0,5))
        ttk.Combobox(options,textvariable=self.resolution,values=RESOLUTIONS,state='readonly',width=7).pack(side='left')
        ttk.Button(options,text='Apply size to all slots',command=self.apply_resolution).pack(side='left',padx=6)
        self.tabs=ttk.Notebook(outer);self.tabs.pack(fill='both',expand=True)
        meshes=ttk.Frame(self.tabs,padding=10);materials=ttk.Frame(self.tabs,padding=10);review=ttk.Frame(self.tabs,padding=10)
        sockets=ttk.Frame(self.tabs,padding=10);self.socket_tab=sockets;self.material_tab=materials;self.review_tab=review
        self.tabs.add(meshes,text='1 · Meshes & sockets');self.tabs.add(sockets,text='2 · Socket types')
        self.tabs.add(materials,text='3 · Materials');self.tabs.add(review,text='4 · Review & convert')
        self.tabs.bind('<<NotebookTabChanged>>',self.tab_changed)
        split=ttk.Panedwindow(meshes,orient='horizontal');split.pack(fill='both',expand=True)
        left=ttk.Frame(split);right=ttk.Frame(split);split.add(left,weight=3);split.add(right,weight=2)
        self.objects=self.table(left,('type','role','faces'),[('Source object',230),('Type',65),('Assigned role',175),('Faces',65)])
        self.objects.bind('<<TreeviewSelect>>',self.object_selected)
        ttk.Label(left,text='Select one or several rows, then apply a role. Object names do not need to match game names.').pack(anchor='w',pady=(8,4))
        assignment=ttk.Frame(left);assignment.pack(fill='x')
        ttk.Combobox(assignment,textvariable=self.role,values=list(ROLES.values()),state='readonly',width=29).pack(side='left')
        ttk.Button(assignment,text='Apply role',command=self.apply_role).pack(side='left',padx=6)
        socketbar=ttk.Frame(left);socketbar.pack(fill='x',pady=8)
        ttk.Label(socketbar,text='Socket target').pack(side='left',padx=(0,5))
        self.socket_combo=ttk.Combobox(socketbar,textvariable=self.socket,state='readonly',width=30);self.socket_combo.pack(side='left',fill='x',expand=True)
        ttk.Button(socketbar,text='Assign socket',command=self.apply_socket).pack(side='left',padx=6)
        ttk.Button(left,text='Choose thruster / weapon / module types…',command=lambda:self.tabs.select(self.socket_tab)).pack(anchor='w',pady=(0,5))
        ttk.Checkbutton(left,text='Use Interceptor positions for unassigned sockets',variable=self.defaults).pack(anchor='w')
        ttk.Label(left,text='A socket uses the selected object’s origin. Default socket positions are already in meters.',wraplength=550).pack(anchor='w',pady=4)
        self.canvas=tk.Canvas(right,background='#182332',highlightthickness=0,height=250)
        self.canvas.pack(fill='both',expand=True,padx=(10,0))
        self.canvas.bind('<Configure>',lambda _:self.draw_preview())
        self.canvas.bind('<Button-1>',lambda e:setattr(self,'drag',(e.x,e.y)))
        self.canvas.bind('<B1-Motion>',self.rotate_preview)
        ttk.Label(right,text='Wireframe preview · drag to rotate',anchor='center').pack(fill='x')
        self.details=tk.Text(right,height=8,wrap='word',state='disabled',font=('Segoe UI',9))
        self.details.pack(fill='x',padx=(10,0),pady=8)
        ttk.Label(sockets,text='SOCKET TYPES',font=('Segoe UI',12,'bold')).pack(anchor='w')
        ttk.Label(sockets,text='Select source objects, then assign a thruster, weapon, module slot, light or cockpit camera position.').pack(anchor='w',pady=(4,10))
        self.socket_objects=self.table(sockets,('type','assignment','target'),[('Source object',220),('Type',65),('Socket type / current role',600),('Socket name',230)])
        self.socket_objects.bind('<<TreeviewSelect>>',self.socket_selected)
        filters=ttk.Frame(sockets);filters.pack(fill='x',pady=(10,5))
        ttk.Label(filters,text='Category').pack(side='left',padx=(0,5))
        kinds=ttk.Combobox(filters,textvariable=self.socket_kind,values=['Thrusters','Weapons','Modules','Lights','Cameras'],state='readonly',width=15)
        kinds.pack(side='left',padx=(0,15));kinds.bind('<<ComboboxSelected>>',self.filter_presets)
        ttk.Label(filters,text='Source ship').pack(side='left',padx=(0,5))
        self.ship_combo=ttk.Combobox(filters,textvariable=self.socket_ship,state='readonly',width=18)
        self.ship_combo.pack(side='left');self.ship_combo.bind('<<ComboboxSelected>>',self.filter_presets)
        ttk.Label(filters,text='Weapon group').pack(side='left',padx=(20,5))
        self.weapon_group_combo=ttk.Combobox(filters,textvariable=self.weapon_group,values=list(range(1,11)),state='disabled',width=5)
        self.weapon_group_combo.pack(side='left')
        choose=ttk.Frame(sockets);choose.pack(fill='x',pady=5)
        self.preset_combo=ttk.Combobox(choose,textvariable=self.socket_type,state='readonly',width=78)
        self.preset_combo.pack(side='left',fill='x',expand=True);self.preset_combo.bind('<<ComboboxSelected>>',self.preset_selected)
        ttk.Button(choose,text='Assign type to selected',command=self.apply_preset).pack(side='left',padx=8)
        ttk.Button(choose,text='Ignore selected',command=self.ignore_sockets).pack(side='left')
        self.preset_details=tk.Text(sockets,height=4,wrap='word',state='disabled',font=('Segoe UI',10));self.preset_details.pack(fill='x',pady=6)
        ttk.Label(sockets,text='Changing a socket type keeps its existing target name. Each attachment uses the selected object’s origin and rotation. Stock effect / weapon sizes are retained.',wraplength=1150).pack(anchor='w')
        ttk.Label(sockets,text='Weapons are fitted in a custom default loadout. Module slots are empty and can be equipped in-game. Hangar launch bays require additional carrier behavior and are not included.',wraplength=1150).pack(anchor='w',pady=4)
        ttk.Label(materials,text='Target shader: Interceptor opaque hull · color, roughness, metallic, tangent normals and emission',font=('Segoe UI',10,'bold')).pack(anchor='w')
        ttk.Label(materials,text='Choose any material from the source file. Collision and ignored objects do not need material conversion.').pack(anchor='w',pady=(4,10))
        self.materials=self.table(materials,('source','conversion','size','status'),[('Mesh / slot',225),('Blender material',220),('Conversion',210),('Size',65),('Status',260)])
        self.materials.bind('<<TreeviewSelect>>',self.material_selected)
        materialbar=ttk.Frame(materials);materialbar.pack(fill='x',pady=10)
        self.material_combo=ttk.Combobox(materialbar,textvariable=self.material,state='readonly',width=32);self.material_combo.pack(side='left',padx=(0,8))
        ttk.Combobox(materialbar,textvariable=self.mode,values=list(MODES.values()),state='readonly',width=27).pack(side='left',padx=(0,8))
        ttk.Combobox(materialbar,textvariable=self.material_resolution,values=RESOLUTIONS,state='readonly',width=7).pack(side='left',padx=(0,8))
        ttk.Button(materialbar,text='Apply to selected slots',command=self.apply_material).pack(side='left')
        self.material_details=tk.Text(materials,height=5,wrap='word',state='disabled',font=('Segoe UI',9));self.material_details.pack(fill='x')
        ttk.Label(materials,text='Principled baking preserves supported inputs and linked textures/procedurals. Transparency, transmission, coat and other unsupported inputs are reported before conversion.',wraplength=1100).pack(anchor='w',pady=6)
        self.review=tk.Text(review,wrap='word',font=('Segoe UI',10),state='disabled');self.review.pack(fill='both',expand=True)
        self.log=tk.Text(review,height=6,wrap='word',state='disabled',font=('Consolas',9));self.log.pack(fill='x',pady=(8,0))
        controls=ttk.Frame(outer);controls.pack(fill='x',pady=(12,6))
        ttk.Button(controls,text='Validate assignments',command=self.validate).pack(side='left',padx=(0,8))
        ttk.Button(controls,text='Save recipe…',command=self.save_recipe).pack(side='left',padx=(0,8))
        ttk.Button(controls,text='Save assigned .blend…',command=lambda:self.convert(True)).pack(side='left',padx=(0,8))
        ttk.Button(controls,text='Convert → new mod folder…',command=lambda:self.convert(False)).pack(side='right')
        self.progress=ttk.Progressbar(outer,mode='indeterminate');self.progress.pack(fill='x')
        ttk.Label(outer,textvariable=self.status,wraplength=1200).pack(anchor='w',pady=(5,0))
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.poll_id=self.after(100,self.poll);self.grab_set()

    def table(self,parent,columns,headings):
        frame=ttk.Frame(parent);frame.pack(fill='both',expand=True)
        tree=ttk.Treeview(frame,columns=columns,selectmode='extended',height=10)
        for key,(label,width) in zip(('#0',*columns),headings):
            tree.heading(key,text=label);tree.column(key,width=width,minwidth=45,stretch=True)
        scroll=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);tree.configure(yscrollcommand=scroll.set)
        horizontal=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview);tree.configure(xscrollcommand=horizontal.set)
        tree.grid(row=0,column=0,sticky='nsew');scroll.grid(row=0,column=1,sticky='ns');horizontal.grid(row=1,column=0,sticky='ew')
        frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        return tree

    @staticmethod
    def write(widget,text):
        widget.configure(state='normal');widget.delete('1.0','end');widget.insert('end',text);widget.configure(state='disabled')

    def work(self,func,kind):
        if self.busy:return
        self.busy=True;self.progress.start(12);self.status.set('Working… Source and game files are not modified.')
        self.set_editing(False)
        def task():
            try:self.events.put((kind,func()))
            except Exception as e:self.events.put(('error',str(e)))
        threading.Thread(target=task,daemon=True).start()

    def set_editing(self,enabled):
        def walk(parent):
            for widget in parent.winfo_children():
                if isinstance(widget,(ttk.Button,ttk.Entry,ttk.Combobox,ttk.Checkbutton,ttk.Treeview)):
                    widget.state(['!disabled' if enabled else 'disabled'])
                walk(widget)
        walk(self)
        if enabled and self.socket_kind.get()!='Weapons':self.weapon_group_combo.state(['disabled'])

    def poll(self):
        while not self.events.empty():
            kind,value=self.events.get()
            if kind=='log':
                self.log.configure(state='normal');self.log.insert('end',value+'\n');self.log.see('end');self.log.configure(state='disabled')
                continue
            self.busy=False;self.progress.stop();self.set_editing(True)
            if kind=='inspection':self.load_inspection(value)
            elif kind=='error':self.status.set(value);messagebox.showerror('Import stopped',value,parent=self)
            else:self.status.set('Completed: '+str(value));self.validate(select_tab=False)
        self.poll_id=self.after(100,self.poll)

    def logger(self,line):self.events.put(('log',line))

    def browse(self):
        if self.busy:return
        source=filedialog.askopenfilename(parent=self,title='Custom Blender or glTF file',filetypes=[('Blender / glTF','*.blend *.glb *.gltf'),('Blender','*.blend'),('glTF','*.glb *.gltf')])
        if source:
            self.pending_recipe=None;self.source.set(source)
            self.work(lambda:inspect_custom_file(self.game,source,self.blender,self.logger),'inspection')

    def load_inspection(self,inspection):
        self.inspection=inspection;self.plan=default_plan(inspection)
        recipe=self.pending_recipe;self.pending_recipe=None
        if recipe:
            if recipe_structure_errors(recipe):
                messagebox.showwarning('Invalid recipe','The recipe is incomplete or malformed. Fresh assignments are shown.',parent=self)
            elif recipe.get('source_sha256')!=inspection['source_sha256']:
                messagebox.showwarning('Source changed','The saved recipe belongs to an older file. Fresh assignments are shown; inspect and reassign before converting.',parent=self)
            elif set(a.get('name') for a in recipe.get('objects',[]))!=set(o['name'] for o in inspection['objects']):
                messagebox.showwarning('Objects changed','The object list differs. Fresh assignments are shown.',parent=self)
            elif any(a.get('role') not in ROLES for a in recipe.get('objects',[])) or any(a.get('mode') not in MODES for a in recipe.get('materials',[])):
                messagebox.showwarning('Invalid recipe','The recipe contains unsupported assignments. Fresh assignments are shown.',parent=self)
            elif len(recipe['objects'])!=len(self.plan['objects']) or len(recipe['materials'])!=len(self.plan['materials']) or {(a['object'],a['slot']) for a in recipe['materials']}!={(a['object'],a['slot']) for a in self.plan['materials']}:
                messagebox.showwarning('Slots changed','The object or material slot assignments differ. Fresh assignments are shown.',parent=self)
            else:self.plan=recipe
        self.source.set(inspection['source']);self.name.set(self.plan['name']);self.scale.set(str(self.plan['scale']))
        self.resolution.set(str(self.plan['resolution']));self.defaults.set(self.plan['default_sockets'])
        self.target_labels={socket_label(key):key for key in inspection['sockets']}
        self.socket_combo.configure(values=list(self.target_labels))
        self.presets={p['id']:p for p in inspection.get('socket_catalog',{}).get('presets',[])}
        self.ship_combo.configure(values=['All ships',*sorted({s for p in self.presets.values() for s in p['ships']})])
        self.filter_presets();self.refresh_sockets()
        self.material_combo.configure(values=['(Keep current material)','(Default grey)',*[m['name'] for m in inspection['materials']]])
        self.objects.delete(*self.objects.get_children());self.object_rows={}
        for index,obj in enumerate(inspection['objects']):
            key=str(index);self.object_rows[key]=obj['name']
            assignment=next(a for a in self.plan['objects'] if a['name']==obj['name'])
            self.objects.insert('', 'end',iid=key,text=obj['name'],values=(obj['type'],ROLES.get(assignment['role'],assignment['role']),obj.get('faces','—')))
        self.refresh_materials();self.status.set(f'Inspected {len(inspection["objects"])} objects and {len(inspection["materials"])} materials. Review the assignments before converting.')
        if self.object_rows:self.objects.selection_set(next(iter(self.object_rows)))

    def current_plan(self):
        if self.plan is None:raise ValueError('Open a source file first.')
        plan=copy.deepcopy(self.plan)
        plan.update(name=self.name.get().strip(),scale=float(self.scale.get()),resolution=int(self.resolution.get()),default_sockets=self.defaults.get())
        return plan

    def assignment(self,name):return next(a for a in self.plan['objects'] if a['name']==name)

    def apply_resolution(self):
        if self.busy or not self.plan:return
        for item in self.plan['materials']:item['resolution']=int(self.resolution.get())
        self.refresh_materials()

    def object_selected(self,_=None):
        selected=self.objects.selection()
        if not selected or not self.inspection:return
        name=self.object_rows[selected[0]];obj=next(o for o in self.inspection['objects'] if o['name']==name)
        assignment=self.assignment(name);self.role.set(ROLES[assignment['role']])
        target=assignment.get('socket','');self.socket.set(socket_label(target) if target in self.inspection['sockets'] else '')
        self.preview=obj.get('preview');self.draw_preview()
        slots='\n'.join(f'  {s["index"]+1}: {s["material"] or "Unassigned"}' for s in obj['slots'])
        details=f'{name}\n{obj["type"]} · {obj.get("vertices",0):,} vertices · {obj.get("faces",0):,} faces\nDimensions in source coordinates: '+', '.join(f'{x:.3g}' for x in obj['dimensions'])
        details+='\nMaterials:\n'+(slots or '  None')+'\n'+(obj.get('geometry_issue') or '')
        self.write(self.details,details)

    def apply_role(self):
        if self.busy or not self.plan:return
        role=next(k for k,v in ROLES.items() if v==self.role.get())
        for key in self.objects.selection():
            name=self.object_rows[key];self.assignment(name)['role']=role
            values=list(self.objects.item(key,'values'));values[1]=ROLES[role];self.objects.item(key,values=values)
        self.refresh_materials()
        self.refresh_sockets()

    def apply_socket(self):
        if self.busy or not self.plan:return
        selected=self.objects.selection()
        if len(selected)!=1:
            messagebox.showinfo('Select one object','Choose one object for each socket target.',parent=self);return
        if not self.socket.get():return
        self.assignment(self.object_rows[selected[0]]).update(socket=self.target_labels.get(self.socket.get(),self.socket.get()),socket_preset='',socket_group=0)
        self.role.set(ROLES['socket']);self.apply_role()

    def refresh_sockets(self):
        self.socket_objects.delete(*self.socket_objects.get_children());self.socket_rows={}
        if not self.plan:return
        objects={o['name']:o for o in self.inspection['objects']}
        for index,a in enumerate(self.plan['objects']):
            key=str(index);self.socket_rows[key]=a['name']
            label=self.presets.get(a.get('socket_preset'),{}).get('label')
            if a['role']!='socket':label=ROLES.get(a['role'],a['role'])
            elif not label:label='Inherited · '+socket_label(a['socket']) if a['socket'] else 'Choose a socket target or type'
            self.socket_objects.insert('','end',iid=key,text=a['name'],values=(objects[a['name']]['type'],label,a.get('socket') if a['role']=='socket' else ''))

    def filter_presets(self,_=None):
        kind={'Thrusters':'thruster','Weapons':'weapon','Modules':'module','Lights':'light','Cameras':'camera'}[self.socket_kind.get()]
        self.weapon_group_combo.configure(state='readonly' if kind=='weapon' else 'disabled')
        selected=[p for p in self.presets.values() if p['kind']==kind and (self.socket_ship.get()=='All ships' or self.socket_ship.get() in p['ships'])]
        self.preset_labels={p['label']:p['id'] for p in selected}
        self.preset_combo.configure(values=list(self.preset_labels))
        if self.socket_type.get() not in self.preset_labels:self.socket_type.set(next(iter(self.preset_labels),''))
        self.preset_selected()

    def preset_selected(self,_=None):
        preset=self.presets.get(self.preset_labels.get(self.socket_type.get()),{})
        self.write(self.preset_details,preset.get('description','No matching socket types are available.'))

    def socket_selected(self,_=None):
        selected=self.socket_objects.selection()
        if not selected or not self.plan:return
        a=self.assignment(self.socket_rows[selected[0]]);p=self.presets.get(a.get('socket_preset'))
        if p:
            self.socket_kind.set({'thruster':'Thrusters','weapon':'Weapons','module':'Modules','light':'Lights','camera':'Cameras'}[p['kind']])
            self.socket_ship.set('All ships');self.filter_presets();self.socket_type.set(p['label'])
            self.weapon_group.set(str(a.get('socket_group',0)+1));self.preset_selected()

    def apply_preset(self):
        if self.busy or not self.plan:return
        ident=self.preset_labels.get(self.socket_type.get())
        if not ident:return
        selected=[self.socket_rows[k] for k in self.socket_objects.selection()]
        if ident==COCKPIT_CAMERA:
            objects={o['name']:o for o in self.inspection['objects']}
            if len(selected)!=1 or objects[selected[0]]['type']!='EMPTY':
                messagebox.showinfo('Cockpit camera','Select one Empty for Cockpit_Camera_Position.',parent=self);return
            for a in self.plan['objects']:
                if a['name']!=selected[0] and a['role']=='socket' and a.get('socket_preset')==COCKPIT_CAMERA:
                    a['role']='ignore'
                    row=next(k for k,v in self.object_rows.items() if v==a['name'])
                    values=list(self.objects.item(row,'values'));values[1]=ROLES['ignore'];self.objects.item(row,values=values)
        for name in selected:
            a=self.assignment(name)
            target=a.get('socket') if ident!=COCKPIT_CAMERA and a['role']=='socket' and a.get('socket') else new_socket_name(name)
            a.update(role='socket',socket=target,socket_preset=ident,socket_group=int(self.weapon_group.get())-1)
            row=next(k for k,v in self.object_rows.items() if v==name)
            values=list(self.objects.item(row,'values'));values[1]=ROLES['socket'];self.objects.item(row,values=values)
        if selected:self.plan['socket_catalog_sha256']=self.inspection['socket_catalog']['sha256']
        self.refresh_sockets();self.refresh_materials()

    def ignore_sockets(self):
        if self.busy or not self.plan:return
        for key in self.socket_objects.selection():
            name=self.socket_rows[key];self.assignment(name)['role']='ignore'
            row=next(k for k,v in self.object_rows.items() if v==name)
            values=list(self.objects.item(row,'values'));values[1]=ROLES['ignore'];self.objects.item(row,values=values)
        self.refresh_sockets();self.refresh_materials()

    def refresh_materials(self):
        self.materials.delete(*self.materials.get_children());self.material_rows={}
        if not self.plan:return
        roles={a['name']:a['role'] for a in self.plan['objects']};materials={m['name']:m for m in self.inspection['materials']}
        for i,assignment in enumerate(self.plan['materials']):
            if roles.get(assignment['object']) not in VISUAL_ROLES:continue
            key=str(i);self.material_rows[key]=i;source=assignment['source_material'];mode=assignment['mode']
            issue=materials.get(source,{}).get('issue')
            status='Color only (links omitted)' if mode=='diffuse' else (issue or ('Ready' if source else 'Choose a material'))
            self.materials.insert('', 'end',iid=key,text=f'{assignment["object"]} / {assignment["slot"]+1}',values=(source or '(Default grey)',MODES[mode],assignment['resolution'],status))

    def material_selected(self,_=None):
        selected=self.materials.selection()
        if not selected:return
        item=self.plan['materials'][self.material_rows[selected[0]]]
        self.material.set((item['source_material'] or '(Default grey)') if len(selected)==1 else '(Keep current material)')
        self.mode.set(MODES[item['mode']]);self.material_resolution.set(str(item['resolution']))
        source=next((m for m in self.inspection['materials'] if m['name']==item['source_material']),None)
        if source:
            details=(source['issue'] or 'Supported Principled material')+'\n'
            details+=' · '.join(f'{k}: {v}' for k,v in source['channels'].items())+'\n'
            details+='Textures: '+', '.join(f'{im["name"] or "MISSING"} ({im["size"][0]} × {im["size"][1]})' for im in source['images'])
            self.write(self.material_details,details)
        else:self.write(self.material_details,'No source material. Choose a Blender material or explicitly use Diffuse color only for a default grey surface.')

    def apply_material(self):
        if self.busy or not self.plan:return
        mode=next(k for k,v in MODES.items() if v==self.mode.get())
        for key in self.materials.selection():
            item=self.plan['materials'][self.material_rows[key]]
            if self.material.get()!='(Keep current material)':item['source_material']=None if self.material.get()=='(Default grey)' else self.material.get()
            item['mode']=mode;item['resolution']=int(self.material_resolution.get())
        self.refresh_materials()

    def tab_changed(self,_=None):
        if hasattr(self,'review') and self.plan and self.tabs.select()==str(self.review_tab):self.validate(select_tab=False)

    def validate(self,select_tab=True):
        if self.busy:return False
        try:
            plan=self.current_plan();errors,warnings=validate_plan(plan,self.inspection)
        except (ValueError,TypeError) as e:errors=[str(e)];warnings=[];plan=None
        lines=['ASSIGNMENT REVIEW','']
        if plan:
            lines += ['Actor: '+plan['name'],'Source: '+plan['source'],f'Scale to meters: {plan["scale"]}','']
            for role,label in ROLES.items():
                selected=[a['name']+(' → '+a.get('socket','(unassigned)') if role=='socket' else '') for a in plan['objects'] if a['role']==role]
                if selected:lines.append(label+': '+', '.join(selected))
        lines+=['','ERRORS' if errors else 'Ready to convert']+errors
        if warnings:lines+=['','NOTES']+warnings
        if plan:
            chosen=[a for a in plan['objects'] if a['role']=='socket' and a.get('socket_preset')]
            if chosen:
                lines+=['','SOCKET TYPES']+[a['name']+' → '+self.presets.get(a['socket_preset'],{}).get('label',a['socket_preset'])+(' · weapon group '+str(a.get('socket_group',0)+1) if self.presets.get(a['socket_preset'],{}).get('kind')=='weapon' else '') for a in chosen]
                if any(a['socket_preset']!=COCKPIT_CAMERA for a in chosen):
                    lines+=['New thruster config, hardpoint layout and default loadout will be created. Required stock equipment permissions will be extended for this actor only.']
                if any(a['socket_preset']==COCKPIT_CAMERA for a in chosen):
                    lines+=['Cockpit and internal camera positions will use the assigned Empty’s world position, converted using Scale to meters.']
        lines+=['','Creates separate game assets and a staged mod. Installation is a separate action.',
                'Uses the verified Interceptor opaque shader. Team skins are disabled. Materials that cannot be represented must be reassigned or explicitly simplified.',
                'Flight settings and unassigned camera positions are inherited from the Interceptor. Check fit and attachment placement in-game.']
        self.write(self.review,'\n'.join(lines))
        if select_tab:self.tabs.select(self.review_tab)
        return not errors

    def save_recipe(self):
        if self.busy or not self.plan:return
        try:plan=self.current_plan()
        except ValueError as e:messagebox.showerror('Recipe',str(e),parent=self);return
        path=filedialog.asksaveasfilename(parent=self,title='Save import assignments',initialfile=plan['name']+'.import.json',defaultextension='.json',filetypes=[('Import recipe','*.json')])
        if path:Path(path).write_text(json.dumps(plan,indent=2),encoding='utf8');self.status.set('Saved recipe: '+path)

    def load_recipe(self):
        if self.busy:return
        path=filedialog.askopenfilename(parent=self,title='Load import assignments',filetypes=[('Import recipe','*.json')])
        if not path:return
        try:
            recipe=json.loads(Path(path).read_text('utf8'))
            errors=recipe_structure_errors(recipe)
            if errors:raise ValueError('\n'.join(errors))
            if recipe.get('version')!=1 or not Path(recipe['source']).is_file():raise ValueError('Unsupported recipe or source file no longer exists.')
            self.pending_recipe=recipe;self.source.set(recipe['source'])
            self.work(lambda:inspect_custom_file(self.game,recipe['source'],self.blender,self.logger),'inspection')
        except (ValueError,KeyError,OSError) as e:messagebox.showerror('Cannot load recipe',str(e),parent=self)

    def convert(self,prepare=False):
        if self.busy or not self.validate():return
        plan=self.current_plan()
        if prepare:
            output=filedialog.asksaveasfilename(parent=self,title='New assigned Blender file',initialfile=plan['name']+'_Assigned.blend',defaultextension='.blend',filetypes=[('Blender','*.blend')])
        else:
            output=filedialog.asksaveasfilename(parent=self,title='Name a NEW mod directory',initialfile=plan['name']+'_Mod',filetypes=[('New mod directory','*')])
        if not output:return
        if Path(output).exists():messagebox.showerror('Output exists','Choose a new output path.',parent=self);return
        def task():
            convert_custom_file(self.game,self.blender,plan,output,prepare,self.logger)
            recipe_path=Path(output).with_suffix('.import.json') if prepare else Path(output)/'import-recipe.json'
            if not recipe_path.exists():recipe_path.write_text(json.dumps(plan,indent=2),encoding='utf8')
            return output
        self.work(task,'converted')

    def rotate_preview(self,event):
        if self.drag:
            self.yaw+=(event.x-self.drag[0])*.01;self.pitch+=(event.y-self.drag[1])*.01
            self.drag=(event.x,event.y);self.draw_preview()

    def draw_preview(self):
        self.canvas.delete('all')
        if not self.preview or not self.preview['points']:
            self.canvas.create_text(20,25,anchor='nw',text='Select a mesh for a wireframe preview.',fill='#cfdaeb');return
        points=self.preview['points'];cx=[sum(p[i] for p in points)/len(points) for i in range(3)]
        projected=[];cy,sy=math.cos(self.yaw),math.sin(self.yaw);cp,sp=math.cos(self.pitch),math.sin(self.pitch)
        for p in points:
            x,y,z=[p[i]-cx[i] for i in range(3)]
            a=x*cy-y*sy;b=x*sy+y*cy
            projected.append((a,b*sp-z*cp))
        radius=max(max(abs(x),abs(y)) for x,y in projected) or 1
        w,h=max(1,self.canvas.winfo_width()),max(1,self.canvas.winfo_height());scale=min(w,h)*.43/radius
        for i,j in self.preview['edges']:
            x,y=projected[i];xx,yy=projected[j]
            self.canvas.create_line(w/2+x*scale,h/2+y*scale,w/2+xx*scale,h/2+yy*scale,fill='#69b6d9')

    def close(self):
        if self.busy:
            messagebox.showinfo('Working','Wait for inspection/conversion to finish before closing.',parent=self);return
        self.after_cancel(self.poll_id);self.grab_release();self.destroy()
