"""Standalone desktop entry point and automatable CLI."""
from pathlib import Path
import argparse
import contextlib
import json
import os
import queue
import sys
import threading
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from ibworkbench.formats import Assets
from ibworkbench.project import catalog
from ibworkbench.runner import blender_path, export_actor, stage_mod, new_actor_template, stage_new_actor, inspect_custom_file, convert_custom_file
from ibworkbench.mods import install, restore
from ibworkbench.editor_package import export_package

DEFAULT_GAME = 'A:/Steam/steamapps/common/Infinity Battlescape'
if not getattr(sys,'frozen',False):
    local_tcl=Path(__file__).parent/'build/tcl-runtime'
    if (local_tcl/'tcl8.6/init.tcl').exists():
        os.environ.setdefault('TCL_LIBRARY',str(local_tcl/'tcl8.6'))
        os.environ.setdefault('TK_LIBRARY',str(local_tcl/'tk8.6'))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Actor Workbench — Infinity Battlescape (experimental)')
        self.geometry('1120x820')
        self.minsize(850,650)
        self.busy = False
        self.rows = []
        self.events = queue.Queue()
        self.game = tk.StringVar(value=DEFAULT_GAME if Path(DEFAULT_GAME).exists() else '')
        self.blender = tk.StringVar(value=blender_path())
        self.search = tk.StringVar()
        self.status = tk.StringVar(value='Choose your game installation, then scan actors.')
        outer = ttk.Frame(self,padding=18)
        outer.pack(fill='both',expand=True)
        ttk.Label(outer,text='ACTOR WORKBENCH',font=('Segoe UI',22,'bold')).pack(anchor='w')
        ttk.Label(outer,text='Local Blender export • Original mesh data • Guarded mod write-back',font=('Segoe UI',10)).pack(anchor='w',pady=(0,16))
        for title,var,command in [('Game folder',self.game,self.pick_game),('Blender executable',self.blender,self.pick_blender)]:
            row = ttk.Frame(outer)
            row.pack(fill='x',pady=3)
            ttk.Label(row,text=title,width=20).pack(side='left')
            ttk.Entry(row,textvariable=var).pack(side='left',fill='x',expand=True)
            ttk.Button(row,text='Browse…',command=command).pack(side='right',padx=(8,0))
        row = ttk.Frame(outer)
        row.pack(fill='x',pady=(16,8))
        ttk.Button(row,text='Scan actors',command=self.scan).pack(side='left')
        ttk.Label(row,text='Filter').pack(side='left',padx=(20,8))
        ttk.Entry(row,textvariable=self.search).pack(side='left',fill='x',expand=True)
        self.search.trace_add('write',lambda *_:self.filter())
        self.tree = ttk.Treeview(outer,columns=('kind','path'),selectmode='browse',height=12)
        self.tree.heading('#0',text='Actor / module')
        self.tree.heading('kind',text='Type')
        self.tree.heading('path',text='Original config')
        self.tree.column('#0',width=290)
        self.tree.column('kind',width=135)
        self.tree.column('path',width=470)
        self.tree.pack(fill='both',expand=True)
        actions = ttk.Frame(outer)
        actions.pack(fill='x',pady=10)
        for label,command in [('Export selected → .blend',self.export),('Edited .blend → mod folder',self.stage),
                              ('Install staged mod…',self.install),('Restore backup…',self.restore)]:
            ttk.Button(actions,text=label,command=command).pack(side='left',padx=(0,8))
        new_actions=ttk.Frame(outer)
        new_actions.pack(fill='x',pady=(0,8))
        ttk.Button(new_actions,text='New actor template…',command=self.new_template).pack(side='left',padx=(0,8))
        ttk.Button(new_actions,text='New actor .blend → mod folder',command=self.new_actor).pack(side='left')
        ttk.Button(new_actions,text='Import custom meshes…',command=self.import_custom).pack(side='left',padx=8)
        ttk.Label(new_actions,text='Blender / glTF · Principled conversion').pack(side='left')
        package_actions=ttk.Frame(outer)
        package_actions.pack(fill='x',pady=(0,8))
        ttk.Button(package_actions,text='Mission Editor collision package…',command=self.package).pack(side='left')
        self.package_all=tk.BooleanVar(value=False)
        ttk.Checkbutton(package_actions,text='All actors/modules (otherwise selected actor)',variable=self.package_all).pack(side='left',padx=12)
        ttk.Button(package_actions,text='Mesh/texture import help…',command=self.import_help).pack(side='right')
        warning = ('Experimental: materials use a Blender approximation, not the compiled game shader. Particles are placed markers.\n'
                   'Write-back supports replacement static meshes/UVs, texture images, sockets, assembly transforms and XML lights.\n'
                   'Custom import assigns meshes, LODs, cockpits, collisions and sockets, and bakes supported Principled materials. Dynamic loadouts are inherited.')
        ttk.Label(outer,text=warning,foreground='#924600',wraplength=1060).pack(anchor='w',pady=(0,8))
        self.output = tk.Text(outer,height=10,font=('Consolas',9),state='disabled',wrap='word')
        self.output.pack(fill='x')
        ttk.Label(outer,textvariable=self.status).pack(anchor='w',pady=(8,0))
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.after(100,self.poll)

    def pick_game(self):
        path = filedialog.askdirectory(title='Infinity Battlescape installation (containing Dev)')
        if path:
            self.game.set(path)

    def pick_blender(self):
        path = filedialog.askopenfilename(title='Select blender.exe',filetypes=[('Blender','blender.exe')])
        if path:
            self.blender.set(path)

    def log(self,message):
        self.events.put(('log',message))

    def start(self,func):
        if self.busy:
            messagebox.showinfo('Working','Wait for the current operation to finish.')
            return
        self.busy = True
        self.status.set('Working… Game files are only changed by Install / Restore.')
        def work():
            try:
                func()
                self.events.put(('done','Operation completed.'))
            except Exception as e:
                self.log(traceback.format_exc())
                self.events.put(('error',str(e)))
        threading.Thread(target=work,daemon=True).start()

    def poll(self):
        while not self.events.empty():
            kind,value = self.events.get()
            if kind=='log':
                self.output.configure(state='normal')
                self.output.insert('end',value+'\n')
                self.output.see('end')
                self.output.configure(state='disabled')
            elif kind=='rows':
                self.rows=value
                self.filter()
            else:
                self.busy=False
                self.status.set(value)
                if kind=='error':
                    messagebox.showerror('Operation stopped',value)
        self.after(100,self.poll)

    def scan(self):
        game = self.game.get()
        def task():
            rows=catalog(Assets(game))
            self.events.put(('rows',rows))
            self.log(f'Found {len(rows)} actor/module configs.')
        self.start(task)

    def filter(self):
        self.tree.delete(*self.tree.get_children())
        term=self.search.get().lower()
        for i,row in enumerate(self.rows):
            if term in ' '.join(row.values()).lower():
                self.tree.insert('','end',iid=str(i),text=row['name'],values=(row['kind'],row['path']))

    def export(self):
        if self.busy: return
        selected=self.tree.selection()
        if not selected:
            messagebox.showinfo('Choose an actor','Scan and select an actor or module first.')
            return
        row=self.rows[int(selected[0])]
        output=filedialog.asksaveasfilename(title='New Blender file',initialfile=row['name']+'.blend',defaultextension='.blend',filetypes=[('Blender file','*.blend')])
        if output:
            game,blender=self.game.get(),self.blender.get()
            self.start(lambda:export_actor(game,row['path'],blender,output,self.log))

    def stage(self):
        if self.busy: return
        blend=filedialog.askopenfilename(title='Edited Actor Workbench .blend',filetypes=[('Blender file','*.blend')])
        if not blend: return
        output=filedialog.asksaveasfilename(title='Name a NEW mod directory',initialfile=Path(blend).stem+'-mod',filetypes=[('Mod directory','*')])
        if output:
            game,blender=self.game.get(),self.blender.get()
            self.start(lambda:stage_mod(game,blend,blender,output,self.log))

    def import_help(self):
        messagebox.showinfo('Replace game geometry and textures',
            'Export the actor and keep its original objects/hierarchy.\n\n'
            'MESH: replace geometry inside an existing object in Edit Mode, or add a mesh named REPLACE:<exact exported object name>. '
            'Keep the original object as the target. Modifiers are evaluated. Reuse original game material slots; a helper without materials uses slot 0.\n\n'
            'For a whole ship, replace its LODs and collision objects as well. They are not generated automatically.\n\n'
            'TEXTURES: paint and pack the original image, or select a replacement image in an existing game texture node. Keep its color space and shader links.\n\n'
            'Save the .blend, stage a NEW mod folder, inspect mod.json, then Install staged mod. Close the game first. Originals are backed up; Restore backup reverses it.\n\n'
            'Experimental: binary round-trips tested, but in-game compatibility still needs validation. Shared assets affect other actors.')

    def new_template(self):
        if self.busy:return
        name=simpledialog.askstring('New actor','Unique actor name (letters, digits, underscores):',initialvalue='CustomInterceptor',parent=self)
        if not name:return
        output=filedialog.asksaveasfilename(title='New actor Blender template',initialfile=name+'.blend',defaultextension='.blend',filetypes=[('Blender file','*.blend')])
        if output:
            game,blender=self.game.get(),self.blender.get()
            self.start(lambda:new_actor_template(game,blender,output,name,self.log))

    def import_custom(self):
        if self.busy:return
        from ibworkbench.import_ui import ImportDialog
        ImportDialog(self,self.game.get(),self.blender.get())

    def new_actor(self):
        if self.busy:return
        blend=filedialog.askopenfilename(title='New actor template .blend',filetypes=[('Blender file','*.blend')])
        if not blend:return
        output=filedialog.asksaveasfilename(title='Name a NEW actor mod directory',initialfile=Path(blend).stem+'-new-actor-mod')
        if output:
            game,blender=self.game.get(),self.blender.get()
            self.start(lambda:stage_new_actor(game,blend,blender,output,log=self.log))

    def package(self):
        if self.busy: return
        actors=[]
        if not self.package_all.get():
            selected=self.tree.selection()
            if not selected:
                messagebox.showinfo('Select an actor','Select an actor or enable All actors/modules.')
                return
            actors=[self.rows[int(selected[0])]['path']]
        output=filedialog.asksaveasfilename(title='NEW encrypted collision package (no LODs or bounds)',
            initialfile='actor-collisions.ibmesh',defaultextension='.ibmesh',filetypes=[('Encrypted Mission Editor package','*.ibmesh')])
        if output:
            game=self.game.get()
            self.start(lambda:export_package(game,actors,output,self.log))

    def install(self):
        if self.busy: return
        folder=filedialog.askdirectory(title='Choose staged mod folder (contains mod.json)')
        if not folder: return
        try:
            manifest=json.loads((Path(folder)/'mod.json').read_text('utf8'))
            paths='\n'.join(e['path'] for e in manifest['files'])
        except Exception as e:
            messagebox.showerror('Invalid mod',str(e))
            return
        if not messagebox.askyesno('Modify game assets?',f'Close the game first. Files will be added or replaced as listed in this mod:\n\n{paths[:3500]}\n\nExisting files will be backed up. Restore also removes added files. Install this mod?'):
            return
        game=self.game.get()
        backups=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'IBActorWorkbench/Backups'
        def task():
            backup=install(folder,game,backups)
            self.log('Installed. Recovery backup: '+str(backup))
        self.start(task)

    def restore(self):
        if self.busy: return
        folder=filedialog.askdirectory(title='Choose original backup folder (contains mod.json)')
        if folder and messagebox.askyesno('Restore original assets?','Close the game first. Restore these backed-up files? Conflicting newer edits will be rejected.'):
            game=self.game.get()
            self.start(lambda:restore(folder,game))

    def close(self):
        if self.busy:
            messagebox.showinfo('Operation running','Please wait until the operation finishes before closing.')
        else:
            self.destroy()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--game',default=DEFAULT_GAME)
    parser.add_argument('--blender',default=blender_path())
    parser.add_argument('--log',help='Write CLI output/errors to a new log file (use before the subcommand)')
    sub=parser.add_subparsers(dest='command')
    sub.add_parser('list')
    export=sub.add_parser('export')
    export.add_argument('actor')
    export.add_argument('output')
    stage=sub.add_parser('stage')
    stage.add_argument('blend')
    stage.add_argument('output')
    template=sub.add_parser('new-template',help='Create a Principled-based Interceptor dummy actor')
    template.add_argument('output')
    template.add_argument('--name',default='CustomInterceptor')
    new_actor=sub.add_parser('new-actor',help='Bake and stage an independent actor from a new template')
    new_actor.add_argument('blend')
    new_actor.add_argument('output')
    new_actor.add_argument('--name')
    inspect=sub.add_parser('inspect-custom',help='Inspect objects/materials in a Blender or glTF file')
    inspect.add_argument('source');inspect.add_argument('report')
    custom=sub.add_parser('convert-custom',help='Convert explicit assignments from an import recipe')
    custom.add_argument('recipe');custom.add_argument('output');custom.add_argument('--prepare-blend',action='store_true')
    package=sub.add_parser('package')
    package.add_argument('output')
    package.add_argument('actors',nargs='*',help='Config paths; omit to package all catalog actors/modules')
    sub.add_parser('self-test')
    args=parser.parse_args()
    if args.command=='list':
        print(json.dumps(catalog(Assets(args.game)),indent=2))
    elif args.command=='export':
        export_actor(args.game,args.actor,args.blender,args.output)
    elif args.command=='stage':
        stage_mod(args.game,args.blend,args.blender,args.output)
    elif args.command=='new-template':
        new_actor_template(args.game,args.blender,args.output,args.name)
    elif args.command=='new-actor':
        stage_new_actor(args.game,args.blend,args.blender,args.output,args.name)
    elif args.command=='inspect-custom':
        if Path(args.report).exists():raise ValueError('Choose a new report filename')
        report=inspect_custom_file(args.game,args.source,args.blender)
        Path(args.report).write_text(json.dumps(report,indent=2),encoding='utf8')
    elif args.command=='convert-custom':
        plan=json.loads(Path(args.recipe).read_text('utf8'))
        convert_custom_file(args.game,args.blender,plan,args.output,args.prepare_blend)
    elif args.command=='package':
        export_package(args.game,args.actors,args.output)
    elif args.command=='self-test':
        assert Assets(args.game).resolve('Ships/SFC-Fighter/SM_SFC_Fighter_exterior_no_cockpit_Lod0','.insm').is_file()
        root=App()
        root.withdraw()
        root.rows=catalog(Assets(args.game))
        root.filter()
        root.update()
        assert len(root.tree.get_children())>0
        root.destroy()
        print('SELF-TEST PASSED')
    else:
        App().mainloop()


if __name__=='__main__':
    # Windowed builds have no console; explicit CLI logs also prevent a hidden
    # native exception dialog from making unattended staging appear hung.
    if '--log' in sys.argv and sys.argv.index('--log')+1 < len(sys.argv):
        log_path = Path(sys.argv[sys.argv.index('--log')+1])
        with log_path.open('x',encoding='utf8') as stream, contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            try:
                main()
            except Exception:
                traceback.print_exc()
                raise SystemExit(1)
    else:
        main()
