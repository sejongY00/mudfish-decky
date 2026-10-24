import json
import unittest

from mudfish_decky.selfupdate import LATEST_RELEASE_API, latest_plugin_release

RELEASE = {
    "tag_name": "v0.1.2",
    "assets": [
        {"name": "notes.txt", "browser_download_url": "https://git.example/notes.txt"},
        {"name": "mudfish-decky-0.1.2.zip",
         "browser_download_url": "https://git.sejong.dev/ysj7705/mudfish-decky/releases/download/v0.1.2/mudfish-decky-0.1.2.zip"},
    ],
}


class SelfUpdateTest(unittest.TestCase):
    def test_reads_latest_release_zip(self):
        urls = []

        def fetch(url):
            urls.append(url)
            return json.dumps(RELEASE)

        self.assertEqual(latest_plugin_release(fetch), {
            "version": "0.1.2",
            "url": "https://git.sejong.dev/ysj7705/mudfish-decky/releases/download/v0.1.2/mudfish-decky-0.1.2.zip",
        })
        self.assertEqual(urls, [LATEST_RELEASE_API])
        self.assertEqual(LATEST_RELEASE_API,
                         "https://git.sejong.dev/api/v1/repos/ysj7705/mudfish-decky/releases/latest")

    def test_none_when_release_has_no_zip(self):
        self.assertIsNone(latest_plugin_release(lambda url: json.dumps({"tag_name": "v1", "assets": []})))

    def test_none_when_unreachable(self):
        def fetch(url):
            raise OSError("offline")

        self.assertIsNone(latest_plugin_release(fetch))


if __name__ == "__main__":
    unittest.main()
