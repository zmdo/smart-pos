"""New ZIP intake: keep originals and accept production store folders only."""

import re, shutil, stat, zipfile
from pathlib import Path, PurePosixPath
from .common import read, save, sha

IMAGE_EXT = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".heic",
    ".heif",
}
EXCLUDED = ("参考模板", "参考模版", "生产标准", "说明文件")


def extract(archive, dest, max_bytes=12 * 1024**3, max_files=10000):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=False)
    total = 0
    seen = set()
    skipped = []
    with zipfile.ZipFile(archive) as z:
        entries = z.infolist()
        if len(entries) > max_files:
            raise ValueError("压缩包文件数量超过上限")
        for info in entries:
            name = info.filename
            if not info.flag_bits & 0x800:
                try:
                    name = name.encode("cp437").decode("gb18030")
                except (UnicodeError, LookupError):
                    pass
            p = PurePosixPath(name)
            if (
                "\\" in name
                or "\x00" in name
                or p.is_absolute()
                or ".." in p.parts
                or len(name) > 700
            ):
                raise ValueError("压缩包包含不安全路径")
            if stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
                raise ValueError("不支持符号链接或加密 ZIP")
            if any(
                x == "__MACOSX" or x.startswith("._") or x == ".DS_Store"
                for x in p.parts
            ):
                skipped.append(name)
                continue
            if not p.parts:
                continue
            if str(p) in seen:
                raise ValueError("压缩包包含重名路径")
            seen.add(str(p))
            total += info.file_size
            if (
                total > max_bytes
                or info.file_size > 512 * 1024**2
                or info.file_size / max(1, info.compress_size) > 1000
            ):
                raise ValueError("压缩包展开大小或压缩比例超限")
            target = dest.joinpath(*p.parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            count = 0
            with z.open(info) as src, target.open("xb") as out:
                while block := src.read(1024 * 1024):
                    count += len(block)
                    if count > info.file_size:
                        raise ValueError("压缩文件尺寸不一致")
                    out.write(block)
    return {"expanded_bytes": total, "skipped": skipped}


def identity(member_dir):
    name = re.sub(r"[（(].*?[）)]", "", member_dir).strip()
    parts = name.split("-", 1)
    return {
        "coach": parts[0].strip() if len(parts) > 1 else "",
        "member": parts[-1].strip() or "未命名会员",
    }


def inventory(extracted, dataset):
    extracted = Path(extracted)
    dataset = Path(dataset)
    image_root = dataset / "input/私教会员案例项目"
    image_root.mkdir(parents=True)
    sources = []
    groups = {}
    excluded = []
    used = set()
    index = 0
    for path in sorted(extracted.rglob("*")):
        if not path.is_file():
            continue
        parts = path.relative_to(extracted).parts
        if any(any(s in x for s in EXCLUDED) for x in parts):
            excluded.append(str(path.relative_to(extracted)))
            continue
        if any(x.lower() == "logo" for x in parts[:-1]):
            target = image_root / "logo" / path.name
            target.parent.mkdir(exist_ok=True)
            if not target.exists():
                shutil.copy2(path, target)
            continue
        pos = next((i for i, x in enumerate(parts[:-1]) if x.endswith("店")), None)
        if pos is None or len(parts) - pos < 3:
            excluded.append(str(path.relative_to(extracted)))
            continue
        relative = Path(*parts[pos:])
        directory = str(Path(*relative.parts[:2]))
        profile = identity(relative.parts[1])
        key = directory
        groups[key] = {"store": relative.parts[0], "directory": directory, **profile}
        target = image_root / relative
        if str(relative) in used:
            raise ValueError("多个外层目录包含相同门店会员文件，请合并后上传")
        used.add(str(relative))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        if path.suffix.lower() not in IMAGE_EXT:
            continue
        index += 1
        aid = f"a{index:04d}"
        sources.append(
            {
                "id": aid,
                "path": str(target.relative_to(dataset / "input")),
                "kind": "image",
                "status": "ok",
                "source_sha256": sha(target),
                "store": relative.parts[0],
                **profile,
                "directory": directory,
                "class": {},
            }
        )
    if not groups:
        raise ValueError("没有找到 xxx店/会员目录，请保留门店与会员的目录结构")
    job = {
        "version": "website-intake-v1",
        "assets": sources,
        "groups": list(groups.values()),
        "excluded": excluded,
    }
    save(dataset / "job.json", job)
    return job
