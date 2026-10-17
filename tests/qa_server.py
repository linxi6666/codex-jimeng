"""Browser end-to-end sandbox. Fake CLI only; cannot call Dreamina servers."""
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from manager import App, Handler, Store, ThreadingHTTPServer
from test_manager import FakeCLI, PROJECT


def make_png(path, color):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    rows = (b'\0' + bytes(color) * 64) * 64
    body = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 64, 64, 8, 2, 0, 0, 0))
    path.write_bytes(body + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


class BrowserFakeCLI(FakeCLI):
    def __init__(self, movie):
        super().__init__()
        self.movie = movie
        self.fail_upload_once = True  # Exercise a lost response and safe resume.
        self.resource = "63b499e5-74d3-4f20-a470-2f797ac30ddc"
        self.resources[self.resource] = {"resourceId": self.resource, "type": "video", "status": "success"}
        self.nodes['node_0123456789'] = {"nodeId": 'node_0123456789', "type": 'video',
            "title": '本地测试视频', "status": 'success', "resources": [self.resources[self.resource]],
            "generation": {"prompt": '自动测试：纯色短片，不使用用户素材', "durationSeconds": 1}}

    def call(self, args, timeout=60):
        def flag(name, default=None):
            return args[args.index(name)+1] if name in args else default
        if args == ['version']:
            return {'version': 'TEST-FAKE-CLI / 无网络'}
        if args[:2] == ['canvas', 'ls']:
            return {'items': [{'projectId': PROJECT, 'name': '测试沙箱（不会上传到即梦）',
                               'webUrl': f'https://jimeng.jianying.com/ai-tool/ai-canvas/{PROJECT}'}], 'hasMore': False}
        if args[:2] == ['node', 'find']:
            items = [n for n in self.nodes.values() if n['type'] == flag('--type')]
            if flag('--name'):
                items = [n for n in items if flag('--name') in n.get('title', '')]
            if flag('--status'):
                items = [n for n in items if n.get('status') == flag('--status')]
            offset, limit = int(flag('--offset', 0)), int(flag('--limit', 50))
            return {'items': [{k:v for k,v in n.items() if k in {'nodeId','type','title','status'}} for n in items[offset:offset+limit]],
                    'total': len(items), 'hasMore': offset+limit < len(items), 'offset': offset}
        if args[:2] == ['resource', 'download']:
            path = Path(flag('--output')) / '本地测试视频.webm'
            body = self.movie.read_bytes()
            path.write_bytes(body)
            return {'path': str(path), 'size': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
        result = super().call(args, timeout)
        if args[:2] == ['node', 'create']:
            n = self.nodes[flag('--node-id')]
            n.update(title=flag('--title'), status='success')
        return result


def main():
    with tempfile.TemporaryDirectory(prefix='dreamina-browser-qa-') as directory:
        root = Path(directory)
        fixtures = root / '素材'
        a, b = fixtures / '商品A', fixtures / '商品B'
        a.mkdir(parents=True)
        b.mkdir()
        for path, color in [(a/'主图.png', (70, 100, 160)), (a/'辅助.png', (100, 160, 90)),
                            (b/'主图.png', (180, 100, 60))]:
            make_png(path, color)
        movie = root / 'movie.webm'
        subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
            '-i', 'color=c=blue:s=160x120:d=1', '-an', '-c:v', 'libvpx-vp9', str(movie)], check=True, timeout=30)
        store = Store(root/'state')
        app = App(store, BrowserFakeCLI(movie))
        server = ThreadingHTTPServer(('127.0.0.1', 8767), Handler)
        server.daemon_threads = True
        server.app = app
        app.worker.thread.start()
        print(json.dumps({'url':'http://127.0.0.1:8767/', 'fixtures':str(fixtures),
            'files':[str(a/'主图.png'),str(a/'辅助.png'),str(b/'主图.png')],
            'mode':'FAKE_CLI_NO_NETWORK'}, ensure_ascii=False), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            app.worker.stop.set()
            app.worker.wake.set()
            app.worker.thread.join()
            server.server_close()


if __name__ == '__main__':
    main()
