import ast
import base64
import copy
import io
import tempfile
import unittest
from pathlib import Path

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None


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


def _module_constant(tree: ast.Module, name: str):
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found")


def _plugin_method(tree: ast.Module, name: str):
    plugin_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "EpicFreeGamePlugin"
    )
    return next(
        node
        for node in plugin_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )


def _t2i_render_options(tree: ast.Module) -> list[dict]:
    method = _plugin_method(tree, "_t2i_render_options")
    result = next(node for node in method.body if isinstance(node, ast.Return))
    return ast.literal_eval(result.value)


def _attribute_calls(node: ast.AST, attribute: str) -> list[ast.Call]:
    return [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr == attribute
    ]


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

    @staticmethod
    def debug(*_args, **_kwargs):
        pass


def _render_result_helper(tree: ast.Module):
    plugin_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "EpicFreeGamePlugin"
    )
    method_names = {
        "_has_image_magic",
        "_crop_t2i_to_browser_width",
        "_image_component_from_t2i_result",
    }
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
    namespace = {
        "base64": base64,
        "Comp": _FakeComp,
        "HAS_PILLOW": PILImage is not None,
        "io": io,
        "logger": _FakeLogger,
        "Path": Path,
        "PILImage": PILImage,
    }
    exec(compile(module, str(MAIN_PATH), "exec"), namespace)
    return namespace["RenderResultHelper"]


class T2ITemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = _parse_main()
        cls.template = _html_template(cls.tree)
        cls.browser_width = _module_constant(cls.tree, "T2I_BROWSER_WIDTH")

    def test_template_keeps_the_original_epic_browser_layout(self):
        self.assertEqual(self.browser_width, 600)
        self.assertIn('name="viewport"', self.template)
        self.assertIn("width: 600px;", self.template)
        self.assertIn("padding: 24px;", self.template)
        self.assertIn("repeat(2, minmax(0, 1fr))", self.template)
        self.assertIn("gap: 28px;", self.template)
        self.assertNotIn("max-width: 1020px;", self.template)
        self.assertNotIn('class="page"', self.template)
        self.assertNotIn("@media", self.template)
        self.assertNotIn("min-height: 100vh", self.template)

    def test_browser_screenshots_the_body_without_fixed_output_dimensions(self):
        method = _plugin_method(self.tree, "_render_html_with_browser")

        new_page = _attribute_calls(method, "new_page")
        self.assertEqual(len(new_page), 1)
        new_page_kwargs = {kw.arg: kw.value for kw in new_page[0].keywords}
        viewport = new_page_kwargs["viewport"]
        self.assertIsInstance(viewport, ast.Dict)
        viewport_values = {
            key.value: value.id
            for key, value in zip(viewport.keys, viewport.values)
        }
        self.assertEqual(viewport_values["width"], "T2I_BROWSER_WIDTH")
        self.assertEqual(viewport_values["height"], "T2I_INITIAL_VIEWPORT_HEIGHT")
        self.assertEqual(ast.literal_eval(new_page_kwargs["device_scale_factor"]), 2)

        query = _attribute_calls(method, "query_selector")
        self.assertEqual(len(query), 1)
        self.assertEqual(ast.literal_eval(query[0].args[0]), "body")

        screenshots = _attribute_calls(method, "screenshot")
        self.assertEqual(len(screenshots), 1)
        screenshot_kwargs = {kw.arg for kw in screenshots[0].keywords}
        self.assertFalse({"path", "clip", "full_page", "width", "height"} & screenshot_kwargs)

    def test_browser_render_is_tried_before_framework_t2i(self):
        method = _plugin_method(self.tree, "_render_games_api")
        direct_call = _attribute_calls(method, "_render_html_with_browser")
        t2i_call = _attribute_calls(method, "html_render")
        self.assertEqual(len(direct_call), 1)
        self.assertEqual(len(t2i_call), 1)
        self.assertLess(direct_call[0].lineno, t2i_call[0].lineno)

        t2i_kwargs = {kw.arg: kw.value for kw in t2i_call[0].keywords}
        self.assertFalse(ast.literal_eval(t2i_kwargs["return_url"]))

        converters = _attribute_calls(method, "_image_component_from_t2i_result")
        fallback_converter = next(
            call
            for call in converters
            if any(kw.arg == "crop_css_width" for kw in call.keywords)
        )
        crop_kwarg = next(
            kw.value
            for kw in fallback_converter.keywords
            if kw.arg == "crop_css_width"
        )
        self.assertIsInstance(crop_kwarg, ast.Name)
        self.assertEqual(crop_kwarg.id, "T2I_BROWSER_WIDTH")

    def test_t2i_fallback_uses_supported_full_page_strategies(self):
        strategies = _t2i_render_options(self.tree)
        self.assertEqual(len(strategies), 2)
        self.assertEqual(strategies[0]["type"], "png")
        self.assertNotIn("quality", strategies[0])
        self.assertEqual(strategies[1]["type"], "jpeg")
        self.assertEqual(strategies[1]["quality"], 80)
        self.assertEqual(strategies[0]["timeout"], 50_000)
        self.assertEqual(strategies[1]["timeout"], 100_000)
        for strategy in strategies:
            self.assertTrue(strategy["full_page"])
            self.assertEqual(strategy["scale"], "css")
            self.assertNotIn("viewport_width", strategy)
            self.assertNotIn("width", strategy)
            self.assertNotIn("height", strategy)

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

    @unittest.skipIf(PILImage is None, "Pillow is not installed")
    def test_t2i_crop_removes_only_the_extra_right_canvas(self):
        helper = _render_result_helper(self.tree)
        source = PILImage.new("RGB", (1280, 321), (23, 31, 43))
        buffer = io.BytesIO()
        source.save(buffer, format="PNG")

        component = helper._image_component_from_t2i_result(
            buffer.getvalue(),
            crop_css_width=600,
        )
        result = base64.b64decode(component.file.removeprefix("base64://"))
        with PILImage.open(io.BytesIO(result)) as cropped:
            self.assertEqual(cropped.size, (600, 321))


if __name__ == "__main__":
    unittest.main()
