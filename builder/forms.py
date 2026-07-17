from django import forms


class WebsiteUploadForm(forms.Form):
    name = forms.CharField(
        max_length=160,
        label="Project name",
        widget=forms.TextInput(attrs={"placeholder": "e.g. Order Siaw Website"}),
    )
    website_zip = forms.FileField(
        label="Website ZIP",
        help_text="Upload a static HTML website ZIP containing index.html.",
        widget=forms.ClearableFileInput(attrs={"accept": ".zip"}),
    )

    def clean_website_zip(self):
        uploaded = self.cleaned_data["website_zip"]
        if not uploaded.name.lower().endswith(".zip"):
            raise forms.ValidationError("Please upload a .zip website file.")
        if uploaded.size > 25 * 1024 * 1024:
            raise forms.ValidationError("The ZIP must be 25 MB or smaller for this MVP.")
        return uploaded
