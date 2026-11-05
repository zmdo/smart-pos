"""Estimate relative image scale from matched wall pixels, not human body widths."""
import cv2
import numpy as np

from .geometry import project
from .wall_geometry import wall_mask, local_jacobian


def features(image, scene, person):
    mask=wall_mask(image,scene,person)
    h,w=image.shape[:2]; scale=min(1.,1200/max(h,w))
    gray=cv2.resize(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),None,fx=scale,fy=scale)
    smallmask=cv2.resize(mask,(gray.shape[1],gray.shape[0]),interpolation=cv2.INTER_NEAREST)
    detector=cv2.SIFT_create(nfeatures=5000,contrastThreshold=.025)
    keys,desc=detector.detectAndCompute(gray,smallmask)
    points=np.array([k.pt for k in keys],float).reshape(-1,2)/scale
    return points,desc


def registration(a,b,Ha,Hb,shape_a,shape_b,anchor_a):
    pa,da=a;pb,db=b
    if da is None or db is None or min(len(da),len(db))<25:
        raise ValueError('wall_features_insufficient')
    matcher=cv2.BFMatcher()
    ab=matcher.knnMatch(da,db,k=2);ba=matcher.knnMatch(db,da,k=2)
    backwards={m.queryIdx:m.trainIdx for m,n in ba if m.distance<.7*n.distance}
    good=[m for m,n in ab if m.distance<.7*n.distance and backwards.get(m.trainIdx)==m.queryIdx]
    if len(good)<25:
        raise ValueError('wall_matches_insufficient')
    x=np.array([pa[m.queryIdx] for m in good]);y=np.array([pb[m.trainIdx] for m in good])
    cv2.setRNGSeed(7)
    H,inliers=cv2.findHomography(x,y,cv2.USAC_MAGSAC,3,maxIters=10000,confidence=.999)
    if H is None or inliers is None:
        raise ValueError('wall_registration_failed')
    valid=inliers[:,0]>0;x=x[valid];y=y[valid]
    if len(x)<25 or np.mean(valid)<.5:
        raise ValueError('wall_registration_inliers_insufficient')
    for points,shape in ((x,shape_a),(y,shape_b)):
        spread=np.ptp(points,axis=0)/[shape[1],shape[0]]
        if spread[0]<.25 or spread[1]<.35:
            raise ValueError('wall_matches_not_spread')
    errors=np.linalg.norm(project(x,H)-y,axis=1)
    if np.percentile(errors,90)>2.5:
        raise ValueError('wall_registration_error')
    C=np.asarray(Hb)@H@np.linalg.inv(Ha)
    J=local_jacobian(C,anchor_a);sv=np.linalg.svd(J,compute_uv=False)
    if np.linalg.det(J)<=0 or sv[0]/sv[1]>1.15 or not .6<np.sqrt(np.linalg.det(J))<1.7:
        raise ValueError('wall_registration_local_geometry')
    # Cross-check the reverse derivative at the same physical wall position.
    mapped=project([anchor_a],C)[0]
    inverse=local_jacobian(np.linalg.inv(C),mapped)
    if not np.allclose(J@inverse,np.eye(2),atol=.002):
        raise ValueError('wall_registration_inverse_inconsistent')
    return float(np.sqrt(np.linalg.det(J))), {
        'matches':len(good),'inliers':len(x),'inlier_fraction':float(np.mean(valid)),
        'median_error_px':float(np.median(errors)),'p90_error_px':float(np.percentile(errors,90)),
        'relative_scale':float(np.sqrt(np.linalg.det(J))),'local_anisotropy':float(sv[0]/sv[1]),
        'H_source_a_to_b':H.tolist(),'H_corrected_a_to_b':C.tolist()}


def raised_arms(row,scene):
    if scene.get('pose',{}).get('arms_raised') is True:
        return True
    p=np.asarray(row['pose']['keypoints_source'])
    # Use source-coordinate torso for this posture test.
    torso=np.mean([np.linalg.norm(p[s,:2]-p[h,:2]) for s,h in row['pose']['selected_pairs']])
    return any(min(p[s,2],p[e,2])>.8 and p[e,1]<p[s,1]+.2*torso for s,e in ((5,7),(6,8)))


def proposals(contexts):
    """Require at least two neutral references to corroborate a scale outlier."""
    neutral=[c for c in contexts if c['row']['classification']['view'] in ('front','back')
             and not raised_arms(c['row'],c['scene'])]
    proposals=[]
    for target in contexts:
        row=target['row']
        if not raised_arms(row,target['scene']) or len(neutral)<2:
            continue
        votes=[];proof=[]
        for ref in neutral:
            if ref is target:
                continue
            rr=ref['row']
            try:
                relative,detail=registration(ref['features'],target['features'],
                     np.array(rr['geometry']['H_source_to_corrected']),np.array(row['geometry']['H_source_to_corrected']),
                     ref['source'].shape,target['source'].shape,rr['pose']['anchor'])
                votes.append(rr['frame']['uniform_scale']/relative)
                A=np.asarray(rr['frame']['H_corrected_to_aligned'])
                detail.update({'reference_id':rr['asset_id'],'proposed_scale':votes[-1],
                               'reference_hip_y':float(project([rr['pose']['hip_anchor']],A)[0,1])})
                proof.append(detail)
            except ValueError:
                continue
        if len(votes)<2 or max(votes)/min(votes)>1.06:
            continue
        scale=float(np.median(votes));ratio=scale/row['frame']['uniform_scale']
        if not 1.08<ratio<1.22:
            continue
        proposals.append((target,{'method':'wall-registered-neutral-scale-v1','uniform_scale':scale,
                                  'scale_multiplier':ratio,'reference_votes':proof,
                                  'target_hip_y':float(np.median([p['reference_hip_y'] for p in proof])),
                                  'anchor_policy':'hip_with_neutral_torso'}))
    return proposals
