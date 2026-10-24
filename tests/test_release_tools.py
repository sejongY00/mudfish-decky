import importlib.util
import json
import os
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "scripts", f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


package = load("package")
gitea_release = load("gitea_release")


def make_tree(root, version="0.3.1"):
    files = {
        "plugin.json": json.dumps({"name": "Mudfish VPN"}),
        "package.json": json.dumps({"name": "mudfish-decky", "version": version}),
        "main.py": "print('x')",
        "README.md": "# readme",
        "dist/index.js": "js",
        "dist/index.js.map": "source map: debugging only, not shipped",
        "py_modules/mudfish_decky/__init__.py": "",
        "py_modules/mudfish_decky/nodes.py": "x = 1",
        "py_modules/mudfish_decky/__pycache__/nodes.cpython-314.pyc": "junk",
        "tests/test_x.py": "not shipped",
        "src/index.tsx": "not shipped",
    }
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)


class PackageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self.tmp.name, "src")
        os.makedirs(self.src)
        make_tree(self.src)

    def tearDown(self):
        self.tmp.cleanup()

    def test_version_from_package_json(self):
        self.assertEqual(package.read_version(self.src), "0.3.1")

    def test_zip_has_decky_layout_and_only_runtime_files(self):
        out = package.build_zip(self.src, os.path.join(self.tmp.name, "out"))
        self.assertEqual(os.path.basename(out), "mudfish-decky-0.3.1.zip")
        with zipfile.ZipFile(out) as z:
            names = sorted(z.namelist())
        self.assertEqual(names, [
            "mudfish-decky/README.md",
            "mudfish-decky/dist/index.js",
            "mudfish-decky/main.py",
            "mudfish-decky/package.json",
            "mudfish-decky/plugin.json",
            "mudfish-decky/py_modules/mudfish_decky/__init__.py",
            "mudfish-decky/py_modules/mudfish_decky/nodes.py",
        ])

    def test_missing_build_output_fails(self):
        os.remove(os.path.join(self.src, "dist", "index.js"))
        with self.assertRaises(SystemExit):
            package.build_zip(self.src, os.path.join(self.tmp.name, "out"))


class FakeApi:
    """Stands in for the Gitea REST API: (method, path) -> (status, json)."""

    def __init__(self, existing_tag=None):
        self.existing_tag = existing_tag
        self.calls = []

    def __call__(self, method, path, body=None, headers=None):
        self.calls.append((method, path, body, headers))
        if method == "GET" and path.endswith("/releases/tags/" + (self.existing_tag or "")) and self.existing_tag:
            return 200, {"id": 7, "tag_name": self.existing_tag}
        if method == "GET":
            return 404, {"message": "not found"}
        if method == "POST" and path.endswith("/releases"):
            return 201, {"id": 42, "html_url": "https://git.example/r/42"}
        if method == "POST" and "/assets" in path:
            return 201, {"id": 1, "browser_download_url": "https://git.example/a/1"}
        return 500, {}


class GiteaReleaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.zip = os.path.join(self.tmp.name, "mudfish-decky-0.3.1.zip")
        with open(self.zip, "wb") as f:
            f.write(b"PK-zip-bytes")

    def tearDown(self):
        self.tmp.cleanup()

    def test_skips_when_release_exists(self):
        api = FakeApi(existing_tag="v0.3.1")
        result = gitea_release.publish(api, "ysj7705/mudfish-decky", "0.3.1", "abc123", self.zip)
        self.assertIsNone(result)
        self.assertEqual([c[0] for c in api.calls], ["GET"])

    def test_creates_release_and_uploads_zip(self):
        api = FakeApi()
        result = gitea_release.publish(api, "ysj7705/mudfish-decky", "0.3.1", "abc123", self.zip)
        self.assertEqual(result, "https://git.example/a/1")
        method, path, body, _ = api.calls[1]
        self.assertEqual((method, path), ("POST", "/api/v1/repos/ysj7705/mudfish-decky/releases"))
        self.assertEqual(body["tag_name"], "v0.3.1")
        self.assertEqual(body["target_commitish"], "abc123")
        method, path, body, headers = api.calls[2]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/api/v1/repos/ysj7705/mudfish-decky/releases/42/assets?name=mudfish-decky-0.3.1.zip")
        self.assertIn(b"PK-zip-bytes", body)
        self.assertIn("multipart/form-data; boundary=", headers["Content-Type"])

    def test_api_error_raises(self):
        def forbidden(method, path, body=None, headers=None):
            return (404, {}) if method == "GET" else (403, {"message": "token lacks scope"})

        with self.assertRaises(gitea_release.ReleaseError):
            gitea_release.publish(forbidden, "o/r", "0.3.1", "abc", self.zip)


if __name__ == "__main__":
    unittest.main()
