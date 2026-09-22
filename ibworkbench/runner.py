from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import ctypes
import shutil
from .project import prepare


def blender_path():
    candidates = sorted(Path('C:/Program Files/Blender Foundation').glob('Blender */blender.exe'),reverse=True)
    return str(candidates[0]) if candidates else ''


def run_blender(blender, job, log=print):
    executable = Path(blender)
    if not executable.is_file():
        raise ValueError('Select your installed blender.exe')
    # Frozen app ships source alongside its bundled Python runtime. Blender uses
    # its own Python/numpy, not the executable's PyInstaller environment.
    worker_source = Path(__file__).with_name('blender_worker.py')
    with tempfile.TemporaryDirectory(prefix='ibaw-job-') as folder:
        # Never add PyInstaller's _internal directory to Blender's sys.path:
        # its Python ABI differs, and bundled pyexpat.pyd shadows Blender's.
        # Copy only our Python sources into this isolated job directory.
        worker_dir = Path(folder)/'ibworkbench'
        worker_dir.mkdir()
        for source in worker_source.parent.glob('*.py'):
            shutil.copy2(source,worker_dir/source.name)
        worker = worker_dir/'blender_worker.py'
        path = Path(folder)/'job.json'
        path.write_text(json.dumps(job),encoding='utf8')
        cmd = [str(executable),'--background','--factory-startup','--disable-autoexec',
               '--python-exit-code','1','--python',str(worker),'--',str(path)]
        env = os.environ.copy()
        env['BLENDER_USER_RESOURCES'] = str(Path(folder)/'blender-user')
        for key in ('PYTHONHOME','PYTHONPATH'):
            env.pop(key,None)
        if os.name=='nt' and getattr(sys,'frozen',False):
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        try:
            process = subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,
                                       encoding='utf8',errors='replace',env=env,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        finally:
            if os.name=='nt' and getattr(sys,'frozen',False):
                ctypes.windll.kernel32.SetDllDirectoryW(sys._MEIPASS)
        with process:
            for line in process.stdout:
                log(line.rstrip())
            if process.wait():
                raise RuntimeError('Blender conversion failed. See the log above; game files were not modified.')


def export_actor(game, actor, blender, destination, log=print):
    destination = Path(destination).resolve()
    if destination.suffix.lower() != '.blend' or destination.exists():
        raise ValueError('Choose a new filename ending in .blend')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ibaw-export-') as temp:
        project = prepare(game,actor,Path(temp)/'textures',log)
        manifest = Path(temp)/'manifest.json'
        manifest.write_text(json.dumps(project),encoding='utf8')
        # Export to a sibling temporary file; failed exports never occupy the chosen name.
        temp_blend = destination.with_name(destination.stem+'.working.blend')
        if temp_blend.exists():
            raise ValueError('An earlier working file exists: '+str(temp_blend))
        run_blender(blender,dict(action='export',game=str(game),manifest=str(manifest),output=str(temp_blend)),log)
        if not temp_blend.is_file() or temp_blend.stat().st_size < 100:
            raise RuntimeError('Blender did not produce a valid file')
        if destination.exists():
            raise ValueError('Destination appeared during export; output retained at '+str(temp_blend))
        temp_blend.rename(destination)
        report = destination.with_suffix('.report.json')
        if not report.exists():
            report.write_text(json.dumps(dict(actor=actor,counts=project['counts'],skin=project.get('skin'),warnings=project['warnings']),indent=2),encoding='utf8')
        log('Saved '+str(destination))
        return project


def stage_mod(game, blend, blender, destination, log=print):
    run_blender(blender,dict(action='mod',game=str(game),blend=str(Path(blend).resolve()),output=str(Path(destination).resolve())),log)


def new_actor_template(game, blender, destination, name='CustomInterceptor', log=print):
    from .new_actor import actor_name
    run_blender(blender,dict(action='new-template',game=str(game),output=str(Path(destination).resolve()),name=actor_name(name)),log)


def stage_new_actor(game, blend, blender, destination, name=None, log=print):
    from .new_actor import actor_name
    run_blender(blender,dict(action='new-actor',game=str(game),blend=str(Path(blend).resolve()),output=str(Path(destination).resolve()),name=actor_name(name) if name else None),log)


def inspect_custom_file(game, source, blender, log=print):
    with tempfile.TemporaryDirectory(prefix='ibaw-inspect-') as temp:
        report=Path(temp)/'inspection.json'
        run_blender(blender,dict(action='inspect-custom',game=str(game),source=str(Path(source).resolve()),report=str(report)),log)
        return json.loads(report.read_text('utf8'))


def convert_custom_file(game, blender, plan, destination, prepare=False, log=print):
    run_blender(blender,dict(action='prepare-custom' if prepare else 'convert-custom',game=str(game),plan=plan,output=str(Path(destination).resolve())),log)
