import zipfile, tarfile, stat, re
from pathlib import Path, PurePosixPath
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MAX_TOTAL = 2 * 1024**3
MAX_FILE = 64 * 1024**2
MAX_IMAGES = 500

def natural_key(name):
    """Sort img2 before img10 and keep directory order stable."""
    return [int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", name)]

def zip_member_name(info):
    """Recover UTF-8 / GBK member names that the ZIP header does not flag as UTF-8."""
    name = info.filename
    if info.flag_bits & 0x800:
        return name
    try:
        raw = name.encode("cp437")
    except UnicodeEncodeError:
        return name
    for encoding in ("utf-8", "gbk", "big5", "shift_jis"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return name

def safe_name(name):
    name = name.replace("\\", "/")
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or not p.parts or ":" in p.parts[0] or "\x00" in name:
        raise ValueError("压缩包含有不安全路径")
    return p

def extract_images(archive, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    images, ignored, names = [], 0, set()
    total = 0
    def process(name, size, special, opener):
        nonlocal total, ignored
        p = safe_name(name)
        if special:
            raise ValueError("不支持包含符号链接或设备文件的压缩包")
        total += size
        if total > MAX_TOTAL:
            raise ValueError("解压后总大小不可超过 2 GB")
        if any(part.startswith(".") or part == "__MACOSX" for part in p.parts) or p.suffix.lower() not in EXTENSIONS:
            ignored += 1
            return
        if size > MAX_FILE:
            raise ValueError("单张图片不可超过 64 MB")
        if len(images) >= MAX_IMAGES:
            raise ValueError("每个任务最多支持 500 张图片")
        normalized = p.as_posix()
        if normalized in names:
            raise ValueError("压缩包含有重复文件路径")
        names.add(normalized)
        out = destination / normalized
        out.parent.mkdir(parents=True, exist_ok=True)
        with opener() as src, out.open("wb") as dst:
            written = 0
            while chunk := src.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_FILE or written > size:
                    raise ValueError("解压文件大小异常")
                dst.write(chunk)
        images.append(normalized)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            if len(z.infolist()) > 10000:
                raise ValueError("压缩包文件数量超过 10000")
            for info in z.infolist():
                name = zip_member_name(info)
                safe_name(name)
                if info.flag_bits & 1:
                    raise ValueError("请先移除压缩包密码")
                if not info.is_dir():
                    mode = info.external_attr >> 16
                    special = stat.S_ISLNK(mode) or stat.S_ISCHR(mode) or stat.S_ISBLK(mode) or stat.S_ISFIFO(mode)
                    process(name, info.file_size, special, lambda i=info: z.open(i))
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive) as z:
            for index, info in enumerate(z):
                if index >= 10000:
                    raise ValueError("压缩包文件数量超过 10000")
                safe_name(info.name)
                if info.isdir():
                    continue
                process(info.name, info.size, not info.isfile(), lambda i=info: z.extractfile(i))
    else:
        raise ValueError("请上传 ZIP、TAR 或 TAR.GZ 压缩包")
    if not images:
        raise ValueError("压缩包内没有 JPG、PNG、WebP 或 BMP 图片")
    return sorted(images, key=natural_key), ignored
