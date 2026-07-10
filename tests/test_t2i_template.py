import ast
import base64
import copy
import tempfile
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


def _html_render_call(tree: ast.Module) -> ast.Call:
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef) or node.name != "_render_games_api":
            continue
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "html_render"
            ):
                return child
    raise AssertionError("_render_games_api html_render call not found")


class _FakeImage:
    def __init__(self, file=None, kind="direct"):
        self.file = file
        self.kind = kind

    @classmethod
    def fromURL(cls, url):
        return cls(url, "url")

    @classmethod
    def fromFileSystem(cls, path):
        return cls(path, "file")


class _FakeComp:
    Image = _FakeImage


class _FakeLogger:
    @staticmethod
    def warning(*_args, **_kwargs):
        pass


def _render_result_helper(tree: ast.Module):
    plugin_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "EpicFreeGamePlugin"
    )
    method_names = {"_has_image_magic", "_image_component_from_t2i_result"}
    methods = [
        copy.deepcopy(node)
        for node in plugin_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in method_names
    ]
    helper_class = ast.ClassDef(
        name="RenderResultHelper",
        bases=[],
        keywords=[],
        body=methods,
        decorator_list=[],
    )
    module = ast.fix_missing_locations(ast.Module(body=[helper_class], type_ignores=[]))
    namespace = {"base64": base64, "Comp": _FakeComp, "logger": _FakeLogger, "Path": Path}
    exec(compile(module, str(MAIN_PATH), "exec"), namespace)
    return namespace["RenderResultHelper"]


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
        self.assertIn("max-width: 1020px;", self.template)

    def test_grid_handles_narrow_columns_and_long_text(self):
        self.assertIn("repeat(2, minmax(0, 1fr))", self.template)
        self.assertIn("overflow-wrap: anywhere;", self.template)
        self.assertIn("@media (max-width: 640px)", self.template)

    def test_reference_plugin_render_strategy_is_used(self):
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
            "device_scale_factor_level",
        }
        self.assertLessEqual(options.keys(), supported)
        self.assertEqual(options["type"], "png")
        self.assertEqual(options["device_scale_factor_level"], "ultra")
        self.assertEqual(options["timeout"], 30_000)
        self.assertNotIn("quality", options)
        self.assertNotIn("viewport_width", options)
        self.assertTrue(options["full_page"])

        render_call = _html_render_call(self.tree)
        keywords = {keyword.arg: keyword.value for keyword in render_call.keywords}
        self.assertIn("return_url", keywords)
        self.assertIsInstance(keywords["return_url"], ast.Constant)
        self.assertFalse(keywords["return_url"].value)

    def test_t2i_result_conversion_validates_and_localizes_images(self):
        helper = _render_result_helper(self.tree)
        png_data = b"\x89PNG\r\n\x1a\nrendered-image"

        byte_component = helper._image_component_from_t2i_result(png_data)
        self.assertEqual(byte_component.kind, "direct")
        self.assertTrue(byte_component.file.startswith("base64://"))
        self.assertEqual(
            base64.b64decode(byte_component.file.removeprefix("base64://")),
            png_data,
        )

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as image_file:
            image_file.write(png_data)
            image_path = Path(image_file.name)
        try:
            file_component = helper._image_component_from_t2i_result(str(image_path))
            self.assertEqual(file_component.kind, "file")
            self.assertEqual(Path(file_component.file), image_path.resolve())
        finally:
            image_path.unlink(missing_ok=True)

        with self.assertRaisesRegex(RuntimeError, "invalid image bytes"):
            helper._image_component_from_t2i_result(b"not-an-image")


if __name__ == "__main__":
    unittest.main()
