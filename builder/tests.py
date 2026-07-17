import io
import json
import tempfile
import zipfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import WebsiteProject


class EditorWorkflowTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.temp_dir.name)
        self.override.enable()

        self.project = WebsiteProject.objects.create(
            name="Test Website",
            entry_file="index.html",
            stylesheet_files=["style.css"],
        )
        self.project.source_dir.mkdir(parents=True)
        self.project.entry_path.write_text(
            "<!doctype html><html><head><link rel=\"stylesheet\" href=\"style.css\"></head>"
            "<body><nav><a href=\"#home\">Home</a></nav><main><h1>Hello</h1></main>"
            "<script src=\"script.js\"></script></body></html>",
            encoding="utf-8",
        )
        (self.project.source_dir / "style.css").write_text("h1{color:black}", encoding="utf-8")
        (self.project.source_dir / "script.js").write_text("console.log('ok')", encoding="utf-8")

    def tearDown(self):
        self.override.disable()
        self.temp_dir.cleanup()

    def test_dashboard_and_editor_data(self):
        dashboard = self.client.get(reverse("builder:dashboard"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, "Test Website")

        response = self.client.get(reverse("builder:editor_data", args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("<h1>Hello</h1>", payload["html"])
        self.assertNotIn("script.js", payload["html"])
        self.assertTrue(payload["canvasStyles"][0].endswith("/style.css"))

    def test_save_preserves_original_script_and_css(self):
        save_url = reverse("builder:save_project", args=[self.project.id])
        response = self.client.post(
            save_url,
            data=json.dumps(
                {
                    "html": '<nav><a href="#projects">Projects</a></nav><main><h1>Changed</h1></main>',
                    "css": ".new-rule{color:red}",
                    "projectData": {"pages": [{"component": "Changed"}]},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        saved_html = self.project.entry_path.read_text(encoding="utf-8")
        self.assertIn("Changed", saved_html)
        self.assertIn('<script src="script.js"></script>', saved_html)
        self.assertIn('data-siaw-editor="true"', saved_html)
        self.assertEqual((self.project.source_dir / "style.css").read_text(), "h1{color:black}")
        self.assertIn(".new-rule", (self.project.source_dir / "siaw-editor-overrides.css").read_text())
        self.assertTrue(self.project.project_data_path.is_file())

    def test_save_syncs_javascript_driven_product_image(self):
        (self.project.source_dir / "script.js").write_text(
            'const products = [{ id: "agrisense-probe", image: "images/old.webp" }];',
            encoding="utf-8",
        )
        response = self.client.post(
            reverse("builder:save_project", args=[self.project.id]),
            data=json.dumps(
                {
                    "html": '<main><img id="detailImage" src="images/uploads/new.webp"></main>',
                    "css": "",
                    "projectData": {"pages": []},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("AgriSense product image", response.json()["synced"])
        saved_script = (self.project.source_dir / "script.js").read_text(encoding="utf-8")
        self.assertIn('image: "images/uploads/new.webp"', saved_script)

    def test_editor_data_includes_editor_only_visibility_css(self):
        response = self.client.get(reverse("builder:editor_data", args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(url.endswith("/static/builder/canvas-fixes.css") for url in response.json()["canvasStyles"]))

    def test_export_contains_working_project_files(self):
        response = self.client.get(reverse("builder:export_project", args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = set(archive.namelist())
        self.assertIn("index.html", names)
        self.assertIn("style.css", names)
        self.assertIn("script.js", names)


class UploadSecurityTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.temp_dir.name)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        self.temp_dir.cleanup()

    def test_upload_rejects_path_traversal(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("index.html", "<html><body>Safe</body></html>")
            archive.writestr("../outside.txt", "unsafe")
        upload = SimpleUploadedFile("unsafe.zip", buffer.getvalue(), content_type="application/zip")
        response = self.client.post(
            reverse("builder:upload_project"),
            {"name": "Unsafe", "website_zip": upload},
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Unsafe path", status_code=400)
        self.assertFalse(WebsiteProject.objects.filter(name="Unsafe").exists())

    def test_upload_accepts_single_html_file(self):
        upload = SimpleUploadedFile(
            "landing.html",
            b"<!doctype html><html><body><h1>Hello</h1></body></html>",
            content_type="text/html",
        )
        response = self.client.post(
            reverse("builder:upload_project"),
            {"name": "HTML Only", "website_zip": upload},
        )
        self.assertEqual(response.status_code, 302)
        project = WebsiteProject.objects.get(name="HTML Only")
        self.assertEqual(project.entry_file, "landing.html")
        self.assertTrue(project.entry_path.is_file())
        self.assertIn("Hello", project.entry_path.read_text(encoding="utf-8"))

    def test_upload_accepts_zip_without_index_html(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("site/home.html", "<!doctype html><html><body><h1>Home</h1></body></html>")
            archive.writestr("site/about.html", "<!doctype html><html><body><h1>About</h1></body></html>")
            archive.writestr("site/styles.css", "body{margin:0}")
        upload = SimpleUploadedFile("no-index.zip", buffer.getvalue(), content_type="application/zip")
        response = self.client.post(
            reverse("builder:upload_project"),
            {"name": "No Index", "website_zip": upload},
        )
        self.assertEqual(response.status_code, 302)
        project = WebsiteProject.objects.get(name="No Index")
        self.assertEqual(project.entry_file, "home.html")
        self.assertTrue((project.source_dir / "styles.css").is_file())
        self.assertTrue((project.source_dir / "about.html").is_file())
        self.assertIn("Home", project.entry_path.read_text(encoding="utf-8"))

    def test_upload_accepts_source_only_web_project(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("package.json", '{"name":"demo","private":true}')
            archive.writestr("src/main.tsx", "export const App = () => <div>Hi</div>;")
            archive.writestr("vite.config.ts", "export default {}")
            archive.writestr("node_modules/ignore/index.js", "should be skipped")
        upload = SimpleUploadedFile("vite-app.zip", buffer.getvalue(), content_type="application/zip")
        response = self.client.post(
            reverse("builder:upload_project"),
            {"name": "Vite App", "website_zip": upload},
        )
        self.assertEqual(response.status_code, 302)
        project = WebsiteProject.objects.get(name="Vite App")
        self.assertEqual(project.entry_file, "src/main.tsx")
        self.assertFalse((project.source_dir / "node_modules").exists())
        data = self.client.get(reverse("builder:editor_data", args=[project.id]))
        self.assertEqual(data.status_code, 200)
        payload = data.json()
        self.assertEqual(payload["mode"], "code")
        self.assertIn("App", payload["content"])

    def test_upload_detects_zip_bytes_even_with_html_filename(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "3dnow_17 (1).html",
                "<!doctype html><html><body><h1>3DNow</h1></body></html>",
            )
            archive.writestr("__MACOSX/._3dnow_17 (1).html", b"\x00\x05\x16\x07")
        upload = SimpleUploadedFile(
            "3dnow_17 (1).html",
            buffer.getvalue(),
            content_type="text/html",
        )
        response = self.client.post(
            reverse("builder:upload_project"),
            {"name": "Zip As Html", "website_zip": upload},
        )
        self.assertEqual(response.status_code, 302)
        project = WebsiteProject.objects.get(name="Zip As Html")
        self.assertEqual(project.entry_file, "3dnow_17 (1).html")
        html = project.entry_path.read_text(encoding="utf-8")
        self.assertIn("3DNow", html)
        self.assertFalse(html.startswith("PK"))

class CompatibilityAndSmartManagerTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.temp_dir.name)
        self.override.enable()
        self.project = WebsiteProject.objects.create(name="Inline Website", entry_file="index.html")
        self.project.source_dir.mkdir(parents=True)
        self.project.entry_path.write_text(
            '<!doctype html><html lang="de" class="no-js"><head><style>.mark{width:44px}</style></head>'
            '<body class="site-body"><section id="services"><div class="service-grid">'
            '<article class="service-card service-detail-trigger" data-service="engineering">'
            '<img src="images/service.webp"><div><h3>Engineering</h3><p>Card summary</p>'
            '<span class="service-detail-link">View details</span></div></article>'
            '</div></section><script src="script.js"></script></body></html>',
            encoding="utf-8",
        )
        (self.project.source_dir / "script.js").write_text(
            '''const serviceExpandedContent = {
  engineering: {
    title: "Engineering",
    image: "images/service.webp",
    summary: "Popup summary",
    details: `
      <div class="modal-detail-grid">
        <div class="modal-detail-section"><h4>What we help with</h4><p>First text</p></div>
        <div class="modal-detail-section"><h4>Examples</h4><ul><li>One</li><li>Two</li></ul></div>
        <div class="modal-detail-section"><h4>What you get</h4><p>Third text</p></div>
      </div>
    `
  }
};''',
            encoding="utf-8",
        )

    def tearDown(self):
        self.override.disable()
        self.temp_dir.cleanup()

    def test_editor_data_restores_inline_styles_and_document_attributes(self):
        response = self.client.get(reverse("builder:editor_data", args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["inlineStyles"], [".mark{width:44px}"])
        self.assertEqual(payload["htmlAttributes"]["lang"], "de")
        self.assertEqual(payload["htmlAttributes"]["class"], "no-js")
        self.assertEqual(payload["bodyAttributes"]["class"], "site-body")
        self.assertTrue(payload["smartServices"]["available"])
        self.assertEqual(payload["smartServices"]["services"][0]["detailSectionTwoBullets"], ["One", "Two"])

    def test_save_rebuilds_service_javascript_from_smart_manager(self):
        smart_services = [{
            "key": "engineering",
            "title": "Engineering Consultancy",
            "cardDescription": "Updated card",
            "buttonText": "Read more",
            "image": "images/new.webp",
            "detailSummary": "Updated popup summary",
            "detailSectionOneHeading": "Support",
            "detailSectionOneText": "Updated first text",
            "detailSectionTwoHeading": "Examples",
            "detailSectionTwoBullets": ["Alpha", "Beta"],
            "detailSectionThreeHeading": "Outcome",
            "detailSectionThreeText": "Updated result",
        }]
        response = self.client.post(
            reverse("builder:save_project", args=[self.project.id]),
            data=json.dumps({
                "html": '<section id="services"><article class="service-card service-detail-trigger" data-service="engineering"><img src="images/new.webp"><h3>Engineering Consultancy</h3><p>Updated card</p><span class="service-detail-link">Read more</span></article></section>',
                "css": "",
                "projectData": {"pages": []},
                "smartServices": smart_services,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Services manager", response.json()["synced"][0])
        script = (self.project.source_dir / "script.js").read_text(encoding="utf-8")
        self.assertIn('title: "Engineering Consultancy"', script)
        self.assertIn("<li>Alpha</li>", script)
        self.assertIn("Updated result", script)

class UniversalCompatibilityEngineTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.temp_dir.name)
        self.override.enable()
        self.project = WebsiteProject.objects.create(
            name="Dynamic App",
            entry_file="index.html",
            stylesheet_files=["styles.css"],
        )
        self.project.source_dir.mkdir(parents=True)
        self.project.entry_path.write_text(
            '''<!doctype html><html><head><link rel="stylesheet" href="styles.css"></head><body>
            <img data-src="images/photo.webp" alt="Lazy">
            <section class="io-reveal"><h2>Animated</h2></section>
            <div id="reviewsTrack"></div>
            <form><button type="submit">Save</button></form>
            <script src="app.js"></script></body></html>''',
            encoding="utf-8",
        )
        (self.project.source_dir / "styles.css").write_text(
            ".io-reveal{opacity:0;transform:translateY(20px)} .hero{background-image:url('images/photo.webp')}",
            encoding="utf-8",
        )
        (self.project.source_dir / "app.js").write_text(
            '''const reviews = [{name:"A"}]; localStorage.getItem("journeys");
            const track = document.getElementById("reviewsTrack");
            const card = document.createElement("article"); track.appendChild(card);''',
            encoding="utf-8",
        )
        (self.project.source_dir / "images").mkdir()
        (self.project.source_dir / "images" / "photo.webp").write_bytes(b"image")

    def tearDown(self):
        self.override.disable()
        self.temp_dir.cleanup()

    def test_editor_data_hydrates_lazy_media_and_reports_dynamic_regions(self):
        response = self.client.get(reverse("builder:editor_data", args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('src="images/photo.webp"', payload["html"])
        report = payload["compatibility"]
        self.assertEqual(report["websiteType"], "Interactive web application")
        self.assertEqual(report["hydratedLazyMediaCount"], 1)
        self.assertEqual(report["runtimeRegionCount"], 1)
        self.assertEqual(report["runtimeRegions"][0]["selector"], "#reviewsTrack")
        self.assertGreaterEqual(report["animationSelectorCount"], 1)
        self.assertEqual(report["missingResourceCount"], 0)
        self.assertIn(".runtime.localhost", payload["runtimeUrl"])

    def test_isolated_runtime_enables_storage_without_sharing_editor_origin(self):
        host = f"{self.project.id}.runtime.localhost:8000"
        response = self.client.get(
            reverse("builder:project_file", kwargs={"project_id": self.project.id, "file_path": "index.html"}),
            HTTP_HOST=host,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("allow-same-origin", response["Content-Security-Policy"])
        self.assertEqual(response["X-Frame-Options"], "ALLOWALL")

    def test_preview_uses_isolated_project_origin(self):
        response = self.client.get(reverse("builder:preview", args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{self.project.id}.runtime.localhost")
        self.assertContains(response, "allow-same-origin")

class NavigationAndCaptureTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.temp_dir.name)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        self.temp_dir.cleanup()

    def test_static_navigation_manager_is_detected(self):
        project = WebsiteProject.objects.create(name="Static Nav", entry_file="index.html")
        project.source_dir.mkdir(parents=True)
        project.entry_path.write_text(
            '<html><body><header><nav class="navbar"><div id="navLinks">'
            '<a href="#home">Home</a><a href="#projects">Projects</a>'
            '</div></nav></header><main><h1>Hello</h1></main></body></html>',
            encoding="utf-8",
        )
        response = self.client.get(reverse("builder:editor_data", args=[project.id]))
        self.assertEqual(response.status_code, 200)
        navigation = response.json()["smartNavigation"]
        self.assertTrue(navigation["available"])
        self.assertEqual(navigation["mode"], "static-html")
        self.assertEqual(navigation["containerSelector"], "#navLinks")
        self.assertEqual([item["label"] for item in navigation["items"]], ["Home", "Projects"])

    def test_javascript_navigation_manager_updates_inline_array(self):
        project = WebsiteProject.objects.create(name="Generated Nav", entry_file="index.html")
        project.source_dir.mkdir(parents=True)
        project.entry_path.write_text(
            '''<html><body><nav><ul id="desktop-nav-list"></ul></nav><main>App</main>
            <script>const NAV=[
              {id:'home',label:'Home',type:'page',items:[]},
              {id:'offers',label:'Offers',type:'page',cta:true,items:[]}
            ]; function buildNavigation(){document.getElementById('desktop-nav-list').innerHTML='';} buildNavigation();</script>
            </body></html>''',
            encoding="utf-8",
        )
        data_response = self.client.get(reverse("builder:editor_data", args=[project.id]))
        navigation = data_response.json()["smartNavigation"]
        self.assertEqual(navigation["mode"], "javascript-array")
        self.assertEqual(len(navigation["items"]), 2)
        navigation["items"][0]["label"] = "Start"
        navigation["items"] = [navigation["items"][1], navigation["items"][0]]
        response = self.client.post(
            reverse("builder:save_project", args=[project.id]),
            data=json.dumps({
                "html": '<nav><ul id="desktop-nav-list"></ul></nav><main>App</main>',
                "css": "",
                "projectData": {"pages": [], "siawCaptures": []},
                "smartNavigation": navigation,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any("Navigation manager" in item for item in response.json()["synced"]))
        saved = project.entry_path.read_text(encoding="utf-8")
        self.assertLess(saved.index("offers"), saved.index("home"))
        self.assertIn('label:"Start"', saved.replace(" ", ""))

    def test_runtime_entry_injects_capture_bridge(self):
        project = WebsiteProject.objects.create(name="Runtime", entry_file="index.html")
        project.source_dir.mkdir(parents=True)
        project.entry_path.write_text('<html><body><main>Hello</main></body></html>', encoding="utf-8")
        host = f"{project.id}.runtime.localhost:8000"
        response = self.client.get(
            reverse("builder:project_file", kwargs={"project_id": project.id, "file_path": "index.html"}),
            HTTP_HOST=host,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "runtime-bridge.js")
        self.assertContains(response, 'data-siaw-runtime-bridge="true"')

    def test_editor_template_includes_capture_panel(self):
        project = WebsiteProject.objects.create(name="Capture UI", entry_file="index.html")
        project.source_dir.mkdir(parents=True)
        project.entry_path.write_text('<html><body><main>Hello</main></body></html>', encoding="utf-8")
        response = self.client.get(reverse("builder:editor", args=[project.id]))
        self.assertContains(response, "Dynamic component capture")
        self.assertContains(response, "Capture component")
