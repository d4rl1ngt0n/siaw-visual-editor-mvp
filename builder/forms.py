from django import forms


class WebsiteUploadForm(forms.Form):
    name = forms.CharField(
        max_length=160,
        label="Project name",
        widget=forms.TextInput(attrs={"placeholder": "e.g. Order Siaw Website"}),
    )
    website_zip = forms.FileField(
        label="Project file",
        help_text="Upload a folder, .zip, or a source/HTML file from any common web stack.",
        widget=forms.ClearableFileInput(
            attrs={
                "accept": (
                    ".zip,.html,.htm,.css,.js,.ts,.tsx,.jsx,.vue,.svelte,.py,.json,.md,.txt,"
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
        uploaded = self.cleaned_data["website_zip"]
        name = uploaded.name.lower()
        allowed_suffixes = (
            ".zip", ".html", ".htm", ".css", ".js", ".ts", ".tsx", ".jsx",
            ".vue", ".svelte", ".py", ".json", ".md", ".txt", ".php",
        )
        if not name.endswith(allowed_suffixes):
            raise forms.ValidationError("Please upload a folder ZIP, archive, or supported source file.")
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
