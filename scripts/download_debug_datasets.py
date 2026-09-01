from __future__ import annotations

import argparse
import io
import time
import zipfile
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

import requests
from huggingface_hub import HfApi, hf_hub_url
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "raw" / "debug10"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

COCO_IMAGE_IDS = (
    139,
    285,
    632,
    724,
    776,
    785,
    802,
    872,
    885,
    1000,
)

DIV2K_URL = "https://data.vision.ee.ethz.ch/cvl/DIV2K/DIV2K_valid_HR.zip"
DIFFUSIONDB_URL = (
    "https://huggingface.co/datasets/poloclub/diffusiondb/resolve/main/"
    "images/part-000001.zip"
)


def _request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    **kwargs: object,
) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            response = session.request(method, url, timeout=(30, 120), **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            last_error = error
            if attempt == 4:
                break
            time.sleep(2**attempt)
    raise RuntimeError(f"download failed after retries: {url}") from last_error


class HttpRangeReader(io.RawIOBase):
    """Seekable HTTP reader backed by bounded Range-request block caching."""

    def __init__(
        self,
        url: str,
        session: requests.Session,
        *,
        block_size: int = 2 * 1024 * 1024,
        cache_blocks: int = 32,
    ) -> None:
        self._session = session
        self._url = url
        self._block_size = block_size
        self._cache_blocks = cache_blocks
        self._cache: OrderedDict[int, bytes] = OrderedDict()
        self._position = 0

        response = _request_with_retry(session, "HEAD", url, allow_redirects=True)
        self._url = response.url
        length = response.headers.get("content-length")
        if length is None:
            probe = _request_with_retry(
                session,
                "GET",
                self._url,
                headers={"Range": "bytes=0-0"},
                allow_redirects=True,
            )
            content_range = probe.headers.get("content-range", "")
            if "/" not in content_range:
                raise RuntimeError(f"server did not report remote file size: {url}")
            length = content_range.rsplit("/", 1)[1]
        self._size = int(length)

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            position = offset
        elif whence == io.SEEK_CUR:
            position = self._position + offset
        elif whence == io.SEEK_END:
            position = self._size + offset
        else:
            raise ValueError(f"unsupported whence: {whence}")
        if position < 0:
            raise ValueError("negative seek position")
        self._position = min(position, self._size)
        return self._position

    def _fetch_block(self, block_index: int) -> bytes:
        cached = self._cache.get(block_index)
        if cached is not None:
            self._cache.move_to_end(block_index)
            return cached
        start = block_index * self._block_size
        end = min(start + self._block_size, self._size) - 1
        response = _request_with_retry(
            self._session,
            "GET",
            self._url,
            headers={"Range": f"bytes={start}-{end}"},
            allow_redirects=True,
        )
        if response.status_code != 206:
            raise RuntimeError(
                f"server ignored Range request ({response.status_code}): {self._url}"
            )
        data = response.content
        expected = end - start + 1
        if len(data) != expected:
            raise RuntimeError(f"short Range response: expected {expected}, got {len(data)}")
        self._cache[block_index] = data
        self._cache.move_to_end(block_index)
        while len(self._cache) > self._cache_blocks:
            self._cache.popitem(last=False)
        return data

    def read(self, size: int = -1) -> bytes:
        if self._position >= self._size:
            return b""
        remaining = (
            self._size - self._position
            if size < 0
            else min(size, self._size - self._position)
        )
        output = bytearray()
        while remaining:
            block_index = self._position // self._block_size
            offset = self._position % self._block_size
            block = self._fetch_block(block_index)
            chunk_size = min(remaining, len(block) - offset)
            output.extend(block[offset : offset + chunk_size])
            self._position += chunk_size
            remaining -= chunk_size
        return bytes(output)


def _valid_existing_image(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except (OSError, ValueError):
        return False


def _download_file(session: requests.Session, url: str, destination: Path) -> None:
    if _valid_existing_image(destination):
        print(f"  cached: {destination.name}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    if temporary.exists():
        temporary.unlink()
    response = _request_with_retry(session, "GET", url, stream=True, allow_redirects=True)
    with temporary.open("wb") as stream:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                stream.write(chunk)
    if not _valid_existing_image(temporary):
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"downloaded file is not a valid image: {url}")
    temporary.replace(destination)
    print(f"  saved: {destination.name}")


def download_coco(session: requests.Session, output_root: Path) -> Path:
    destination = output_root / "coco2017_val"
    destination.mkdir(parents=True, exist_ok=True)
    print("[COCO 2017 val]")
    for image_id in COCO_IMAGE_IDS:
        filename = f"{image_id:012d}.jpg"
        # The official host currently presents a mismatched TLS certificate;
        # COCO's own download page also publishes this endpoint over HTTP.
        url = f"http://images.cocodataset.org/val2017/{filename}"
        _download_file(session, url, destination / filename)
    return destination


def _extract_first_images(
    session: requests.Session,
    url: str,
    destination: Path,
    *,
    count: int,
    predicate: Callable[[str], bool],
    sort_key: Callable[[str], object] | None = None,
) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    reader = HttpRangeReader(url, session)
    with zipfile.ZipFile(reader) as archive:
        members = [
            name
            for name in archive.namelist()
            if not name.endswith("/")
            and Path(name).suffix.lower() in IMAGE_EXTENSIONS
            and predicate(name)
        ]
        members.sort(key=sort_key)
        selected = members[:count]
        if len(selected) != count:
            raise RuntimeError(f"expected {count} images in archive, found {len(selected)}")
        for member in selected:
            output_path = destination / Path(member).name
            if _valid_existing_image(output_path):
                print(f"  cached: {output_path.name}")
                continue
            temporary = output_path.with_suffix(output_path.suffix + ".part")
            if temporary.exists():
                temporary.unlink()
            with archive.open(member) as source, temporary.open("wb") as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
            if not _valid_existing_image(temporary):
                temporary.unlink(missing_ok=True)
                raise RuntimeError(f"invalid image extracted from archive: {member}")
            temporary.replace(output_path)
            print(f"  saved: {output_path.name}")
    return destination


def download_div2k(session: requests.Session, output_root: Path) -> Path:
    print("[DIV2K validation HR]")
    return _extract_first_images(
        session,
        DIV2K_URL,
        output_root / "div2k_valid_hr",
        count=10,
        predicate=lambda name: Path(name).stem.isdigit(),
    )


def download_diffusiondb(session: requests.Session, output_root: Path) -> Path:
    print("[DiffusionDB 2M part-000001]")
    return _extract_first_images(
        session,
        DIFFUSIONDB_URL,
        output_root / "diffusiondb_2m",
        count=10,
        predicate=lambda name: True,
    )


def download_w_bench(session: requests.Session, output_root: Path) -> Path:
    print("[W-Bench DET_INVERSION_1K]")
    destination = output_root / "w_bench_det_inversion"
    destination.mkdir(parents=True, exist_ok=True)
    repo_id = "Shilin-LU/W-Bench"
    prefix = "DET_INVERSION_1K/image/"
    files = [
        name
        for name in HfApi().list_repo_files(repo_id, repo_type="dataset")
        if name.startswith(prefix) and Path(name).suffix.lower() in IMAGE_EXTENSIONS
    ]
    files.sort(key=lambda name: int(Path(name).stem.split("_", 1)[0]))
    for filename in files[:10]:
        url = hf_hub_url(repo_id, filename, repo_type="dataset")
        _download_file(session, url, destination / Path(filename).name)
    return destination


DOWNLOADERS = {
    "coco": download_coco,
    "div2k": download_div2k,
    "diffusiondb": download_diffusiondb,
    "w_bench": download_w_bench,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download fixed 10-image debug subsets")
    parser.add_argument(
        "--datasets",
        nargs="+",
        choices=tuple(DOWNLOADERS),
        default=tuple(DOWNLOADERS),
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    session = requests.Session()
    session.headers["User-Agent"] = "watermark-lab-course-research/0.1"
    for dataset in args.datasets:
        DOWNLOADERS[dataset](session, args.output_root.resolve())
    print(f"debug datasets ready: {args.output_root.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
