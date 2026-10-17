import http.client, http.cookiejar, json, tempfile, threading, unittest, urllib.request, urllib.error, zipfile
from pathlib import Path
from unittest.mock import patch
import canvas_results as appmod

P='11111111-1111-4111-8111-111111111111';R='22222222-2222-4222-8222-222222222222'
class CoreTests(unittest.TestCase):
    def test_header_and_sort(self):
        a=appmod.parse_header('浪子回头-86-1-10\n正文','旧标题')
        self.assertEqual((a['drama'],a['episode'],a['shot']),('浪子回头',86,'1-10'))
        self.assertEqual(appmod.parse_header('这是正文。\n浪子回头-86-1-01','素材')['episode'],None)
        self.assertEqual(appmod.parse_header('','26-1-C｜镜头')['shot'],'1-C')
        self.assertLess(appmod.natural('1-2'),appmod.natural('1-10'))
        self.assertEqual(appmod.filename('../../x<>'),'_.._x__')
    def test_scan_all_candidates_and_drafts(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=appmod.App('fake',tmp)
            node={'nodeId':'node_0123456789','type':'video','title':'节点','status':'success','resources':[{'resourceId':R,'type':'video','status':'success','createdAt':2},{'resourceId':P,'type':'video','status':'success','createdAt':1}],'generation':{'prompt':'剧名-86-1-02\n正文'}}
            def call(args,timeout=90):
                if args[:2]==['node','find']:return {'items':[{'nodeId':node['nodeId']}],'draftVersion':1,'hasMore':False}
                return {'nodes':[{'node':node}],'draftVersion':1}
            app.call=call
            got=app.scan(P);self.assertEqual(got['outputCount'],2);self.assertEqual(len(got['items']),2);self.assertEqual(got['items'][0]['candidate'],2)
            with self.assertRaises(ValueError):app.resource_row(P,'33333333-3333-4333-8333-333333333333')
            app.pool.shutdown();app.zip_pool.shutdown()
    def test_pagination_limit_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=appmod.App('fake',tmp)
            app.call=lambda args,timeout=90: {'items':[{'nodeId':'node_0123456789'}]*50,'hasMore':True} if args[0]=='node' and args[1]=='find' else {'nodes':[]}
            got=app.scan(P);self.assertFalse(got['complete']);self.assertTrue(got['warnings']);app.pool.shutdown();app.zip_pool.shutdown()
    def test_generation_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=appmod.App('fake',tmp)
            with self.assertRaises(ValueError):app.call(['node','run'])
            app.pool.shutdown();app.zip_pool.shutdown()

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=appmod.App('fake',self.tmp.name)
        self.server=appmod.ThreadingHTTPServer(('127.0.0.1',0),appmod.Handler);self.server.app=self.app;self.port=self.server.server_port;self.server.allowed_hosts={f'127.0.0.1:{self.port}'}
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.cookie='';self.csrf=''
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.app.pool.shutdown();self.app.zip_pool.shutdown();self.app.thumb_pool.shutdown();self.tmp.cleanup()
    def request(self,path,body=None,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.port)
        h={'Cookie':self.cookie,'X-CSRF-Token':self.csrf};h.update(headers or {})
        data=json.dumps(body).encode() if body is not None else None
        if data:h['Content-Type']='application/json'
        conn.request('POST' if body is not None else 'GET',path,data,h);r=conn.getresponse();blob=r.read();out=(r.status,dict(r.headers),blob);conn.close();return out
    def login(self):
        status,headers,_=self.request('/api/login',{'code':self.app.code});self.assertEqual(status,200);self.cookie=headers['Set-Cookie'].split(';')[0]
        status,_,data=self.request('/api/session');self.csrf=json.loads(data)['csrf'];self.assertEqual(status,200)
    def test_auth_csrf_static(self):
        self.assertEqual(self.request('/api/session')[0],401)
        self.assertEqual(self.request('/api/login',{'code':'bad'})[0],401)
        self.assertEqual(self.request('/')[0],200)
        self.assertEqual(self.request('/api/session',headers={'Host':'evil.example'})[0],401)
        self.login();csrf=self.csrf;self.csrf='wrong';self.assertEqual(self.request('/api/zip',{})[0],401);self.csrf=csrf
        self.assertEqual(self.request('/api/logout',{},headers={'Origin':'http://evil.example'})[0],401)
        self.assertEqual(self.request('/api/node/run',{})[0],404)
    def test_range_and_download(self):
        self.login();path=Path(self.tmp.name)/'sample.mp4';path.write_bytes(b'0123456789')
        self.app.snapshots[P]={'items':[{'resourceId':R,'downloadable':True}]}
        self.app.downloads[(P,R)]={'status':'ready','path':str(path),'name':'剧名-86-1-01.mp4'}
        url=f'/media?projectId={P}&resourceId={R}'
        s,h,b=self.request(url,headers={'Range':'bytes=2-5'});self.assertEqual((s,b),(206,b'2345'));self.assertEqual(h['Content-Range'],'bytes 2-5/10')
        self.assertEqual(self.request(url,headers={'Range':'bytes=100-'})[0],416)
        s,h,b=self.request(url+'&download=1');self.assertEqual(s,200);self.assertIn('attachment',h['Content-Disposition'])
        self.assertEqual(self.request('/media?projectId=../../&resourceId=bad')[0],400)
    def test_prepare_and_zip(self):
        self.login();self.app.snapshots[P]={'items':[{'resourceId':R,'downloadable':True,'title':'草稿','label':'剧名-86-1-01','source':'prompt','episode':86,'drama':'剧名','shot':'1-01','candidate':1}]}
        def fake(args,timeout=90):
            folder=Path(args[-1]);(folder/'output.mp4').write_bytes(b'fake video');return {}
        self.app.call=fake
        status,_,b=self.request('/api/zip',{'projectId':P,'resources':[R]});self.assertEqual(status,200);job=json.loads(b)
        import time
        for _ in range(50):
            if self.app.jobs[job['id']]['status'] in {'ready','failed'}:break
            time.sleep(.05)
        self.assertEqual(self.app.jobs[job['id']]['status'],'ready')
        status,_,data=self.request('/download.zip?id='+job['id']);self.assertEqual(status,200)
        import io
        with zipfile.ZipFile(io.BytesIO(data)) as z:self.assertEqual(len(z.namelist()),1);self.assertIn('剧名-86-1-01',z.namelist()[0])

if __name__=='__main__':unittest.main()

