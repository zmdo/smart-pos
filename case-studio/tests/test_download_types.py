import io, unittest, zipfile
from fastapi.testclient import TestClient
from test_studio import sample
from studio import config, review, store
from studio.common import job_dir
import app


class DownloadTypeTests(unittest.TestCase):
    def setUp(self):
        store.initialize()
        self.jid = store.create("download-types", config.snapshot())["id"]
        members = []
        for mid, kinds in (
            ("m001", sorted(review.PRODUCT_KINDS)),
            ("m002", ["report"]),
        ):
            products = []
            for kind in kinds:
                file = job_dir(self.jid) / f"{mid}-{kind}.jpg"
                file.write_bytes(f"{mid}-{kind}".encode())
                products.append(
                    dict(
                        kind=kind, media=store.media(self.jid, file), name=kind + ".jpg"
                    )
                )
            members.append(
                dict(
                    member_id=mid,
                    profile=dict(name=mid, coach="教练", gender=""),
                    store="甲店",
                    products=products,
                    review_required=["a1"],
                    gaps=[],
                )
            )
        store.add_version(self.jid, dict(id="v1", review_version=1, members=members))

    def entries(self, path):
        with zipfile.ZipFile(path) as archive:
            self.assertIsNone(archive.testzip())
            return archive.namelist()

    def test_default_keeps_all_products_and_original_filename(self):
        path, name = review.archive(self.jid, "v1")
        names = self.entries(path)
        self.assertEqual(sum(n.endswith(".jpg") for n in names), 9)
        self.assertEqual(sum(n.endswith("审核说明.json") for n in names), 2)
        self.assertEqual(name, "会员案例成品.zip")

    def test_filter_cache_is_separate_and_does_not_create_empty_member_folders(self):
        all_path, _ = review.archive(self.jid, "v1")
        before = all_path.read_bytes()
        selected, _ = review.archive(self.jid, "v1", kinds=["vs", "cover"])
        same, _ = review.archive(self.jid, "v1", kinds=["cover", "vs", "cover"])
        self.assertEqual(selected, same)
        self.assertNotEqual(selected, all_path)
        self.assertEqual(all_path.read_bytes(), before)
        self.assertEqual(
            set(self.entries(selected)),
            {
                "甲店/教练-m001/cover.jpg",
                "甲店/教练-m001/vs.jpg",
                "甲店/教练-m001/审核说明.json",
            },
        )
        member, name = review.archive(self.jid, "v1", "m001", ["cover"])
        self.assertEqual(name, "教练-m001.zip")
        self.assertEqual(set(self.entries(member)), {"cover.jpg", "审核说明.json"})
        with zipfile.ZipFile(member) as archive:
            self.assertEqual(archive.read("cover.jpg"), b"m001-cover")
        self.assertEqual(
            len(store.version(self.jid, "v1")["members"][0]["products"]), 8
        )

    def test_invalid_empty_and_unavailable_selections_are_rejected(self):
        for kinds in ([], [""], ["../../file"], ["cover", "unknown"], "cover"):
            with self.subTest(kinds=kinds), self.assertRaises(ValueError):
                review.archive(self.jid, "v1", kinds=kinds)
        with self.assertRaisesRegex(ValueError, "没有所选类型"):
            review.archive(self.jid, "v1", "m002", ["cover"])

    def test_http_repeated_type_parameters_and_auth(self):
        with TestClient(app.app, base_url="https://studio.test") as client:
            url = f"/api/jobs/{self.jid}/download/v1"
            self.assertEqual(
                client.get(url, params=[("types", "cover")]).status_code, 401
            )
            client.post(
                "/api/session",
                json={"code": config.load()["access_token"]},
                headers={"Origin": "https://studio.test"},
            ).raise_for_status()
            response = client.get(url, params=[("types", "cover"), ("types", "report")])
            self.assertEqual(response.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                images = [n for n in archive.namelist() if n.endswith(".jpg")]
                self.assertEqual(len(images), 3)
                self.assertTrue(
                    all(n.endswith(("cover.jpg", "report.jpg")) for n in images)
                )
            self.assertEqual(client.get(url, params={"types": ""}).status_code, 400)
            self.assertEqual(
                client.get(url, params={"types": "unknown"}).status_code, 400
            )
