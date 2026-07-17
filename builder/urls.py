from django.urls import path

from . import views

app_name = "builder"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("projects/upload/", views.upload_project, name="upload_project"),
    path("projects/<uuid:project_id>/editor/", views.editor, name="editor"),
    path("projects/<uuid:project_id>/data/", views.editor_data, name="editor_data"),
    path("projects/<uuid:project_id>/save/", views.save_project, name="save_project"),
    path("projects/<uuid:project_id>/tree/", views.project_files, name="project_files"),
    path("projects/<uuid:project_id>/entry/", views.set_entry_file, name="set_entry_file"),
    path(
        "projects/<uuid:project_id>/source/<path:file_path>",
        views.source_file,
        name="source_file",
    ),
    path("projects/<uuid:project_id>/assets/upload/", views.upload_asset, name="upload_asset"),
    path("projects/<uuid:project_id>/preview/", views.preview, name="preview"),
    path("projects/<uuid:project_id>/export/", views.export_project, name="export_project"),
    path("projects/<uuid:project_id>/restore/", views.restore_original, name="restore_original"),
    path(
        "projects/<uuid:project_id>/files/<path:file_path>",
        views.project_file,
        name="project_file",
    ),
]
