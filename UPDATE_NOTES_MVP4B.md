# Siaw Visual Website Editor | MVP 4B

## Smart Navigation Manager

MVP 4B introduces a universal first version of the Navigation Manager.

### Static HTML menus

For compatible simple menus, users can:

- rename menu items;
- change links and section destinations;
- open links in a new tab;
- show or hide an item;
- add and duplicate links;
- move links up or down;
- delete links.

Complex dropdown or mega-menu structures are detected and protected. Their labels and destinations remain editable, but structural changes are locked to reduce the risk of breaking nested menu behaviour.

### JavaScript-generated menus

The manager detects supported arrays such as `const NAV = [...]`. It can safely:

- rename top-level menu items;
- reorder them;
- show or hide them;
- preserve call-to-action styling.

New JavaScript routes are not created automatically because adding a menu item does not create the page or router logic behind it.

## Editable JavaScript-generated component capture

Interactive mode now loads a small runtime bridge into the isolated preview. This bridge can inspect the running page without modifying the exported website.

Users can:

1. open Interactive mode;
2. click **Capture component**;
3. select a generated menu, review, carousel, card, form or application region;
4. save the captured design in the **Capture** tab;
5. insert it as editable static HTML or add it to the Blocks panel.

Captured HTML is sanitised by removing scripts and inline event handlers. Captures are stored in the editor project data and return after restarting the platform.

## Compatibility test set

MVP 4B was developed against:

- Order Siaw Manufacturing v32;
- Eurasien v50;
- 3DNow;
- Lung Compass;
- Fahrklar Tax/Fahrtenbuch.

Expected navigation support:

- Order Siaw: full simple-menu editing;
- Fahrklar: full simple sidebar-navigation editing;
- Lung Compass: JavaScript-array navigation editing;
- Eurasien and 3DNow: protected complex-menu label and destination editing.

## Security and honesty

A captured runtime component becomes a static editable copy. The platform does not claim that its original JavaScript, data source, carousel engine or application state has been transferred. Dedicated Smart Managers will progressively connect more component types to their real data.
