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

    def test_delete_project_soft_deletes_then_purge_removes_files(self):
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
        project.refresh_from_db()
        self.assertIsNotNone(project.deleted_at)
        self.assertTrue(project_dir.exists())
        purged = self.client.post(reverse("builder:purge_project", args=[project.id]))
        self.assertEqual(purged.status_code, 302)
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

    def test_recover_shopify_media_urls_from_ngrok_proxy(self):
        from builder.services.editor_assets import recover_shopify_media_urls

        html = (
            '<img src="https://abc.ngrok-free.app/s/files/1/0982/2925/6474/files/hero.png?v=1">'
            '<img src="/s/files/1/0982/2925/6474/files/card.png">'
            '<img src="https://cdn.shopify.com/s/files/1/0982/2925/6474/files/ok.png">'
        )
        fixed = recover_shopify_media_urls(html)
        self.assertIn("https://cdn.shopify.com/s/files/1/0982/2925/6474/files/hero.png?v=1", fixed)
        self.assertIn("https://cdn.shopify.com/s/files/1/0982/2925/6474/files/card.png", fixed)
        self.assertIn("https://cdn.shopify.com/s/files/1/0982/2925/6474/files/ok.png", fixed)
        self.assertNotIn("ngrok-free.app", fixed)
        self.assertNotIn('src="/s/files/', fixed)

    def test_localize_shopify_media_downloads_into_project(self):
        from unittest.mock import patch

        from builder.services.remote_media import localize_shopify_media_in_text

        html = (
            '<img src="https://abc.ngrok-free.app/s/files/1/0982/2925/6474/files/hero.png?v=1">'
            '<img src="https://cdn.shopify.com/s/files/1/0982/2925/6474/files/card.png">'
        )
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
            b"\x01\x01\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        with patch("builder.services.remote_media.download_remote_image", return_value=png):
            updated, count = localize_shopify_media_in_text(html, self.project.source_dir)
        self.assertEqual(count, 2)
        self.assertIn("images/shopify/", updated)
        self.assertNotIn("ngrok-free.app", updated)
        self.assertNotIn("cdn.shopify.com", updated)
        self.assertTrue(any((self.project.source_dir / "images" / "shopify").glob("*.png")))
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
        self.assertContains(response, "Log in to build")
        self.assertContains(response, "next=/workspace/ai/")
        self.assertContains(response, "personal AI Builder")
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

    def test_site_edit_reorder_and_image_upload(self):
        from pathlib import Path

        from django.core.files.uploadedfile import SimpleUploadedFile

        pricing = Path(__file__).resolve().parents[1] / "templates" / "builder" / "partials" / "pricing_section.html"
        original = pricing.read_text(encoding="utf-8")
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
        )
        uploaded_path = None
        try:
            with self.settings(DEBUG=True):
                upload = self.client.post(
                    reverse("builder:upload_site_edit_image"),
                    {"image": SimpleUploadedFile("dot.png", png, content_type="image/png")},
                    HTTP_HOST="127.0.0.1",
                )
                self.assertEqual(upload.status_code, 200, upload.content)
                url = upload.json()["url"]
                uploaded_path = Path(__file__).resolve().parents[1] / upload.json()["path"]
                self.assertTrue(uploaded_path.is_file())

                save = self.client.post(
                    reverse("builder:save_site_edit"),
                    data=json.dumps({
                        "edits": [{"kind": "reorder", "group": "pricing", "order": ["studio", "free", "pro"]}],
                    }),
                    content_type="application/json",
                    HTTP_HOST="127.0.0.1",
                )
            self.assertEqual(save.status_code, 200, save.content)
            text = pricing.read_text(encoding="utf-8")
            self.assertLess(text.index('data-site-block="pricing:studio"'), text.index('data-site-block="pricing:free"'))
            self.assertTrue(url.startswith("/static/builder/site-edits/"))
        finally:
            pricing.write_text(original, encoding="utf-8")
            if uploaded_path and uploaded_path.exists():
                uploaded_path.unlink()

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
        self.assertIn("/workspace/", login["Location"])
        workspace = self.client.get(reverse("builder:workspace"))
        self.assertContains(workspace, "Open AI Builder")
        self.assertContains(workspace, "Log out")
        self.assertContains(workspace, "demo")
        ai_entry = self.client.get(f"{reverse('builder:ai_builder')}?new=1")
        self.assertEqual(ai_entry.status_code, 302)
        self.assertIn("/workspace/ai/", ai_entry["Location"])
        wizard = self.client.get(ai_entry["Location"])
        self.assertEqual(wizard.status_code, 200)
        self.assertContains(wizard, "Creative brief")
        self.assertContains(wizard, "Tell us about your idea.")
        self.assertContains(wizard, "data-step-panel")
        self.assertContains(wizard, "Step 1 of 2")
        self.assertContains(wizard, "industrySelect")
        self.assertNotContains(wizard, "How should we begin?")
        self.assertNotContains(wizard, "Create something new")
        self.assertNotContains(wizard, "Redesign a website")
        self.assertNotContains(wizard, "Main button text")
        prompt_page = self.client.get(reverse("builder:ai_builder_prompt"))
        self.assertEqual(prompt_page.status_code, 200)
        self.assertContains(prompt_page, "generateForm")
        self.assertContains(prompt_page, "Advanced path")
        self.assertContains(prompt_page, "Use guided brief")
        self.assertContains(prompt_page, "Open the guided brief instead")
        self.assertContains(prompt_page, "Prefer guided questions?")
        workspace = self.client.get(reverse("builder:workspace"))
        self.assertContains(workspace, "Advanced: paste a prompt")
        dash = self.client.get(reverse("builder:dashboard"))
        self.assertNotContains(dash, "Start building now")
        self.assertContains(dash, "Open AI Builder")

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
        self.assertIn("/workspace/", signup["Location"])
        self.assertTrue(User.objects.filter(username="harborhost").exists())

        self.client.get(reverse("builder:logout"))
        login = self.client.post(
            reverse("builder:login"),
            data={"username": "harborhost", "password": "siaw-test-pass-99"},
        )
        self.assertEqual(login.status_code, 302)
        self.assertIn("/workspace/", login["Location"])
        workspace = self.client.get(reverse("builder:workspace"))
        self.assertContains(workspace, "Log out")
        self.assertContains(workspace, "harborhost")

    def test_login_next_upload_redirects_to_workspace(self):
        User.objects.create_user(username="uploadnext", password="siaw-test-pass-99")
        response = self.client.post(
            f"{reverse('builder:login')}?next=/projects/upload/",
            data={"username": "uploadnext", "password": "siaw-test-pass-99"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/workspace/", response["Location"])

    def test_upload_get_redirects_to_workspace(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("builder:upload_project"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/workspace/", response["Location"])

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

    def test_ai_generate_starts_build_with_short_description(self):
        from builder.models import AIWebsiteBrief
        from builder.services.ai_prefetch import brief_can_prefetch

        self.client.force_login(self.user)
        brief = AIWebsiteBrief.objects.create(
            owner=self.user,
            business_name="lare",
            industry="Health and wellness",
            description="we sell and distribute gym tools",
            primary_goal="book",
            primary_cta={"goals": ["book", "leads", "credibility"]},
            status="ready",
        )
        self.assertTrue(brief_can_prefetch(brief))

        response = self.client.post(
            reverse("builder:ai_generate", args=[brief.id]),
            HTTP_ACCEPT="application/json",
        )
        self.assertIn(response.status_code, {200, 202})
        payload = response.json()
        self.assertFalse(payload.get("failed"))
        if response.status_code == 202:
            self.assertTrue(payload.get("building"))
        else:
            self.assertTrue(payload.get("redirectUrl") or payload.get("ready"))

    def test_assembled_build_prompt_can_exceed_user_brief_limit(self):
        from django.core.exceptions import ValidationError

        from builder.services.ai_builder import MAX_PROMPT_CHARS, _clean_prompt
        from builder.services.sitewright_prompt import sitewright_quality_rules

        assembled = (
            f"{sitewright_quality_rules(multipage=True)}\n\n"
            "WEBSITE GOALS (prioritize in this order, max three)\n"
            "- 1. PRIORITY (user-defined): Get parents to enroll this term\n"
            "STRUCTURED SPEC (for reference)\n"
            + ("x" * 5000)
        )
        self.assertGreater(len(assembled), MAX_PROMPT_CHARS)
        cleaned = _clean_prompt(assembled)
        self.assertIn("Siaw Sitewright", cleaned)
        self.assertIn("\n", cleaned)

        with self.assertRaises(ValidationError) as ctx:
            _clean_prompt("short user paste " + ("y" * 4100))
        self.assertIn("Keep the brief under 4000 characters.", str(ctx.exception))

    def test_custom_other_goal_is_priority_in_prompt(self):
        from builder.models import AIWebsiteBrief
        from builder.services.ai_website import brief_goals, brief_to_generation_prompt, display_goal

        self.client.force_login(self.user)
        brief = AIWebsiteBrief.objects.create(
            owner=self.user,
            business_name="class statr",
            industry="Education and coaching",
            description="After-school coding classes for kids who want a stronger start.",
            location="berlin",
            primary_goal="other",
            primary_cta={
                "goals": ["educate", "book", "other"],
                "other": "Get parents to enroll this term",
            },
        )
        self.assertEqual(brief_goals(brief)[0], "other")
        self.assertEqual(display_goal("other", brief), "Get parents to enroll this term")
        prompt = brief_to_generation_prompt(brief)
        self.assertIn("PRIORITY (user-defined): Get parents to enroll this term", prompt)
        self.assertLess(
            prompt.index("PRIORITY (user-defined)"),
            prompt.index("Explain the offer"),
        )

    def test_question_tailor_varies_goals_step_from_idea(self):
        from builder.services.question_tailor import tailor_goals_question

        restaurant = tailor_goals_question(
            business_name="Harbor Table",
            industry="Restaurants and hospitality",
            description="A warm Accra restaurant for couples booking weekend dinners and tasting menus.",
            location="Accra, Ghana",
            language="English",
        )
        saas = tailor_goals_question(
            business_name="Slow Lion",
            industry="Technology and SaaS",
            description="B2B software with a free trial for ops teams who need clearer workflows.",
            location="Worldwide",
            language="English",
        )
        self.assertIn("Harbor Table", restaurant["headline"])
        self.assertIn("Accra", restaurant["lead"])
        self.assertEqual(restaurant["goals"][0]["value"], "reserve")
        self.assertIn("table", restaurant["goals"][0]["desc"].lower())

        self.assertIn("Slow Lion", saas["headline"])
        self.assertNotEqual(restaurant["headline"], saas["headline"])
        self.assertEqual(saas["goals"][0]["value"], "trial")
        self.assertIn("trial", saas["lead"].lower())
        self.assertNotIn("—", restaurant["headline"] + restaurant["lead"])

        again = tailor_goals_question(
            business_name="Harbor Table",
            industry="Restaurants and hospitality",
            description="A warm Accra restaurant for couples booking weekend dinners and tasting menus.",
            location="Accra, Ghana",
            language="English",
        )
        self.assertEqual(restaurant, again)

    def test_sitewright_quality_rules_in_build_prompts(self):
        from builder.services.ai_builder import _codex_build_prompt, build_brief
        from builder.services.sitewright_prompt import sitewright_quality_rules

        single = sitewright_quality_rules(multipage=False)
        multi = sitewright_quality_rules(multipage=True)
        self.assertIn("Siaw Sitewright", single)
        self.assertIn("No em dashes", single)
        self.assertIn('href="#features"', single)
        self.assertIn("separate .html files", multi)
        self.assertNotIn("ONE complete homepage", multi)
        self.assertNotIn("—", single)
        self.assertNotIn("—", multi)

        brief = build_brief("Cafe website for Harbor Roast", project_name="Harbor")
        prompt = _codex_build_prompt("Build Harbor Roast", brief, "Harbor")
        self.assertIn("Siaw Sitewright", prompt)
        self.assertIn("EDITOR COMPATIBILITY", prompt)

    def test_ollama_is_disabled_and_codex_is_preferred(self):
        from builder.services import ai_builder
        from pathlib import Path

        fake_bin = Path(self.temp_dir.name) / "codex"
        fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
        fake_bin.chmod(0o755)

        self.assertFalse(ai_builder._ollama_reachable())
        self.assertEqual(ai_builder._ollama_list_models(), [])

        with override_settings(
            SIAW_AI_FORCE_OFFLINE=False,
            SIAW_AI_PROVIDER="ollama",
            SIAW_CODEX_DISABLE=False,
            SIAW_CODEX_BIN=str(fake_bin),
            SIAW_AI_API_KEY="",
            OPENAI_API_KEY="",
        ):
            self.assertEqual(ai_builder._resolve_provider(), "codex")
            status = ai_builder.ai_status()
            self.assertEqual(status["provider"], "codex")
            self.assertTrue(status["configured"])

        with override_settings(
            SIAW_AI_FORCE_OFFLINE=False,
            SIAW_AI_PROVIDER="ollama",
            SIAW_CODEX_DISABLE=True,
            SIAW_CODEX_BIN=str(fake_bin),
            SIAW_AI_API_KEY="",
            OPENAI_API_KEY="",
        ):
            # Without Codex or OpenAI, fall back to offline. Never Ollama.
            self.assertEqual(ai_builder._resolve_provider(), "offline")
            self.assertEqual(ai_builder._resolve_chat_provider(), "offline")

        with override_settings(
            SIAW_AI_FORCE_OFFLINE=False,
            SIAW_AI_PROVIDER="auto",
            SIAW_CODEX_DISABLE=False,
            SIAW_CODEX_BIN=str(fake_bin),
            SIAW_CODEX_MODEL="gpt-5.6-sol",
            SIAW_AI_API_KEY="",
            OPENAI_API_KEY="",
        ):
            self.assertEqual(ai_builder._resolve_chat_provider(), "codex")
            chat = ai_builder._ai_settings(chat=True)
            self.assertEqual(chat["provider"], "codex")
            self.assertEqual(chat["model"], "gpt-5.6-sol")

    def test_create_website_from_prompt_uses_codex_path(self):
        from builder.services import ai_builder
        from pathlib import Path
        from unittest.mock import patch

        project_dir = Path(self.temp_dir.name) / "codex-project"
        project_dir.mkdir()

        def fake_codex(project_dir, *, prompt, project_name="", brief=None, seed_files=None):
            source = project_dir / "source"
            source.mkdir(parents=True, exist_ok=True)
            (source / "index.html").write_text(
                "<!DOCTYPE html><html><body><h1>Codex Site</h1>"
                '<section id="features"></section><section id="story"></section>'
                '<section id="proof"></section><section id="contact"></section>'
                "</body></html>",
                encoding="utf-8",
            )
            return ai_builder._finalize_codex_source(
                project_dir,
                brief=brief or ai_builder.build_brief(prompt, project_name=project_name),
            )

        with override_settings(
            SIAW_AI_FORCE_OFFLINE=False,
            SIAW_AI_PROVIDER="codex",
            SIAW_CODEX_DISABLE=False,
            SIAW_CODEX_BIN=str(Path(self.temp_dir.name) / "missing-codex"),
        ):
            with patch.object(ai_builder, "_codex_available", return_value=True):
                with patch.object(ai_builder, "create_website_with_codex", side_effect=fake_codex):
                    result = ai_builder.create_website_from_prompt(
                        project_dir,
                        prompt="Build a cafe website called Harbor",
                        project_name="Harbor",
                    )
        self.assertEqual(result.provider, "codex")
        self.assertEqual(result.entry_file, "index.html")
        self.assertIn("Codex Site", (project_dir / "source" / "index.html").read_text(encoding="utf-8"))


class MultiUserTenancyAndPlansTests(TestCase):
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
        self.owner = _make_user("owner-a")
        self.intruder = _make_user("intruder-b")
        self.project = WebsiteProject.objects.create(
            name="Owner Site",
            entry_file="index.html",
            owner=self.owner,
        )
        self.project.source_dir.mkdir(parents=True)
        self.project.entry_path.write_text(
            "<!doctype html><html><body><h1>Private</h1></body></html>",
            encoding="utf-8",
        )

    def tearDown(self):
        self.override.disable()
        self.temp_dir.cleanup()

    def test_intruder_cannot_open_owner_project_routes(self):
        self.client.force_login(self.intruder)
        for name in ("editor", "preview", "editor_data", "export_project"):
            response = self.client.get(reverse(f"builder:{name}", args=[self.project.id]))
            self.assertEqual(response.status_code, 404, name)
        runtime = self.client.get(reverse("builder:runtime_site", args=[self.project.id]))
        self.assertEqual(runtime.status_code, 404)
        files = self.client.get(
            reverse("builder:project_file", kwargs={"project_id": self.project.id, "file_path": "index.html"})
        )
        self.assertEqual(files.status_code, 404)

    def test_anonymous_cannot_preview_or_runtime(self):
        preview = self.client.get(reverse("builder:preview", args=[self.project.id]))
        self.assertEqual(preview.status_code, 302)
        runtime = self.client.get(reverse("builder:runtime_site", args=[self.project.id]))
        self.assertEqual(runtime.status_code, 404)
        host = f"{self.project.id}.runtime.localhost:8000"
        isolated = self.client.get("/", HTTP_HOST=host)
        self.assertEqual(isolated.status_code, 404)

    def test_anonymous_runtime_assets_work_without_access_cookie(self):
        """Preview iframes are cross-site; CSS must load even when the access cookie is blocked."""
        (self.project.source_dir / "styles.css").write_text("body{color:#111}", encoding="utf-8")
        (self.project.source_dir / "script.js").write_text("console.log('ok')", encoding="utf-8")
        host = f"{self.project.id}.runtime.localhost:8000"
        css = self.client.get("/styles.css", HTTP_HOST=host)
        self.assertEqual(css.status_code, 200)
        self.assertIn(b"color:#111", b"".join(css.streaming_content))
        js = self.client.get("/script.js", HTTP_HOST=host)
        self.assertEqual(js.status_code, 200)
        html = self.client.get("/", HTTP_HOST=host)
        self.assertEqual(html.status_code, 404)

    def test_owner_runtime_and_preview_still_work(self):
        self.client.force_login(self.owner)
        preview = self.client.get(reverse("builder:preview", args=[self.project.id]))
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, "access=")
        runtime = self.client.get(reverse("builder:runtime_site", args=[self.project.id]))
        self.assertEqual(runtime.status_code, 200)
        host = f"{self.project.id}.runtime.localhost:8000"
        isolated = self.client.get("/", HTTP_HOST=host)
        self.assertEqual(isolated.status_code, 200)

    def test_soft_delete_hides_project_and_undelete_restores(self):
        self.client.force_login(self.owner)
        deleted = self.client.post(reverse("builder:delete_project", args=[self.project.id]))
        self.assertEqual(deleted.status_code, 302)
        self.project.refresh_from_db()
        self.assertIsNotNone(self.project.deleted_at)
        editor = self.client.get(reverse("builder:editor", args=[self.project.id]))
        self.assertEqual(editor.status_code, 404)
        account = self.client.get(reverse("builder:account"))
        self.assertEqual(account.status_code, 200)
        self.assertContains(account, "Owner Site")
        restored = self.client.post(reverse("builder:undelete_project", args=[self.project.id]))
        self.assertEqual(restored.status_code, 302)
        self.project.refresh_from_db()
        self.assertIsNone(self.project.deleted_at)

    def test_free_plan_blocks_third_project_and_fourth_ai_generation(self):
        from builder.services.plans import ensure_profile, record_ai_generation

        self.client.force_login(self.owner)
        profile = ensure_profile(self.owner)
        self.assertEqual(profile.plan, "free")
        WebsiteProject.objects.create(name="Second", entry_file="index.html", owner=self.owner)
        blocked = self.client.post(
            reverse("builder:generate_project"),
            data={
                "name": "Third",
                "prompt": "Luxury fragrance boutique in Accra called Alvora with warm cream tones.",
            },
        )
        self.assertEqual(blocked.status_code, 400)
        self.assertContains(blocked, "allows 2 active projects", status_code=400)

        from django.utils import timezone as dj_timezone

        WebsiteProject.objects.filter(owner=self.owner).exclude(id=self.project.id).update(
            deleted_at=dj_timezone.now()
        )
        for _ in range(3):
            record_ai_generation(self.owner)
        ai_blocked = self.client.post(
            reverse("builder:generate_project"),
            data={
                "name": "AI Over Limit",
                "prompt": "Luxury fragrance boutique in Accra called Alvora with warm cream tones.",
            },
        )
        self.assertEqual(ai_blocked.status_code, 400)
        self.assertContains(ai_blocked, "AI generations this month", status_code=400)

    def test_account_can_change_plan_and_password(self):
        self.client.force_login(self.owner)
        plan = self.client.post(
            reverse("builder:account"),
            data={"action": "plan", "plan": "pro"},
        )
        self.assertEqual(plan.status_code, 302)
        from builder.services.plans import ensure_profile

        self.assertEqual(ensure_profile(self.owner).plan, "pro")
        password = self.client.post(
            reverse("builder:account"),
            data={
                "action": "password",
                "old_password": "siaw-test-pass-99",
                "new_password1": "siaw-new-pass-22",
                "new_password2": "siaw-new-pass-22",
            },
        )
        self.assertEqual(password.status_code, 302)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password("siaw-new-pass-22"))

    def test_pro_plan_unlocks_project_limit(self):
        from builder.services.plans import ensure_profile

        self.client.force_login(self.owner)
        WebsiteProject.objects.create(name="Second", entry_file="index.html", owner=self.owner)
        blocked = self.client.post(
            reverse("builder:generate_project"),
            data={
                "name": "Third",
                "prompt": "Luxury fragrance boutique in Accra called Alvora with warm cream tones.",
            },
        )
        self.assertEqual(blocked.status_code, 400)
        profile = ensure_profile(self.owner)
        profile.plan = "pro"
        profile.save(update_fields=["plan", "updated_at"])
        allowed = self.client.post(
            reverse("builder:generate_project"),
            data={
                "name": "Third",
                "prompt": "Luxury fragrance boutique in Accra called Alvora with warm cream tones.",
            },
        )
        self.assertEqual(allowed.status_code, 302)
        self.assertTrue(WebsiteProject.objects.filter(owner=self.owner, name="Third", deleted_at__isnull=True).exists())
        workspace = self.client.get(reverse("builder:workspace"))
        self.assertEqual(workspace.status_code, 200)
        self.assertContains(workspace, "Pro")


class ShopifyConnectTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="shop-owner", password="siaw-test-pass-99")
        self.client.force_login(self.user)

    def test_normalize_and_token_roundtrip(self):
        from builder.services.shopify.oauth import normalize_shop_domain
        from builder.services.shopify.tokens import decrypt_token, encrypt_token

        self.assertEqual(normalize_shop_domain("Cool-Store"), "cool-store.myshopify.com")
        self.assertEqual(
            normalize_shop_domain("https://Cool-Store.myshopify.com/admin"),
            "cool-store.myshopify.com",
        )
        with self.assertRaises(ValueError):
            normalize_shop_domain("not a shop!!!")
        token = "shpat_test_access_token_value"
        self.assertEqual(decrypt_token(encrypt_token(token)), token)

    def test_oauth_hmac_and_connect_redirect(self):
        import hashlib
        import hmac

        from django.test import override_settings

        from builder.services.shopify.oauth import verify_oauth_hmac

        secret = "shopify-test-secret"
        params = {
            "code": "abc",
            "shop": "demo-store.myshopify.com",
            "state": "xyz",
            "timestamp": "1710000000",
        }
        message = "&".join(f"{k}={params[k]}" for k in sorted(params))
        params["hmac"] = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
        with override_settings(SHOPIFY_API_SECRET=secret):
            self.assertTrue(verify_oauth_hmac(params))
            bad = dict(params)
            bad["hmac"] = "0" * 64
            self.assertFalse(verify_oauth_hmac(bad))

        with override_settings(SHOPIFY_API_KEY="key123", SHOPIFY_API_SECRET=secret):
            account = self.client.get(reverse("builder:account"))
            self.assertEqual(account.status_code, 200)
            self.assertContains(account, "Connect Shopify store")
            workspace = self.client.get(reverse("builder:workspace"))
            self.assertContains(workspace, "Build from Shopify")
            start = self.client.post(
                reverse("builder:shopify_connect"),
                data={"shop": "demo-store.myshopify.com"},
            )
            self.assertEqual(start.status_code, 302)
            self.assertIn("demo-store.myshopify.com/admin/oauth/authorize", start["Location"])
            self.assertIn("client_id=key123", start["Location"])

    def test_callback_stores_shop_and_build_seeds_brief(self):
        import hashlib
        import hmac
        from unittest.mock import patch

        from django.test import override_settings

        from builder.models import AIWebsiteBrief, ShopifyShop
        from builder.services.shopify.oauth import make_oauth_state
        from builder.services.shopify.tokens import decrypt_token

        secret = "shopify-test-secret"
        state = make_oauth_state(user_id=self.user.id, next_url="/account/#shopify")
        params = {
            "code": "auth-code-1",
            "shop": "demo-store.myshopify.com",
            "state": state,
            "timestamp": "1710000000",
        }
        message = "&".join(f"{k}={params[k]}" for k in sorted(params))
        params["hmac"] = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

        with override_settings(SHOPIFY_API_KEY="key123", SHOPIFY_API_SECRET=secret):
            with patch(
                "builder.views_shopify.exchange_code_for_token",
                return_value={"access_token": "shpat_live_token", "scope": "read_products"},
            ), patch(
                "builder.services.shopify.install.refresh_shop_profile",
                side_effect=lambda shop: shop,
            ):
                callback = self.client.get(reverse("builder:shopify_callback"), data=params)
            self.assertEqual(callback.status_code, 302)
            shop = ShopifyShop.objects.get(owner=self.user, shop_domain="demo-store.myshopify.com")
            self.assertTrue(shop.is_active)
            self.assertEqual(decrypt_token(shop.access_token_encrypted), "shpat_live_token")

            with patch(
                "builder.services.shopify.catalog.catalog_snapshot",
                return_value={
                    "shop": {
                        "domain": shop.shop_domain,
                        "name": "Demo Store",
                        "email": "owner@example.com",
                        "primary_domain": "demo.example",
                        "currency": "USD",
                        "plan_name": "Basic",
                        "description": "Handmade goods",
                    },
                    "products": [
                        {
                            "title": "Canvas Tote",
                            "handle": "canvas-tote",
                            "status": "ACTIVE",
                            "description": "Sturdy tote",
                            "price_amount": "28.00",
                            "price_currency": "USD",
                            "image_url": "",
                            "online_store_url": "https://demo.example/products/canvas-tote",
                        }
                    ],
                    "product_count": 1,
                },
            ):
                build = self.client.post(reverse("builder:shopify_build_site", args=[shop.id]))
            self.assertEqual(build.status_code, 302)
            brief = AIWebsiteBrief.objects.get(owner=self.user, starting_point="shopify")
            self.assertEqual(brief.business_name, "Demo Store")
            self.assertEqual(brief.industry, "Ecommerce and retail")
            self.assertEqual(brief.services_json[0]["name"], "Canvas Tote")
            self.assertIn(str(brief.id), build["Location"])

    def test_webhook_uninstall_deactivates_shop(self):
        import base64
        import hashlib
        import hmac

        from django.test import override_settings

        from builder.models import ShopifyShop
        from builder.services.shopify.tokens import encrypt_token

        secret = "shopify-test-secret"
        shop = ShopifyShop.objects.create(
            owner=self.user,
            shop_domain="demo-store.myshopify.com",
            access_token_encrypted=encrypt_token("shpat_x"),
            is_active=True,
        )
        body = b'{"id":1}'
        digest = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
        with override_settings(SHOPIFY_API_SECRET=secret):
            response = self.client.post(
                reverse("builder:shopify_webhook"),
                data=body,
                content_type="application/json",
                headers={
                    "X-Shopify-Hmac-Sha256": digest,
                    "X-Shopify-Topic": "app/uninstalled",
                    "X-Shopify-Shop-Domain": "demo-store.myshopify.com",
                },
            )
        self.assertEqual(response.status_code, 200)
        shop.refresh_from_db()
        self.assertFalse(shop.is_active)
        self.assertEqual(shop.access_token_encrypted, "")

    def _session_jwt(self, *, secret: str, api_key: str, shop: str = "demo-store.myshopify.com"):
        import base64
        import hashlib
        import hmac
        import json
        import time

        def b64(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        now = int(time.time())
        payload = b64(
            json.dumps(
                {
                    "iss": f"https://{shop}/admin",
                    "dest": f"https://{shop}",
                    "aud": api_key,
                    "sub": "1",
                    "exp": now + 60,
                    "nbf": now - 5,
                    "iat": now,
                    "jti": "test-jti",
                    "sid": "test-sid",
                }
            ).encode()
        )
        signing_input = f"{header}.{payload}".encode()
        sig = b64(hmac.new(secret.encode(), signing_input, hashlib.sha256).digest())
        return f"{header}.{payload}.{sig}"

    def test_merchant_app_home_and_install_callback(self):
        import hashlib
        import hmac
        from unittest.mock import patch

        from django.test import override_settings

        from builder.models import ShopifyShop
        from builder.services.shopify.oauth import make_oauth_state
        from builder.services.shopify.tokens import decrypt_token

        secret = "shopify-test-secret"
        api_key = "key123"
        with override_settings(SHOPIFY_API_KEY=api_key, SHOPIFY_API_SECRET=secret):
            home = self.client.get(reverse("builder:shopify_app"))
            self.assertEqual(home.status_code, 200)
            self.assertContains(home, "Siaw for Shopify")
            self.assertContains(home, "cdn.shopify.com/shopifycloud/app-bridge.js")
            self.assertIn(
                "frame-ancestors https://admin.shopify.com",
                home.get("Content-Security-Policy", ""),
            )
            self.assertNotIn("X-Frame-Options", home)

            # Uninstalled shop + valid Admin HMAC should start OAuth install.
            params = {
                "shop": "merchant-store.myshopify.com",
                "host": "YWRtaW4uc2hvcGlmeS5jb20vc3RvcmUvbWVyY2hhbnQ",
                "timestamp": "1710000000",
            }
            message = "&".join(f"{k}={params[k]}" for k in sorted(params))
            params["hmac"] = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
            install = self.client.get(reverse("builder:shopify_app"), data=params)
            self.assertEqual(install.status_code, 302)
            self.assertIn("merchant-store.myshopify.com/admin/oauth/authorize", install["Location"])

            state = make_oauth_state(mode="install", shop="merchant-store.myshopify.com")
            callback_params = {
                "code": "install-code",
                "shop": "merchant-store.myshopify.com",
                "state": state,
                "timestamp": "1710000000",
            }
            msg2 = "&".join(f"{k}={callback_params[k]}" for k in sorted(callback_params))
            callback_params["hmac"] = hmac.new(secret.encode(), msg2.encode(), hashlib.sha256).hexdigest()
            with patch(
                "builder.views_shopify.exchange_code_for_token",
                return_value={"access_token": "shpat_merchant", "scope": "read_products"},
            ), patch(
                "builder.services.shopify.install.refresh_shop_profile",
                side_effect=lambda shop: shop,
            ):
                # Merchant install should work without a logged-in Siaw user.
                self.client.logout()
                callback = self.client.get(reverse("builder:shopify_callback"), data=callback_params)
            self.assertEqual(callback.status_code, 302)
            self.assertIn("/shopify/app/", callback["Location"])
            shop = ShopifyShop.objects.get(shop_domain="merchant-store.myshopify.com")
            self.assertTrue(shop.is_active)
            self.assertIsNone(shop.owner_id)
            self.assertEqual(decrypt_token(shop.access_token_encrypted), "shpat_merchant")

    def test_session_token_exchange_and_app_build(self):
        from unittest.mock import patch

        from django.test import override_settings

        from builder.models import AIWebsiteBrief, ShopifyShop

        secret = "shopify-test-secret"
        api_key = "key123"
        jwt = self._session_jwt(secret=secret, api_key=api_key, shop="session-store.myshopify.com")
        with override_settings(SHOPIFY_API_KEY=api_key, SHOPIFY_API_SECRET=secret):
            with patch(
                "builder.views_shopify.exchange_session_token",
                return_value={"access_token": "shpat_session", "scope": "read_products"},
            ), patch(
                "builder.services.shopify.install.refresh_shop_profile",
                side_effect=lambda shop: shop,
            ):
                session = self.client.post(
                    reverse("builder:shopify_session"),
                    data=b"{}",
                    content_type="application/json",
                    headers={"Authorization": f"Bearer {jwt}"},
                )
            self.assertEqual(session.status_code, 200)
            payload = session.json()
            self.assertTrue(payload["ok"])
            shop = ShopifyShop.objects.get(shop_domain="session-store.myshopify.com")
            self.assertTrue(shop.is_active)

            with patch(
                "builder.services.shopify.catalog.catalog_snapshot",
                return_value={
                    "shop": {
                        "domain": shop.shop_domain,
                        "name": "Session Store",
                        "email": "merchant@example.com",
                        "primary_domain": "session.example",
                        "currency": "USD",
                        "plan_name": "Basic",
                        "description": "Session goods",
                    },
                    "products": [
                        {
                            "title": "Mug",
                            "handle": "mug",
                            "status": "ACTIVE",
                            "description": "Ceramic mug",
                            "price_amount": "12.00",
                            "price_currency": "USD",
                            "image_url": "",
                            "online_store_url": "https://session.example/products/mug",
                        }
                    ],
                    "product_count": 1,
                },
            ):
                build = self.client.post(
                    reverse("builder:shopify_app_build"),
                    data=b"{}",
                    content_type="application/json",
                    headers={"Authorization": f"Bearer {jwt}"},
                )
            self.assertEqual(build.status_code, 200)
            body = build.json()
            self.assertTrue(body["ok"])
            self.assertIn("/shopify/continue/", body["wizard_url"])
            brief = AIWebsiteBrief.objects.get(id=body["brief_id"])
            self.assertEqual(brief.starting_point, "shopify")
            self.assertEqual(brief.business_name, "Session Store")
            shop.refresh_from_db()
            self.assertIsNotNone(shop.owner_id)

            # Handoff logs in the shop user and opens the wizard (fixes ownership 404).
            continue_path = body["wizard_url"].split(".app", 1)[-1]
            if not continue_path.startswith("/"):
                from urllib.parse import urlparse

                continue_path = urlparse(body["wizard_url"]).path + "?" + urlparse(body["wizard_url"]).query
            opened = self.client.get(continue_path)
            self.assertEqual(opened.status_code, 302)
            self.assertIn(str(brief.id), opened["Location"])
            wizard = self.client.get(opened["Location"])
            self.assertEqual(wizard.status_code, 200)
            self.assertContains(wizard, "Session Store")
