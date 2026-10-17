"""Per-user results supervisor; never invokes generation or touches canvas data."""
import json,logging,logging.handlers,msvcrt,os,shutil,subprocess,sys,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parent
DATA=ROOT/'.data'/'results-watchdog';DATA.mkdir(parents=True,exist_ok=True)
logger=logging.getLogger('results-watchdog');logger.setLevel(logging.INFO)
h=logging.handlers.RotatingFileHandler(DATA/'watchdog.log',maxBytes=1024*1024,backupCount=3,encoding='utf8');logger.addHandler(h)
def healthy():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8769/health',timeout=4) as r:
            return json.load(r).get('service')=='canvas-results'
    except Exception:return False

def child_environment():
    home=Path(os.environ.get('USERPROFILE') or os.path.expanduser('~')).resolve()
    env=os.environ.copy();env['PYTHONUTF8']='1';env['HOME']=str(home);env['USERPROFILE']=str(home)
    env.setdefault('APPDATA',str(home/'AppData'/'Roaming'));env.setdefault('LOCALAPPDATA',str(home/'AppData'/'Local'))
    cli=home/'bin'/'dreamina-canvas.exe'
    node_candidates=[env.get('DREAMINA_NODE',''),str(home/'.cache'/'codex-runtimes'/'codex-primary-runtime'/'dependencies'/'node'/'bin'/'node.exe'),shutil.which('node') or '',shutil.which('node.exe') or '']
    node=next((Path(p) for p in node_candidates if p and Path(p).is_file()),None)
    if node:env['DREAMINA_NODE']=str(node)
    dirs=[str(cli.parent)]+([str(node.parent)] if node else [])
    env['PATH']=os.pathsep.join(dirs+[env.get('PATH','')])
    env['DREAMINA_CANVAS_CLI']=str(cli)
    return env,cli

def main():
    lock=open(DATA/'watchdog.lock','a+b');lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
    try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:return
    (DATA/'watchdog.pid').write_text(str(os.getpid()))
    child=None;failures=0;backoff=3;started=0
    logger.info('Supervisor started pid=%s',os.getpid())
    with open(DATA/'server.log','ab',buffering=0) as output:
        while True:
            try:
                if child is not None and child.poll() is not None:
                    logger.warning('Server exited code=%s',child.returncode);child=None;failures=0
                    time.sleep(backoff);backoff=min(60,backoff*2)
                if healthy():
                    failures=0
                    if child and time.monotonic()-started>120:backoff=3
                elif child is None:
                    # Existing servers are never terminated or force-adopted.
                    import socket
                    with socket.socket() as probe:
                        probe.settimeout(2)
                        occupied=probe.connect_ex(('127.0.0.1',8769))==0
                    if occupied:
                        logger.warning('Port occupied but health unavailable; not killing an unrelated process')
                    else:
                        env,cli=child_environment();env['PYTHONUTF8']='1'
                        python=str(Path(sys.executable).with_name('python.exe'))
                        args=[python,str(ROOT/'canvas_results.py'),'--host','0.0.0.0','--port','8769','--cli',str(cli)]
                        child=subprocess.Popen(args,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=output,stderr=output,creationflags=subprocess.CREATE_NO_WINDOW)
                        started=time.monotonic();(ROOT/'.data'/'canvas-results.pid').write_text(str(child.pid));logger.info('Server started pid=%s',child.pid)
                else:
                    failures+=1
                    if failures>=3 and time.monotonic()-started>60:
                        logger.warning('Owned server failed health checks; restarting pid=%s',child.pid)
                        child.terminate()
                        try:child.wait(timeout=15)
                        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
                        child=None;failures=0;time.sleep(backoff)
                time.sleep(10)
            except Exception:
                logger.exception('Supervisor loop error');time.sleep(10)
if __name__=='__main__':main()
