"""Fetch only the CSV files from the CGMacros zip on PhysioNet.

The archive is ~657 MB, almost all of it meal photos. PhysioNet serves it with
HTTP range support, so we read the zip's central directory remotely and pull
just the *.csv members (~20 MB). Stdlib only, so it runs before `uv sync`.

    python scripts/fetch_cgmacros.py [dest_dir]
"""

import io
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

URL = "https://physionet.org/files/cgmacros/1.0.0/CGMacros_dateshifted365.zip"
DEFAULT_DEST = Path(__file__).resolve().parent.parent / "data" / "raw" / "cgmacros"


class HttpRangeFile(io.RawIOBase):
    """Read-only, seekable file over HTTP byte ranges, with a small read-ahead buffer."""

    def __init__(self, url: str, block: int = 1 << 20):
        self.url, self.block, self.pos = url, block, 0
        head = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(head, timeout=60) as r:
            self.size = int(r.headers["Content-Length"])
        self._buf_start, self._buf = -1, b""

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=io.SEEK_SET):
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self.pos, io.SEEK_END: self.size}[whence]
        self.pos = base + offset
        return self.pos

    def _fetch(self, start: int, end: int) -> bytes:
        req = urllib.request.Request(self.url, headers={"Range": f"bytes={start}-{end - 1}"})
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    return r.read()
            except OSError:
                if attempt == 4:
                    raise
                time.sleep(2**attempt)
        raise RuntimeError("unreachable")

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        n = min(n, self.size - self.pos)
        if n <= 0:
            return b""
        buf_end = self._buf_start + len(self._buf)
        if not (self._buf_start <= self.pos and self.pos + n <= buf_end):
            end = min(self.size, self.pos + max(n, self.block))
            self._buf_start, self._buf = self.pos, self._fetch(self.pos, end)
        off = self.pos - self._buf_start
        data = self._buf[off : off + n]
        self.pos += len(data)
        return data

    def readinto(self, b):
        data = self.read(len(b))
        b[: len(data)] = data
        return len(data)


def main() -> None:
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DEST
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(HttpRangeFile(URL)) as zf:
        members = [m for m in zf.infolist() if m.filename.lower().endswith(".csv")]
        total = sum(m.compress_size for m in members)
        print(f"{len(members)} CSV members, {total / 1e6:.1f} MB compressed")
        for i, m in enumerate(members, 1):
            # Drop the archive's top-level folder: CGMacros/CGMacros-001/x.csv -> CGMacros-001/x.csv
            rel = Path(*Path(m.filename).parts[1:])
            out = dest / rel
            if out.exists() and out.stat().st_size == m.file_size:
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(zf.read(m))
            print(f"[{i}/{len(members)}] {rel}")
    print(f"done -> {dest}")


if __name__ == "__main__":
    main()
