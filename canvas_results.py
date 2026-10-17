"""LAN canvas output viewer and explicit subject imports; never runs generation."""
from __future__ import annotations
import argparse, concurrent.futures, hashlib, hmac, ipaddress, json, mimetypes, os, re, secrets, shutil, socket, subprocess, threading, time, uuid, zipfile
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, quote

ROOT=Path(__file__).resolve().parent
UUID=re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z')
NODE=re.compile(r'node_[0-9a-hjkmnp-tv-z]{10}\Z')

def ident(v):
    if not isinstance(v,str) or not UUID.fullmatch(v): raise ValueError('标识格式错误')
    return v

def natural(text):
    return tuple((0,int(x)) if x.isdigit() else (1,x.casefold()) for x in re.split(r'(\d+)',text))

def parse_header(prompt,title):
    # Prompt first line is authoritative. Legacy numeric titles remain recognisable.
    line=(prompt or '').lstrip('\ufeff').splitlines()[0].strip() if (prompt or '').strip() else ''
    for source,text in [('prompt',line),('title',title or '')]:
        match=re.match(r'^(.+?)-(\d+)-((?:\d+|[A-Za-z]+)(?:-(?:\d+|[A-Za-z]+))*)(?=$|[\s｜|])',text)
        if match and not match[1].isdigit(): return {'drama':match[1],'episode':int(match[2]),'shot':match[3],'source':source,'label':match[0]}
        if source=='title':
            match=re.match(r'^(\d+)-((?:\d+|[A-Za-z]+)(?:-(?:\d+|[A-Za-z]+))*)(?=$|[\s｜|])',text)
            if match:return {'drama':'','episode':int(match[1]),'shot':match[2],'source':'legacy-title','label':match[0]}
    return {'drama':'','episode':None,'shot':'','source':'unknown','label':'未识别'}

def filename(text):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_',text).strip(' .')[:130] or '产出'

def find_node():
    candidates=[os.environ.get('DREAMINA_NODE',''),str(Path.home()/'.cache'/'codex-runtimes'/'codex-primary-runtime'/'dependencies'/'node'/'bin'/'node.exe'),shutil.which('node') or '',shutil.which('node.exe') or '']
    for candidate in candidates:
        if candidate and Path(candidate).is_file():return str(Path(candidate).resolve())
    return ''

class App:
    def __init__(self,cli,data):
        self.cli=str(cli);self.data=Path(data);self.data.mkdir(parents=True,exist_ok=True)
        self.media=self.data/'media';self.media.mkdir(exist_ok=True)
        self.sessions={};self.snapshots={};self.downloads={};self.jobs={};self.thumbnails={};self.lock=threading.RLock()
        self.thumb_pool=concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=3)
        self.zip_pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.cli_slots=threading.BoundedSemaphore(4)
    def call(self,args,timeout=90):
        if tuple(args[:2]) not in {('canvas','ls'),('node','find'),('node','show'),('resource','download')}:
            raise ValueError('仅支持固定的读取和下载命令')
        return self._invoke(args,timeout)
    def _invoke(self,args,timeout):
        if any(a in args for a in ['--run','--yes','--credit-token','--credit-ceiling']):raise ValueError('禁止生成')
        with self.cli_slots:
            try:r=subprocess.run([self.cli,'--format','json','--non-interactive',*args],capture_output=True,text=True,encoding='utf8',errors='replace',timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            except subprocess.TimeoutExpired:raise ValueError('CLI 等待超时，请稍后重试查询') from None
        j=None
        for output in (r.stdout,r.stderr):
            try:
                parsed=json.loads(output.lstrip('\ufeff').strip())
                if isinstance(parsed,dict) and isinstance(parsed.get('ok'),bool):
                    j=parsed;break
            except (ValueError,AttributeError):pass
        if j is None:
            command=' '.join(args[:2])
            raise ValueError(f'CLI {command} 未返回结构化结果（退出码 {r.returncode}）；可能是网络或进程异常，并非已确认登录失效。请重试读取；若正在保存请勿重复提交。')
        if r.returncode or not j.get('ok'):
            e=j.get('error') or {};message=re.sub(r'https?://\S+','[链接隐藏]',str(e.get('message','CLI 操作失败')))
            raise ValueError(message[:500])
        return j.get('data') or {}
    def official_subjects(self,search='',refresh=False):
        if len(search)>100:raise ValueError('搜索词过长')
        if not hasattr(self,'subject_cache_lock'):self.subject_cache_lock=threading.Lock();self.subject_cache=None;self.subject_images={}
        with self.subject_cache_lock:
            if refresh or self.subject_cache is None or time.time()-self.subject_cache['time']>300:
                node=find_node()
                if not node:raise ValueError('未找到 Node.js')
                try:r=subprocess.run([node,str(ROOT/'subjects.cjs'),'_preview-list'],capture_output=True,text=True,encoding='utf8',timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                except subprocess.TimeoutExpired:raise ValueError('主体库读取超时，请稍后重试') from None
                if r.returncode:raise ValueError('请启动专用 Chrome、登录即梦，并只保留一个即梦标签页')
                result=json.loads(r.stdout);urls={}
                for item in result['items']:
                    url=item.pop('previewUrl','');u=urlsplit(url)
                    if u.scheme=='https' and u.hostname and u.hostname.endswith('.byteimg.com') and not u.username and u.port in (None,443):urls[item['subjectId']]=url
                    item['thumbnail']=item['subjectId'] in urls
                self.subject_cache={'time':time.time(),'result':result,'urls':urls}
            result=self.subject_cache['result']
            items=[i for i in result['items'] if search.casefold() in i['name'].casefold()]
            return {**result,'items':items,'total':len(items)}
    def subject_thumbnail(self,subject):
        import urllib.request
        self.official_subjects()
        if not isinstance(subject,str) or len(subject)>150:raise ValueError('主体标识错误')
        with self.subject_cache_lock:
            url=self.subject_cache['urls'].get(subject);cached=self.subject_images.get(subject)
        if cached:return cached
        if not url:raise ValueError('主体暂无缩略图')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        opener=urllib.request.build_opener(NoRedirect)
        with opener.open(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=25) as r:
            mime=r.headers.get_content_type();blob=r.read(5*1024*1024+1)
        if mime not in {'image/jpeg','image/png','image/webp','image/avif'} or len(blob)>5*1024*1024:raise ValueError('缩略图格式或大小不支持')
        with self.subject_cache_lock:self.subject_images[subject]=(blob,mime)
        return blob,mime
    def import_subjects(self,project,subjects):
        ident(project)
        if not isinstance(subjects,list) or not 1<=len(subjects)<=20 or any(not isinstance(x,str) or not x or len(x)>150 for x in subjects):raise ValueError('每批选择1–20个主体')
        args=[find_node() or 'node',str(ROOT/'subjects.cjs'),'add','--project-id',project]
        for subject in subjects:args+=['--subject-id',subject]
        jobid=str(uuid.uuid4());job={'status':'running','projectId':project};self.jobs[jobid]=job
        def work():
            try:
                r=subprocess.run(args,capture_output=True,text=True,encoding='utf8',timeout=1800,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if r.returncode:raise ValueError(r.stderr.strip()[:400] or '添加失败')
                job.update(status='ready',result=json.loads(r.stdout))
            except Exception as e:job.update(status='failed',error=str(e)[:400])
        self.zip_pool.submit(work)
        return {'jobId':jobid,**job}
    def canvases(self):
        data=self.call(['canvas','ls','--limit','100'])
        return {'items':data.get('items',[]),'hasMore':data.get('hasMore',False)}
    def scan(self,project,offset_start=None,media_type=""):
        ident(project);summaries={};offset=offset_start or 0;warnings=[];versions=set()
        if media_type not in {"","video","image","audio","timeline"}:raise ValueError("媒体类型不正确")
        if offset<0 or offset>1000:raise ValueError("分页超出范围")
        while True:
            data=self.call(['node','find','--project-id',project,'--limit','20' if offset_start is not None else '50','--offset',str(offset)]+(['--type',media_type] if media_type else []))
            if data.get('draftVersion') is not None:versions.add(data['draftVersion'])
            page=data.get('items',[])
            for n in page:summaries[n['nodeId']]=n
            if offset_start is not None or not data.get('hasMore'):break
            offset+=len(page)
            if not page or offset>1000:
                warnings.append('CLI 分页已达上限，当前列表不是完整画布；请在画布拆分或缩小范围。');break
        data_find_more=data.get('hasMore',False);total_found=data.get('total',len(summaries))
        nodes=[]
        ids=list(summaries)
        for i in range(0,len(ids),20):
            data=self.call(['node','show','--project-id',project,*sum((['--node-id',n] for n in ids[i:i+20]),[])])
            if data.get('draftVersion') is not None:versions.add(data['draftVersion'])
            nodes.extend(x['node'] for x in data.get('nodes',[]) if x.get('node'))
        if len(versions)>1:warnings.append('读取期间画布有更新，分页不绑定快照；可刷新再次核对。')
        if len(nodes)<len(ids):warnings.append('部分节点已删除或无法读取。')
        items=[]
        for n in nodes:
            if n.get('type') not in {'video','image','audio','timeline'}:continue
            g=n.get('generation') or {};prompt=g.get('prompt','');header=parse_header(prompt,n.get('title',''))
            resources=n.get('resources') or []
            rows=resources or [None]
            for index,r in enumerate(rows):
                row={'nodeId':n['nodeId'],'title':n.get('title',''),'type':(r or {}).get('type',n['type']),'nodeStatus':n.get('status','unknown'),'status':(r or {}).get('status',n.get('status','empty')),'prompt':prompt,'model':g.get('model',''),'ratio':g.get('ratio',''),'resolution':g.get('resolution',''),'duration':g.get('durationSeconds'),'resourceId':(r or {}).get('resourceId'),'createdAt':(r or {}).get('createdAt',0),'provenance':(r or {}).get('source',''),'candidate':index+1,'candidateCount':len(resources),'hasOutput':r is not None,**header}
                row['key']=n['nodeId']+':'+str(row['resourceId'] or 'draft')
                row['downloadable']=bool(row['resourceId'] and row['status']=='success')
                items.append(row)
        items.sort(key=lambda x:(x['episode'] is None,natural(x['drama']),x['episode'] or 0,natural(x['shot']),x['createdAt'] or 0,x['key']))
        result={'projectId':project,'items':items,'scannedAt':time.time(),'nodeCount':len(nodes),'outputCount':sum(x['hasOutput'] for x in items),'warnings':warnings,'complete':not warnings,'mediaType':media_type}
        if offset_start is not None:
            result.update(hasMore=bool(data_find_more),nextOffset=offset+len(summaries),total=total_found)
        with self.lock:
            previous=self.snapshots.get(project,{}).get('items',[])
            merged={x['key']:x for x in previous}
            merged.update({x['key']:x for x in items})
            self.snapshots[project]={**result,'items':list(merged.values())} if offset_start is not None else result
        return result
    def resource_row(self,project,resource):
        ident(project);ident(resource)
        with self.lock:snapshot=self.snapshots.get(project)
        if not snapshot:raise ValueError('请先选择画布并读取产出')
        row=next((x for x in snapshot['items'] if x.get('resourceId')==resource),None)
        if not row or not row['downloadable']:raise ValueError('该资源不属于当前已读取画布，或尚未成功')
        return row
    def prepare(self,project,resource):
        row=self.resource_row(project,resource);key=(project,resource)
        with self.lock:
            previous=self.downloads.get(key)
            if previous and previous['status'] in {'queued','running','ready'}:return {k:v for k,v in previous.items() if k!='path'}
            item={'status':'queued','projectId':project,'resourceId':resource};self.downloads[key]=item
            self.pool.submit(self.fetch,project,resource,row,item)
            return dict(item)
    def fetch(self,project,resource,row,item):
        item['status']='running';root=self.media/project/resource;root.mkdir(parents=True,exist_ok=True);marker=root/'complete.json'
        try:
            saved=json.loads(marker.read_text(encoding='utf8'));cached=(root/saved['file']).resolve()
            if cached.is_relative_to(root.resolve()) and cached.is_file() and cached.stat().st_size==saved['size'] and saved['size']>0:
                item.update(status='ready',path=str(cached),size=saved['size'],name=self.output_name(row,cached.suffix));return
        except (OSError,ValueError,KeyError,TypeError):pass
        folder=root/secrets.token_hex(6);folder.mkdir()
        try:
            # The CLI obtains and consumes any temporary download URL internally.
            self.call(['resource','download',resource,'--project-id',project,'--output',str(folder)],timeout=600)
            paths=[p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {'.mp4','.webm','.mov','.m4v','.png','.jpg','.jpeg','.webp','.gif','.mp3','.wav','.m4a','.ogg'} and p.stat().st_size>0]
            if len(paths)!=1:raise ValueError('下载文件数量或格式不符合预期，未提供预览')
            metadata={'file':str(paths[0].relative_to(root)),'size':paths[0].stat().st_size};temporary=marker.with_suffix('.tmp');temporary.write_text(json.dumps(metadata),encoding='utf8');temporary.replace(marker)
            item.update(status='ready',path=str(paths[0]),size=paths[0].stat().st_size,name=self.output_name(row,paths[0].suffix))
        except Exception as e:item.update(status='failed',error=str(e) if isinstance(e,ValueError) else '下载失败，请检查 CLI 登录状态与网络')
    def thumbnail(self,project,resource):
        row=self.resource_row(project,resource)
        if row['type'] not in {'video','image','timeline'}:raise ValueError('此素材没有画面缩略图')
        key=(project,resource)
        with self.lock:
            existing=self.thumbnails.get(key)
            if existing:return {k:v for k,v in existing.items() if k!='path'}
            path=self.data/'thumbnails'/project/(resource+'.jpg')
            if path.is_file() and path.stat().st_size>2 and path.read_bytes()[:2]==b'\xff\xd8':
                item={'status':'ready','path':str(path)};self.thumbnails[key]=item
                return {'status':'ready'}
            item={'status':'queued'};self.thumbnails[key]=item
            self.thumb_pool.submit(self.thumbnail_work,project,resource,path,item)
            return {'status':'queued'}
    def thumbnail_work(self,project,resource,path,item):
        item['status']='running'
        try:
            ffmpeg=shutil.which('ffmpeg')
            if not ffmpeg:raise ValueError('本机未安装FFmpeg，仍可点击预览视频')
            self.prepare(project,resource)
            for _ in range(1320):
                with self.lock:download=dict(self.downloads[(project,resource)])
                if download['status']=='failed':raise ValueError(download['error'])
                if download['status']=='ready':break
                time.sleep(.5)
            else:raise ValueError('缩略图等待下载超时，仍可手动预览')
            path.parent.mkdir(parents=True,exist_ok=True)
            temporary=path.with_suffix('.tmp.jpg')
            # Local file only, no remote/signed URLs or external media protocols.
            result=subprocess.run([ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-protocol_whitelist','file,pipe','-i',download['path'],'-map','0:v:0','-frames:v','1','-vf','scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2','-q:v','4','-threads','1','-y',str(temporary)],capture_output=True,timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode or not temporary.is_file() or temporary.stat().st_size<3:raise ValueError('无法提取缩略图，仍可点击预览或下载')
            temporary.replace(path)
            item.update(status='ready',path=str(path))
        except Exception as e:item.update(status='failed',error=str(e) if isinstance(e,ValueError) else '缩略图提取失败，仍可点击预览')
    @staticmethod
    def output_name(row,suffix):
        label=row['label'] if row['source'] in {'prompt','title','legacy-title'} else row['title']
        # source field means provenance in rows; classification field is separate below.
        if row.get('episode') is not None:label=(row.get('drama')+'-' if row.get('drama') else '')+str(row['episode'])+'-'+row['shot']
        return filename(label)+f"-候选{row['candidate']:02d}-"+row['resourceId'][:8]+suffix
    def make_zip(self,project,resources):
        if not isinstance(resources,list) or not 1<=len(resources)<=300 or len(resources)!=len(set(resources)):raise ValueError('每批选择1–300个不同产出')
        for r in resources:self.resource_row(project,r)
        with self.lock:
            if any(x['status'] in {'queued','running'} for x in self.jobs.values()):raise ValueError('已有打包任务，请等待完成')
            jobid=secrets.token_urlsafe(18);job={'id':jobid,'status':'queued','done':0,'total':len(resources)};self.jobs[jobid]=job
        self.zip_pool.submit(self.zip_work,project,resources,job)
        return {k:v for k,v in job.items() if k!='path'}
    def zip_work(self,project,resources,job):
        job['status']='running'
        try:
            for r in resources:self.prepare(project,r)
            paths=[]
            for r in resources:
                while True:
                    with self.lock:item=dict(self.downloads[(project,r)])
                    if item['status']=='failed':raise ValueError(item['error'])
                    if item['status']=='ready':break
                    time.sleep(.3)
                paths.append((item['path'],item['name']));job['done']+=1
            path=self.data/('outputs-'+job['id']+'.zip')
            with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_STORED) as archive:
                for file,name in paths:archive.write(file,name)
            job.update(status='ready',path=str(path))
        except Exception as e:job.update(status='failed',error=str(e) if isinstance(e,ValueError) else '打包失败')

class Handler(BaseHTTPRequestHandler):
    server_version='CanvasResults/1.0'
    def log_message(self,*args):pass
    @property
    def app(self):return self.server.app
    def json(self,data,status=200,headers=None):
        blob=json.dumps(data,ensure_ascii=False).encode();self.send_response(status);self.base_headers('application/json; charset=utf-8');self.send_header('Content-Length',str(len(blob)))
        for k,v in (headers or {}).items():self.send_header(k,v)
        self.end_headers();self.wfile.write(blob)
    def base_headers(self,mime):
        self.send_header('Content-Type',mime);self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Frame-Options','DENY');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self' blob:; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
    def host_ok(self):
        host=self.headers.get('Host','')
        if host not in self.server.allowed_hosts:raise PermissionError('访问地址不在允许的本机地址中')
    def ensure_session(self):
        sid=''
        try:
            cookie=SimpleCookie();cookie.load(self.headers.get('Cookie',''))
            token=cookie.get('results_session');sid=token.value if token else ''
        except Exception:sid=''
        with self.app.lock:
            s=self.app.sessions.get(sid)
            if not s or s['expires']<time.time():
                sid=secrets.token_urlsafe(32);s={'expires':time.time()+43200,'csrf':secrets.token_urlsafe(24)};self.app.sessions[sid]=s
        return sid,s
    def session(self):
        cookie=SimpleCookie()
        try:cookie.load(self.headers.get('Cookie',''))
        except Exception:raise PermissionError('请求校验失败，请刷新页面')
        token=cookie.get('results_session');sid=token.value if token else ''
        with self.app.lock:s=self.app.sessions.get(sid)
        if not s or s['expires']<time.time():raise PermissionError('请求校验失败，请刷新页面')
        return sid,s
    def body(self):
        if self.headers.get('Transfer-Encoding'):raise ValueError('不支持分块请求')
        size=int(self.headers.get('Content-Length','0'))
        if size<1 or size>65536:raise ValueError('请求长度不合法')
        value=json.loads(self.rfile.read(size))
        if not isinstance(value,dict):raise ValueError('请求应为对象')
        return value
    def do_GET(self):self.handle_request(False)
    def do_POST(self):self.handle_request(True)
    def handle_request(self,post):
        try:
            self.host_ok();u=urlsplit(self.path);q=parse_qs(u.query);path=u.path
            if post:
                origin=self.headers.get('Origin')
                if origin and origin!='http://'+self.headers.get('Host'):raise PermissionError('拒绝跨站请求')
                data=self.body()
                _,session=self.session()
                if not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),session['csrf']):raise PermissionError('请求校验失败，请刷新页面')
                if path=='/api/subjects/add':return self.json(self.app.import_subjects(data.get('projectId'),data.get('subjectIds')))
                if path=='/api/prepare':return self.json(self.app.prepare(data.get('projectId'),data.get('resourceId')))
                if path=='/api/thumbnail':return self.json(self.app.thumbnail(data.get('projectId'),data.get('resourceId')))
                if path=='/api/zip':return self.json(self.app.make_zip(data.get('projectId'),data.get('resources')))
                return self.json({'error':'不支持的操作'},404)
            if path in {'/','/app.js','/style.css'}:
                file=ROOT/'web-results'/({'/':'index.html'}.get(path,path[1:]));blob=file.read_bytes();self.send_response(200);self.base_headers(mimetypes.guess_type(file)[0]+'; charset=utf-8');self.send_header('Content-Length',str(len(blob)));self.end_headers();self.wfile.write(blob);return
            if path=='/health':return self.json({'ok':True,'service':'canvas-results','generationAllowed':False})
            if path=='/api/session':
                sid,session=self.ensure_session()
                return self.json({'csrf':session['csrf'],'mode':'canvas-results','generationAllowed':False},headers={'Set-Cookie':'results_session='+sid+'; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200'})
            if path=='/api/subject-job':
                job=self.app.jobs.get(ident(q.get('id',[''])[0]))
                if not job:return self.json({'error':'任务不存在'},404)
                return self.json(job)
            if path=='/subject-thumbnail':
                blob,mime=self.app.subject_thumbnail(q.get('id',[''])[0]);self.send_response(200);self.base_headers(mime);self.send_header('Content-Length',str(len(blob)));self.end_headers();self.wfile.write(blob);return
            if path=='/api/official-subjects':return self.json(self.app.official_subjects(q.get('search',[''])[0],q.get('refresh',[''])[0]=='1'))
            if path=='/api/canvases':return self.json(self.app.canvases())
            if path=='/api/results':
                project=ident(q.get('projectId',[''])[0])
                if 'offset' in q:
                    return self.json(self.app.scan(project,int(q['offset'][0]),q.get('type',['video'])[0]))
                with self.app.lock:cached=self.app.snapshots.get(project)
                return self.json(cached if cached and cached.get('mediaType','')==q.get('type',[''])[0] and q.get('refresh',[''])[0]!='1' else self.app.scan(project,media_type=q.get('type',[''])[0]))
            if path=='/api/download-status':
                key=(ident(q.get('projectId',[''])[0]),ident(q.get('resourceId',[''])[0]))
                with self.app.lock:item=self.app.downloads.get(key,{'status':'not-prepared'})
                return self.json({k:v for k,v in item.items() if k!='path'})
            if path in {'/api/thumbnail-status','/thumbnail'}:
                project=ident(q.get('projectId',[''])[0]);resource=ident(q.get('resourceId',[''])[0]);self.app.resource_row(project,resource)
                with self.app.lock:item=self.app.thumbnails.get((project,resource),{'status':'not-prepared'})
                if path=='/api/thumbnail-status':return self.json({k:v for k,v in item.items() if k!='path'})
                if item['status']!='ready':return self.json({'error':'缩略图尚未就绪'},409)
                return self.send_file(Path(item['path']),'thumbnail.jpg',False)
            if path=='/api/job':
                job=self.app.jobs.get(q.get('id',[''])[0])
                if not job:return self.json({'error':'任务不存在'},404)
                return self.json({k:v for k,v in job.items() if k!='path'})
            if path=='/media':
                project=ident(q.get('projectId',[''])[0]);resource=ident(q.get('resourceId',[''])[0]);self.app.resource_row(project,resource)
                item=self.app.downloads.get((project,resource))
                if not item or item['status']!='ready':return self.json({'error':'请先加载预览或准备下载'},409)
                return self.send_file(Path(item['path']),item['name'],q.get('download',[''])[0]=='1')
            if path=='/download.zip':
                job=self.app.jobs.get(q.get('id',[''])[0])
                if not job or job['status']!='ready':return self.json({'error':'打包尚未完成'},409)
                return self.send_file(Path(job['path']),'画布产出.zip',True)
            return self.json({'error':'不存在'},404)
        except PermissionError as e:self.json({'error':str(e)},401)
        except (ValueError,TypeError,KeyError) as e:self.json({'error':str(e)[:500]},400)
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception:self.json({'error':'服务异常，请检查本机服务状态'},500)
    def send_file(self,file,name,attachment):
        size=file.stat().st_size;start,end=0,size-1;status=200
        range_header=self.headers.get('Range')
        if range_header:
            m=re.fullmatch(r'bytes=(\d*)-(\d*)',range_header)
            if not m or not any(m.groups()):self.send_error(416);return
            if m[1]:start=int(m[1]);end=min(int(m[2]),end) if m[2] else end
            else:start=max(0,size-int(m[2]))
            if start>end or start>=size:self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers();return
            status=206
        self.send_response(status);self.base_headers(mimetypes.guess_type(file)[0] or 'application/octet-stream');self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1))
        if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        if attachment:self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(name))
        self.end_headers()
        with file.open('rb') as stream:
            stream.seek(start);left=end-start+1
            while left:
                chunk=stream.read(min(256*1024,left))
                if not chunk:break
                self.wfile.write(chunk);left-=len(chunk)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--host',default='0.0.0.0');parser.add_argument('--port',type=int,default=8769);parser.add_argument('--cli',default=os.environ.get('DREAMINA_CANVAS_CLI') or str(Path.home()/'bin/dreamina-canvas.exe'));parser.add_argument('--data-dir',default=str(ROOT/'.data/canvas-results'));args=parser.parse_args()
    app=App(args.cli,args.data_dir);server=ThreadingHTTPServer((args.host,args.port),Handler);server.daemon_threads=True;server.app=app
    ips={'127.0.0.1','localhost',*socket.gethostbyname_ex(socket.gethostname())[2]}
    if args.host not in {'0.0.0.0','::'}:ips.add(args.host)
    server.allowed_hosts={f'{ip}:{args.port}' for ip in ips}
    print(f'Canvas results ready: http://127.0.0.1:{args.port}/',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();app.pool.shutdown(wait=False);app.zip_pool.shutdown(wait=False);app.thumb_pool.shutdown(wait=False)
if __name__=='__main__':main()



