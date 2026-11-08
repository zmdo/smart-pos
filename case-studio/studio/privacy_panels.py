"""Place equal-size avatars after each photo has reached its final panel size."""

import math
from PIL import Image, ImageOps
from . import privacy, stickers
from .common import signature


def project_faces(evidence, source_size, transform, panel_size):
    """Map source face boxes through the exact resize/crop/perspective matrix."""
    width, height = source_size
    pw, ph = panel_size
    faces = []
    for index, face in enumerate(evidence["faces"]):
        l, t, r, b = [v*s/1000 for v, s in zip(face["box"], (width, height, width, height))]
        points, denominators = [], []
        for x, y in ((l,t), (r,t), (r,b), (l,b)):
            q = [row[0]*x + row[1]*y + row[2] for row in transform]
            if any(not math.isfinite(v) for v in q) or abs(q[2]) < 1e-9:
                raise ValueError("取景后的面部位置无效，请调整取景框")
            denominators.append(q[2])
            points.append((q[0]/q[2], q[1]/q[2]))
        if min(denominators)*max(denominators) <= 0:
            raise ValueError("取景后的面部位置无效，请调整取景框")
        xs, ys = zip(*points)
        box = [min(xs), min(ys), max(xs), max(ys)]
        if box[2] <= box[0] or box[3] <= box[1]:
            raise ValueError("取景后的面部范围无效，请调整取景框")
        if box[2] <= 0 or box[3] <= 0 or box[0] >= pw or box[1] >= ph:
            continue
        faces.append(dict(face, box=box, source_face=index))
    return faces


def artwork_size(avatar, box):
    l, t, r, b = box
    scale = max((r-l)/avatar.width, (b-t)/avatar.height)*privacy.STICKER_SCALE
    return max(1, math.ceil(avatar.width*scale)), max(1, math.ceil(avatar.height*scale))


def head_anchor(face, points=None):
    """Attach the avatar chin to this person's jaw, not to a shared canvas row.

    A face box excludes hair and its side-view midpoint is biased toward the
    nose. Reliable ears locate the head above the neck without moving the body.
    Points are already projected into this final photo panel.
    """
    l, t, r, b = face["box"]
    cx, method = (l+r)/2, "face_box"
    def valid(index, threshold):
        if not points or len(points) <= index or len(points[index]) != 3:
            return False
        x, y, confidence = points[index]
        return (all(math.isfinite(v) for v in (x,y,confidence)) and confidence >= threshold
                and l-.3*(r-l) <= x <= r+.3*(r-l) and t-.2*(b-t) <= y <= b)
    if face.get("front") or face["state"] == "hidden":
        for pair, threshold, label in [((3,4),.6,"bilateral_ears"), ((1,2),.7,"bilateral_eyes")]:
            if face["state"] == "hidden" and pair == (1,2):
                continue
            if all(valid(i,threshold) for i in pair):
                cx = sum(points[i][0] for i in pair)/2
                method = label
                break
    else:
        ears = [i for i in (3,4) if valid(i,.75)]
        if ears and valid(0,.6):
            ear = max(ears, key=lambda i: points[i][2])
            cx, method = points[ear][0], "visible_ear"
    return [cx, b+.04*(b-t)], method


def head_at_top_edge(face):
    """Detection tolerates a small border around an already cropped head."""
    _, top, _, bottom = face["box"]
    return top <= max(2, .1*(bottom-top))


def vertical_bounds(face, height):
    """Only a default top-clipped avatar may be dragged above the photo."""
    return min(0, face.get("default_rect", [0, 0])[1]), height-face["sticker_size"][1]


def fit_shared_size(size, subjects):
    """Fit the group avatar above each jaw without pushing a chin downward."""
    scale = fallback = 1.0
    for panel, face in subjects:
        (cx, bottom), _ = head_anchor(face, panel.get("head_points"))
        w,h = panel["image"].size
        width_limit = min(2*cx/size[0], 2*(w-cx)/size[0])
        scale = min(scale, width_limit, bottom/size[1])
        top_limit = h if head_at_top_edge(face) else bottom
        fallback = min(fallback, width_limit, top_limit/size[1])
        if not 0 < bottom <= h:
            raise ValueError("取景框过紧，无法完整放下统一头像，请扩大取景范围")
    # Keep every previously successful layout unchanged. Only a failed fit may
    # use top clipping for a head already at the edge of the photo.
    if scale < .85:
        scale = fallback
    if scale < .85:
        raise ValueError("取景框过紧，无法完整放下统一头像，请扩大取景范围")
    return tuple(max(1,math.floor(n*scale)) for n in size)


def apply_manual_layout(member, scope, panel, face):
    """Apply live review state to immutable geometry (also used by cached editors)."""
    edits = member.get('mask_edits', {}).get(scope, {}).get(panel['asset_id'], {})
    edit = edits.get('faces', {}).get(str(face['source_face']), {}) if edits.get('signature') == panel['signature'] else {}
    w, h = panel['size']
    sw, sh = face['sticker_size']
    x, y = face['default_rect'][:2]
    if edit.get('position') is not None:
        x = min(max(0, round(edit['position'][0]*w)), w-sw)
        min_y, max_y = vertical_bounds(face, h)
        y = min(max(min_y, round(edit['position'][1]*h)), max_y)
    rear_enabled = privacy.back_enabled(member, {'state': face['head_state']}, panel.get('back', False))
    face.update(sticker_rect=[x,y,x+sw,y+sh], deleted=edit.get('deleted', False),
                manual_position=edit.get('position'), back_disabled=not rear_enabled)
    return face


def mask_panels(member, panels, scope=""):
    """Panels contain image, source and a source-to-panel 3x3 transform.

    The largest face in each panel is the subject. Subject avatars share one
    final pixel size and attach separately to each head/jaw; background faces
    retain their own smaller sizing. Existing stickers are preserved; rear heads
    participate in the same sizing.
    """
    if member.get("privacy", {}).get("enabled") is False:
        return [p["image"].copy() for p in panels], {"enabled": False}
    projected, primary, identities = [], [], []
    for panel in panels:
        evidence = privacy.checked_evidence(member, panel["source"])
        with Image.open(panel["source"]) as source:
            size = ImageOps.exif_transpose(source).size
        faces = project_faces(evidence, size, panel["transform"], panel["image"].size)
        identities.append({"asset_id": panel.get("asset_id", ""), "size": list(panel["image"].size), "back": panel.get("back", False),
                           "signature": signature({"source": evidence["source_sha256"],
                                                   "faces": evidence["faces"], "transform": panel["transform"],
                                                   "size": panel["image"].size, "back": panel.get("back", False)}),
                           "faces": []})
        projected.append(faces)
        primary.append(max(range(len(faces)), key=lambda i:
                           (faces[i]["box"][2]-faces[i]["box"][0])*
                           (faces[i]["box"][3]-faces[i]["box"][1])) if faces else None)
    layout = {"renderer": privacy.RENDER_VERSION, "scope": scope,
              "shared_sticker_size": None, "panels": identities}
    if not any(privacy.needs_mask(f) for faces in projected for f in faces):
        return [p["image"].copy() for p in panels], layout
    sid = member.get("privacy", {}).get("sticker_id")
    if not sid:
        raise ValueError("请先准备或选择本会员的面部贴纸")
    with Image.open(stickers.get(sid)["path"]) as image:
        avatar = image.convert("RGBA")
        avatar = avatar.crop(avatar.getchannel("A").getbbox())
    subjects = [(panel, faces[i]) for panel, faces, i in zip(panels, projected, primary)
                if i is not None and privacy.needs_mask(faces[i])]
    sizes = [artwork_size(avatar, face["box"]) for _, face in subjects]
    shared = max(sizes) if sizes else None
    if shared:
        shared = fit_shared_size(shared, subjects)
    layout["shared_sticker_size"] = list(shared) if shared else None
    layout["alignment"] = "individual_head_and_jaw"
    outputs = []
    for panel, faces, main, identity in zip(panels, projected, primary, identities):
        image = panel["image"].convert("RGBA")
        placements = []
        for index, face in enumerate(faces):
            if not privacy.needs_mask(face):
                continue
            size = shared if index == main else artwork_size(avatar, face["box"])
            sw, sh = size
            if sw > image.width or sh > image.height:
                raise ValueError("取景框过紧，无法完整放下统一头像，请扩大取景范围")
            anchor, method = head_anchor(face, panel.get("head_points") if index == main else None)
            ax, bottom = anchor
            x = min(max(0, round(ax-sw/2)), image.width-sw)
            y = round(bottom-sh)
            if not head_at_top_edge(face):
                y = max(0, y)
            y = min(y, image.height-sh)
            default_rect = [x, y, x+sw, y+sh]
            placement = apply_manual_layout(member, scope, identity, {"source_face": face["source_face"], "shared": index == main,
                               "sticker_size": list(size), "sticker_rect": [x,y,x+sw,y+sh],
                               "default_rect": default_rect,
                               "face_box": face["box"], "head_state": face["state"], "head_anchor": anchor,
                               "anchor_method": method})
            if not placement['back_disabled'] and not placement['deleted']:
                image.alpha_composite(avatar.resize(size, Image.Resampling.LANCZOS), tuple(placement['sticker_rect'][:2]))
            placements.append(placement)
        outputs.append(image.convert("RGB"))
        identity["faces"] = placements
    return outputs, layout
