from django import forms


class WebsiteUploadForm(forms.Form):
    name = forms.CharField(
        max_length=160,
        label="Project name",
        widget=forms.TextInput(attrs={"placeholder": "e.g. Order Siaw Website"}),
    )
    website_zip = forms.FileField(
        label="Website file",
        help_text="Upload a .zip website or a single .html file. Any HTML page can be the entry file.",
        widget=forms.ClearableFileInput(attrs={"accept": ".zip,.html,.htm,application/zip,text/html"}),
    )

    def clean_website_zip(self):
        uploaded = self.cleaned_data["website_zip"]
        name = uploaded.name.lower()
        if not name.endswith((".zip", ".html", ".htm")):
            raise forms.ValidationError("Please upload a .zip website or a .html file.")
        if uploaded.size > 25 * 1024 * 1024:
            raise forms.ValidationError("The file must be 25 MB or smaller for this MVP.")
        return uploaded
