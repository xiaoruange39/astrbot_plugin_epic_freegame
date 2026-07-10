import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = ROOT / "main.py"


def _parse_main() -> ast.Module:
    return ast.parse(MAIN_PATH.read_text(encoding="utf-8"))


def _html_template(tree: ast.Module) -> str:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "HTML_TEMPLATE"
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("HTML_TEMPLATE not found")


def _render_options(tree: ast.Module) -> dict:
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef) or node.name != "_render_games_api":
            continue
        for child in node.body:
            if (
                isinstance(child, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "options"
                    for target in child.targets
                )
            ):
                return ast.literal_eval(child.value)
    raise AssertionError("_render_games_api options not found")


class T2ITemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = _parse_main()
        cls.template = _html_template(cls.tree)

    def test_template_fills_the_t2i_viewport(self):
        self.assertIn('name="viewport"', self.template)
        self.assertIn("body {", self.template)
        self.assertIn("width: 100%;", self.template)
        self.assertNotIn("width: 600px;", self.template)
        self.assertIn("max-width: 1200px;", self.template)

    def test_grid_handles_narrow_columns_and_long_text(self):
        self.assertIn("repeat(2, minmax(0, 1fr))", self.template)
        self.assertIn("overflow-wrap: anywhere;", self.template)
        self.assertIn("@media (max-width: 560px)", self.template)

    def test_only_supported_playwright_screenshot_options_are_used(self):
        options = _render_options(self.tree)
        supported = {
            "timeout",
            "type",
            "quality",
            "omit_background",
            "full_page",
            "clip",
            "animations",
            "caret",
            "scale",
        }
        self.assertLessEqual(options.keys(), supported)
        self.assertNotIn("viewport_width", options)
        self.assertTrue(options["full_page"])


if __name__ == "__main__":
    unittest.main()
