from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
VISION = ROOT / "plugins" / "iphone-use-wda-vision" / "server"


@unittest.skipUnless(VISION.is_dir(), "the vision plugin is not part of an installed copy")
class SharedModuleTests(unittest.TestCase):
    def test_both_plugins_ship_the_same_text_and_image_helpers(self):
        # Each plugin is installed on its own, so the helpers are copied rather than imported.
        for name in ("wda_text.py", "wda_image.py"):
            with self.subTest(name=name):
                self.assertEqual((ROOT / "server" / name).read_bytes(), (VISION / name).read_bytes())


if __name__ == "__main__":
    unittest.main()
