"""Extract WID_data_US.csv and WID_metadata_US.csv from WID's 880MB bulk zip
using HTTP range requests, so we never download the whole archive."""
import io, urllib.request, zipfile, pathlib

URL = "https://wid.world/bulk_download/wid_all_data.zip"
OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw"


class HttpRangeFile(io.RawIOBase):
    def __init__(self, url):
        self.url, self.pos = url, 0
        req = urllib.request.Request(url, method="HEAD")
        self.size = int(urllib.request.urlopen(req).headers["Content-Length"])

    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos

    def seek(self, off, whence=0):
        self.pos = {0: off, 1: self.pos + off, 2: self.size + off}[whence]
        return self.pos

    def readinto(self, buf):
        n = len(buf)
        if n == 0 or self.pos >= self.size: return 0
        end = min(self.pos + n, self.size) - 1
        req = urllib.request.Request(self.url, headers={"Range": f"bytes={self.pos}-{end}"})
        data = urllib.request.urlopen(req).read()
        buf[:len(data)] = data
        self.pos += len(data)
        return len(data)


if __name__ == "__main__":
    zf = zipfile.ZipFile(io.BufferedReader(HttpRangeFile(URL), buffer_size=8 << 20))
    for name in ("WID_data_US.csv", "WID_metadata_US.csv"):
        info = zf.getinfo(name)
        print(f"extracting {name} ({info.file_size/1e6:.1f} MB uncompressed)")
        (OUT / name).write_bytes(zf.read(name))
