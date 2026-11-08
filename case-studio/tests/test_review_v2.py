import copy, json, unittest, tempfile, sys
from pathlib import Path
from unittest.mock import patch
from test_studio import sample
from studio import store, config, review, copywriter, identity, workflow
from studio.common import job_dir, save


class ProcessIsolationTests(unittest.TestCase):
    def test_current_app_wins_over_old_snapshot_package(self):
        store.initialize()
        jid = store.create("process-isolation", config.snapshot())["id"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("current", "snapshot"):
                pkg = root / name / "studio"
                pkg.mkdir(parents=True)
                (pkg / "__init__.py").write_text("")
                (pkg / "probe.py").write_text(f"print({name!r})")
            log = root / "probe.log"
            with patch.object(workflow, "APP_ROOT", root / "current"), patch.object(
                workflow, "REPO", root / "snapshot"
            ):
                workflow.command(jid, [sys.executable, "-m", "studio.probe"], log)
            self.assertEqual(log.read_text().strip(), "current")


class IdentityEvidenceTests(unittest.TestCase):
    def evidence(self, field="gender", **overrides):
        raw = dict(
            value="女",
            confidence=0.96,
            basis="explicit",
            source_id="d1",
            quote="会员张三 性别：女",
            bound_to_member=True,
            conflict=False,
        )
        raw.update(overrides)
        sources = [
            dict(
                id="d1",
                name="report.docx",
                kind="document_text",
                text="会员张三 性别：女；教练：王教练",
            )
        ]
        return identity.decision(field, raw, sources, "张三", 0.9)

    def test_explicit_gender_above_threshold(self):
        self.assertEqual(self.evidence()["value"], "女")

    def test_low_confidence_preserves_candidate_without_adoption(self):
        answer = self.evidence(confidence=0.8)
        self.assertEqual(answer["candidate"], "女")
        self.assertEqual(answer["value"], "")

    def test_conflicting_or_wrong_subject_is_not_adopted(self):
        self.assertEqual(self.evidence(conflict=True)["value"], "")
        self.assertEqual(self.evidence(bound_to_member=False)["value"], "")

    def test_high_confidence_appearance_and_name_guess_rejected(self):
        for quote in ("名字像女性", "外貌像女性", "张三"):
            self.assertEqual(
                self.evidence(quote=quote, basis="text_inference", confidence=1)[
                    "value"
                ],
                "",
            )

    def test_fabricated_document_quote_is_rejected(self):
        self.assertEqual(self.evidence(quote="性别：男", value="男")["value"], "")

    def test_textual_member_reference_supported(self):
        source = [
            dict(
                id="d1",
                name="notes.txt",
                kind="document_text",
                text="张三坚持训练，她完成了这次记录。",
            )
        ]
        raw = dict(
            value="女",
            confidence=0.91,
            basis="text_inference",
            source_id="d1",
            quote=source[0]["text"],
            bound_to_member=True,
        )
        self.assertEqual(
            identity.decision("gender", raw, source, "张三", 0.9)["value"], "女"
        )

    def test_coach_requires_explicit_role_and_quote(self):
        self.assertEqual(
            self.evidence("coach", value="王教练", quote="教练：王教练")["value"],
            "王教练",
        )
        self.assertEqual(
            self.evidence("coach", value="张三", quote="会员张三")["value"], ""
        )


class ReviewV2Tests(unittest.TestCase):
    def setUp(self):
        store.initialize()
        self.job = store.create("review-v2-test", config.snapshot())
        self.jid = self.job["id"]
        m = sample()
        m["directory"] = "甲店/张三"
        m["gaps"] = []
        m["_engine"]["initial_profile"] = copy.deepcopy(m["profile"])
        self.review = store.save_review(self.jid, {"members": [m]}, 0)
        self.member = m

    def test_fingerprints_isolate_sections_and_photo_selection(self):
        original = {
            s: review.preview_key(self.member, s) for s in ("vs", "cover", "table")
        }
        changed = copy.deepcopy(self.member)
        changed["cover"]["title"] = "新标题"
        self.assertEqual(review.preview_key(changed, "vs"), original["vs"])
        self.assertEqual(review.preview_key(changed, "table"), original["table"])
        self.assertNotEqual(review.preview_key(changed, "cover"), original["cover"])
        changed = copy.deepcopy(self.member)
        changed["photos"][0]["phase"] = "after"
        self.assertNotEqual(review.preview_key(changed, "vs"), original["vs"])
        self.assertNotEqual(review.preview_key(changed, "cover"), original["cover"])
        self.assertEqual(review.preview_key(changed, "table"), original["table"])

    def test_server_cache_reuses_unrelated_review_version(self):
        def render(jid, args, log):
            dest = args[-2]
            dest.mkdir(parents=True)
            f = dest / "test.png"
            from PIL import Image
            Image.new('RGB', (10, 10), 'white').save(f)
            save(
                dest / "result.json",
                dict(products=[dict(file=str(f), kind=args[-1])], cover_sources=[]),
            )

        with patch("studio.workflow.command", side_effect=render) as command:
            first = review.preview(self.jid, "m001", 1, "vs")
            cover = copy.deepcopy(self.member["cover"])
            cover["title"] = "新标题"
            review.update(self.jid, "m001", {"version": 1, "member": {"cover": cover}})
            second = review.preview(self.jid, "m001", 2, "vs")
        self.assertEqual(command.call_count, 1)
        self.assertTrue(second["cached"])
        self.assertEqual(first["products"], second["products"])
        self.assertEqual(first["fingerprint"], second["fingerprint"])

    def test_backfill_preserves_manual_clear_and_fills_other_blank(self):
        m = copy.deepcopy(self.member)
        m["profile"].update(gender="", coach="")
        m["_engine"]["initial_profile"] = copy.deepcopy(m["profile"])
        self.jid = store.create("blank-profile", config.snapshot())["id"]
        store.save_review(self.jid, {"members": [m]}, 0)
        p = dict(m["profile"], gender="女")
        review.update(self.jid, "m001", {"version": 1, "member": {"profile": p}})
        p["gender"] = ""
        review.update(self.jid, "m001", {"version": 2, "member": {"profile": p}})
        source = {
            m["directory"]: {
                "profile": {"gender": "男", "coach": "新教练"},
                "evidence": {"gender": {}, "coach": {}},
            }
        }
        with patch("studio.identity.extract", return_value=source):
            changed = identity.backfill(self.jid)
        final = store.review(self.jid)["members"][0]
        self.assertEqual(final["profile"]["gender"], "")
        self.assertEqual(final["profile"]["coach"], "新教练")
        self.assertEqual(changed, [["m001", "coach"]])

    def test_context_injection_excludes_unselected_personal_fields(self):
        m = copy.deepcopy(self.member)
        m["table"]["rows"] = [
            dict(type="体重", before="60", after="58", delta="-2", unit="kg")
        ]
        c = copywriter.context_for(m, ["outcomes"])
        self.assertEqual(set(c), {"阶段成果"})
        self.assertNotIn("张三", json.dumps(c, ensure_ascii=False))
        self.assertNotIn("before", json.dumps(c))
        self.assertEqual(copywriter.context_for(m, []), {})

    def test_ai_only_returns_selected_fields_and_does_not_mutate_review(self):
        body = dict(version=1, fields=["title"], injections=[], prompt="简短标题")
        with patch(
            "studio.model_client.ask",
            return_value=({"title": "记录改变", "story": "不应覆盖"}, {}),
        ) as ask:
            result = copywriter.generate(self.jid, "m001", body)
        self.assertEqual(result["fields"], {"title": "记录改变"})
        self.assertEqual(
            store.review(self.jid)["members"][0]["cover"], self.member["cover"]
        )
        self.assertNotIn("张三", ask.call_args.args[1])

    def test_ai_rejects_fabricated_numbers_and_stale_version(self):
        body = dict(version=1, fields=["subtitle"], injections=[], prompt="简短")
        with patch(
            "studio.model_client.ask", return_value=({"subtitle": "坚持30天"}, {})
        ):
            with self.assertRaises(RuntimeError):
                copywriter.generate(self.jid, "m001", body)

        def concurrent(*args, **kwargs):
            review.update(self.jid, "m001", {"version": 1, "member": {}})
            return {"subtitle": "每一步都算数"}, {}

        with patch("studio.model_client.ask", side_effect=concurrent):
            with self.assertRaises(store.Conflict):
                copywriter.generate(self.jid, "m001", body)

    def test_template_crud_stores_options_without_member_context(self):
        values = dict(
            name="单元验收",
            prompt="提示词",
            fields=["title"],
            injections=["name"],
            member={"name": "不应保存"},
        )
        entry = copywriter.save_template(values)
        self.assertNotIn("member", entry)
        self.assertIn(entry, copywriter.templates()["templates"])
        updated = copywriter.save_template(dict(values, name="新版模板"), entry["id"])
        self.assertEqual(updated["name"], "新版模板")
        copywriter.delete_template(entry["id"])
        self.assertNotIn(
            entry["id"], [t["id"] for t in copywriter.templates()["templates"]]
        )

    def test_manual_gender_retains_evidence_and_flags_override(self):
        data = store.review(self.jid)
        data["members"][0]["identity"] = {
            "gender": {"status": "adopted", "confidence": 0.95}
        }
        store.save_review(self.jid, data, 1)
        p = dict(self.member["profile"], gender="女")
        answer = review.update(
            self.jid, "m001", {"version": 2, "member": {"profile": p}}
        )
        self.assertEqual(answer["members"][0]["identity"]["gender"]["status"], "manual")
        self.assertEqual(answer["members"][0]["vs"]["nickname"], "张女士")
