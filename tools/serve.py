"""Local preview server with gzip + cache headers.

`python -m http.server` sends the ~100 MB of JSON shards behind the search
page uncompressed and without caching, which makes local browsing sluggish.
This server compresses text assets on the fly (threaded) and sends cache
headers so repeat navigations come straight from the browser cache.

Usage:
    python tools/serve.py            # port 8761, serves the repo root
    python tools/serve.py 9000
"""

import gzip
import io
import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GZIP_SUFFIXES = (".json", ".html", ".css", ".js", ".svg", ".txt", ".map")


class GzipHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def send_head(self):
        path = self.translate_path(self.path)
        if (os.path.isdir(path) or not os.path.isfile(path)
                or not path.endswith(GZIP_SUFFIXES)):
            return super().send_head()
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError:
            return super().send_head()
        payload = gzip.compress(raw, 6)
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "public, max-age=600")
        self.end_headers()
        return io.BytesIO(payload)

    def log_message(self, fmt, *args):
        sys.stderr.write("[serve] %s\n" % (fmt % args))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8761
    server = ThreadingHTTPServer(("", port), partial(GzipHandler, directory=ROOT))
    print(f"Serving {ROOT} at http://localhost:{port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
