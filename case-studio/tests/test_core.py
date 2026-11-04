import io, os, sys, zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plan
from archives import _junk, kind_of, safe_name
from facts import parse_table, parse_text


def test_split_member_coach_member():
    r = plan.split_member("陈丽-潘艺文（缺生活照）")
    assert r["coach"] == "陈丽"
    assert r["name"] == "潘艺文"
    assert "缺生活照" in r["note"]


def test_split_member_single_name_with_latin_alias():
    r = plan.split_member("任胜男-candy")
    assert r["name"] == "任胜男-candy"
    assert r["coach"] is None


def test_split_member_plain():
    r = plan.split_member("关文博")
    assert r["name"] == "关文博" and r["coach"] is None


def test_phase_slots_two_unknown_become_pair():
    a = {"class": {"phase": "unknown"}}
    b = {"class": {"phase": "unknown"}}
    s = plan._phase_slots([a, b])
    assert s["before"] is a and s["after"] is b and s["ambiguous"]


def test_phase_slots_both_in_one_image():
    a = {"class": {"phase": "both"}}
    s = plan._phase_slots([a])
    assert s["before"] is a and s["after"] is a


def test_phase_slots_single_unknown():
    a = {"class": {"phase": "unknown"}}
    s = plan._phase_slots([a])
    assert s["before"] is a and s["after"] is None and s["ambiguous"]


def _asset(kind, view=None, phase=None, status="ok", background=None):
    return {"kind": "image", "status": status,
            "class": {"kind": kind, "view": view, "phase": phase, "background": background}}


def test_plan_missing_everything():
    m = plan.build_member("张三", "宝安店", [], None)
    assert m["produced_count"] == 0
    labels = {g["label"] for g in m["gaps"]}
    assert "会员体测三视图对比拼图" in labels
    assert "会员感言" in labels


def test_plan_full_body_scan_and_metrics():
    assets = []
    for view in ("front", "side", "back"):
        assets.append(_asset("body_scan", view, "before"))
        assets.append(_asset("body_scan", view, "after"))
    assets += [_asset("life_photo"), _asset("life_photo"), _asset("testimonial"),
               _asset("body_report"), _asset("body_report"), _asset("training_report")]
    facts = {"ok": True, "metrics": {"weight": {"delta": -10}, "fat": {"delta": -5}}}
    m = plan.build_member("张三", "宝安店", assets, facts)
    ok = {o["id"] for o in m["outputs"] if o["ok"]}
    for oid in ("F1", "F2", "F3", "S3", "B3", "O10", "O11", "O12", "O13", "O14", "O15"):
        assert oid in ok, oid


def test_plan_one_sided_front_only_single():
    assets = [_asset("body_scan", "front", "before")]
    m = plan.build_member("张三", "宝安店", assets, None)
    ok = {o["id"] for o in m["outputs"] if o["ok"]}
    assert "F1" in ok and "F3" not in ok and "O10" not in ok


def test_plan_video_only_notes_deferred():
    assets = [{"kind": "video", "status": "ok", "class": {}}]
    m = plan.build_member("张三", "宝安店", assets, None)
    assert any("视频" in g["reason"] for g in m["gaps"] if g["label"].startswith("会员训练日常"))


def test_facts_parse_sample_table():
    rows = [["类别", "初始数据（训练前）", "阶段数据（训练后）", "变化量（+/-）", "单位"],
            ["时间", "2024年5月6日", "2025年4月28日", "+358", "天"],
            ["身高", "169", "169", "0", "cm"],
            ["体重", "114", "87", "-26.4", "kg"],
            ["体脂率", "41.4%", "26.5%", "-14.9%", "%"],
            ["BMI", "35.2", "30.3", "-4.9", "无"]]
    out = parse_table(rows)
    assert out["metrics"]["weight"]["delta"] == -26.4
    assert out["metrics"]["fat"]["before"] == 41.4
    assert any("BMI" in w for w in out["warnings"])


def test_facts_parse_text_meta():
    text = "门店：UP健身私教馆（宝安店）\n教练：Blue\n姓名：曾繁治\n性别：男\n年龄：28 岁\n卡种：年卡\n训练目标： ☑ 减脂 ☑ 塑形"
    out = parse_text(text)
    assert out["store"] == "宝安"
    assert out["coach"] == "Blue"
    assert out["member"] == "曾繁治"
    assert out["age"] == 28
    assert out["goals"] == ["减脂", "塑形"]


def test_archive_rejects_traversal():
    for bad in ("../a.jpg", "/etc/passwd", "a/../../b.jpg"):
        with pytest.raises(ValueError):
            safe_name(bad)


def test_archive_junk_detection():
    assert _junk("__MACOSX/._x.jpg")
    assert _junk("a/.DS_Store")
    assert not _junk("宝安店/任胜男-candy/1.jpg")


def test_kind_of():
    assert kind_of("a/b.JPG") == "image"
    assert kind_of("a/b.mp4") == "video"
    assert kind_of("a/b.docx") == "document"
    assert kind_of("a/b.psd") == "other"


def test_side_left_preferred_over_right():
    assets = [_asset("body_scan", "side_right", "before", background="wood"),
              _asset("body_scan", "side_left", "before", background="grid_board")]
    m = plan.build_member("张三", "宝安店", assets, None)
    side = m["slots"]["side"]
    assert side["label"] == "侧视图（左侧）"
    assert side["background"]["before"] == "网格板"
    assert "S1" in {o["id"] for o in m["outputs"] if o["ok"]}


def test_side_right_used_when_left_missing():
    assets = [_asset("body_scan", "side_right", "after", background="white_wall")]
    m = plan.build_member("张三", "宝安店", assets, None)
    assert m["slots"]["side"]["label"] == "侧视图（右侧）"


def test_background_mismatch_goes_to_review():
    assets = [_asset("body_scan", "front", "before", background="grid_board"),
              _asset("body_scan", "front", "after", background="white_wall")]
    m = plan.build_member("张三", "宝安店", assets, None)
    assert any("背景不一致" in r["reason"] for r in m["review"])


def test_compute_split_uses_gap_between_two_people():
    s = plan.compute_split([[100, 100, 400, 900], [700, 100, 1000, 900]], 1100, 1000)
    assert s["method"] == "gap"
    assert 400 <= s["x"] <= 700


def test_compute_split_center_fallback_when_no_person():
    s = plan.compute_split([], 1000, 1200)
    assert s["method"] == "center" and s["x"] == 500


def test_compute_split_rejects_gap_outside_middle():
    s = plan.compute_split([[0, 0, 60, 900], [940, 0, 1000, 900]], 1000, 1000)
    assert s["method"] == "gap" and s["x"] == 500   # 500 落在 30%-70%，保留


def test_split_twins_count_as_one_photo():
    a = _asset("body_scan", "front", "before")
    b = _asset("body_scan", "front", "after")
    a["path"] = b["path"] = "x.jpg"
    a["split"] = b["split"] = {"x": 500}
    m = plan.build_member("张三", "宝安店", [a, b], None)
    assert m["counts"]["body_scan"] == 1
    assert m["slots"]["front"]["before"] and m["slots"]["front"]["after"]
    assert m["slots"]["front"]["from_split"]["before"] is True
