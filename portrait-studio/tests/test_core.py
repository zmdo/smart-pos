import io, json, zipfile, tarfile
from pathlib import Path
from unittest.mock import Mock
import pytest
from PIL import Image
from archives import extract_images
from imaging import render_person,make_sheets,validate_box
OPTIONS={"width":128,"height":192,"padding":10,"gap":8,"mask_enabled":True,"mask_scale":1.2,"background":"#ffffff","confidence":.35}
def png():
    b=io.BytesIO();Image.new("RGB",(24,24),"red").save(b,format="PNG");return b.getvalue()
def test_nested_archive_only_images(tmp_path):
    p=tmp_path/"test.zip"
    with zipfile.ZipFile(p,"w") as z:
        z.writestr("人物/前.PNG",png());z.writestr("人物/readme.txt","ignored");z.writestr("__MACOSX/._a.png","junk")
    paths,ignored=extract_images(p,tmp_path/"out")
    assert paths==["人物/前.PNG"] and ignored==2
@pytest.mark.parametrize("name",["../escape.png","/tmp/escape.png","x/../../escape.png","C:/escape.png","x\\..\\..\\escape.png"])
def test_path_traversal(tmp_path,name):
    p=tmp_path/"test.zip"
    with zipfile.ZipFile(p,"w") as z:z.writestr(name,png())
    with pytest.raises(ValueError):extract_images(p,tmp_path/"out")
def test_symlink_rejected(tmp_path):
    p=tmp_path/"test.zip";i=zipfile.ZipInfo("link.png");i.create_system=3;i.external_attr=0o120777<<16
    with zipfile.ZipFile(p,"w") as z:z.writestr(i,"/etc/passwd")
    with pytest.raises(ValueError):extract_images(p,tmp_path/"out")
def test_tar_regular_nested(tmp_path):
    p=tmp_path/"test.tar.gz";content=png()
    with tarfile.open(p,"w:gz") as t:
        i=tarfile.TarInfo("person/photo.png");i.size=len(content);t.addfile(i,io.BytesIO(content))
    assert extract_images(p,tmp_path/"out")[0]==["person/photo.png"]
def test_duplicate_rejected(tmp_path):
    p=tmp_path/"test.zip"
    with zipfile.ZipFile(p,"w") as z:z.writestr("x.png",png());z.writestr("x.png",png())
    with pytest.raises(ValueError):extract_images(p,tmp_path/"out")
def test_centering_and_size():
    im=Image.new("RGB",(1000,1000),"white")
    output,t=render_person(im,[100,200,300,800],None,OPTIONS)
    assert output.size==(128,192)
    x,y=t["source_origin"];s=t["scale"]
    assert abs((200-x)*s-64)<1e-7 and abs((500-y)*s-96)<1e-7
def test_transparent_sticker_still_covers_face():
    im=Image.new("RGB",(100,200),"red")
    output,t=render_person(im,[0,0,100,200],[25,10,75,60],OPTIONS,Image.new("RGBA",(30,30),(0,0,0,0)))
    a,b,c,d=t["face_bbox_output"]
    assert output.getpixel(((a+c)//2,(b+d)//2))!=(255,0,0)


SQUARE={"width":200,"height":200,"padding":0,"gap":0,"mask_enabled":True,"mask_scale":1.5,"background":"#000000","confidence":.35}
def _red_pixels(output):
    return [(x,y) for y in range(output.height) for x in range(output.width) if output.getpixel((x,y))==(255,0,0)]
def test_sticker_keeps_original_pixels_by_default():
    im=Image.new("RGB",(100,100),"black")
    sticker=Image.new("RGBA",(20,20),(255,0,0,255))
    output,t=render_person(im,[0,0,100,100],[30,30,70,70],SQUARE,sticker)
    assert t["mask_mode"]=="native"
    pixels=_red_pixels(output)
    assert len(pixels)==400                      # 20x20, untouched by the face size
    xs=[p[0] for p in pixels];ys=[p[1] for p in pixels]
    assert abs((min(xs)+max(xs)+1)/2-100)<1      # centred on the face box centre
    assert abs((min(ys)+max(ys)+1)/2-100)<1
def test_scaled_sticker_follows_the_face_box():
    im=Image.new("RGB",(100,100),"black")
    sticker=Image.new("RGBA",(20,20),(255,0,0,255))
    options=dict(SQUARE,mask_scaled=True)
    output,t=render_person(im,[0,0,100,100],[30,30,70,70],options,sticker)
    assert t["mask_mode"]=="scaled"
    assert len(_red_pixels(output))>14000        # 40px face * 2 scale * 1.5 ratio = 120px square
def test_missing_directions_and_order(tmp_path):
    records=[]
    for i,(d,color) in enumerate([("right","yellow"),("front","red"),("left","blue")]):
        name=f"{i}.png";Image.new("RGB",(128,192),color).save(tmp_path/name)
        records.append({"status":"done","directory":"person","orientation":d,"output":name})
    sheets=make_sheets(records,tmp_path,OPTIONS);assert len(sheets)==1
    with Image.open(tmp_path/sheets[0]["file"]) as s:
        assert s.size==(128*4+24,192)
        assert s.getpixel((50,50))==(255,0,0)
        assert s.getpixel((136+50,50))==(255,255,255)
        assert s.getpixel((272+50,50))==(0,0,255)
        assert s.getpixel((408+50,50))==(255,255,0)
    assert sheets[0]["missing"]==[{"row":0,"direction":"back"}]
@pytest.mark.parametrize("box",[[float("nan"),0,100,100],[10,10,5,5],None])
def test_invalid_boxes(box):
    with pytest.raises(ValueError):validate_box(box,100,100)
def fake_job(tmp_path,monkeypatch,direction):
    import engine
    job_id="f"*24;root=tmp_path/"jobs"/job_id;root.mkdir(parents=True)
    with zipfile.ZipFile(root/"upload","w") as z:z.writestr("person/a.png",png())
    monkeypatch.setattr(engine,"DATA",tmp_path)
    monkeypatch.setattr(engine,"load",lambda:{"model":"test"})
    engine.write_job({"id":job_id,"status":"queued","options":OPTIONS,"records":[]})
    def detect(im,c,mask):
        Image.new("L",(24,24),255).save(mask)
        return {"bbox":[0,0,24,24],"confidence":.9},[],{"mask":None}
    monkeypatch.setattr(engine,"detect",detect)
    monkeypatch.setattr(engine,"detect_face",lambda *a:None)
    monkeypatch.setattr(engine,"segment_face",lambda *args:None)
    monkeypatch.setattr(engine,"orientation",lambda *args:(direction,.99,"test"))
    return engine,job_id
def test_back_never_calls_face_model(tmp_path,monkeypatch):
    engine,job_id=fake_job(tmp_path,monkeypatch,"back")
    spy=Mock(side_effect=AssertionError("face model should not run"))
    monkeypatch.setattr(engine,"locate_face",spy);engine.process_job(job_id)
    j=engine.read_job(job_id);assert j["status"]=="completed"
    assert j["records"][0]["face_bbox"] is None
    assert j["records"][0]["face_detection"]=="skipped_back"
    spy.assert_not_called()
def test_no_person_skips_all_api_calls(tmp_path,monkeypatch):
    engine,job_id=fake_job(tmp_path,monkeypatch,"front")
    monkeypatch.setattr(engine,"detect",lambda *a:(None,[],None))
    spy=Mock(side_effect=AssertionError("vision should not run"))
    monkeypatch.setattr(engine,"orientation",spy);engine.process_job(job_id)
    assert engine.read_job(job_id)["status"]=="empty"
    spy.assert_not_called()
def test_front_missing_face_not_exported(tmp_path,monkeypatch):
    engine,job_id=fake_job(tmp_path,monkeypatch,"front")
    monkeypatch.setattr(engine,"locate_face",lambda *a:None);engine.process_job(job_id)
    j=engine.read_job(job_id);assert j["records"][0]["status"]=="review" and j["sheets"]==[]
def test_auth_and_settings_do_not_leak_key():
    from fastapi.testclient import TestClient
    from app import app, AUTH_SECRET
    with TestClient(app) as c:
        assert c.get("/api/settings").status_code==401
        assert c.post("/api/login",json={"code":AUTH_SECRET}).status_code==200
        payload=c.get("/api/settings").json()
        assert "api_key" not in payload and "access_code" not in payload
        assert c.post("/api/jobs",files={"archive":("a.zip",b"x")},data={"options":'{"width":99999}'}).status_code==422


def test_gbk_zip_member_names_recovered():
    from archives import zip_member_name
    class Info:
        flag_bits=0
    legacy=Info();legacy.filename="人物/正面.png".encode("gbk").decode("cp437")
    assert zip_member_name(legacy)=="人物/正面.png"
    modern=Info();modern.filename="人物/正面.png";modern.flag_bits=0x800
    assert zip_member_name(modern)=="人物/正面.png"


def test_natural_file_order():
    from archives import natural_key
    names=["组A/img10.jpg","组A/img2.jpg","组A/img1.jpg"]
    assert sorted(names,key=natural_key)==["组A/img1.jpg","组A/img2.jpg","组A/img10.jpg"]


def test_sam2_face_box_is_used_for_masking(tmp_path,monkeypatch):
    engine,job_id=fake_job(tmp_path,monkeypatch,"front")
    monkeypatch.setattr(engine,"locate_face",lambda *a:[5,5,15,15])
    prompts={}
    def refine(context,box,path):
        prompts["box"]=box
        Image.new("L",(24,24),255).save(path)
        return {"bbox":[6,6,16,16],"score":.93,"area_ratio":.08}
    monkeypatch.setattr(engine,"segment_face",refine)
    engine.process_job(job_id)
    record=engine.read_job(job_id)["records"][0]
    assert prompts["box"]==[5,5,15,15]
    assert record["status"]=="done"
    assert record["face_bbox_model"]==[5.0,5.0,15.0,15.0]
    assert record["face_bbox"]==[6.0,6.0,16.0,16.0]
    assert record["face_mask"]=="face-0001.png"
    assert record["face_segmentation_score"]==.93


def test_face_refinement_failure_keeps_model_box(tmp_path,monkeypatch):
    engine,job_id=fake_job(tmp_path,monkeypatch,"front")
    monkeypatch.setattr(engine,"locate_face",lambda *a:[5,5,15,15])
    def boom(*args):
        raise RuntimeError("cuda oom")
    monkeypatch.setattr(engine,"segment_face",boom)
    engine.process_job(job_id)
    record=engine.read_job(job_id)["records"][0]
    assert record["status"]=="done"
    assert record["face_bbox"]==[5.0,5.0,15.0,15.0]
    assert record["face_segmentation_error"]=="cuda oom"


def test_rejected_face_mask_notes_reason(tmp_path,monkeypatch):
    engine,job_id=fake_job(tmp_path,monkeypatch,"front")
    monkeypatch.setattr(engine,"locate_face",lambda *a:[5,5,15,15])
    monkeypatch.setattr(engine,"segment_face",lambda *a:{"rejected":"face mask size implausible"})
    engine.process_job(job_id)
    record=engine.read_job(job_id)["records"][0]
    assert record["status"]=="done"
    assert record["face_bbox"]==[5.0,5.0,15.0,15.0]
    assert record["face_segmentation_note"]=="face mask size implausible"
    assert "face_mask" not in record


def test_face_detector_runs_before_the_vision_model(tmp_path,monkeypatch):
    engine,job_id=fake_job(tmp_path,monkeypatch,"front")
    seen={}
    def detector(im,ctx,**kw):
        return {"box":[4,4,16,16],"score":.93,"landmarks":[]}
    def refine(ctx,box,path):
        seen["prompt"]=box
        Image.new("L",(24,24),255).save(path)
        return {"bbox":[5,5,17,17],"score":.9,"area_ratio":.1}
    spy=Mock(side_effect=AssertionError("vision model must not be asked when the detector fires"))
    monkeypatch.setattr(engine,"detect_face",detector)
    monkeypatch.setattr(engine,"segment_face",refine)
    monkeypatch.setattr(engine,"locate_face",spy)
    engine.process_job(job_id)
    record=engine.read_job(job_id)["records"][0]
    spy.assert_not_called()
    assert record["face_source"]=="detector"
    assert record["face_detector_score"]==.93
    # box expanded by 6% before SAM 2 is prompted
    assert seen["prompt"][0]<4 and seen["prompt"][2]>16
    assert record["status"]=="done"


def test_face_detector_miss_falls_back_to_vision(tmp_path,monkeypatch):
    engine,job_id=fake_job(tmp_path,monkeypatch,"left")
    monkeypatch.setattr(engine,"locate_face",lambda *a:[5,5,15,15])
    engine.process_job(job_id)
    record=engine.read_job(job_id)["records"][0]
    assert record["face_source"]=="vision"
    assert record["face_bbox"]==[5.0,5.0,15.0,15.0]


def test_sam2_face_box_is_clipped_to_the_detector_box(tmp_path,monkeypatch):
    engine,job_id=fake_job(tmp_path,monkeypatch,"front")
    monkeypatch.setattr(engine,"detect_face",lambda *a:{"box":[5,5,15,15],"score":.9,"landmarks":[]})
    def refine(ctx,box,path):
        # SAM 2 overshoots onto the whole head
        Image.new("L",(24,24),255).save(path)
        return {"bbox":[0,0,20,20],"score":.9,"area_ratio":.2}
    monkeypatch.setattr(engine,"segment_face",refine)
    engine.process_job(job_id)
    record=engine.read_job(job_id)["records"][0]
    x1,y1,x2,y2=record["face_bbox"]
    assert x1>0 and y1>0 and abs((x2-x1)-14.56)<0.05


def test_box_helpers():
    from engine import expand_box,clip_box
    assert expand_box([10,10,20,20],.1,100,100)==[9.0,9.0,21.0,21.0]
    assert expand_box([0,0,10,10],.5,100,100)==[0.0,0.0,15.0,15.0]
    assert clip_box([0,0,50,50],[0,0,40,40])==[0,0,40,40]
    assert clip_box([0,0,100,100],[90,90,100,100])==[0,0,100,100]


