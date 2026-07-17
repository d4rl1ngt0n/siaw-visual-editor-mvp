(() => {
  const form = document.querySelector(".upload-form");
  if (!form) return;

  const fileInput = form.querySelector('input[type="file"]');
  const nameInput = form.querySelector('input[name="name"]');
  const dropLabel = form.querySelector(".file-drop");
  const dropTitle = dropLabel?.querySelector("strong");
  const dropHint = dropLabel?.querySelector("small");
  const preview = document.querySelector("[data-upload-preview]");
  if (!fileInput || !preview) return;

  const previewFrame = preview.querySelector("[data-preview-frame]");
  const previewMeta = preview.querySelector("[data-preview-meta]");
  const previewFiles = preview.querySelector("[data-preview-files]");
  const previewStatus = preview.querySelector("[data-preview-status]");
  const clearButton = preview.querySelector("[data-preview-clear]");

  const PREFERRED_ENTRY_NAMES = [
    "index.html",
    "index.htm",
    "default.html",
    "default.htm",
    "home.html",
    "home.htm",
    "main.html",
    "main.htm",
    "app.html",
    "app.htm",
  ];

  let activeObjectUrl = "";

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

  function resetDropCopy() {
    if (dropTitle) dropTitle.textContent = "Select ZIP or HTML";
    if (dropHint) dropHint.textContent = "Maximum 25 MB. Full sites need a ZIP with assets.";
    dropLabel?.classList.remove("has-file");
  }

  function hidePreview() {
    revokePreviewUrl();
    preview.hidden = true;
    preview.classList.remove("is-visible");
    if (previewFrame) previewFrame.removeAttribute("src");
    if (previewMeta) previewMeta.textContent = "";
    if (previewFiles) previewFiles.innerHTML = "";
    if (previewStatus) previewStatus.textContent = "";
    resetDropCopy();
  }

  function showPreviewShell(file, statusText) {
    preview.hidden = false;
    preview.classList.add("is-visible");
    dropLabel?.classList.add("has-file");
    if (dropTitle) dropTitle.textContent = file.name;
    if (dropHint) dropHint.textContent = `${formatBytes(file.size)} ready to import`;
    if (previewMeta) {
      previewMeta.textContent = `${file.name} · ${formatBytes(file.size)}`;
    }
    if (previewStatus) previewStatus.textContent = statusText;
    if (nameInput && !nameInput.value.trim()) {
      nameInput.value = file.name.replace(/\.(zip|html|htm)$/i, "").replace(/[-_]+/g, " ").trim();
    }
  }

  function setFrameHtml(htmlText) {
    revokePreviewUrl();
    const blob = new Blob([htmlText], { type: "text/html" });
    activeObjectUrl = URL.createObjectURL(blob);
    if (previewFrame) previewFrame.src = activeObjectUrl;
  }

  function preferredEntryScore(path) {
    const name = path.split("/").pop().toLowerCase();
    const preferred = PREFERRED_ENTRY_NAMES.indexOf(name);
    const depth = path.split("/").filter(Boolean).length;
    return [preferred === -1 ? 100 : preferred, depth, path.toLowerCase()];
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

  function renderFileList(paths, entryPath) {
    if (!previewFiles) return;
    previewFiles.innerHTML = "";
    const unique = [...new Set(paths)].sort(compareEntries).slice(0, 8);
    unique.forEach((path) => {
      const item = document.createElement("li");
      item.textContent = path;
      if (path === entryPath) item.classList.add("is-entry");
      previewFiles.appendChild(item);
    });
    if (paths.length > unique.length) {
      const more = document.createElement("li");
      more.className = "is-more";
      more.textContent = `+${paths.length - unique.length} more files`;
      previewFiles.appendChild(more);
    }
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

      if (!name || name.endsWith("/") || name.split("/").some((part) => part === "__MACOSX" || part.startsWith("."))) {
        continue;
      }
      entries.push({ name, compression, compressedSize, localHeaderOffset });
    }

    if (!entries.length) throw new Error("No files were found inside this ZIP.");

    const htmlEntries = entries.filter((entry) => /\.(html|htm)$/i.test(entry.name));
    if (!htmlEntries.length) throw new Error("No HTML file was found inside this ZIP.");

    htmlEntries.sort((a, b) => compareEntries(a.name, b.name));
    const entry = htmlEntries[0];

    const localOffset = entry.localHeaderOffset;
    if (readU32(view, localOffset) !== 0x04034b50) {
      throw new Error("Could not read the HTML entry from this ZIP.");
    }
    const localNameLength = readU16(view, localOffset + 26);
    const localExtraLength = readU16(view, localOffset + 28);
    const dataStart = localOffset + 30 + localNameLength + localExtraLength;
    const compressed = bytes.subarray(dataStart, dataStart + entry.compressedSize);

    let htmlBytes;
    if (entry.compression === 0) {
      htmlBytes = compressed;
    } else if (entry.compression === 8) {
      htmlBytes = await inflateRaw(compressed);
    } else {
      throw new Error("This ZIP uses a compression type the preview cannot open.");
    }

    const htmlText = new TextDecoder("utf-8", { fatal: false }).decode(htmlBytes);
    return {
      htmlText,
      entryPath: entry.name,
      paths: entries.map((item) => item.name),
    };
  }

  async function handleFileChange() {
    const file = fileInput.files && fileInput.files[0];
    if (!file) {
      hidePreview();
      return;
    }

    const lower = file.name.toLowerCase();
    const isHtml = lower.endsWith(".html") || lower.endsWith(".htm");
    const isZip = lower.endsWith(".zip");

    if (!isHtml && !isZip) {
      hidePreview();
      if (previewStatus) {
        preview.hidden = false;
        preview.classList.add("is-visible");
        previewStatus.textContent = "Please choose a .zip or .html file.";
      }
      return;
    }

    if (file.size > 25 * 1024 * 1024) {
      hidePreview();
      preview.hidden = false;
      preview.classList.add("is-visible");
      if (previewStatus) previewStatus.textContent = "File is larger than 25 MB.";
      return;
    }

    showPreviewShell(file, "Building preview…");
    if (previewFiles) previewFiles.innerHTML = "";

    try {
      if (isHtml) {
        const htmlText = await file.text();
        setFrameHtml(htmlText);
        renderFileList([file.name], file.name);
        if (previewStatus) previewStatus.textContent = "HTML preview ready. Click import when it looks right.";
        return;
      }

      const zipPreview = await readZipPreview(file);
      setFrameHtml(zipPreview.htmlText);
      renderFileList(zipPreview.paths, zipPreview.entryPath);
      if (previewStatus) {
        previewStatus.textContent = `Previewing ${zipPreview.entryPath}. Click import when it looks right.`;
      }
    } catch (error) {
      revokePreviewUrl();
      if (previewFrame) previewFrame.removeAttribute("src");
      if (previewFiles) previewFiles.innerHTML = "";
      if (previewStatus) {
        previewStatus.textContent = error instanceof Error ? error.message : "Could not preview this file.";
      }
    }
  }

  fileInput.addEventListener("change", () => {
    void handleFileChange();
  });

  clearButton?.addEventListener("click", () => {
    fileInput.value = "";
    hidePreview();
  });
})();
