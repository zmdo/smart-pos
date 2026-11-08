"""Only explicitly approved render errors may cross the worker/API boundary."""
from pathlib import Path
from .common import read, save

MESSAGES = {
    'privacy_unprepared': '尚未完成头部遮挡检查。请在「会员基础信息」点击「准备头部遮挡」，完成后再更新展示效果。',
    'rear_unprepared': '背向照片尚无可靠头部位置。请在「会员基础信息」重新检查头部，完成后再更新展示效果。',
    'sticker_missing': '尚未准备本会员的头像贴纸。请在「会员基础信息」准备或选择贴纸后重试。',
    'avatar_frame_tight': '照片取景过紧，无法完整放下统一头像。请检查人物头部是否贴近边缘；封面可调整照片取景范围。',
    'cover_crop_invalid': '封面取景超出了有效图片范围，请重新调整左右照片取景框。',
    'face_projection_invalid': '取景后的头部位置无效，请重新检查头部位置和照片取景范围。',
}
KNOWN_ERRORS = {
    '面部遮挡尚未完成检查，请在会员信息顶部准备或重新检查': 'privacy_unprepared',
    '背向图尚无可靠头部位置，请在会员信息顶部重新检查头部': 'rear_unprepared',
    '请先准备或选择本会员的面部贴纸': 'sticker_missing',
    '取景框过紧，无法完整放下统一头像，请扩大取景范围': 'avatar_frame_tight',
    '取景后的面部位置无效，请调整取景框': 'face_projection_invalid',
    '取景后的面部范围无效，请调整取景框': 'face_projection_invalid',
}


class RenderInputError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(MESSAGES[code])


def error_file(out):
    return Path(str(out) + '.error.json')


def record(out, error):
    message = str(error)
    code = KNOWN_ERRORS.get(message)
    if message.startswith('封面取景不可用，请调整到有效原图范围内：'):
        code = 'cover_crop_invalid'
    if code:
        save(error_file(out), {'code': code}, True)


def read_error(out):
    code = read(error_file(out), {}).get('code')
    return RenderInputError(code) if isinstance(code, str) and code in MESSAGES else None
