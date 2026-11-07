import copy, io, json, os, sys, tempfile, unittest, zipfile, stat
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

TEMP = tempfile.TemporaryDirectory()
os.environ["CASE_DATA"] = TEMP.name
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import intake, store, config, review
from studio.common import WEB_DATA, DATA, save, read, job_dir
import app


class IntakeTests(unittest.TestCase):
    def zip(self, entries):
        folder = Path(tempfile.mkdtemp(dir=TEMP.name))
        path = folder / "in.zip"
        with zipfile.ZipFile(path, "w") as z:
            for k, v in entries:
                z.writestr(k, v)
        return path, folder / "out"

    def test_traversal_rejected(self):
        for name in ("../outside", "/absolute", "x\\escape"):
            a, b = self.zip([(name, b"x")])
            with self.assertRaises(ValueError):
                intake.extract(a, b)

    def test_symlink_rejected(self):
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        a, b = self.zip([(info, b"/etc/passwd")])
        with self.assertRaises(ValueError):
            intake.extract(a, b)

    def test_stores_only_and_documents_preserved(self):
        a, b = self.zip(
            [
                ("项目/参考模板/甲店/人/p.jpg", b"x"),
                ("项目/甲店/教练-会员/a.jpg", b"photo"),
                ("项目/甲店/教练-会员/report.docx", b"doc"),
                ("项目/logo/mark.png", b"logo"),
            ]
        )
        intake.extract(a, b)
        result = intake.inventory(b, b.parent / "dataset")
        self.assertEqual(len(result["assets"]), 1)
        self.assertEqual(result["groups"][0]["coach"], "教练")
        self.assertEqual(result["groups"][0]["member"], "会员")
        self.assertTrue(
            (
                b.parent / "dataset/input/私教会员案例项目/甲店/教练-会员/report.docx"
            ).exists()
        )
        self.assertEqual(len(result["excluded"]), 1)

    def test_expansion_limit(self):
        a, b = self.zip([("large", b"x" * 100)])
        with self.assertRaises(ValueError):
            intake.extract(a, b, max_bytes=99)


def sample():
    return {
        "id": "m001",
        "store": "甲店",
        "directory": "甲店/教练-张三",
        "profile": {"name": "张三", "gender": "男", "coach": "教练"},
        "photos": [
            dict(
                asset_id="a0001",
                phase="before",
                view="front",
                confirmed=False,
                preferred=False,
                source_sha256="sha",
                label_kind="inferred",
            )
        ],
        "vs": dict(
            brand_name="UP",
            address="地址",
            nickname="张先生",
            consent_text="",
            before_text="Before",
            after_text="After",
            vs_text="VS",
            titles=dict(front="正面", side="侧面", back="背面"),
            metrics=[],
        ),
        "cover": dict(
            title="标题",
            subtitle="副标题",
            headline="成果",
            story="张先生在教练的陪伴下记录改变。",
            badge="会员案例",
            store_text="甲店",
            address="地址",
            brand_name="UP",
            crops={},
        ),
        "table": dict(
            headers=["类型", "初始", "阶段", "变化", "单位"],
            rows=[],
            table_title="成果",
            report_title="对比",
            before_label="前",
            after_label="后",
        ),
        "_engine": {
            "editors": {"a0001": {"size": [1000, 1000]}},
            "private_path": "secret",
        },
    }


class ReviewTests(unittest.TestCase):
    def setUp(self):
        store.initialize()
        self.job = store.create("test.zip", config.snapshot())
        self.jid = self.job["id"]
        self.original = store.save_review(self.jid, {"members": [sample()]}, 0)

    def update(self, changes, version=1):
        return review.update(self.jid, "m001", {"version": version, "member": changes})

    def test_identity_propagates_and_preserves_old_version(self):
        result = self.update(
            {"profile": {"name": "李四", "gender": "女", "coach": "新教练"}}
        )
        self.assertEqual(result["members"][0]["vs"]["nickname"], "李女士")
        self.assertIn("李女士", result["members"][0]["cover"]["story"])
        self.assertEqual(
            store.review(self.jid, 1)["members"][0]["profile"]["name"], "张三"
        )

    def test_optimistic_conflict(self):
        self.update({})
        with self.assertRaises(store.Conflict):
            self.update({})

    def test_photo_collection_is_bound(self):
        with self.assertRaises(ValueError):
            self.update({"photos": []})

    def test_phase_correction_retains_provenance(self):
        result = self.update(
            {
                "photos": [
                    dict(
                        asset_id="a0001",
                        phase="after",
                        view="front",
                        confirmed=True,
                        preferred=True,
                    )
                ]
            }
        )
        p = result["members"][0]["photos"][0]
        self.assertEqual(p["phase"], "after")
        self.assertEqual(p["source_sha256"], "sha")

    def test_arbitrary_table_row(self):
        table = sample()["table"]
        table["rows"] = [
            dict(
                type="肩宽",
                key="custom",
                before="40",
                after="41",
                delta="+1",
                unit="cm",
            )
        ]
        result = self.update({"table": table})
        self.assertEqual(result["members"][0]["table"]["rows"][0]["type"], "肩宽")

    def test_crop_requires_uniform_scale(self):
        c = sample()["cover"]
        c["crops"] = {"a0001": [0, 0, 0.5, 0.3]}
        with self.assertRaises(ValueError):
            self.update({"cover": c})
        c["crops"] = {"a0001": [0.1, 0.1, 0.5, 0.478]}
        self.update({"cover": c})

    def test_private_engine_never_serialized(self):
        self.assertNotIn("private_path", json.dumps(review.public(self.original)))

    def test_media_cannot_register_external_paths(self):
        with self.assertRaises(ValueError):
            store.media(self.jid, Path("/etc/passwd"))

    def test_archive_uses_frozen_identity(self):
        file = job_dir(self.jid) / "a.jpg"
        file.write_bytes(b"picture")
        mid = store.media(self.jid, file)
        v = {
            "id": "v1",
            "review_version": 1,
            "members": [
                {
                    "member_id": "m001",
                    "profile": sample()["profile"],
                    "store": "甲店",
                    "products": [{"media": mid, "name": "照片.jpg"}],
                    "review_required": ["a0001"],
                    "gaps": [],
                }
            ],
        }
        store.add_version(self.jid, v)
        self.update({"profile": dict(name="新版名字", coach="新教练", gender="女")})
        archive, _ = review.archive(self.jid, "v1")
        with zipfile.ZipFile(archive) as z:
            self.assertIn("甲店/教练-张三/照片.jpg", z.namelist())


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        store.initialize()
        cls.client = TestClient(app.app, base_url="https://studio.test")
        cls.origin = {"Origin": "https://studio.test"}

    def login(self):
        return self.client.post(
            "/api/session",
            json={"code": config.load()["access_token"]},
            headers=self.origin,
        )

    def test_auth_and_proxy_origin(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/api/jobs").status_code, 401)
        r = self.login()
        self.assertEqual(r.status_code, 200)
        self.assertIn("HttpOnly", r.headers["set-cookie"])
        self.assertIn("Secure", r.headers["set-cookie"])
        r = self.client.post(
            "/api/session", json={"code": "bad"}, headers={"Origin": app.PUBLIC_URL}
        )
        self.assertEqual(r.status_code, 401)

    def test_cross_site_rejected(self):
        self.assertEqual(
            self.client.post(
                "/api/session",
                json={"code": "bad"},
                headers={"Origin": "https://evil.test"},
            ).status_code,
            403,
        )

    def test_settings_never_echo_key(self):
        self.login()
        r = self.client.put(
            "/api/settings",
            json={
                "model": {
                    "base_url": "https://example.test/v1",
                    "model": "vision",
                    "api_key": "TEST_SECRET",
                }
            },
            headers=self.origin,
        )
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("TEST_SECRET", r.text)
        self.assertNotIn("access_token", self.client.get("/api/settings").text)

    def test_upload_queue_not_http_inference(self):
        self.login()
        with patch("studio.workflow.enqueue") as enqueue:
            r = self.client.post(
                "/api/jobs",
                files={"file": ("batch.zip", b"zip", "application/zip")},
                headers=self.origin,
            )
        self.assertEqual(r.status_code, 200)
        enqueue.assert_called_once()


class ShutdownTests(unittest.TestCase):
    def test_all_same_job_processes_stop_and_no_new_child_starts(self):
        import queue, threading, time
        from studio import workflow

        errors = []
        root = Path(tempfile.mkdtemp(dir=TEMP.name))

        def run(i):
            try:
                workflow.command(
                    "same-job",
                    [sys.executable, "-c", "import time; time.sleep(60)"],
                    root / f"{i}.log",
                )
            except RuntimeError as e:
                errors.append(e)

        with patch.object(workflow, "QUEUE", queue.Queue()), patch.object(
            workflow, "WORKER", None
        ):
            threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
            try:
                for thread in threads:
                    thread.start()
                deadline = time.monotonic() + 5
                while len(workflow.PROCESSES) < 2 and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(len(workflow.PROCESSES), 2)
                workflow.stop()
                for thread in threads:
                    thread.join(timeout=5)
                self.assertFalse(any(t.is_alive() for t in threads))
                self.assertEqual(len(errors), 2)
                self.assertFalse(workflow.PROCESSES)
                with self.assertRaises(RuntimeError):
                    workflow.command(
                        "new-job", [sys.executable, "-c", "pass"], root / "new.log"
                    )
            finally:
                workflow.STOPPING.clear()


class ReportBridgeTests(unittest.TestCase):
    def test_original_first_data_is_shared_without_retranscription(self):
        from studio.report_bridge import build

        root = Path(tempfile.mkdtemp(dir=TEMP.name))
        tables = root / "tables"
        tables.mkdir()
        row = dict(
            type="体脂率",
            key="fat_percent",
            before="30",
            after="25",
            delta="wrong display text",
            unit="%",
        )
        case = dict(
            case_id="c001",
            store="甲店",
            member="目录姓名",
            display_member="报告姓名",
            rows=[row],
            as_of="2026-11-07",
            source_policy="original_measurements_first_summary_fills_gaps",
            pair={"before_date": "2025-01-01", "after_date": "2025-02-01"},
        )
        for name, value in [
            ("tables.json", [case]),
            ("records.json", []),
            ("bundle.json", {}),
        ]:
            save(tables / name, value)
        build(tables, root / "reports")
        report = read(root / "reports/reports.json")[0]
        self.assertEqual(report["metrics"]["fat"]["computed_delta"], [-5])
        self.assertEqual(report["stated_days"], 31)
        self.assertEqual(report["member"], "目录姓名")
        self.assertEqual(report["printed_member"], "报告姓名")
        case["pair"]["after_date"] = "20266-01-01"
        save(tables / "tables.json", [case])
        build(tables, root / "bad-dates")
        self.assertEqual(
            read(root / "bad-dates/reports.json")[0]["date_issue"],
            "report_dates_unverified",
        )


if __name__ == "__main__":
    unittest.main()
