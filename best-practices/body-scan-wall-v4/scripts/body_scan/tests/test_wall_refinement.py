import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

import cv2
import numpy as np

from .. import wall_geometry as wall,group_scale,refinement
from ..framing import UniformConfig
from ..geometry import project
from scripts.non_grid_camera.geometry import rotation


def camera_scene(yaw=12):
    K=np.array([[1100.,0,540],[0,1100.,720],[0,0,1]])
    a=math.radians(yaw);Y=np.array([[math.cos(a),0,math.sin(a)],[0,1,0],[-math.sin(a),0,math.cos(a)]])
    R=rotation(.02,-.04)
    def photograph(points):
        rays=np.asarray(points)@Y@R.T@K.T
        return rays[:,:2]/rays[:,2:]
    horizontal=[];vertical=[]
    for height in (.9,1.3):
        p=photograph([[-1.05,height,3],[1.05,height,3]])
        horizontal.append({'segment':p.ravel().tolist(),'length':float(np.linalg.norm(p[1]-p[0]))})
    for x in (-1,1):
        p=photograph([[x,-1.1,3],[x,1.2,3]])
        vertical.append({'segment':p.ravel().tolist(),'length':float(np.linalg.norm(p[1]-p[0]))})
    return {'K':K.tolist(),'R':R.tolist()},horizontal,vertical,photograph


class WallGeometryTests(unittest.TestCase):
    def test_independent_3d_wall_recovers_both_directions_and_square_metric(self):
        calibration,h,v,photo=camera_scene()
        H,report=wall.refine(calibration,(1440,1080,3),[300,250,750,1300],h,v)
        self.assertAlmostEqual(report['yaw_deg'],12,places=7)
        self.assertLess(max(np.abs(wall.residual(h,H))),1e-7)
        self.assertLess(max(np.abs(np.abs(wall.residual(v,H))-90)),1e-7)
        points=project(photo([[0,0,3],[.5,0,3],[0,.5,3],[.5,.5,3]]),H)
        x,y=points[1]-points[0],points[2]-points[0]
        self.assertAlmostEqual(float(np.dot(x,y)),0,places=6)
        self.assertAlmostEqual(np.linalg.norm(x),np.linalg.norm(y),places=6)
        np.testing.assert_allclose(points[3],points[0]+x+y,atol=1e-7)

    def test_disagreeing_lines_and_unsupported_wall_rejected(self):
        c,h,v,_=camera_scene()
        bad=copy.deepcopy(h);bad[1]['segment'][3]+=100
        with self.assertRaises(ValueError):wall.refine(c,(1440,1080,3),[300,250,750,1300],bad,v)
        with self.assertRaisesRegex(ValueError,'support'):wall.refine(c,(1440,1080,3),[300,250,750,1300],[],v)

    def test_extreme_or_already_level_yaw_is_not_applied(self):
        for angle in (0,40):
            c,h,v,_=camera_scene(angle)
            with self.assertRaises(ValueError):wall.refine(c,(1440,1080,3),[300,250,750,1300],h,v)

    def test_short_semantic_false_positive_does_not_override_long_consensus(self):
        c,h,v,_=camera_scene()
        bad=copy.deepcopy(h[0]);bad['segment'][3]+=100;bad['length']=100
        _,report=wall.refine(c,(1440,1080,3),[300,250,750,1300],h+[bad],v)
        self.assertAlmostEqual(report['yaw_deg'],12,places=7)
        self.assertEqual(len(report['rejected_horizontal_lines']),1)

    def test_model_cannot_select_unknown_or_wrong_direction_lines(self):
        lines=[{'id':1,'direction':'horizontal'},{'id':2,'direction':'vertical'}]
        for response in ({'confidence':.9,'horizontal_ids':[99]},
                         {'confidence':.9,'horizontal_ids':[2]},
                         {'confidence':float('nan'),'horizontal_ids':[1]},
                         {'confidence':.9,'horizontal_ids':['1']}):
            self.assertEqual(wall.selected_lines(lines,response),([],[]))

    def test_hallucinated_reference_on_flat_image_has_no_measured_support(self):
        source=np.full((500,400,3),128,np.uint8)
        scene={'near_planar_wall':True,'confidence':.9,'wall_polygon':[[0,0],[1,0],[1,1],[0,1]],
               'references':[{'direction':'horizontal','kind':'wall_skirt_seam','segment':[0,.8,1,.8],'confidence':.9}]}
        self.assertEqual(wall.candidates(source,scene,np.zeros((500,400),bool)),[])
        scene['confidence']=float('inf');self.assertFalse(wall.scene_valid(scene))

    def test_wall_matching_excludes_person_pixels(self):
        scene={'near_planar_wall':True,'confidence':.9,'wall_polygon':[[0,0],[1,0],[1,1],[0,1]]}
        person=np.zeros((200,200),bool);person[40:160,80:120]=True
        mask=wall.wall_mask(np.zeros((200,200,3),np.uint8),scene,person)
        self.assertFalse(mask[person].any());self.assertTrue(mask[30,30])

    def test_relative_scale_comes_from_spread_background_matches(self):
        rng=np.random.default_rng(7)
        points=rng.uniform([20,20],[470,550],(100,2)).astype(float)
        desc=rng.random((100,128)).astype(np.float32)
        transformed=points*1.12+[15,-8]
        scale,report=group_scale.registration((points,desc),(transformed,desc),np.eye(3),np.eye(3),
                                             (600,500,3),(700,600,3),[250,300])
        self.assertAlmostEqual(scale,1.12,places=5);self.assertEqual(report['inliers'],100)
        with self.assertRaisesRegex(ValueError,'spread'):
            group_scale.registration((points*.05,desc),(transformed*.05,desc),np.eye(3),np.eye(3),
                                     (600,500,3),(700,600,3),[250,300])


def context(aid,raised=False):
    kp=np.zeros((17,3));kp[:,2]=.95
    kp[[5,6,11,12],:2]=[[40,60],[85,60],[40,140],[85,140]]
    kp[[7,8],:2]=[[30,60 if raised else 110],[100,60 if raised else 110]]
    row={'asset_id':aid,'classification':{'view':'side_right' if raised else 'front'},
         'pose':{'keypoints_source':kp.tolist(),'torso_length':80.,'selected_pairs':[[5,11],[6,12]],
                 'anchor':[62.5,60.],'hip_anchor':[62.5,140.]},
         'geometry':{'H_source_to_corrected':np.eye(3).tolist()},
         'frame':{'uniform_scale':1. if raised else 1.14,'H_corrected_to_aligned':np.eye(3).tolist()}}
    return {'row':row,'scene':{'pose':{'arms_raised':raised}},'source':np.zeros((256,128,3),np.uint8),'features':None}


class GroupScaleTests(unittest.TestCase):
    def test_requires_two_consistent_neutral_references_and_scale_outlier(self):
        members=[context('front'),context('back'),context('side',True)]
        with patch.object(group_scale,'registration',return_value=(1.,{})):
            result=group_scale.proposals(members)
            self.assertEqual(len(result),1)
            self.assertAlmostEqual(result[0][1]['scale_multiplier'],1.14)
            self.assertEqual(group_scale.proposals(members[1:]),[])
            members[-1]['row']['frame']['uniform_scale']=1.1
            self.assertEqual(group_scale.proposals(members),[])

    def test_disagreeing_background_references_do_not_force_scale(self):
        members=[context('front'),context('back'),context('side',True)]
        with patch.object(group_scale,'registration',side_effect=[(1.,{}),(1.15,{})]):
            self.assertEqual(group_scale.proposals(members),[])

    def test_neutral_anchor_is_translation_and_uniform_scale_only(self):
        row=context('side',True)['row'];row['subject_box']=[20,20,110,245]
        source=np.full((256,128,3),128,np.uint8);config=UniformConfig(128,256)
        plan={'uniform_scale':.95,'target_hip_y':130.}
        before=copy.deepcopy(row['pose']['keypoints_source'])
        with patch.object(cv2,'warpPerspective',wraps=cv2.warpPerspective) as warp:
            result=refinement.compose(source,row,np.eye(3),config,plan)
        image_calls=[c for c in warp.call_args_list if c.args[0].ndim==3]
        self.assertEqual(len(image_calls),1)
        A=np.asarray(result[4]['H_source_to_aligned'])
        np.testing.assert_allclose(A[:2,:2],np.eye(2)*.95)
        self.assertAlmostEqual(project([result[3]['hip_anchor']],A)[0,1],130.)
        self.assertEqual(row['pose']['keypoints_source'],before)

    def test_visual_veto_preserves_existing_pixels_and_frame(self):
        target=context('side',True);row=target['row'];row['subject_box']=[20,20,110,245]
        target['source'][:]=128;row['refinement']={};config=UniformConfig(128,256)
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);(out/'side').mkdir()
            refinement.save_render(out,row,refinement.compose(target['source'],row,np.eye(3),config))
            frame=copy.deepcopy(row['frame']);before=(out/'side/aligned.png').read_bytes()
            evidence=Mock();evidence.ask.return_value=({'accept':False,'scale_improved':True,'new_severe_crop':False},{})
            refinement.apply_group_scale(out,target,{'uniform_scale':1.,'target_hip_y':130.},[target],config,evidence)
            evidence.ask.assert_called_once()
            self.assertEqual(row['refinement']['scale_status'],'retained_visual_review')
            self.assertEqual((out/'side/aligned.png').read_bytes(),before)
            self.assertEqual(row['frame'],frame)

    def test_changed_original_rejected_before_output_or_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)/'base';base.mkdir();out=Path(tmp)/'out';source=base/'source';source.write_bytes(b'changed')
            (base/'summary.json').write_text(json.dumps([{'status':'rectangular','source':str(source),'source_sha256':'wrong','asset_id':'a'}]))
            (base/'config.json').write_text(json.dumps({'version':'body-scan-unified-v2-pinhole','non_grid_transform':'pinhole'}))
            (base/'groups.json').write_text('[]')
            model=Mock()
            with self.assertRaisesRegex(ValueError,'source_changed'):refinement.run(base,out,model)
            self.assertFalse(out.exists());model.scene.assert_not_called()


if __name__=='__main__':unittest.main()
