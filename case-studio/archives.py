"""安全解包：拒绝路径穿越/符号链接/加密包，过滤 macOS 垃圾文件。"""
import re, stat, tarfile, zipfile
from pathlib import Path, PurePosixPath

MAX_TOTAL = 8 * 1024 ** 3
MAX_FILE = 512 * 1024 ** 2
MAX_ENTRIES = 20000
SKIP_PARTS = {"__MACOSX", ".DS_Store", "Thumbs.db", "desktop.ini"}
IGNORE_SUFFIX = (".ds_store",)

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif", ".tif", ".tiff", ".gif"}
DOC_EXT = {".pdf", ".docx", ".doc", ".xlsx", ".txt", ".md"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}


def _junk(name: str) -> bool:
    parts = PurePosixPath(name.replace("\\", "/")).parts
    if any(p in SKIP_PARTS or p.startswith("._") for p in parts):
        return True
    return name.lower().endswith(IGNORE_SUFFIX)


def _zip_name(info: zipfile.ZipInfo) -> str:
    name = info.filename
    if info.flag_bits & 0x800:
        return name
    try:
        raw = name.encode("cp437")
    except UnicodeEncodeError:
        return name
    for enc in ("utf-8", "gbk", "big5", "shift_jis"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return name


def safe_name(name: str) -> PurePosixPath:
    name = name.replace("\\", "/")
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or not p.parts or ":" in p.parts[0] or "\x00" in name:
        raise ValueError("压缩包含不安全路径")
    return p


def kind_of(name: str) -> str:
    ext = PurePosixPath(name).suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    if ext in DOC_EXT:
        return "document"
    return "other"


def extract(archive: Path, dest: Path, log=None) -> dict:
    """返回 {files: [{path, size, kind}], skipped: n, rejected: [..]}"""
    dest.mkdir(parents=True, exist_ok=True)
    out, skipped, total = [], 0, 0

    def add(name: str, size: int, special: bool, opener):
        nonlocal total, skipped
        p = safe_name(name)
        if special:
            raise ValueError("压缩包含符号链接/设备文件")
        if _junk(name):
            skipped += 1
            return
        total += size
        if total > MAX_TOTAL:
            raise ValueError("解压后总大小超过 8 GB")
        if size > MAX_FILE:
            raise ValueError(f"单文件超过 512 MB: {name}")
        if len(out) >= MAX_ENTRIES:
            raise ValueError("压缩包条目超过 20000")
        rel = p.as_posix()
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with opener() as src, target.open("wb") as dst:
            written = 0
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_FILE:
                    raise ValueError("解压文件大小异常")
                dst.write(chunk)
        out.append({"path": rel, "size": size, "kind": kind_of(rel)})

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            if len(z.infolist()) > MAX_ENTRIES:
                raise ValueError("压缩包条目超过 20000")
            for info in z.infolist():
                name = _zip_name(info)
                safe_name(name)
                if info.flag_bits & 1:
                    raise ValueError("压缩包已加密，请先解压后重传")
                if info.is_dir():
                    continue
                mode = info.external_attr >> 16
                special = (stat.S_ISLNK(mode) or stat.S_ISCHR(mode)
                           or stat.S_ISBLK(mode) or stat.S_ISFIFO(mode))
                add(name, info.file_size, special, lambda i=info: z.open(i))
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive) as t:
            for i, info in enumerate(t):
                if i >= MAX_ENTRIES:
                    raise ValueError("压缩包条目超过 20000")
                safe_name(info.name)
                if info.isdir():
                    continue
                add(info.name, info.size, not info.isfile(), lambda j=info: t.extractfile(j))
    else:
        raise ValueError("只支持 zip / tar / tar.gz；.rar 请先转换")

    if log:
        log(f"解包完成：{len(out)} 个文件，跳过 {skipped} 个系统文件")
    return {"files": out, "skipped": skipped}
