"""Read-only image helpers shared by visual evidence nodes."""
from datetime import datetime
from pathlib import Path
import cv2
from PIL import Image
from .io import sha as digest

def capture_metadata(path):
    """EXIF camera time only, never filesystem/download timestamps."""
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            nested = exif.get_ifd(34665) if 34665 in exif else {}
            raw = nested.get(36867) or exif.get(36867)
        if not isinstance(raw, str):
            return None
        timestamp = datetime.strptime(raw.strip('\x00 '), '%Y:%m:%d %H:%M:%S')
        return {'datetime_original': timestamp.isoformat(), 'independently_verified': False}
    except (ValueError, TypeError, OSError, SyntaxError):
        return None


def image_for(item, field):
    path = Path(item[field])
    if digest(path) != item[field+'_sha256']:
        raise ValueError('input_changed_during_model_read')
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError('unreadable_model_image')
    return image

