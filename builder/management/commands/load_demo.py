from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from builder.models import WebsiteProject
from builder.services.archive import import_website_zip


class Command(BaseCommand):
    help = "Import the bundled Order Siaw Manufacturing v32 website as the demo project."

    def handle(self, *args, **options):
        demo_zip = Path(settings.BASE_DIR) / "demo_projects" / "order_siaw_manufacturing_v32.zip"
        if not demo_zip.is_file():
            raise CommandError(f"Demo ZIP not found: {demo_zip}")

        project = WebsiteProject.objects.filter(name="Order Siaw Manufacturing v32").first()
        if project and project.entry_path.is_file():
            self.stdout.write(self.style.WARNING(f"Demo already loaded: {project.id}"))
            return

        if project is None:
            project = WebsiteProject.objects.create(name="Order Siaw Manufacturing v32")

        try:
            with demo_zip.open("rb") as source:
                imported = import_website_zip(File(source, name=demo_zip.name), project.project_dir)
            project.entry_file = imported.entry_file
            project.stylesheet_files = imported.stylesheet_files
            project.save(update_fields=["entry_file", "stylesheet_files", "updated_at"])
        except Exception:
            project.delete()
            raise

        self.stdout.write(self.style.SUCCESS(f"Loaded demo project: {project.id}"))
