from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User


class SignUpForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "you@studio.com"}),
    )

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")
        widgets = {
            "username": forms.TextInput(attrs={"autocomplete": "username", "placeholder": "studio-name"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].widget.attrs.update({"autocomplete": "new-password", "placeholder": "At least 8 characters"})
        self.fields["password2"].widget.attrs.update({"autocomplete": "new-password", "placeholder": "Repeat password"})

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Show prefilled demo password in the input (normally PasswordInput clears it).
        self.fields["password"].widget.render_value = True
        if not self.is_bound:
            if self.initial.get("username"):
                self.fields["username"].initial = self.initial["username"]
            if self.initial.get("password"):
                self.fields["password"].initial = self.initial["password"]
        self.fields["username"].widget.attrs.update(
            {
                "autocomplete": "username",
                "placeholder": "demo",
                "spellcheck": "false",
            }
        )
        self.fields["password"].widget.attrs.update(
            {
                "autocomplete": "current-password",
                "placeholder": "siawdemo123",
            }
        )


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
