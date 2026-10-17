"""Standalone local official-video catalogue. Does not run CLI or touch queues."""
import argparse
from pathlib import Path
from urllib.parse import urlsplit

from manager import App, Handler, StateLock, Store, ThreadingHTTPServer


class AssetHandler(Handler):
    # Observed public playback hosts from the official rendered video elements.
    # No arbitrary media origins or backend proxy/private endpoint requests.
    media_sources = "'self' blob: https://v3-artist.vlabvod.com https://v26-artist.vlabvod.com"

    def get(self):
        path = urlsplit(self.path).path
        if path == "/api/session":
            self.authorized()
            return self.json({"csrf": self.app.csrf, "dataDirectory": str(self.app.store.root),
                              "videoAssets": True, "mode": "video-assets-only"})
        if path not in {"/", "/app.js", "/style.css", "/health", "/favicon.ico", "/api/assets", "/api/assets/export"}:
            self.authorized()
            return self.json({"error": {"message": "此服务仅管理视频资产清单；画布管理仍在原服务"}}, 404)
        return super().get()

    def post(self):
        if urlsplit(self.path).path not in {"/api/assets/import", "/api/assets/projects"}:
            raise ValueError("视频资产目录不支持上传素材、生成、下载或画布操作")
        return super().post()


def main():
    parser = argparse.ArgumentParser(description="独立视频资产目录，不自动同步官方，不修改资产")
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--data-dir", default=str(Path.home() / ".dreamina-video-assets"))
    args = parser.parse_args()
    lock = StateLock(args.data_dir)
    server = None
    try:
        store = Store(args.data_dir)
        # No CLI and no background upload worker. All remote actions are denied.
        app = App(store, None)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), AssetHandler)
        server.daemon_threads = True
        server.app = app
        print(f"视频资产目录已启动：http://127.0.0.1:{args.port}/\n仅已读取/导入的官方视频详情，不是自动全量同步。", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if server:
            server.server_close()
        lock.close()


if __name__ == "__main__":
    main()
