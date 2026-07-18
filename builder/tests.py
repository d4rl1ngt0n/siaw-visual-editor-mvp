import io
import json
import tempfile
import zipfile
from pathlib import Path

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import WebsiteProject


def _make_user(username="siaw-tester"):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="siaw-test-pass-99",
    )
from .services.html_tools import (
    extract_hero_photos,
    extract_reviews,
    guard_hero_carousel_script,
    hydrate_js_hero_carousel,
    hydrate_js_reviews,
    materialize_hero_photo_files,
    sync_js_interactive_arrays,
)


class HeroCarouselHydrationTests(TestCase):
    def test_extract_hydrate_and_guard_hero_carousel(self):
        # 1x1 PNG
        tiny_png = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
        html_text = f"""<!doctype html><html><body>
<div data-hero-carousel class="hero-carousel">
  <div class="hc-frame"><div class="hc-track js-hc-track"></div></div>
  <div class="hc-dots js-hc-dots"></div>
</div>
<div id="reviewsTrack"></div>
<div id="reviewsDots"></div>
<script>
var REVIEWS = [
  {{ name: "Chris H.", stars: 5, text: "Great service.\\nFast delivery." }},
  {{ name: "Amber C.", stars: 4, text: "Helpful team." }}
];
var HERO_PHOTOS = [
  {{ src: 'data:image/png;base64,{tiny_png}', alt_en: 'Printer', alt_de: 'Drucker' }},
  {{ src: 'images/part.jpg', alt_en: 'Part', alt_de: 'Teil' }}
];
var track = root.querySelector('.js-hc-track');
var dotsWrap = root.querySelector('.js-hc-dots');
var slides = [], dots = [];
HERO_PHOTOS.forEach(function(p, i){{ track.appendChild(document.createElement('div')); }});
</script>
</body></html>"""
        photos = extract_hero_photos(html_text)
        self.assertEqual(len(photos), 2)
        self.assertEqual(photos[0]["alt"], "Printer")
        reviews = extract_reviews(html_text)
        self.assertEqual(len(reviews), 2)
        self.assertEqual(reviews[0]["name"], "Chris H.")
        self.assertIn("Great service", reviews[0]["text"])

        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            materialized = materialize_hero_photo_files(root, photos)
            self.assertTrue((root / "siaw-hydrated" / "hero-0.png").is_file())
            self.assertEqual(materialized[0]["src"], "siaw-hydrated/hero-0.png")
            self.assertEqual(materialized[1]["src"], "images/part.jpg")

            body = """<div data-hero-carousel class="hero-carousel">
  <div class="hc-frame"><div class="hc-track js-hc-track"></div></div>
  <div class="hc-dots js-hc-dots"></div>
</div>
<div id="reviewsTrack"></div>
<div id="reviewsDots"></div>"""
            hydrated, count = hydrate_js_hero_carousel(body, materialized)
            self.assertEqual(count, 2)
            self.assertIn('class="hc-slide is-active"', hydrated)
            self.assertIn('src="siaw-hydrated/hero-0.png"', hydrated)
            self.assertIn('class="hc-dot is-active"', hydrated)
            self.assertIn('data-siaw-hydrated="hero-carousel"', hydrated)

            hydrated, review_count = hydrate_js_reviews(hydrated, reviews)
            self.assertEqual(review_count, 2)
            self.assertIn('data-siaw-hydrated="reviews"', hydrated)
            self.assertIn("Chris H.", hydrated)
            self.assertIn("Great service", hydrated)

            edited = hydrated.replace("images/part.jpg", "images/new-part.jpg").replace(
                "Helpful team.", "Updated review text."
            )
            synced_html, synced = sync_js_interactive_arrays(html_text, edited)
            self.assertTrue(any("Hero slideshow" in item for item in synced))
            self.assertTrue(any("Reviews" in item for item in synced))
            self.assertIn("images/new-part.jpg", synced_html)
            self.assertIn("Updated review text.", synced_html)

            reordered_html, reordered_synced = sync_js_interactive_arrays(
                html_text,
                edited,
                slideshow_photos=[
                    {"src": "images/new-part.jpg", "alt": "Part", "alt_en": "Part", "alt_de": "Teil"},
                    {"src": "siaw-hydrated/hero-0.png", "alt": "Printer", "alt_en": "Printer", "alt_de": "Drucker"},
                ],
            )
            self.assertTrue(any("Hero slideshow (2 slides)" in item for item in reordered_synced))
            photos_literal_start = reordered_html.find("HERO_PHOTOS")
            photos_chunk = reordered_html[photos_literal_start:photos_literal_start + 260]
            self.assertLess(photos_chunk.find("images/new-part.jpg"), photos_chunk.find("siaw-hydrated/hero-0.png"))

        guarded = guard_hero_carousel_script(html_text)
        self.assertIn("siaw-hc-guard", guarded)
        self.assertIn("track.querySelector('.hc-slide')", guarded)
        self.assertEqual(guard_hero_carousel_script(guarded), guarded)


class EditorWorkflowTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.temp_dir.name)
        self.override.enable()
        self.user = _make_user("editor-user")
        self.client.force_login(self.user)

        self.project = WebsiteProject.objects.create(
            name="Test Website",
            entry_file="index.html",
            stylesheet_files=["style.css"],
            owner=self.user,
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
        # Local CSS is inlined for Safe Edit so GrapesJS canvas does not miss styles.
        inline_blob = "\n".join(payload.get("inlineStyles") or [])
        self.assertTrue(inline_blob or any("style.css" in s for s in payload.get("canvasStyles") or []))

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
        self.user = _make_user("upload-user")
        self.client.force_login(self.user)

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
        self.assertEqual(project.owner_id, self.user.id)
        self.assertEqual(project.entry_file, "landing.html")
        self.assertTrue(project.entry_path.is_file())
        self.assertIn("Hello", project.entry_path.read_text(encoding="utf-8"))

    def test_delete_project_removes_files_and_record(self):
        project = WebsiteProject.objects.create(
            name="Disposable",
            entry_file="index.html",
            owner=self.user,
        )
        project.source_dir.mkdir(parents=True)
        project.entry_path.write_text("<html><body>Bye</body></html>", encoding="utf-8")
        project_dir = project.project_dir
        self.assertTrue(project_dir.is_dir())
        response = self.client.post(reverse("builder:delete_project", args=[project.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(WebsiteProject.objects.filter(id=project.id).exists())
        self.assertFalse(project_dir.exists())

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
        self.user = _make_user("compat-user")
        self.client.force_login(self.user)
        self.project = WebsiteProject.objects.create(
            name="Inline Website",
            entry_file="index.html",
            owner=self.user,
        )
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
        self.user = _make_user("universal-user")
        self.client.force_login(self.user)
        self.project = WebsiteProject.objects.create(
            name="Dynamic App",
            entry_file="index.html",
            stylesheet_files=["styles.css"],
            owner=self.user,
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
        self.assertIn("images/photo.webp", payload["html"])
        self.assertIn('alt="Lazy"', payload["html"])
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
        response = self.client.get("/", HTTP_HOST=host)
        self.assertEqual(response.status_code, 200)
        self.assertIn("allow-same-origin", response["Content-Security-Policy"])
        self.assertEqual(response["X-Frame-Options"], "ALLOWALL")
        self.assertContains(response, "runtime-bridge.js")

    def test_preview_uses_isolated_project_origin(self):
        response = self.client.get(reverse("builder:preview", args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{self.project.id}.runtime.localhost")
        self.assertContains(response, "allow-same-origin")
        # Preview loads the website root, not /files/entry.html
        self.assertContains(response, f"{self.project.id}.runtime.localhost")
        self.assertRegex(response.content.decode("utf-8"), r"\.runtime\.localhost(?::\d+)?/\?v=")

class NavigationAndCaptureTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.temp_dir.name)
        self.override.enable()
        self.user = _make_user("nav-user")
        self.client.force_login(self.user)

    def tearDown(self):
        self.override.disable()
        self.temp_dir.cleanup()

    def _project(self, name, entry_file="index.html", **kwargs):
        return WebsiteProject.objects.create(
            name=name,
            entry_file=entry_file,
            owner=self.user,
            **kwargs,
        )

    def test_static_navigation_manager_is_detected(self):
        project = self._project("Static Nav")
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
        project = self._project("Generated Nav")
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
        project = self._project("Runtime")
        project.source_dir.mkdir(parents=True)
        project.entry_path.write_text('<html><body><main>Hello</main></body></html>', encoding="utf-8")
        host = f"{project.id}.runtime.localhost:8000"
        response = self.client.get("/", HTTP_HOST=host)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "runtime-bridge.js")
        self.assertContains(response, 'data-siaw-runtime-bridge="true"')

    def test_vite_shell_prefers_live_preview(self):
        from builder.services.compatibility import analyze_website

        project = self._project("Vite Shell", entry_file="dist/index.html")
        dist = project.source_dir / "dist"
        dist.mkdir(parents=True)
        (dist / "index.html").write_text(
            '<!doctype html><html><body><div id="root"></div>'
            '<script type="module" src="/assets/index-abc.js"></script></body></html>',
            encoding="utf-8",
        )
        report = analyze_website(
            project.source_dir,
            project.entry_file,
            (dist / "index.html").read_text(encoding="utf-8"),
        )
        self.assertTrue(report["spaShell"]["isSpaShell"])
        self.assertTrue(report["preferLivePreview"])
        self.assertFalse(report["canSafeEdit"])

    def test_nitro_ssr_output_is_detected(self):
        from builder.services.preview_server import detect_ssr_preview

        project = self._project("Nitro App", entry_file="package.json")
        server = project.source_dir / "dist" / "server"
        server.mkdir(parents=True)
        (project.source_dir / "dist" / "nitro.json").write_text(
            '{"serverEntry":"server/index.mjs","commands":{"preview":"node ./server/index.mjs"},'
            '"framework":{"name":"nitro"}}',
            encoding="utf-8",
        )
        (server / "index.mjs").write_text("console.log('ssr')\n", encoding="utf-8")
        info = detect_ssr_preview(project.source_dir, project.source_dir)
        self.assertIsNotNone(info)
        self.assertEqual(info.kind, "nitro")
        self.assertTrue(str(info.server_script).endswith("dist/server/index.mjs"))

    def test_path_based_site_root_rewrites_vite_assets(self):
        project = self._project("Site Root", entry_file="dist/index.html")
        dist = project.source_dir / "dist" / "assets"
        dist.mkdir(parents=True)
        (project.source_dir / "dist" / "index.html").write_text(
            '<!doctype html><html><body><div id="root"></div>'
            '<script type="module" src="/assets/index-abc.js"></script></body></html>',
            encoding="utf-8",
        )
        (dist / "index-abc.js").write_text("console.log('ok')", encoding="utf-8")
        html_response = self.client.get(reverse("builder:runtime_site", args=[project.id]))
        self.assertEqual(html_response.status_code, 200)
        self.assertContains(html_response, 'src="assets/index-abc.js"')
        self.assertContains(html_response, "runtime-bridge.js")
        asset_response = self.client.get(
            reverse("builder:runtime_site_asset", kwargs={"project_id": project.id, "asset_path": "assets/index-abc.js"})
        )
        self.assertEqual(asset_response.status_code, 200)

    def test_editor_template_includes_capture_panel(self):
        project = self._project("Capture UI")
        project.source_dir.mkdir(parents=True)
        project.entry_path.write_text('<html><body><main>Hello</main></body></html>', encoding="utf-8")
        response = self.client.get(reverse("builder:editor", args=[project.id]))
        self.assertContains(response, "Dynamic component capture")
        self.assertContains(response, "Capture component")


class Phase1TrustTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.temp_dir.name)
        self.override.enable()
        self.user = _make_user("phase1-user")
        self.client.force_login(self.user)
        self.project = WebsiteProject.objects.create(
            name="Phase1 Site",
            entry_file="index.html",
            owner=self.user,
        )
        self.project.source_dir.mkdir(parents=True)
        self.project.entry_path.write_text(
            "<!doctype html><html><body>"
            "<a href='about.html'>About</a>"
            "<img src='images/hero.png'>"
            "<h1>Home</h1>"
            "</body></html>",
            encoding="utf-8",
        )
        (self.project.source_dir / "about.html").write_text(
            "<!doctype html><html><body><h1>About</h1><a href=''>Empty</a></body></html>",
            encoding="utf-8",
        )
        (self.project.source_dir / "images").mkdir()
        (self.project.source_dir / "images" / "hero.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    def tearDown(self):
        self.override.disable()
        self.temp_dir.cleanup()

    def test_support_profile_in_editor_data(self):
        response = self.client.get(reverse("builder:editor_data", args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        profile = response.json()["compatibility"]["supportProfile"]
        self.assertIn("supported", profile)
        self.assertTrue(profile["supported"])

    def test_pages_add_duplicate_rename(self):
        add = self.client.post(
            reverse("builder:project_pages", args=[self.project.id]),
            data=json.dumps({"action": "add", "name": "contact.html"}),
            content_type="application/json",
        )
        self.assertEqual(add.status_code, 200)
        self.assertTrue((self.project.source_dir / "contact.html").is_file())

        dup = self.client.post(
            reverse("builder:project_pages", args=[self.project.id]),
            data=json.dumps({"action": "duplicate", "path": "about.html"}),
            content_type="application/json",
        )
        self.assertEqual(dup.status_code, 200)
        self.assertIn("about-copy", dup.json()["path"])

        renamed = self.client.post(
            reverse("builder:project_pages", args=[self.project.id]),
            data=json.dumps({"action": "rename", "path": "contact.html", "name": "reach-us.html"}),
            content_type="application/json",
        )
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json()["path"], "reach-us.html")
        self.assertTrue((self.project.source_dir / "reach-us.html").is_file())

    def test_export_validation_detects_empty_link(self):
        response = self.client.get(reverse("builder:export_validate", args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertGreaterEqual(payload["warningCount"], 1)

    def test_snapshot_create_and_restore(self):
        create = self.client.post(
            reverse("builder:project_snapshots", args=[self.project.id]),
            data=json.dumps({"action": "create", "label": "Before edit"}),
            content_type="application/json",
        )
        self.assertEqual(create.status_code, 200)
        snapshot_id = create.json()["snapshot"]["id"]
        self.project.entry_path.write_text("<html><body><h1>Changed</h1></body></html>", encoding="utf-8")
        restore = self.client.post(
            reverse("builder:project_snapshots", args=[self.project.id]),
            data=json.dumps({"action": "restore", "id": snapshot_id}),
            content_type="application/json",
        )
        self.assertEqual(restore.status_code, 200)
        self.assertIn("Home", self.project.entry_path.read_text(encoding="utf-8"))

    def test_demo_zip_import_export_roundtrip(self):
        demo = Path(__file__).resolve().parents[1] / "demo_projects" / "order_siaw_manufacturing_v32.zip"
        if not demo.is_file():
            self.skipTest("Demo ZIP missing")
        upload = SimpleUploadedFile("order_siaw.zip", demo.read_bytes(), content_type="application/zip")
        response = self.client.post(
            reverse("builder:upload_project"),
            {"name": "Demo Roundtrip", "website_zip": upload},
        )
        self.assertEqual(response.status_code, 302)
        project = WebsiteProject.objects.get(name="Demo Roundtrip")
        self.assertTrue(project.entry_path.is_file())
        validate = self.client.get(reverse("builder:export_validate", args=[project.id]))
        self.assertEqual(validate.status_code, 200)
        export = self.client.get(reverse("builder:export_project", args=[project.id]))
        self.assertEqual(export.status_code, 200)
        self.assertEqual(export["Content-Type"], "application/zip")
        self.assertGreater(len(export.content), 1000)


class CaptureFidelityTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.temp_dir.name)
        self.override.enable()
        self.user = _make_user("capture-user")
        self.client.force_login(self.user)
        self.project = WebsiteProject.objects.create(
            name="Capture Site",
            entry_file="index.html",
            owner=self.user,
        )
        self.project.source_dir.mkdir(parents=True)
        assets = self.project.source_dir / "assets"
        assets.mkdir()
        (assets / "styles-abc.css").write_text("body{color:red}", encoding="utf-8")
        (assets / "hero.jpg").write_bytes(b"jpeg")
        self.project.entry_path.write_text(
            '<!doctype html><html><body><div id="root"></div></body></html>',
            encoding="utf-8",
        )

    def tearDown(self):
        self.override.disable()
        self.temp_dir.cleanup()

    def test_capture_rewrites_assets_and_keeps_local_css(self):
        captured_html = """<!DOCTYPE html><html><head>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Jost">
<link rel="stylesheet" href="/assets/styles-abc.css">
<link rel="modulepreload" href="/assets/app.js">
</head><body>
<img src="/assets/hero.jpg" alt="Hero">
<a href="/collection">Collection</a>
</body></html>"""
        response = self.client.post(
            reverse("builder:capture_route", args=[self.project.id]),
            data=json.dumps({
                "html": captured_html,
                "routeUrl": "http://example.runtime.localhost:8000/",
                "title": "Home",
                "setAsEntry": True,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.project.refresh_from_db()
        self.assertTrue(self.project.entry_file.startswith("captured/"))
        saved = self.project.entry_path.read_text(encoding="utf-8")
        self.assertIn('../assets/styles-abc.css', saved)
        self.assertIn('../assets/hero.jpg', saved)
        self.assertNotIn('href="/assets/', saved)
        self.assertNotIn('src="/assets/', saved)
        self.assertIn("assets/styles-abc.css", self.project.stylesheet_files)
        self.assertTrue(any(item.startswith("https://fonts.googleapis.com") for item in self.project.stylesheet_files))

        data = self.client.get(reverse("builder:editor_data", args=[self.project.id]))
        self.assertEqual(data.status_code, 200)
        body = data.json()
        self.assertIn("/files/assets/hero.jpg", body["html"])
        self.assertNotIn('src="../assets/', body["html"])
        # Local CSS is inlined so GrapesJS does not depend on relative <link> loading.
        inline_blob = "\n".join(body.get("inlineStyles") or [])
        self.assertIn("body{color:red}", inline_blob)

    def test_inline_css_promotes_at_import_to_canvas_styles(self):
        from builder.services.editor_assets import inline_local_stylesheets

        assets = self.project.source_dir / "assets"
        (assets / "app.css").write_text(
            '@import "https://fonts.googleapis.com/css2?family=Jost";\nbody{color:navy}',
            encoding="utf-8",
        )
        inline, remote = inline_local_stylesheets(
            ["assets/app.css"],
            source_root=self.project.source_dir,
            project_file_prefix=f"/projects/{self.project.id}/files/",
            origin="http://testserver",
        )
        self.assertEqual(len(inline), 1)
        self.assertIn("body{color:navy}", inline[0])
        self.assertNotIn("@import", inline[0])
        self.assertIn("https://fonts.googleapis.com/css2?family=Jost", remote)

    def test_absolutize_project_data_rewrites_hydrated_hero_paths(self):
        from builder.services.editor_assets import absolutize_data_urls

        hydrated = self.project.source_dir / "siaw-hydrated"
        hydrated.mkdir(parents=True, exist_ok=True)
        (hydrated / "hero-1.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        project_data = {
            "assets": [
                {
                    "type": "image",
                    "src": "siaw-hydrated/hero-1.jpg",
                    "name": "hero-1.jpg",
                    "relativePath": "siaw-hydrated/hero-1.jpg",
                }
            ],
            "pages": [
                {
                    "frames": [
                        {
                            "component": {
                                "type": "image",
                                "attributes": {"src": "siaw-hydrated/hero-1.jpg"},
                            }
                        }
                    ]
                }
            ],
        }
        absolute = absolutize_data_urls(
            project_data,
            source_root=self.project.source_dir,
            entry_file=self.project.entry_file,
            project_file_prefix=f"/projects/{self.project.id}/files/",
            origin="http://testserver",
        )
        expected = f"http://testserver/projects/{self.project.id}/files/siaw-hydrated/hero-1.jpg"
        self.assertEqual(absolute["assets"][0]["src"], expected)
        self.assertEqual(absolute["assets"][0]["relativePath"], "siaw-hydrated/hero-1.jpg")
        self.assertEqual(absolute["pages"][0]["frames"][0]["component"]["attributes"]["src"], expected)


class AIWebsiteBuilderTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(
            MEDIA_ROOT=self.temp_dir.name,
            SIAW_AI_FORCE_OFFLINE=True,
            SIAW_AI_PROVIDER="offline",
            SIAW_AI_API_KEY="",
            OPENAI_API_KEY="",
        )
        self.override.enable()
        self.user = _make_user("ai-user")

    def tearDown(self):
        self.override.disable()
        self.temp_dir.cleanup()

    def test_dashboard_shows_ai_builder(self):
        response = self.client.get(reverse("builder:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create with AI")
        self.assertContains(response, "generateForm")
        self.assertContains(response, "Log in to generate")
        self.assertContains(response, "Sign up")
        self.assertContains(response, "Pricing")
        self.assertContains(response, 'id="pricing"')
        self.assertContains(response, 'id="services"')
        self.assertContains(response, 'id="features"')
        self.assertContains(response, "hero-demo")
        self.assertContains(response, "hero-guide-mouse")
        self.assertContains(response, "Drop to replace")
        self.assertContains(response, "Start building now")
        self.assertContains(response, "data-hero-edit")
        self.assertContains(response, "Prompt a site. Edit by hand.")
        self.assertContains(response, 'data-site-edit="hero.headline"')
        # Django runs tests with DEBUG=False, so local edit chrome stays off by default.
        self.assertNotContains(response, 'data-site-edit="1"')
        self.assertNotContains(response, "site-edit.js")

    def test_site_edit_chrome_enabled_when_debug_on_localhost(self):
        with self.settings(DEBUG=True):
            response = self.client.get(reverse("builder:dashboard"), HTTP_HOST="127.0.0.1")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-site-edit="1"')
        self.assertContains(response, "site-edit.js")

    def test_site_edit_save_updates_template_on_localhost(self):
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "templates" / "builder" / "dashboard.html"
        original = path.read_text(encoding="utf-8")
        try:
            with self.settings(DEBUG=True):
                response = self.client.post(
                    reverse("builder:save_site_edit"),
                    data=json.dumps({
                        "edits": [{"key": "hero.lead", "value": "Local edit smoke test.", "kind": "text"}],
                    }),
                    content_type="application/json",
                    HTTP_HOST="127.0.0.1",
                )
            self.assertEqual(response.status_code, 200, response.content)
            self.assertTrue(response.json()["ok"])
            self.assertIn("Local edit smoke test.", path.read_text(encoding="utf-8"))
        finally:
            path.write_text(original, encoding="utf-8")

    def test_site_edit_save_blocked_when_debug_off(self):
        response = self.client.post(
            reverse("builder:save_site_edit"),
            data=json.dumps({
                "edits": [{"key": "hero.lead", "value": "Should not write.", "kind": "text"}],
            }),
            content_type="application/json",
            HTTP_HOST="127.0.0.1",
        )
        self.assertEqual(response.status_code, 403)

    def test_project_thumbnail_uses_hero_image(self):
        from builder.services.thumbnails import project_thumbnail

        project = WebsiteProject.objects.create(name="Thumb Site", entry_file="index.html")
        source = project.source_dir
        source.mkdir(parents=True, exist_ok=True)
        (source / "index.html").write_text(
            '<!doctype html><html><body><img src="https://images.unsplash.com/photo-test.jpg" alt="Hero"></body></html>',
            encoding="utf-8",
        )
        thumb = project_thumbnail(project)
        self.assertEqual(thumb["kind"], "image")
        self.assertIn("unsplash.com", thumb["src"])

    def test_login_shows_and_accepts_demo_account(self):
        from django.contrib.auth.models import User

        page = self.client.get(reverse("builder:login"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Demo account")
        self.assertContains(page, "siawdemo123")
        self.assertContains(page, 'value="demo"')
        self.assertTrue(User.objects.filter(username="demo").exists())

        login = self.client.post(
            reverse("builder:login"),
            data={"username": "demo", "password": "siawdemo123"},
        )
        self.assertEqual(login.status_code, 302)
        dash = self.client.get(reverse("builder:dashboard"))
        self.assertContains(dash, "Log out")
        self.assertContains(dash, "demo")

    def test_signup_login_logout_and_pricing(self):
        from django.contrib.auth.models import User

        pricing = self.client.get(reverse("builder:pricing"))
        self.assertEqual(pricing.status_code, 200)
        self.assertContains(pricing, "Pro")

        signup = self.client.post(
            reverse("builder:signup"),
            data={
                "username": "harborhost",
                "email": "host@harbor.test",
                "password1": "siaw-test-pass-99",
                "password2": "siaw-test-pass-99",
            },
        )
        self.assertEqual(signup.status_code, 302)
        self.assertTrue(User.objects.filter(username="harborhost").exists())

        self.client.get(reverse("builder:logout"))
        login = self.client.post(
            reverse("builder:login"),
            data={"username": "harborhost", "password": "siaw-test-pass-99"},
        )
        self.assertEqual(login.status_code, 302)
        dash = self.client.get(reverse("builder:dashboard"))
        self.assertContains(dash, "Log out")
        self.assertContains(dash, "harborhost")

    def test_login_next_upload_redirects_to_dashboard(self):
        User.objects.create_user(username="uploadnext", password="siaw-test-pass-99")
        response = self.client.post(
            f"{reverse('builder:login')}?next=/projects/upload/",
            data={"username": "uploadnext", "password": "siaw-test-pass-99"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/#workspace", response["Location"])

    def test_upload_get_redirects_to_dashboard(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("builder:upload_project"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/#workspace", response["Location"])

    def test_generate_project_offline_opens_safe_edit(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("builder:generate_project"),
            data={
                "name": "Alvora Demo",
                "prompt": "Luxury fragrance boutique in Accra called Alvora with warm cream tones and perfume photography.",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("mode=safe", response["Location"])
        project = WebsiteProject.objects.get(name="Alvora Demo")
        self.assertEqual(project.owner_id, self.user.id)
        self.assertEqual(project.entry_file, "index.html")
        html = project.entry_path.read_text(encoding="utf-8")
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Alvora", html)
        self.assertTrue((project.source_dir / "features.html").is_file())
        self.assertTrue((project.source_dir / "story.html").is_file())
        self.assertTrue((project.source_dir / "contact.html").is_file())
        self.assertIn('href="features.html"', html)
        self.assertTrue((project.project_dir / "original.zip").is_file())

        data = self.client.get(reverse("builder:editor_data", args=[project.id]))
        self.assertEqual(data.status_code, 200)
        payload = data.json()
        self.assertEqual(payload["mode"], "visual")
        self.assertIn("Alvora", payload["html"])
        details = payload["compatibility"]["pageDetails"]
        paths = [item["path"] for item in details]
        self.assertIn("features.html", paths)
        self.assertTrue(
            any(item.get("label") in {"Features", "Collection", "Menu"} for item in details)
        )

        pages = self.client.get(reverse("builder:project_pages", args=[project.id]))
        self.assertEqual(pages.status_code, 200)
        self.assertGreaterEqual(len(pages.json()["pages"]), 4)

    def test_detect_sector_and_brief(self):
        from builder.services.ai_builder import build_brief, detect_sector, render_offline_site

        self.assertEqual(detect_sector("luxury perfume boutique"), "luxury")
        brief = build_brief("Create a restaurant website called Harbor Table", project_name="Harbor")
        self.assertEqual(brief.sector, "food")
        self.assertIn("Harbor", brief.brand)
        files = render_offline_site(brief)
        total = sum(len(v) for v in files.values())
        self.assertGreaterEqual(total, 12000)
        self.assertIn("features.html", files)
        self.assertIn("story.html", files)
        self.assertIn("contact.html", files)
        self.assertIn("styles.css", files)
        self.assertIn('id="features"', files["index.html"])
