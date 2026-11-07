"""Choose a presentation policy without changing upstream model evidence."""
import numpy as np
from .geometry import pixels,plan


def _band_limits(dark,hint_start,hint_end):
    """Find long outer padding bands near the model's photo boundaries.

    A short phone home indicator may interrupt the bottom band. It is never
    treated as a second photo. Both outer bands and matching hints are required
    so a dark edge within an ordinary photograph is not enough to trigger this.
    """
    n=len(dark);tolerance=max(3,round(n*.06))
    if hint_start<n*.04 or hint_end>n*.96:return None
    edges=np.flatnonzero(np.diff(np.r_[False,dark,False]))
    runs=[(int(a),int(b)) for a,b in zip(edges[::2],edges[1::2]) if b-a>=max(12,n*.04)]
    leading=[b for a,b in runs if a<=n*.08 and abs(b-hint_start)<=tolerance]
    trailing=[a for a,b in runs if b>=n*.90 and abs(a-hint_end)<=tolerance]
    if not leading or not trailing:return None
    start=min(leading,key=lambda x:abs(x-hint_start));end=min(trailing,key=lambda x:abs(x-hint_end))
    return (start,end) if start<end else None


def screenshot_photo_box(im,hint):
    """Remove only pixel-verified black padding, not model-estimated content."""
    w,h=im.size;box=[0,0,w,h];usable=pixels(hint,im.size)
    black=np.max(np.asarray(im),axis=2)<=12
    vertical=_band_limits(black.mean(axis=1)>=.985,usable[1],usable[3])
    if vertical:box[1],box[3]=vertical
    # Check side bands on the actual photo rows, excluding top/bottom padding.
    horizontal=_band_limits(black[box[1]:box[3]].mean(axis=0)>=.985,usable[0],usable[2])
    if horizontal:box[0],box[2]=horizontal
    return box if vertical or horizontal else None


def _native(record,box,mode,reason):
    l,t,r,b=box;w,h=r-l,b-t
    return {'passed':True,'reason':reason,'code':'','mode':mode,'crop':box,'usable':box,
            'frame':[0,0,w,h],'placement':[0,0,w,h],'uniform_scale':1.,
            'photo_area_ratio':1.,'source_short_side':min(w,h),'action_preserved':True,
            'source_cutoff_parts':record.get('source_cutoff_parts',[])}


def choose_plan(record,im,frame,settings):
    if record.get('kind')=='action_training':
        if record.get('subject_mode')=='ambiguous' and record['status'] in ('accepted','needs_review'):
            return _native(record,[0,0,*im.size],'original_passthrough','主体不明确，原文件直接输出，不取景、不缩放、不调色')
        if (record['status'] in ('accepted','rejected') and record.get('geometry_confidence',0)>=.85
                and record.get('quality',{}).get('clarity',0)>=3
                and record.get('quality',{}).get('exposure',0)>=3):
            box=screenshot_photo_box(im,record['usable_bbox'])
            if box:
                l,t,r,b=box;ratio=(r-l)/(b-t);target=frame[2]/frame[3]
                coverage=min(ratio/target,target/ratio)
                protected=[record['subject_bbox'],record['action_bbox']]+[x['bbox'] for x in record['protected_boxes']]
                inside=all(l<=a<c<=r and t<=y<d<=b for a,y,c,d in (pixels(x,im.size) for x in protected))
                if coverage<settings['min_photo_area'] and inside:
                    return _native(record,box,'native_crop','过窄截图仅剔除黑色填充及底部操作条，完整照片按原像素输出')
    return plan(record,im.size,frame,settings)
