"""Download selected countries of RDD2022 from the official figshare record.

The record is one 13 GB archive holding a separate zip per country. This script
reads only the parts it needs (HTTP range requests), so a single country can be
fetched without downloading everything. Run from the repository root:

    python -m model.training.fetch_rdd2022 --list
    python -m model.training.fetch_rdd2022 --sources Czech

RDD2022 is published under CC BY 4.0 (doi:10.6084/m9.figshare.21431547). Cite it when you use it.
"""
import argparse
import io
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ARCHIVE_URL = "https://ndownloader.figshare.com/files/38030910"
CHUNK = 8 * 1024 * 1024


class RemoteFile(io.RawIOBase):
    """A read-only, seekable view of a file served over HTTP with range support."""

    def __init__(self, url: str):
        self.source_url, self.position = url, 0
        response = self._resolve()
        if response.headers.get("Accept-Ranges") != "bytes":
            raise OSError("The server does not support partial downloads; download the full archive manually instead.")
        self.size = int(response.headers["Content-Length"])

    def _resolve(self):
        """Follow the redirect to the storage link. That link is short-lived, so this is repeated when it expires."""
        response = urllib.request.urlopen(urllib.request.Request(self.source_url, method="HEAD"), timeout=60)
        self.url = response.url
        return response

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        self.position = {io.SEEK_SET: offset, io.SEEK_CUR: self.position + offset, io.SEEK_END: self.size + offset}[whence]
        return self.position

    def readinto(self, buffer) -> int:
        length = min(len(buffer), self.size - self.position)
        if length <= 0:
            return 0
        for attempt in range(4):
            request = urllib.request.Request(self.url, headers={"Range": f"bytes={self.position}-{self.position + length - 1}"})
            try:
                data = urllib.request.urlopen(request, timeout=300).read()
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt == 3:
                    raise
                time.sleep(2 * attempt)
                self._resolve()
        buffer[:len(data)] = data
        self.position += len(data)
        return len(data)


def extract_safely(archive: Path, destination: Path) -> int:
    """Extract, refusing any entry that would land outside the destination."""
    root = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if not (root / name).resolve().is_relative_to(root):
                raise OSError(f"Refusing to extract unexpected path from {archive.name}: {name}")
        bundle.extractall(root)
        return sum(1 for name in bundle.namelist() if not name.endswith("/"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sources", nargs="+", metavar="NAME", help="countries to fetch, e.g. Czech India")
    parser.add_argument("--raw", type=Path, default=Path("datasets/rdd2022/raw"), help="where the country folders are extracted")
    parser.add_argument("--list", action="store_true", help="show the available countries and their sizes, then exit")
    parser.add_argument("--keep-archives", action="store_true", help="keep each downloaded country zip after extracting it")
    args = parser.parse_args(argv)
    try:
        remote = zipfile.ZipFile(io.BufferedReader(RemoteFile(ARCHIVE_URL), buffer_size=CHUNK))
    except (OSError, urllib.error.URLError, zipfile.BadZipFile) as error:
        print(f"error: could not open the RDD2022 archive: {error}", file=sys.stderr)
        return 1
    available = {Path(info.filename).stem: info for info in remote.infolist() if info.filename.endswith(".zip")}
    if args.list or not args.sources:
        print("Countries in RDD2022 (download size):")
        for name, info in available.items():
            print(f"  {name:<18} {info.file_size / 1e6:>8.0f} MB")
        return 0 if args.list else 1
    unknown = [name for name in args.sources if name not in available]
    if unknown:
        print(f"error: unknown source(s) {unknown}. Available: {sorted(available)}", file=sys.stderr)
        return 1
    args.raw.mkdir(parents=True, exist_ok=True)
    for name in args.sources:
        info = available[name]
        if (args.raw / name / "train").is_dir():
            print(f"{name}: already present in {args.raw / name}, skipping")
            continue
        needed = info.file_size * 2.2  # the zip plus its extracted contents
        if shutil.disk_usage(args.raw).free < needed:
            print(f"error: {name} needs about {needed / 1e9:.1f} GB free in {args.raw}", file=sys.stderr)
            return 1
        archive = args.raw / f"{name}.zip.part"
        print(f"{name}: downloading {info.file_size / 1e6:.0f} MB ...", flush=True)
        try:
            with remote.open(info) as source, archive.open("wb") as target:
                done = 0
                while chunk := source.read(CHUNK):
                    target.write(chunk)
                    done += len(chunk)
                    print(f"\r  {done / info.file_size:>4.0%}", end="", flush=True)
            print()
            count = extract_safely(archive, args.raw)
        except (OSError, urllib.error.URLError, zipfile.BadZipFile) as error:
            print(f"\nerror: {name} failed: {error}. Partial download left at {archive}; delete it and retry.", file=sys.stderr)
            return 1
        if args.keep_archives:
            archive.rename(args.raw / f"{name}.zip")
        else:
            archive.unlink()
        print(f"{name}: extracted {count} files into {args.raw / name}")
    print("Next: python -m model.training.prepare_rdd2022 --help")
    return 0


if __name__ == "__main__":
    sys.exit(main())
