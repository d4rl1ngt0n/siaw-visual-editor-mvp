# Phase 1 threat model

Baseline date: 18 July 2026

## Assets

- Uploaded website archives and extracted source trees
- Editor project state (`editor/project.json`) and restore-point snapshots
- Captured HTML from Interactive mode
- Exported ZIP downloads

## Entry points

1. ZIP / HTML upload (`/projects/upload/`)
2. Project file serving (`/projects/<id>/files/...`) including isolated runtime
3. Save / source write endpoints
4. Asset upload
5. Route / component capture POST bodies
6. Snapshot create / restore

## Trust boundaries

- Browser editor UI (authenticated only by local open access in Phase 1; no multi-tenant auth yet)
- Django process writing under `MEDIA_ROOT/projects/<uuid>/`
- Isolated runtime origin (`*.runtime.localhost` locally, `?runtime=1` in production hosts)

## Threats and controls

| Threat | Control in place |
|--------|------------------|
| Zip-slip / path traversal | `safe_project_path`, member path validation, blocked `..` |
| Malicious archive size | File count and uncompressed size caps |
| Dangerous executables in ZIP | Suffix allow/block lists |
| Script execution inside Safe Edit | Scripts stripped from editable body; canvas parser disallows scripts |
| XSS via served HTML | CSP on HTML/SVG responses; sandbox tokens on runtime |
| Capture HTML abuse | Size limits and sanitised capture path (existing bridge) |
| Overwrite via rename/page APIs | Path validation through `safe_project_path` |
| Snapshot path escape | Snapshot ids are directory names under project `snapshots/` without `..` |

## Residual risks (accepted for Phase 1 local/MVP)

- No user authentication: anyone with URL access can edit all projects
- Production runtime isolation is weaker without wildcard DNS
- CSP allows `'unsafe-inline'` / `'unsafe-eval'` for imported site compatibility
- Captured HTML is trusted as user-owned site content

## Phase 1 security exit checklist

- [x] Upload path validation and size limits covered by tests
- [x] Export validation warns on missing local assets / empty links
- [x] Support profile visible so users know JS app limits
- [ ] External penetration review (morning / PO gate)
- [ ] Auth and tenancy (Phase 2)
