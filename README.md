# Siaw Visual Website Editor | MVP 4B

A local drag-and-drop editor for existing HTML websites. GrapesJS provides the visual canvas and Django manages ZIP import, secure project storage, asset upload, backup, preview and export.

## Main features

- Import a static HTML website ZIP containing `index.html`.
- Preserve the original HTML, linked CSS, JavaScript and asset folder structure.
- Edit normal text, headings, links, buttons and images visually.
- Add reusable blocks such as headings, paragraphs, buttons, navigation links, cards and sections.
- Preview Desktop, Tablet and Mobile layouts.
- Save GrapesJS project state and export a working website ZIP.
- Restore the original uploaded ZIP backup.
- Load linked stylesheets and inline `<style>` blocks.
- Hydrate common lazy-loaded media inside Safe Edit.
- Reveal scroll-animation content temporarily in Safe Edit without changing the exported site.
- Use **Interactive mode** for JavaScript-generated navigation, carousels, reviews, filters, modals and application screens.
- Use the **Compatibility Report** to see detected dynamic regions, missing resources and browser-storage requirements.
- Use the **Smart Navigation Manager** for compatible static and JavaScript-generated menus.
- Capture a running JavaScript-generated component and reuse it as an editable static block.
- Use the Smart Services Manager on compatible Order Siaw service cards.

## Windows setup

Open Command Prompt inside the extracted `siaw_visual_editor_mvp` folder and run:

```bat
py -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py load_demo
.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Open `http://127.0.0.1:8000/`.

After the first installation, future restarts need only:

```bat
cd C:\Users\clems\Downloads\siaw_visual_website_editor_mvp1_order_siaw_v28\siaw_visual_editor_mvp
.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

## Modes

### Safe Edit

Imported JavaScript is disabled. Use this mode for normal visual editing. Animation-hidden items are temporarily revealed and empty JavaScript regions receive explanatory placeholders.

### Interactive

The original website runs in an isolated per-project address such as:

```text
http://<project-id>.runtime.localhost:8000/...
```

This allows normal JavaScript and browser storage to operate without sharing the editor origin. Use it to inspect menus, reviews, carousels, product filters and web-application screens.

### Live Preview

Opens a separate isolated preview for final testing before export.

## Smart Navigation Manager

Open the **Smart** tab.

- Simple HTML menus can be renamed, linked, reordered, duplicated, added, hidden and deleted.
- Complex dropdown menus allow safe label and destination editing while structural actions remain locked.
- Supported JavaScript navigation arrays can be renamed, reordered, hidden and styled as call-to-action entries without manually editing JavaScript.
- JavaScript menu additions are intentionally locked when the website router cannot safely create a matching page.

## Dynamic component capture

1. Open **Interactive** mode.
2. Click **Capture component**.
3. Click a generated menu, review, carousel, card, form or application region.
4. Open the **Capture** tab.
5. Choose **Insert static copy** or **Add to Blocks**.

A captured component is sanitised and becomes editable HTML. Its original JavaScript behaviour is not copied automatically. This prevents the editor from pretending that an interactive clone is still connected to its original data or application logic.

## Updating an existing installation

Stop the server with `Ctrl + C`, copy the MVP 4B update folders over the current project and choose **Replace the files in the destination**. Keep your existing `db.sqlite3` and `media` folder because they contain your projects and uploaded assets. Restart and press `Ctrl + F5` once.

## Current limitations

- Complex JavaScript applications still require dedicated Smart Managers for their underlying data.
- Captured runtime components are static editable copies, not automatic rewrites of the original JavaScript.
- Multi-page editing, project version history and direct hosting publication are planned for later MVP stages.
