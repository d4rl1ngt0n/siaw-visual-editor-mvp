(() => {
  const tabs = document.querySelectorAll("[data-create-tab]");
  const panels = document.querySelectorAll("[data-create-panel]");
  const activateTab = (name) => {
    tabs.forEach((tab) => {
      const active = tab.getAttribute("data-create-tab") === name;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
    });
    panels.forEach((panel) => {
      panel.classList.toggle("is-hidden", panel.getAttribute("data-create-panel") !== name);
    });
  };
  window.siawActivateCreateTab = activateTab;
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => activateTab(tab.getAttribute("data-create-tab") || "ai"));
  });

  const generateForm = document.querySelector("[data-generate-form]");
  const generateSubmit = document.querySelector("[data-generate-submit]");
  generateForm?.addEventListener("submit", () => {
    if (!generateSubmit) return;
    generateSubmit.disabled = true;
    generateSubmit.textContent = "Generating website…";
  });
})();

(() => {
  const root = document.querySelector("[data-hero-edit]");
  if (!root) return;

  const headline = root.querySelector("[data-hero-headline]");
  const status = root.querySelector("[data-hero-edit-status]");
  const caret = root.querySelector("[data-hero-caret]");
  if (!headline) return;

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const lines = [
    "Prompt a site. Edit by hand.",
    "Click any line. Rewrite it live.",
  ];

  if (reduceMotion) {
    if (status) status.textContent = "Click to edit";
    return;
  }

  const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

  const typeText = async (el, text) => {
    el.textContent = "";
    el.classList.add("is-typing");
    if (caret) {
      caret.hidden = false;
      el.after(caret);
    }
    for (let i = 0; i < text.length; i += 1) {
      el.textContent = text.slice(0, i + 1);
      await sleep(42 + (text[i] === " " ? 28 : 0));
    }
    el.classList.remove("is-typing");
    if (caret) caret.hidden = true;
  };

  const rewriteHeadline = async (nextText) => {
    if (status) status.textContent = "Editing";
    headline.classList.add("is-selected");
    root.classList.add("is-editing");
    await sleep(900);

    headline.classList.remove("is-selected");
    headline.classList.add("is-clearing");
    await sleep(280);
    headline.classList.remove("is-clearing");
    await typeText(headline, nextText);
    if (status) status.textContent = "Saved";
    root.classList.remove("is-editing");
    await sleep(2600);
    if (status) status.textContent = "Click to edit";
  };

  const loop = async () => {
    let index = 0;
    while (document.body.contains(root)) {
      if (
        document.body.classList.contains("is-site-editing")
        || document.body.classList.contains("site-edit-active")
        || root.hasAttribute("data-hero-edit-paused")
      ) {
        await sleep(800);
        continue;
      }
      await sleep(3200);
      index = (index + 1) % lines.length;
      await rewriteHeadline(lines[index]);
    }
  };

  loop();
})();

(() => {
  const form = document.querySelector("#uploadForm");
  if (!form) return;

  const fileInput = form.querySelector('input[name="website_zip"]');
  const folderInput = form.querySelector("[data-folder-input]");
  const folderButton = form.querySelector("[data-pick-folder]");
  const entryInput = form.querySelector("[data-entry-file], input[name='entry_file']");
  const nameInput = form.querySelector('input[name="name"]');
  const dropLabel = form.querySelector(".file-drop");
  const dropTitle = dropLabel?.querySelector("strong");
  const dropHint = dropLabel?.querySelector("small");
  const preview = document.querySelector("[data-upload-preview]");
  if (!fileInput || !preview) return;

  const previewFrame = preview.querySelector("[data-preview-frame]");
  const previewFrameWrap = preview.querySelector("[data-preview-frame-wrap]");
  const previewCode = preview.querySelector("[data-preview-code]");
  const previewMeta = preview.querySelector("[data-preview-meta]");
  const previewFiles = preview.querySelector("[data-preview-files]");
  const previewStatus = preview.querySelector("[data-preview-status]");
  const clearButton = preview.querySelector("[data-preview-clear]");

  const sideImport = document.querySelector("[data-side-import]");
  const emptyDrop = document.querySelector("[data-empty-drop]");
  const sideReady = document.querySelector("[data-side-ready]");
  const sideMeta = document.querySelector("[data-side-preview-meta]");
  const sideStatus = document.querySelector("[data-side-preview-status]");
  const sideFiles = document.querySelector("[data-side-preview-files]");
  const sideFrame = document.querySelector("[data-side-preview-frame]");
  const sideFrameWrap = document.querySelector("[data-side-preview-frame-wrap]");
  const sideCode = document.querySelector("[data-side-preview-code]");
  const sideName = document.querySelector("[data-side-name]");
  const sideClear = document.querySelector("[data-side-clear]");

  let ingestSource = "left";

  const PREFERRED_ENTRY_NAMES = [
    "index.html", "index.htm", "default.html", "default.htm",
    "home.html", "home.htm", "main.html", "app.html",
    "main.tsx", "main.jsx", "main.ts", "main.js",
    "app.tsx", "app.jsx", "app.vue", "app.svelte",
    "manage.py", "package.json", "readme.md",
  ];

  const SKIP_DIR_NAMES = new Set([
    "node_modules", ".git", "__pycache__", ".venv", "venv", ".tox",
    ".mypy_cache", ".pytest_cache", ".next", ".nuxt", ".svelte-kit",
    ".turbo", ".parcel-cache", ".cache", "coverage", ".idea", ".vscode",
    ".cursor", "__macosx",
  ]);

  let activeObjectUrl = "";
  let selectedEntryPath = "";

  function revokePreviewUrl() {
    if (activeObjectUrl) {
      URL.revokeObjectURL(activeObjectUrl);
      activeObjectUrl = "";
    }
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function setEntryPath(path) {
    selectedEntryPath = path || "";
    if (entryInput) entryInput.value = selectedEntryPath;
  }

  function resetDropCopy() {
    if (dropTitle) dropTitle.textContent = "Select ZIP or HTML file";
    if (dropHint) dropHint.textContent = "Maximum 25 MB after packing.";
    dropLabel?.classList.remove("has-file");
  }

  function syncSideNameFromForm() {
    if (sideName && nameInput) sideName.value = nameInput.value;
  }

  function syncFormNameFromSide() {
    if (sideName && nameInput) nameInput.value = sideName.value;
  }

  function setSideReadyVisible(show) {
    if (!sideImport) return;
    if (emptyDrop) emptyDrop.hidden = show;
    if (sideReady) sideReady.hidden = !show;
  }

  function hidePreview() {
    revokePreviewUrl();
    preview.hidden = true;
    preview.classList.remove("is-visible");
    if (previewFrame) previewFrame.removeAttribute("src");
    if (sideFrame) sideFrame.removeAttribute("src");
    if (previewCode) {
      previewCode.hidden = true;
      previewCode.textContent = "";
    }
    if (sideCode) {
      sideCode.hidden = true;
      sideCode.textContent = "";
    }
    if (previewFrameWrap) previewFrameWrap.hidden = false;
    if (sideFrameWrap) sideFrameWrap.hidden = false;
    if (previewMeta) previewMeta.textContent = "";
    if (sideMeta) sideMeta.textContent = "";
    if (previewFiles) previewFiles.innerHTML = "";
    if (sideFiles) sideFiles.innerHTML = "";
    if (previewStatus) previewStatus.textContent = "";
    if (sideStatus) sideStatus.textContent = "";
    if (sideName) sideName.value = "";
    setEntryPath("");
    resetDropCopy();
    setSideReadyVisible(false);
    ingestSource = "left";
  }

  function showPreviewShell(label, sizeBytes, statusText) {
    const metaText = `${label} · ${formatBytes(sizeBytes)}`;
    dropLabel?.classList.add("has-file");
    if (dropTitle) dropTitle.textContent = label;
    if (dropHint) dropHint.textContent = `${formatBytes(sizeBytes)} ready to import`;
    if (previewMeta) previewMeta.textContent = metaText;
    if (sideMeta) sideMeta.textContent = metaText;
    if (previewStatus) previewStatus.textContent = statusText || "";
    if (sideStatus) sideStatus.textContent = statusText || "";

    if (nameInput && !nameInput.value.trim()) {
      nameInput.value = label.replace(/\.(zip|html|htm|js|ts|tsx|jsx|vue|svelte|py|json|md|txt)$/i, "").replace(/[-_]+/g, " ").trim();
    }
    syncSideNameFromForm();

    // When the empty projects panel exists, show the ready card there.
    // Keep the left form pickers, but put the main preview/import on the right.
    if (sideImport) {
      preview.hidden = true;
      preview.classList.remove("is-visible");
      setSideReadyVisible(true);
    } else {
      preview.hidden = false;
      preview.classList.add("is-visible");
    }
  }

  function showPreviewError(message) {
    showPreviewShell("Import issue", 0, "");
    if (previewMeta) previewMeta.textContent = message;
    if (sideMeta) sideMeta.textContent = message;
    if (previewStatus) previewStatus.textContent = "";
    if (sideStatus) sideStatus.textContent = "";
    if (previewFiles) previewFiles.innerHTML = "";
    if (sideFiles) sideFiles.innerHTML = "";
    if (previewCode) {
      previewCode.hidden = true;
      previewCode.textContent = "";
    }
    if (sideCode) {
      sideCode.hidden = true;
      sideCode.textContent = "";
    }
    if (previewFrameWrap) previewFrameWrap.hidden = true;
    if (sideFrameWrap) sideFrameWrap.hidden = true;
  }

  function setFrameHtml(htmlText) {
    revokePreviewUrl();
    if (previewFrameWrap) previewFrameWrap.hidden = false;
    if (sideFrameWrap) sideFrameWrap.hidden = false;
    if (previewCode) {
      previewCode.hidden = true;
      previewCode.textContent = "";
    }
    if (sideCode) {
      sideCode.hidden = true;
      sideCode.textContent = "";
    }
    const blob = new Blob([htmlText], { type: "text/html" });
    activeObjectUrl = URL.createObjectURL(blob);
    if (previewFrame) previewFrame.src = activeObjectUrl;
    if (sideFrame) sideFrame.src = activeObjectUrl;
  }

  function setCodePreview(text, path) {
    revokePreviewUrl();
    if (previewFrame) previewFrame.removeAttribute("src");
    if (sideFrame) sideFrame.removeAttribute("src");
    if (previewFrameWrap) previewFrameWrap.hidden = true;
    if (sideFrameWrap) sideFrameWrap.hidden = true;
    const clipped = text.length > 4000 ? `${text.slice(0, 4000)}\n…` : text;
    const content = clipped || `(empty file: ${path})`;
    if (previewCode) {
      previewCode.hidden = false;
      previewCode.textContent = content;
    }
    if (sideCode) {
      sideCode.hidden = false;
      sideCode.textContent = content;
    }
  }

  function preferredEntryScore(path) {
    const name = path.split("/").pop().toLowerCase();
    const preferred = PREFERRED_ENTRY_NAMES.indexOf(name);
    const depth = path.split("/").filter(Boolean).length;
    const htmlBoost = /\.(html|htm|xhtml)$/i.test(name) ? 0 : 50;
    return [preferred === -1 ? 100 + htmlBoost : preferred, depth, path.toLowerCase()];
  }

  function compareEntries(a, b) {
    const left = preferredEntryScore(a);
    const right = preferredEntryScore(b);
    for (let i = 0; i < left.length; i += 1) {
      if (left[i] < right[i]) return -1;
      if (left[i] > right[i]) return 1;
    }
    return 0;
  }

  function renderFileListInto(container, paths, entryPath) {
    if (!container) return;
    container.innerHTML = "";
    const unique = [...new Set(paths)].sort(compareEntries).slice(0, 12);
    unique.forEach((path) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = path;
      if (path === entryPath) item.classList.add("is-entry");
      button.addEventListener("click", () => {
        setEntryPath(path);
        [previewFiles, sideFiles].forEach((list) => {
          if (!list) return;
          [...list.children].forEach((child) => {
            const label = child.querySelector("button")?.textContent || "";
            child.classList.toggle("is-entry", label === path);
          });
        });
        const statusText = `Entry set to ${path}. Click import when ready.`;
        if (previewStatus) previewStatus.textContent = statusText;
        if (sideStatus) sideStatus.textContent = statusText;
      });
      item.appendChild(button);
      container.appendChild(item);
    });
    if (paths.length > unique.length) {
      const more = document.createElement("li");
      more.className = "is-more";
      more.textContent = `+${paths.length - unique.length} more files`;
      container.appendChild(more);
    }
  }

  function renderFileList(paths, entryPath) {
    renderFileListInto(previewFiles, paths, entryPath);
    renderFileListInto(sideFiles, paths, entryPath);
  }

  async function inflateRaw(bytes) {
    if (typeof DecompressionStream === "undefined") {
      throw new Error("This browser cannot preview compressed ZIP entries.");
    }
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
    const buffer = await new Response(stream).arrayBuffer();
    return new Uint8Array(buffer);
  }

  function readU16(view, offset) {
    return view.getUint16(offset, true);
  }

  function readU32(view, offset) {
    return view.getUint32(offset, true);
  }

  const CRC_TABLE = (() => {
    const table = new Uint32Array(256);
    for (let i = 0; i < 256; i += 1) {
      let value = i;
      for (let j = 0; j < 8; j += 1) {
        value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
      }
      table[i] = value >>> 0;
    }
    return table;
  })();

  function crc32(bytes) {
    let crc = 0xffffffff;
    for (let i = 0; i < bytes.length; i += 1) {
      crc = CRC_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
    }
    return (crc ^ 0xffffffff) >>> 0;
  }

  function concatBytes(chunks) {
    const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
    const output = new Uint8Array(total);
    let offset = 0;
    chunks.forEach((chunk) => {
      output.set(chunk, offset);
      offset += chunk.length;
    });
    return output;
  }

  function u16(value) {
    const bytes = new Uint8Array(2);
    new DataView(bytes.buffer).setUint16(0, value, true);
    return bytes;
  }

  function u32(value) {
    const bytes = new Uint8Array(4);
    new DataView(bytes.buffer).setUint32(0, value, true);
    return bytes;
  }

  async function createStoreZip(entries) {
    const localChunks = [];
    const centralChunks = [];
    let offset = 0;

    for (const entry of entries) {
      const nameBytes = new TextEncoder().encode(entry.name);
      const data = entry.data;
      const checksum = crc32(data);
      const local = concatBytes([
        u32(0x04034b50),
        u16(20),
        u16(0),
        u16(0),
        u16(0),
        u16(0),
        u32(checksum),
        u32(data.length),
        u32(data.length),
        u16(nameBytes.length),
        u16(0),
        nameBytes,
        data,
      ]);
      localChunks.push(local);

      const central = concatBytes([
        u32(0x02014b50),
        u16(20),
        u16(20),
        u16(0),
        u16(0),
        u16(0),
        u16(0),
        u32(checksum),
        u32(data.length),
        u32(data.length),
        u16(nameBytes.length),
        u16(0),
        u16(0),
        u16(0),
        u16(0),
        u32(0),
        u32(offset),
        nameBytes,
      ]);
      centralChunks.push(central);
      offset += local.length;
    }

    const centralDirectory = concatBytes(centralChunks);
    const end = concatBytes([
      u32(0x06054b50),
      u16(0),
      u16(0),
      u16(entries.length),
      u16(entries.length),
      u32(centralDirectory.length),
      u32(offset),
      u16(0),
    ]);
    return concatBytes([...localChunks, centralDirectory, end]);
  }

  function shouldSkipRelativePath(relativePath) {
    return relativePath.split("/").some((part) => SKIP_DIR_NAMES.has(part.toLowerCase()) || part === ".DS_Store");
  }

  function normalizeFolderEntries(fileList) {
    // Accept FileList from <input webkitdirectory> or [{ relativePath, file }] from showDirectoryPicker.
    if (Array.isArray(fileList) && fileList[0] && fileList[0].relativePath) {
      return fileList.filter((item) => item.relativePath && !shouldSkipRelativePath(item.relativePath));
    }
    return [...fileList]
      .map((file) => ({
        relativePath: file.webkitRelativePath || file.name,
        file,
      }))
      .filter((item) => item.relativePath && !shouldSkipRelativePath(item.relativePath));
  }

  async function walkDirectoryHandle(dirHandle, prefix = "") {
    const collected = [];
    for await (const [name, handle] of dirHandle.entries()) {
      if (SKIP_DIR_NAMES.has(name.toLowerCase()) || name === ".DS_Store") continue;
      const relativePath = prefix ? `${prefix}/${name}` : name;
      if (handle.kind === "directory") {
        collected.push(...await walkDirectoryHandle(handle, relativePath));
        continue;
      }
      if (handle.kind === "file") {
        collected.push({ relativePath, file: await handle.getFile() });
      }
    }
    return collected;
  }

  async function zipFolderFiles(fileList, folderNameHint = "") {
    const items = normalizeFolderEntries(fileList);
    if (!items.length) throw new Error("That folder has no importable files.");

    // Strip the shared top-level folder name so archives match ZIP uploads.
    // showDirectoryPicker paths are already relative to the chosen folder (no prefix).
    const first = items[0].relativePath;
    const hasSharedRoot = items.every((item) => item.relativePath.includes("/"))
      && items.every((item) => item.relativePath.split("/")[0] === first.split("/")[0])
      && Boolean(items[0].file?.webkitRelativePath);
    const rootPrefix = hasSharedRoot ? `${first.split("/")[0]}/` : "";
    const entries = [];
    for (const item of items) {
      const relative = item.relativePath;
      const name = rootPrefix && relative.startsWith(rootPrefix) ? relative.slice(rootPrefix.length) : relative;
      if (!name) continue;
      entries.push({ name, data: new Uint8Array(await item.file.arrayBuffer()) });
    }
    if (!entries.length) throw new Error("That folder has no importable files.");

    const zipBytes = await createStoreZip(entries);
    if (zipBytes.length > 25 * 1024 * 1024) {
      throw new Error("Packed folder is larger than 25 MB. Remove node_modules/build output or zip a smaller subset.");
    }
    const folderName = folderNameHint || rootPrefix.replace(/\/$/, "") || "project";
    return {
      file: new File([zipBytes], `${folderName}.zip`, { type: "application/zip" }),
      paths: entries.map((entry) => entry.name),
    };
  }

  async function packSelectedFolder(fileList, folderNameHint = "") {
    showPreviewShell("Packing folder…", 0, "Skipping node_modules and other tooling folders…");
    const packed = await zipFolderFiles(fileList, folderNameHint);
    assignFileToInput(packed.file);
    await previewSelectedFile(packed.file, packed.paths);
    if (sideImport) {
      sideReady?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      sideName?.focus();
    } else {
      form.scrollIntoView({ behavior: "smooth", block: "nearest" });
      nameInput?.focus();
    }
  }

  function assignFileToInput(file) {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    fileInput.files = transfer.files;
    window.dispatchEvent(new CustomEvent("siaw:upload-selected", {
      detail: {
        file,
        name: nameInput?.value || "",
        entryFile: entryInput?.value || "",
      },
    }));
  }

  async function fileLooksLikeZip(file) {
    const header = new Uint8Array(await file.slice(0, 4).arrayBuffer());
    if (header.length < 4 || header[0] !== 0x50 || header[1] !== 0x4b) return false;
    const third = header[2];
    const fourth = header[3];
    return (
      (third === 0x03 && fourth === 0x04) ||
      (third === 0x05 && fourth === 0x06) ||
      (third === 0x07 && fourth === 0x08)
    );
  }

  async function extractZipEntry(bytes, entry) {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const localOffset = entry.localHeaderOffset;
    if (readU32(view, localOffset) !== 0x04034b50) {
      throw new Error("Could not read the selected file from this ZIP.");
    }
    const localNameLength = readU16(view, localOffset + 26);
    const localExtraLength = readU16(view, localOffset + 28);
    const dataStart = localOffset + 30 + localNameLength + localExtraLength;
    const compressed = bytes.subarray(dataStart, dataStart + entry.compressedSize);
    if (entry.compression === 0) return compressed;
    if (entry.compression === 8) return inflateRaw(compressed);
    throw new Error("This ZIP uses a compression type the preview cannot open.");
  }

  async function readZipPreview(file) {
    const buffer = await file.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    const view = new DataView(buffer);

    let end = bytes.length - 22;
    while (end >= 0) {
      if (readU32(view, end) === 0x06054b50) break;
      end -= 1;
    }
    if (end < 0) throw new Error("This ZIP archive looks invalid.");

    const count = readU16(view, end + 10);
    let offset = readU32(view, end + 16);
    const entries = [];

    for (let i = 0; i < count; i += 1) {
      if (readU32(view, offset) !== 0x02014b50) break;
      const compression = readU16(view, offset + 10);
      const compressedSize = readU32(view, offset + 20);
      const nameLength = readU16(view, offset + 28);
      const extraLength = readU16(view, offset + 30);
      const commentLength = readU16(view, offset + 32);
      const localHeaderOffset = readU32(view, offset + 42);
      const nameStart = offset + 46;
      const name = new TextDecoder().decode(bytes.subarray(nameStart, nameStart + nameLength));
      offset = nameStart + nameLength + extraLength + commentLength;

      if (!name || name.endsWith("/") || shouldSkipRelativePath(name)) continue;
      entries.push({ name, compression, compressedSize, localHeaderOffset });
    }

    if (!entries.length) throw new Error("No files were found inside this ZIP.");

    const ranked = [...entries].map((entry) => entry.name).sort(compareEntries);
    const entryPath = ranked[0];
    const entry = entries.find((item) => item.name === entryPath);
    const raw = await extractZipEntry(bytes, entry);
    const text = new TextDecoder("utf-8", { fatal: false }).decode(raw);
    return {
      entryPath,
      paths: entries.map((item) => item.name),
      text,
      isHtml: /\.(html|htm|xhtml)$/i.test(entryPath),
    };
  }

  async function previewSelectedFile(file, extraPaths = null) {
    const lower = file.name.toLowerCase();
    const isHtml = /\.(html|htm|xhtml)$/i.test(lower);
    const isZip = lower.endsWith(".zip") || (await fileLooksLikeZip(file));
    const isText = /\.(css|js|mjs|cjs|jsx|ts|tsx|vue|svelte|py|json|md|txt|php|rb|yml|yaml|toml)$/i.test(lower);

    if (file.size > 25 * 1024 * 1024) {
      showPreviewError("File is larger than 25 MB.");
      return;
    }

    showPreviewShell(file.name, file.size, "Building preview…");
    if (previewFiles) previewFiles.innerHTML = "";

    try {
      if (isZip) {
        const zipPreview = await readZipPreview(file);
        setEntryPath(zipPreview.entryPath);
        if (zipPreview.isHtml) setFrameHtml(zipPreview.text);
        else setCodePreview(zipPreview.text, zipPreview.entryPath);
        renderFileList(extraPaths || zipPreview.paths, zipPreview.entryPath);
        if (previewStatus) {
          previewStatus.textContent = zipPreview.isHtml
            ? `Previewing ${zipPreview.entryPath}. Click a file below to change the entry, then import.`
            : `Source project detected. Entry: ${zipPreview.entryPath}. Visual canvas needs an HTML file; other files open in the code editor.`;
        }
        return;
      }

      if (isHtml) {
        const htmlText = await file.text();
        setEntryPath(file.name);
        setFrameHtml(htmlText);
        renderFileList([file.name], file.name);
        if (previewStatus) previewStatus.textContent = "HTML preview ready. Click import when it looks right.";
        return;
      }

      if (isText) {
        const text = await file.text();
        setEntryPath(file.name);
        setCodePreview(text, file.name);
        renderFileList([file.name], file.name);
        if (previewStatus) previewStatus.textContent = "Source file ready. It will open in the code editor after import.";
        return;
      }

      showPreviewError("Please choose a folder, .zip, HTML file, or common source file.");
    } catch (error) {
      revokePreviewUrl();
      if (previewFrame) previewFrame.removeAttribute("src");
      showPreviewError(error instanceof Error ? error.message : "Could not preview this file.");
    }
  }

  async function handleFileChange() {
    const file = fileInput.files && fileInput.files[0];
    if (!file) {
      hidePreview();
      window.dispatchEvent(new CustomEvent("siaw:upload-cleared"));
      return;
    }
    window.dispatchEvent(new CustomEvent("siaw:upload-selected", {
      detail: {
        file,
        name: nameInput?.value || "",
        entryFile: entryInput?.value || "",
      },
    }));
    await previewSelectedFile(file);
  }

  async function requestFolderPick(source = "left") {
    ingestSource = source;

    // Prefer File System Access API: avoids Chrome's "Upload N files to this site?" dialog.
    // That prompt only appears for <input webkitdirectory>, which we keep as a fallback.
    if (typeof window.showDirectoryPicker === "function") {
      try {
        const dirHandle = await window.showDirectoryPicker({ mode: "read" });
        showPreviewShell("Reading folder…", 0, "Skipping node_modules and other tooling folders…");
        const entries = await walkDirectoryHandle(dirHandle);
        await packSelectedFolder(entries, dirHandle.name || "project");
      } catch (error) {
        if (error && (error.name === "AbortError" || error.name === "SecurityError")) return;
        showPreviewError(error instanceof Error ? error.message : "Could not open that folder.");
      }
      return;
    }

    folderInput?.click();
  }

  folderButton?.addEventListener("click", () => {
    void requestFolderPick("left");
  });
  dropLabel?.addEventListener("click", () => {
    ingestSource = "left";
  });

  folderInput?.addEventListener("change", async () => {
    const list = folderInput.files;
    if (!list || !list.length) return;
    try {
      await packSelectedFolder(list);
    } catch (error) {
      showPreviewError(error instanceof Error ? error.message : "Could not pack that folder.");
    } finally {
      folderInput.value = "";
    }
  });

  fileInput.addEventListener("change", () => {
    void handleFileChange().then(() => {
      if (sideImport && fileInput.files?.length) {
        sideReady?.scrollIntoView({ behavior: "smooth", block: "nearest" });
        sideName?.focus();
      }
    });
  });

  clearButton?.addEventListener("click", () => {
    fileInput.value = "";
    if (folderInput) folderInput.value = "";
    hidePreview();
    window.dispatchEvent(new CustomEvent("siaw:upload-cleared"));
  });

  async function ingestFiles(fileList, source = "left") {
    ingestSource = source;
    const files = [...(fileList || [])].filter(Boolean);
    if (!files.length) return;
    const looksLikeFolder = files.length > 1
      || files.some((file) => Boolean(file.webkitRelativePath && file.webkitRelativePath.includes("/")));
    try {
      if (looksLikeFolder) {
        await packSelectedFolder(files);
      } else {
        assignFileToInput(files[0]);
        await previewSelectedFile(files[0]);
        if (sideImport && (source === "right" || sideReady)) {
          sideReady?.scrollIntoView({ behavior: "smooth", block: "nearest" });
          sideName?.focus();
        } else {
          form.scrollIntoView({ behavior: "smooth", block: "nearest" });
          nameInput?.focus();
        }
      }
    } catch (error) {
      showPreviewError(error instanceof Error ? error.message : "Could not import that drop.");
      if (sideImport) sideReady?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      else form.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  function bindDropTarget(target, { onClick, source = "left" } = {}) {
    if (!target) return;
    let dragDepth = 0;

    target.addEventListener("dragenter", (event) => {
      event.preventDefault();
      dragDepth += 1;
      target.classList.add("is-dragover");
    });
    target.addEventListener("dragover", (event) => {
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    });
    target.addEventListener("dragleave", (event) => {
      event.preventDefault();
      dragDepth = Math.max(0, dragDepth - 1);
      if (dragDepth === 0) target.classList.remove("is-dragover");
    });
    target.addEventListener("drop", (event) => {
      event.preventDefault();
      dragDepth = 0;
      target.classList.remove("is-dragover");
      void ingestFiles(event.dataTransfer?.files, source);
    });

    if (onClick) {
      target.addEventListener("click", (event) => {
        if (event.target.closest("button, a, input, label")) return;
        onClick(event);
      });
      target.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onClick(event);
        }
      });
    }
  }

  bindDropTarget(dropLabel, { source: "left" });

  const emptyPickFile = document.querySelector("[data-empty-pick-file]");
  const emptyPickFolder = document.querySelector("[data-empty-pick-folder]");
  bindDropTarget(emptyDrop, {
    source: "right",
    onClick: () => {
      ingestSource = "right";
      fileInput.click();
    },
  });
  emptyPickFile?.addEventListener("click", (event) => {
    event.stopPropagation();
    ingestSource = "right";
    fileInput.click();
  });
  emptyPickFolder?.addEventListener("click", (event) => {
    event.stopPropagation();
    void requestFolderPick("right");
  });

  sideName?.addEventListener("input", syncFormNameFromSide);
  nameInput?.addEventListener("input", syncSideNameFromForm);
  sideClear?.addEventListener("click", () => {
    fileInput.value = "";
    if (folderInput) folderInput.value = "";
    hidePreview();
    window.dispatchEvent(new CustomEvent("siaw:upload-cleared"));
  });
  form.addEventListener("submit", () => {
    syncFormNameFromSide();
    window.dispatchEvent(new CustomEvent("siaw:upload-cleared"));
  });

  window.siawRestoreUploadDraft = async ({ file, name, entryFile } = {}) => {
    if (!file) return;
    if (name && nameInput) nameInput.value = name;
    if (entryFile && entryInput) entryInput.value = entryFile;
    assignFileToInput(file);
    await previewSelectedFile(file);
    syncSideNameFromForm();
  };
})();

(() => {
  const AI_KEY = "siaw.draft.ai";
  const META_KEY = "siaw.draft.meta";
  const IDB_NAME = "siaw-drafts";
  const IDB_STORE = "blobs";
  const UPLOAD_KEY = "upload";

  const generateForm = document.querySelector("[data-generate-form]");
  const uploadForm = document.querySelector("#uploadForm");
  const nameAi = generateForm?.querySelector('input[name="name"]');
  const promptAi = generateForm?.querySelector('textarea[name="prompt"]');
  const nameUpload = uploadForm?.querySelector('input[name="name"]');
  const entryUpload = uploadForm?.querySelector('input[name="entry_file"]');

  const openDb = () => new Promise((resolve, reject) => {
    const req = indexedDB.open(IDB_NAME, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(IDB_STORE)) db.createObjectStore(IDB_STORE);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error || new Error("Could not open draft storage."));
  });

  const idbPut = async (key, value) => {
    const db = await openDb();
    await new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, "readwrite");
      tx.objectStore(IDB_STORE).put(value, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
    db.close();
  };

  const idbGet = async (key) => {
    const db = await openDb();
    const value = await new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, "readonly");
      const req = tx.objectStore(IDB_STORE).get(key);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    db.close();
    return value;
  };

  const idbDelete = async (key) => {
    const db = await openDb();
    await new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, "readwrite");
      tx.objectStore(IDB_STORE).delete(key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
    db.close();
  };

  const saveAiDraft = () => {
    const payload = {
      name: nameAi?.value || "",
      prompt: promptAi?.value || "",
      updatedAt: Date.now(),
    };
    if (!payload.name.trim() && !payload.prompt.trim()) {
      sessionStorage.removeItem(AI_KEY);
      return;
    }
    sessionStorage.setItem(AI_KEY, JSON.stringify(payload));
  };

  const saveMeta = (tab) => {
    sessionStorage.setItem(META_KEY, JSON.stringify({ tab, updatedAt: Date.now() }));
  };

  const readAiDraft = () => {
    try {
      return JSON.parse(sessionStorage.getItem(AI_KEY) || "null");
    } catch (_) {
      return null;
    }
  };

  const readMeta = () => {
    try {
      return JSON.parse(sessionStorage.getItem(META_KEY) || "null");
    } catch (_) {
      return null;
    }
  };

  nameAi?.addEventListener("input", saveAiDraft);
  promptAi?.addEventListener("input", saveAiDraft);
  nameUpload?.addEventListener("input", () => {
    const file = uploadForm?.querySelector('input[name="website_zip"]')?.files?.[0];
    if (!file) return;
    void idbPut(UPLOAD_KEY, {
      name: nameUpload.value || "",
      entryFile: entryUpload?.value || "",
      file,
      fileName: file.name,
      fileType: file.type,
      updatedAt: Date.now(),
    });
  });

  window.addEventListener("siaw:upload-selected", (event) => {
    const detail = event.detail || {};
    if (!detail.file) return;
    saveMeta("import");
    void idbPut(UPLOAD_KEY, {
      name: detail.name || nameUpload?.value || "",
      entryFile: detail.entryFile || entryUpload?.value || "",
      file: detail.file,
      fileName: detail.file.name,
      fileType: detail.file.type,
      updatedAt: Date.now(),
    });
  });

  window.addEventListener("siaw:upload-cleared", () => {
    void idbDelete(UPLOAD_KEY);
  });

  generateForm?.addEventListener("submit", () => {
    sessionStorage.removeItem(AI_KEY);
  });

  const flushDraftsBeforeAuth = async (tab) => {
    if (tab === "ai" || !tab) saveAiDraft();
    if (tab) saveMeta(tab);
    const fileInput = uploadForm?.querySelector('input[name="website_zip"]');
    const file = fileInput?.files?.[0];
    if (file) {
      await idbPut(UPLOAD_KEY, {
        name: nameUpload?.value || "",
        entryFile: entryUpload?.value || "",
        file,
        fileName: file.name,
        fileType: file.type,
        updatedAt: Date.now(),
      });
      saveMeta("import");
    }
  };

  document.querySelectorAll("[data-auth-continue]").forEach((link) => {
    link.addEventListener("click", (event) => {
      const tab = link.getAttribute("data-auth-continue") || "ai";
      event.preventDefault();
      void flushDraftsBeforeAuth(tab).finally(() => {
        window.location.href = link.href;
      });
    });
  });

  const showDraftNotice = (message) => {
    const workspace = document.querySelector("#workspace");
    if (!workspace || document.querySelector("[data-draft-notice]")) return;
    const notice = document.createElement("div");
    notice.className = "draft-notice";
    notice.setAttribute("data-draft-notice", "1");
    notice.innerHTML = `<strong>Draft restored</strong><span>${message}</span>`;
    const intro = workspace.querySelector(".workspace-intro");
    if (intro) intro.insertAdjacentElement("afterend", notice);
    else workspace.prepend(notice);
  };

  const DRAFT_MAX_AGE_MS = 24 * 60 * 60 * 1000;
  const isFresh = (stamp) => typeof stamp === "number" && (Date.now() - stamp) < DRAFT_MAX_AGE_MS;

  const restoreDrafts = async () => {
    let ai = readAiDraft();
    if (ai && !isFresh(ai.updatedAt)) {
      sessionStorage.removeItem(AI_KEY);
      ai = null;
    }
    let upload = await idbGet(UPLOAD_KEY).catch(() => null);
    if (upload && !isFresh(upload.updatedAt)) {
      await idbDelete(UPLOAD_KEY).catch(() => null);
      upload = null;
    }
    let meta = readMeta();
    if (meta && !isFresh(meta.updatedAt)) {
      sessionStorage.removeItem(META_KEY);
      meta = null;
    }

    let restoredTab = meta?.tab || null;
    let didRestore = false;

    if (ai && (ai.name || ai.prompt)) {
      if (nameAi && !nameAi.value) nameAi.value = ai.name || "";
      if (promptAi && !promptAi.value) promptAi.value = ai.prompt || "";
      restoredTab = restoredTab || "ai";
      didRestore = true;
    }

    if (upload?.file && typeof window.siawRestoreUploadDraft === "function") {
      await window.siawRestoreUploadDraft({
        file: upload.file,
        name: upload.name || "",
        entryFile: upload.entryFile || "",
      });
      restoredTab = "import";
      didRestore = true;
    }

    if (!didRestore) return;

    if (restoredTab && typeof window.siawActivateCreateTab === "function") {
      window.siawActivateCreateTab(restoredTab);
    }

    const fromAuth = /\/(login|signup)\/?/i.test(document.referrer || "");
    const workspace = document.querySelector("#workspace");
    if (workspace && (fromAuth || window.location.hash === "#workspace")) {
      if (window.location.hash !== "#workspace") {
        window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#workspace`);
      }
      workspace.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    if (fromAuth) {
      if (restoredTab === "import") {
        showDraftNotice("Your import is ready. Continue below to open it in the editor.");
      } else {
        showDraftNotice("Your AI prompt is ready. Continue below to generate.");
      }
    }
  };

  void restoreDrafts();
})();

(() => {
  document.querySelectorAll("[data-delete-project]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const name = form.getAttribute("data-project-name") || "this project";
      const confirmed = await siawConfirm("", {
        danger: true,
        confirmLabel: "Delete",
        cancelLabel: "Cancel",
        title: `Delete “${name}”?`,
        message: "This removes the project from your account. It cannot be undone.",
        eyebrow: "Delete project",
      });
      if (confirmed) form.submit();
    });
  });
})();
