# WeBridge AI Phase 1 product package

Status: Initial baseline for product and architecture review  
Source of truth: `../../../WeBridge_AI_Codex_Handoff.md` in the containing workspace  
Product: WeBridge AI  
Date: 21 July 2026

This package defines the documentation gate that must be approved before Phase 1 implementation continues. It distinguishes confirmed direction from recommendations, assumptions, and open decisions.

## 1. Product requirements document

### Outcome

WeBridge AI helps a qualified non-technical user create, edit, review, and publish a professional service-business website without technical support. The product must feel like a guided professional service rather than an empty design tool.

### Primary persona — confirmed

An independent service professional in Germany who needs a professional five-to-ten-page website, has limited design and technical experience, wants to launch within one week, and values a reliable professional result over unrestricted customisation.

Local service businesses are the adjacent high-priority persona. Freelancers, early-stage entrepreneurs, and small web creators may participate in controlled discovery but must not expand the initial product boundary.

### Phase 1 success definition — confirmed

At least 85% of qualified test users should produce a professional, publishable result without technical support. This is a target, not a guarantee.

Activation requires all of the following:

1. Complete onboarding.
2. Generate a website.
3. Make one meaningful edit.
4. Preview the website.
5. Publish to a temporary or custom domain.

Supporting targets:

| Measure | Target |
|---|---:|
| Registration completion | at least 90% |
| Onboarding completion | at least 80% |
| Successful AI generation | at least 95% |
| First structure accepted | at least 80% |
| Basic editor task completion | at least 85% |
| Publish completion among qualified users | at least 75% |
| Technical publication success | at least 95% |
| Support needed before publication | no more than 10–15% |
| Critical error rate | below 2% |
| SUS | 80 or higher |

### Product principles — confirmed

- Lead with business outcomes, not AI or infrastructure terminology.
- Guide the user through decisions and preserve all answers and meaningful edits.
- Permit local regeneration; never require full-site regeneration for a small change.
- Protect quality with design tokens, reusable components, responsive rules, contrast checks, and preview.
- Make pricing, renewal, domains, publication state, and failures understandable.
- Meet WCAG 2.2 Level AA in the platform and generated sites.
- Flag provider lock-in in AI, hosting, domains, and payments.

### Functional requirements

| Area | Phase 1 requirement |
|---|---|
| Identity | Email/password plus Google, Apple, and Microsoft sign-in; verification returns to onboarding |
| Onboarding | Progressive guided brief, autosave, back, save-and-exit, safe skip, step indicator |
| Generation | Sitemap, pages, initial copy, visual direction, responsive output, progress and retry |
| Reveal | Summarise pages, CTA, direction, responsiveness, SEO and feature status; focused feedback |
| Editor | Pages, Sections, Design, Content, Media, Settings; direct, AI, and structured controls |
| Safety | Autosave, undo/redo, named or automatic versions, recovery, preview before broad AI changes |
| Quality | Readiness checks for content, design, trust, SEO, and technical publication |
| Publishing | Preview, WeBridge subdomain, basic custom-domain connection, hosting, SSL, update and restore |
| Forms | Contact form configuration, delivery verification, and clear failure state |
| Analytics | Basic visits and enquiry visibility plus product-funnel instrumentation |
| Billing | Free, Professional, Business; transparent tax, renewal, AI allowance, and cancellation terms |
| Accessibility | Keyboard operation, focus states, labels, contrast, alt text, accessible errors/dialogs, reduced motion |

### Non-functional requirements

- Published site targets: LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1.
- Editor targets: acknowledgement < 100 ms, standard edit < 300 ms, save confirmation < 1 s, preview change < 2 s.
- AI text should visibly respond within 2–3 seconds; full generation must show immediate meaningful progress.
- Tenant data, previews, publications, assets, form submissions, and versions must be access-controlled and auditable.
- Failed generation, save, payment, domain, or publication operations must be idempotent where practical and must not discard user data.

## 2. MVP scope and non-goals

### In scope — confirmed

- Account registration, authentication, and account recovery.
- Guided business onboarding for independent professionals and service businesses.
- AI sitemap, page, copy, and constrained visual-direction generation.
- Five-to-ten-page component-based generated sites.
- Desktop, tablet, and mobile visual editing and preview.
- Direct text/media editing, structured design controls, and scoped AI edits.
- Autosave, undo/redo, version recovery, readiness checks, and publication warnings.
- WeBridge AI subdomain publishing; basic custom-domain connection; managed hosting and SSL.
- Contact forms, basic analytics, and subscription billing.

### Out of scope — confirmed

- Full CRM, advanced e-commerce, inventory, advanced marketing automation, and complex databases.
- Custom web applications, enterprise procurement, complex roles, and large-agency white labelling.
- Large integration or template marketplaces and hundreds of integrations.
- Code-download-first positioning or unlimited custom development.
- Phase 2 domain-reseller operations beyond the minimum connection experience.
- Phase 3 agents, workflow automation, and ecosystem/marketplace functions.

### Existing-product boundary — assessment

The current Django/GrapesJS codebase provides reusable foundations: authentication, project ownership, guided AI briefs, generation, multi-page editing, asset handling, responsive preview, restore points, and export validation. Direct publication, production-grade autosave/version semantics, readiness checks, complete billing/domain flows, analytics, and the full WeBridge information architecture require validation or implementation. Existing Shopify functionality is not part of the initial Phase 1 promise and must remain isolated so it does not distort the primary journey.

## 3. Primary user stories

Priority uses MoSCoW within Phase 1.

| ID | Priority | User story |
|---|---|---|
| US-01 | Must | As a prospective customer, I can understand the outcome, starting price, and managed nature of the service before registering. |
| US-02 | Must | As a new user, I can register without payment information and resume onboarding after verification. |
| US-03 | Must | As a non-technical professional, I can answer a progressive business brief and return later without losing answers. |
| US-04 | Must | As a user, I can see visual style choices rather than interpret design jargon. |
| US-05 | Must | As a user, I can approve or adjust the proposed sitemap before generation. |
| US-06 | Must | As a user, I can see meaningful generation progress, retry safely, and retain my brief after failure. |
| US-07 | Must | As a user, I can review the generated result and report whether content, design, structure, or information is wrong. |
| US-08 | Must | As a user, I can edit text and replace an image directly, then undo immediately. |
| US-09 | Must | As a user, I can request an AI change scoped to a section, page, or site and preview broad changes. |
| US-10 | Must | As a user, I can preview desktop, tablet, and mobile layouts without changing saved content. |
| US-11 | Must | As a user, I can recover a prior meaningful version after mistakes or failed changes. |
| US-12 | Must | As a user, I can see required and recommended readiness issues and navigate to fix them. |
| US-13 | Must | As a user, I can configure and test the contact-form recipient before publishing. |
| US-14 | Must | As a user, I can publish to a temporary WeBridge AI address and see an unambiguous live state. |
| US-15 | Must | As a paying user, I can connect a custom domain with provider-specific status and keep the temporary address during setup. |
| US-16 | Must | As a buyer, I can understand price, tax, renewal, AI allowance, domain treatment, and cancellation consequences before payment. |
| US-17 | Should | As a newly published user, I can see visits, enquiries, failures, and the next recommended action. |
| US-18 | Should | As an assistive-technology user, I can complete the core journey by keyboard and receive perceivable status and errors. |

## 4. Application sitemap

```text
Public
├── Landing
├── Examples
├── Pricing
├── How it works
├── Help / FAQ
├── Privacy / security / legal
└── Authentication
    ├── Register
    ├── Verify
    ├── Sign in
    └── Recover account

Authenticated
├── Dashboard
│   ├── Websites
│   ├── Website status and recommendations
│   └── Account alerts
├── New website
│   ├── Guided brief
│   ├── Sitemap and direction review
│   ├── Generation progress
│   └── First reveal
├── Website workspace
│   ├── Editor
│   ├── Preview
│   ├── Readiness
│   ├── Versions
│   ├── Forms
│   ├── Domain and publishing
│   └── Basic analytics
├── Billing and plan
├── Account
└── Help and escalation
```

## 5. Onboarding flow specification

Target completion time: 7–12 minutes. Every persisted step displays Back, Continue, Save and exit, progress, and “You can change all information later.” Skip is shown only for genuinely optional data.

| Step | Required input | Optional input | Output / validation |
|---|---|---|---|
| 1. Starting point | New site or existing-site redesign | Existing URL | Route and safe URL validation |
| 2. Business type | Industry/service category | Free-text refinement | Sector defaults; never exclude a valid service business |
| 3. Goals | One primary goal | Up to two secondary goals | Ordered goal list and recommended CTA |
| 4. Identity | Business name | Tagline | Non-empty name; editable later |
| 5. Offer | Plain-language business description | Services and prices | Missing/placeholder states identified |
| 6. Customers | Primary audience | Secondary audience | Audience summary for review |
| 7. Market | Location or service market | Languages | Locale and SEO context; no unsupported compliance claim |
| 8. Differentiation | Key value or approach | Proof points | Claims marked for user review |
| 9. Visitor action | Primary CTA | Secondary CTA | CTA label and destination are compatible |
| 10. Existing assets | Asset checklist | Logo, colours, images, reviews, links | Upload progress, type/size validation, alt-text prompts |
| 11. Visual direction | One visual card | Brand overrides | Accessible visual examples, not labels alone |
| 12. Review | Confirm brief | Edit any section | Proposed sitemap, missing facts, consent to generate |

Autosave uses debounced writes and shows Saving, Saved, Offline, and Failed states. Repeated submission must not create duplicate briefs or generations. Sensitive uploads must be private until publication.

## 6. Website generation workflow

```text
Validated brief
  → generation job and immutable brief snapshot
  → business understanding
  → sitemap and conversion plan
  → structured content draft
  → theme tokens and component selection
  → responsive page composition
  → automated schema/accessibility/link checks
  → versioned preview
  → focused user feedback
  → scoped regeneration or editor
```

### Generation contract — recommendation

Generation should produce structured site data, not treat raw HTML as the canonical model. Each job records the provider, model/version, prompt-template version, brief version, status, timestamps, cost/usage, warnings, and output version. Provider adapters must isolate AI lock-in.

Allowed regeneration scopes are component/section, page, theme, and whole site. Existing user-edited fields are locked by default. A broad regeneration must show a diff/preview and create a recoverable version before application.

Failure handling:

- Keep the brief and all uploads.
- Retrying an identical job is safe and does not duplicate a site.
- Explain whether failure is transient, input-related, quota-related, or internal without inventing state.
- Offer a deterministic professional fallback template when AI generation is unavailable.
- Log partial outputs privately for diagnosis; never expose secrets or another tenant's data.

## 7. Editor information architecture

| Region | Contents |
|---|---|
| Top bar | Website switch/back, undo, redo, viewport, preview, save state, readiness, publish |
| Left: Pages | Page list, hierarchy, add/duplicate/rename, SEO status, home marker |
| Left: Sections | Current-page outline, add/reorder/duplicate/hide/delete with keyboard alternatives |
| Left: Design | Global colours, typography, spacing, buttons, visual direction |
| Left: Content | Site facts, reusable business content, content-state filters |
| Left: Media | Uploads, search/filter, usage, replacement, alt text |
| Left: Settings | Navigation, forms, SEO defaults, site identity, integrations allowed in Phase 1 |
| Canvas | Live responsive page; direct selection and editing; accessible selection model |
| Right panel | Contextual content, layout, style, link, visibility, accessibility, and AI controls |

Content states are Ready, Needs review, Missing information, and Placeholder. AI controls always display the scope and preserve undo. Drag operations require equivalent move controls. Global tokens constrain typography, colour, spacing, buttons, contrast, and responsive behaviour.

## 8. High-level technical architecture

```text
Browser application
  ├── Public/auth/onboarding/dashboard UI
  ├── Structured editor + GrapesJS adapter
  └── Preview/readiness/publish UI
          │ HTTPS
Django application API
  ├── Identity and tenant authorization
  ├── Website/content/version service
  ├── Generation orchestrator + provider adapter
  ├── Asset and form service
  ├── Billing adapter
  ├── Domain/DNS adapter
  ├── Publication orchestrator
  └── Analytics/audit events
          │
  ├── Relational database
  ├── Private object storage
  ├── Queue/background workers
  └── Published-site build/storage/CDN boundary
```

Architecture boundaries:

- Django may remain the initial application/backend, but generated-site content must move toward a versioned schema independent of GrapesJS HTML.
- GrapesJS is an editor adapter, not the product data contract.
- Publishing consumes a frozen website version and produces an immutable build; it must not serve editor-private assets or drafts.
- AI, billing, registrar/DNS, email, analytics, storage, and hosting integrations sit behind explicit adapters.
- Preview and runtime origins must remain isolated from the editor origin; imported or generated scripts are untrusted.
- Background jobs handle generation, image processing, publication, DNS verification, email, and analytics aggregation.

## 9. Core data model

| Entity | Essential relationships / fields |
|---|---|
| User | identity, verification, locale; member of organisations |
| Organisation | owner, members, billing customer; owns websites |
| Website | organisation, name, status, current draft version, published version, subdomain |
| BusinessBrief | website/owner, progressive answers, completion state, version, autosave timestamps |
| Page | website, parent/order, title, slug, status, SEO fields |
| Component | page, stable ID, type, order/tree, props, content state, lock state |
| Theme | website, token set, visual direction, accessibility constraints |
| Asset | organisation, file metadata, privacy, usage, alt text, processing state |
| WebsiteVersion | website, parent, immutable schema snapshot, author/source, reason, timestamp |
| GenerationJob | website/brief/version, scope, provider metadata, status, usage, error class |
| Publication | website/version/domain, build ID, status, URL, timestamps, diagnostics |
| Domain | organisation, hostname, connection method, verification, DNS and SSL state |
| Form | website/page, recipient, fields, consent configuration, verification state |
| FormSubmission | form, encrypted/private payload, spam state, delivery status, retention timestamps |
| Subscription | organisation, plan, billing provider IDs, status, renewal/tax metadata |
| AnalyticsEvent | anonymous/user/session IDs, website, event name, properties, consent context |
| AuditEvent | actor, organisation, target, action, result, timestamp, request correlation ID |

Current `WebsiteProject`, `AIWebsiteBrief`, and `AIWebsiteAsset` models can be migration inputs, not assumed final contracts. Organisation tenancy, canonical page/component/theme schemas, immutable website versions, jobs, publication, domains, forms, subscriptions, and analytics need explicit persistence decisions.

## 10. Analytics event taxonomy

Naming convention: `object_action`; properties contain no generated copy, form contents, passwords, tokens, or unnecessary personal data. Every funnel event includes timestamp, anonymous/session identifier, authenticated user identifier when permitted, website/brief identifier, experiment version, device class, locale, and consent state.

| Journey | Events |
|---|---|
| Acquisition | `landing_viewed`, `example_viewed`, `pricing_viewed`, `registration_started` |
| Identity | `registration_completed`, `verification_completed`, `sign_in_completed`, `identity_error` |
| Onboarding | `onboarding_started`, `onboarding_step_viewed`, `onboarding_step_completed`, `onboarding_saved`, `onboarding_exited`, `onboarding_completed` |
| Generation | `generation_started`, `generation_progressed`, `generation_completed`, `generation_failed`, `generation_retried`, `fallback_selected` |
| Reveal | `website_revealed`, `structure_accepted`, `feedback_submitted`, `direction_regenerated` |
| Editing | `editor_opened`, `meaningful_edit_completed`, `media_replaced`, `ai_edit_requested`, `ai_edit_applied`, `undo_used`, `redo_used`, `autosave_failed`, `version_restored` |
| Preview/readiness | `viewport_previewed`, `full_preview_opened`, `readiness_started`, `readiness_issue_opened`, `readiness_issue_resolved` |
| Commercial | `plan_viewed`, `checkout_started`, `checkout_completed`, `checkout_failed`, `subscription_changed` |
| Domain/publish | `domain_flow_started`, `domain_verification_started`, `domain_connected`, `domain_failed`, `publish_started`, `publish_completed`, `publish_failed`, `site_opened` |
| Activation/support | `activation_completed`, `help_opened`, `ai_support_started`, `human_escalation_requested` |

Required derived funnels: registration, onboarding, generation, first-result acceptance, meaningful editing, preview, readiness, checkout, domain, publication, and activation. Operational metrics must distinguish product abandonment from technical failure.

## 11. Create-to-publish acceptance criteria

### End-to-end gate

Given a qualified new user with no prior project, when the user registers, completes the brief, generates, edits, previews, resolves required readiness items, chooses an eligible plan, and publishes, then the site is accessible at the confirmed URL, its contact form works, the published version is recorded, and the dashboard reports the live state without staff intervention.

### Required criteria

1. Registration requires no payment method, preserves valid input after errors, and returns a verified user to the saved onboarding state.
2. Every onboarding step is keyboard operable, autosaved, revisitable, and recoverable after refresh or sign-out.
3. Generation starts once per confirmed request, displays the six meaningful stages, and retains the complete brief on timeout or failure.
4. The generated website contains the approved pages, primary CTA, service information, responsive navigation, and no unlabelled placeholder presented as fact.
5. The first reveal states page count, CTA, direction, responsive status, SEO status, and enabled forms/features.
6. A user can change the main headline, replace one image with alt text, undo/redo, and preview mobile without losing edits.
7. Section/page/site AI scope is explicit; a broad change is previewed and versioned before application.
8. Autosave confirms within one second under normal conditions and presents a persistent recoverable failure state when saving fails.
9. The user can restore the pre-change version and the restored content persists after reload.
10. Readiness classifies findings as Ready, Recommended improvement, or Required before publishing; it never claims perfection.
11. Publication is blocked only by enumerated required failures, including invalid form delivery, missing required legal/privacy configuration, or an invalid build.
12. Pricing displays monthly/annual price, tax treatment, renewal, AI allowance, domain treatment, cancellation, upgrade, and downgrade rules before purchase.
13. Temporary-subdomain publication succeeds independently of custom-domain propagation and remains available during domain setup.
14. Domain status distinguishes pending verification, DNS propagation, SSL provisioning, connected, and failed, with a safe retry or support route.
15. Publication is idempotent, creates an immutable publication record, and does not expose drafts, private uploads, secrets, or another tenant's data.
16. The published site meets the agreed WCAG 2.2 AA test set and performance targets on the representative test fixture set.
17. Contact-form submission reaches the verified recipient, records delivery state, prevents obvious abuse, and respects retention/privacy rules.
18. Dashboard state answers whether the site and domain work, whether visits or contacts occurred, whether anything is broken, and what to do next.
19. Funnel and operational events are emitted once with schema-valid, privacy-minimised properties.
20. A user can update and republish, then restore and republish a previous version without support.

## 12. Risks, assumptions, dependencies, and unresolved decisions

### Assumptions

- The initial launch market is Germany and requires German/English product and generated-site support.
- Five-to-ten-page service-business sites can be represented by a constrained component schema.
- A temporary WeBridge AI subdomain is available before custom-domain connection.
- Existing editor functionality can be adapted incrementally without making imported raw HTML the permanent canonical format.

### Material risks

| Risk | Impact | Mitigation / decision gate |
|---|---|---|
| Raw HTML/GrapesJS state becomes the canonical model | Fragile regeneration, migration, and responsive quality | Approve structured website schema before feature implementation |
| AI output is generic, inaccurate, or overwrites edits | Trust and activation failure | Claim review states, scoped regeneration, locks, diffs, immutable versions |
| Provider lock-in | Cost, availability, migration risk | Provider adapters; store portable inputs/outputs and provider metadata |
| Publication mixes drafts and live assets | Security/privacy incident | Immutable builds, origin/storage separation, publication manifest |
| Domain/DNS/SSL failures are opaque | High support burden at trust-critical moment | Explicit state machine, provider diagnostics, temporary URL, human escalation |
| Autosave/version semantics are incomplete | Loss of work and trust | Server revisions, concurrency rules, offline/failure states, recovery tests |
| Phase 2/Shopify scope leaks into MVP | Delays core validation | Separate navigation, flags, backlog, and success metrics |
| Accessibility added late | Rework and exclusion | Component acceptance tests, keyboard/AT audits from first implementation |
| Analytics captures personal/business content | Compliance risk | Data minimisation, consent model, schema review, retention controls |
| Five-to-ten-page generation misses performance targets | Poor published experience | Build budgets, image pipeline, static output, representative Lighthouse CI |

### Dependencies

- Approved structured website schema and component/design-token catalogue.
- Identity provider and account-recovery decision.
- AI provider abstraction, data-processing terms, regional/privacy assessment, and fallback behavior.
- Hosting/CDN/object-storage and preview/publication isolation design.
- Temporary subdomain convention and DNS/SSL automation.
- Billing provider, tax/VAT treatment, and plan entitlements.
- Transactional email/form-delivery provider and abuse controls.
- Legal/privacy content responsibilities for Germany/EU.
- Representative usability, accessibility, performance, and publication test fixtures.

### Unresolved decisions — must be resolved before affected implementation

| ID | Decision | Recommended default | Owner |
|---|---|---|---|
| D-01 | Canonical generated-site schema and migration from current projects | Versioned JSON page/component/theme schema | Product + architecture |
| D-02 | Phase 1 page/component catalogue | Small service-business catalogue with guarded variants | Product + design |
| D-03 | Organisation support in first release | Persist organisation boundary; expose single-owner UI initially | Architecture |
| D-04 | Authentication providers at launch | Email plus Google first; confirm Apple/Microsoft timing against requirement | Product |
| D-05 | AI provider/model and fallback | Adapter plus deterministic fallback; no provider-specific domain objects | Architecture + procurement |
| D-06 | Hosting/publication stack | Immutable static builds on object storage/CDN | Architecture/operations |
| D-07 | Temporary hostname format | `<site-slug>-<short-id>.<webridge-domain>` with rename policy | Product + operations |
| D-08 | Custom domain mechanism/provider | DNS connection first; reseller purchasing remains Phase 2 unless explicitly approved | Product + operations |
| D-09 | Billing, VAT, and plan entitlements | Provider-managed checkout/tax where compliant; server-side entitlement table | Finance + product |
| D-10 | Version retention | Autosave revisions plus named milestones; publish versions retained | Product + architecture |
| D-11 | Required legal/privacy readiness rules | Market-specific checklist with explicit user responsibility | Legal + product |
| D-12 | Analytics and consent stack | First-party product events and privacy-minimised site analytics | Privacy + architecture |
| D-13 | Shopify code disposition | Feature-flag and exclude from Phase 1 primary IA and metrics | Product |
| D-14 | Launch languages | German and English recommended; confirm generated-content QA process | Product |

## Approval gate and next work

Implementation may proceed only after stakeholders approve the Phase 1 scope, primary persona, canonical website schema direction, publication boundary, and create-to-publish acceptance criteria. The next design deliverables are:

1. Canonical website JSON schema with versioning and example five-page site.
2. Component catalogue and design-token contract with accessibility constraints.
3. Autosave, optimistic-concurrency, undo, and version-recovery state model.
4. Publication/domain state machines and provider boundary contracts.
5. Traceability matrix mapping current code to user stories and acceptance criteria.
