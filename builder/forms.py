from django import forms


class WebsiteGenerateForm(forms.Form):
    name = forms.CharField(
        max_length=160,
        label="Project name",
        widget=forms.TextInput(attrs={"placeholder": "e.g. Alvora Beauty"}),
    )
    prompt = forms.CharField(
        label="Describe the website",
        widget=forms.Textarea(
            attrs={
                "rows": 5,
                "placeholder": (
                    "e.g. Luxury fragrance boutique in Accra called Alvora. "
                    "Warm cream tones, elegant serif headlines, hero with perfume photography, "
                    "featured scents, boutique locations, and a book-a-visit CTA."
                ),
            }
        ),
    )

    def clean_prompt(self):
        value = (self.cleaned_data.get("prompt") or "").strip()
        if len(value) < 12:
            raise forms.ValidationError("Add a bit more detail so the builder can design the page.")
        if len(value) > 4000:
            raise forms.ValidationError("Keep the brief under 4000 characters.")
        return value


class WebsiteUploadForm(forms.Form):
    name = forms.CharField(
        max_length=160,
        label="Project name",
        widget=forms.TextInput(attrs={"placeholder": "e.g. My website"}),
    )
    website_zip = forms.FileField(
        label="Website file",
        required=True,
        help_text="Upload a folder, .zip, or an HTML file.",
        widget=forms.ClearableFileInput(
            attrs={
                "accept": (
                    ".zip,.html,.htm,.css,.js,.json,.md,.txt,"
                    "application/zip,text/html,text/css,text/javascript,text/plain"
                ),
            }
        ),
    )
    entry_file = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.HiddenInput(attrs={"data-entry-file": "true"}),
    )

    def clean_website_zip(self):
        uploaded = self.cleaned_data.get("website_zip")
        if not uploaded:
            raise forms.ValidationError("Choose a folder, ZIP, or HTML file to import.")
        name = uploaded.name.lower()
        allowed_suffixes = (
            ".zip", ".html", ".htm", ".css", ".js", ".json", ".md", ".txt",
        )
        if not name.endswith(allowed_suffixes):
            raise forms.ValidationError("Please upload a folder ZIP, archive, or HTML file.")
        if uploaded.size > 25 * 1024 * 1024:
            raise forms.ValidationError("The file must be 25 MB or smaller for this MVP.")
        return uploaded

    def clean_entry_file(self):
        value = (self.cleaned_data.get("entry_file") or "").strip().replace("\\", "/").lstrip("/")
        if not value:
            return ""
        if ".." in value.split("/"):
            raise forms.ValidationError("Invalid entry file path.")
        return value
