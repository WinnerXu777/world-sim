# Eden asset expansion H002 — decision plan and bounded pilot

2026-10-08; historical branch record: `1008implementation` (not rechecked in H004). LOCAL EVALUATION ONLY. Public
distribution licence remains uncleared. Bulk expansion remains a proposal; H004 is a separately authorized bounded proof. H004 authoring is limited to this root document and `myassets/h004_modular/`.
H002/H003 remain historical and unmodified. Existing art/catalogs, Python, Godot, maps, tests, ignore rules and
Git state must remain untouched. H002 here names an art batch; it does not replace
the H-002 chunk-loader handoff in `1008decisions.md`.

## Evidence and recommendation

Sources: root `myassets/*.md`, `manifest.json`, A3 provenance review/notices and
H001 progress; Godot README; `1008decisions.md` section 4; worldgen `assets.py`
GAPS and `1008_worldgen.md`; `1008_map_resources_design.md`; scenarios in
`1008implementation.md`; A3 local jobs/export workflow and actual sprites.
Current root catalog has 69 entries, not 69 species or character identities.
Eight residents share four body families. A3 rural sheets are 512x512; legacy
sheets are 384x512. A3 rejected square grids demonstrate that multi-direction
generation in one image is unreliable. H001 already adds 202 candidate tiles
(11 grounds, 188 transitions, three overlays), including tint/blend snow,
desert and marsh; do not count those as missing original grounds. A4 separately
provides static elder trader, baker, woodcutter, silver healer, garden cottage,
timber barn, inn, smith workshop, deer/goat/sheep/hen/dog and plants/props. Reuse
those candidates for style or static roles before commissioning replacements;
A4 static NPCs are not movement sheets. Its selected run/door/step sheets have
nominal pivots and documented contact drift, not general clothing layers.

**User decision, follow-up:** build a scalable **paperdoll system**. Existing
full-sheet characters remain reusable **baked body types**, alongside layered
bodies. Grounded animals, goblin/skeleton/spider, and creative invented creatures
are approved directions for planning. Appearance and mechanics are separate.

Use an imagegen adult base with frozen frame geometry, registered separable
layers, semantic anchors and explicit occlusion metadata. The production target
is detailed existing-game style. Preview stacking is QA only; future client
draws stacked sprites with one shared clock. Existing baked art stays reusable.
H003's deterministic prototype tested registration but did not settle art style.

## Shared export contract

All sizes below are **final native PNG canvas pixels**, not inference resolution.
Transparent RGBA upright sprites; nearest filtering; top-left origin, +x right,
+y down. Ground: 48x48, pivot [0,0], opaque for bases/transparent for overlays.
48px = 8 backend units = 6px/u. Actors are positioned by feet, current character
render scale 0.72. Keep a fixed contact pivot through every pose and direction;
no per-pose bbox recentering. Collision stays explicitly authored, not inferred
from alpha/shadows. Doors/main aisles 10u, secondary aisles >=8u, anchors >=3.4u
from walls. New building visual canvases do not define collision or usable space.

Naming: `<kind>-<identity>-<variant>-<state>-h002-v1.png`, lower-case kebab case;
e.g. `character-farmer-adult-female-sturdy-brown-work-idle-s-h002-v1.png`.
Full sheets replace `idle-s` with `walk4`; individual source strips use
`walk-s`, `walk-w`, `walk-e`, `walk-n`. Equipment: `overlay-<item>-<body>-walk4`.
Buildings include wall/roof, e.g. `building-hut-wood-thatch-closed-h002-v1.png`.
Terrain transitions use H001's directed pair directory and `mask-XX-h002-v1.png`.
Use new version filenames for revised pixels, preserve rejected/raw evidence.
Manifest IDs replace hyphens with underscores and are unique. Standalone
manifest only; future root-catalog admission/import belongs to a separate task.

Actor movement: four rows **south, west, east, north**, four columns, each
128x128 for humans, pivot [64,112]. Final walk sheet 512x512, walk
[0,1,2,3] at 6fps. Existing baked actors keep idle column 1; new modular actors
use a separate one-frame-per-direction idle sheet. For layered humans freeze
all exports against one pose guide; no runtime per-layer resize/recentering.
H004 raw generation needed documented offline per-design fitting; this is a
candidate limitation, not evidence of imagegen coordinate locking. For creatures, generated single-direction
strips still require one shared transform per strip. Legacy sheets
retain three columns and walk [0,1,2,1]; never silently convert them. Future work,
carry, attack: each separate 4-column x 4-row sheet, same pivot, 16 frames,
nonlooping at 6fps for attack/work; down: one frame per direction, 128x512.
H002 static appearance pilots have one frame/direction and must not be advertised
as movement sheets. H003 is a separately labelled two-frame south feasibility
strip, not a production walk/action atlas.

## Priority and scenario minimums

| Order | Gate / content | Scenario need |
| --- | --- | --- |
| P0 | H004 detailed modular style/fit proof, then complete south/east gait | H003 registration prototype passed; motion and production acceptance remain open |
| P1 | Smith/merchant/traveller, iron/stone states, smith/shop furniture | S-3 generalised commission; S-2 stranger |
| P2 | Farmer/family age variety, hut/farmhouse/stall, pantry/beds, wheat/root crop stages, berry depletion, wolf | S-1 hungry family; wolf near distant forage is a creature configuration, not a visible spawn marker |
| P3 | Winter clothes, crop failure/readable harvested state, granary/hearth, snow edges | S-4 bless harvest; S-5 ten-day winter scarcity |
| P4 | Remaining livestock/wildlife, inns/workshops, trees/POIs | S-2 exploration and trade; S-1 alternative food |
| P5 | Wealth/grand buildings, hostile fantasy creatures, refined biome sets, UI | Variety after minimum scenarios read clearly |

S-1 first replaces farm-plot and stall stand-ins: two homes/interiors, five beds,
three plots, three forage bushes, pantry/trade storage, well and wood pile.
Reuse existing well/crate/cot/wood art where suitable. S-2 needs a recognizable
traveller, merchant and arrival/inn/shop setting. S-3 needs visible material
availability and distinct crafter workplaces; copper/coal art does not implement
recipes. S-4 shows growth/yield through authoritative state, not an invented
blessing animation or count of drawn stalks. S-5 needs readable winter/depletion,
shelter, hearth and stores. Animals, castles and extra identities are enrichment,
not backend acceptance requirements. Scenario changes, spawn tables, maps,
resource state selectors and client admission are outside this asset task.

## (a) Paperdoll characters and appearances

### Modular contract (H004; production target)

Settled: maximum practical modularity and detailed production art matching A3's
warm muted palette, dark outlines and native scale. H003 remains a coarse
registration experiment, not the style target. H004 is an imagegen candidate
proof; actual delivered coverage is recorded in its PILOT_REPORT.md.

Master frame canvas: 256x256 transparent RGBA, origin top left, +x right/+y down;
fixed foot pivot [128,224], adult target height about 160px. Derive compatibility
1x frames by exact nearest downscale to 128x128, pivot [64,112], about 80px adult.
Use one shared rig/clock and full untrimmed margins at either resolution.
Master display .36 equals compatibility .72; .40 matches current A3 rural height.
No trimming, per-layer scaling/recentering, or per-layer animation clocks.
Each rig version freezes per-frame head/crown, neck, shoulders, elbows, wrists,
grips, waist/hips, knees, ankles and sole anchors plus semantic fit/occlusion
masks. Anchors are integer native pixels, separate from collision authority.
Child (100px master / 50px compatibility), elder posture, adult sex/silhouette and slim/average/sturdy builds
are separate fit families, never scaled adult clothing. Skin is independent
of sex, build, role and wealth. Face, eyes, brows, mouth, ears and facial hair
are separate optional layers; do not bake role, hair or equipment into a body.

Production directions: south, west, east, north (row order S/W/E/N), explicit
asymmetric exports, no automatic mirroring of handed equipment. Idle: one
frame per direction, master 256x1024 (compatibility 128x512). Walk: four genuine
gait phases per direction, master 1024x1024 (compatibility 512x512), loop
[0,1,2,3] at 6fps. Run/carry/work/attack/use: separate compatible
four-column sheets; work/attack/use nonlooping, timing authored by action.
Down: one frame/direction. Every visible slot shares action/direction/frame.
Missing action coverage must be explicit; never stretch idle into a walk.
Partial candidates may use s1x1 but must not claim production swen coverage.

### H005 result

The orchestrator accepts H004's earth-tone pixel style on the user's behalf.
H005 delivers higher-detail master/1x south/east idle layers, separate boots,
four tunic palettes and a south-idle gripping-hand candidate. Briefs remain
baked after the separate-underwear edit failed. Raw body root drift improved
from 18.62/14.71px to 11.68/8.15px (south/east); explicit offline corrections
stabilize exported feet but do not prove generated registration. Both four-frame
walk trials fail the production gait/garment-fit gate; generation stopped at
the best achieved state. Integrity passes 120/120 shifted negative controls,
30 exact downscales and 16 stack replays; one thin 1x handle witness fails.
See `myassets/h005_production/PILOT_REPORT.md` and stacked previews for numbers,
scope and options. No hair/cloak/hammer reuse, game edits or Godot imports.
User must check imagegen output terms before public distribution; licence
clearance remains unresolved.

### h006 cut-out rig

H006 replaces generated walk frames with two static imagegen rest designs and
deterministic transform animation. The 256px/[128,224] rig has 15 parts: head,
torso, pelvis, paired upper/lower arms and hands, paired upper/lower legs and
boots. South/east joint pivots and draw orders are frozen in
`myassets/h006_cutout/rig.json`; west is an east mirror rule, north omitted.
Body, tunic, trousers and boots share the same 3px-overlap part masks, with
documented procedural joint caps. Briefs remain baked. Hair is not delivered.

`animations.json` stores per-direction clips with eight time-stamped per-part
local clockwise rotation/offset keyframes in master pixels, parent hierarchy
in rig.json, and contact metadata. The standalone Pillow/numpy animator renders
walk, breathing idle and a work/swing gesture; no Godot import or game changes.
Results **fail production motion at .40 and 2x**: sleeve/hem fragments, rigid
cloth and sliding feet remain. Walk stance x ranges reach 19.74px south/38.69px
east; ground-anchor error reaches 4.31/8.27px. Joint radius3 core gaps are zero,
but radius6 transparent counts are 62/33 and detached pixels total 131/247;
core coverage cannot certify seams. See `myassets/h006_cutout/PILOT_REPORT.md`
for viewed sheets, measurement limitations and the missing-forearm control.
Recommend artist-cleaned parts plus mesh deformation/contact-aware foot motion,
or hand-authored pixel walks; existing baked A3 walks with paperdoll idle remain
a pragmatic hybrid with appearance-transition costs. Two serial calls, 72.038s;
price unavailable. User must check imagegen output terms before distribution.

### Slots and draw order

Increasing order draws later; rear/front fragments are independent registered
textures belonging to one design. Empty fragments remain transparent.

| Slot | South order | North order | East/west rule |
| --- | ---: | ---: | --- |
| held-rear / far-hand equipment | 5 | 5 | 5; visible far hand |
| back-item rear / cloak rear | 8 | 8 | 8 |
| hair-rear | 10 | 10 | 10 |
| body | 20 | 20 | 20 |
| underwear | 25 | 25 | 25 |
| face, eyes, brows, mouth, facial hair | 26-29 | hidden unless visible | 26-29 |
| socks, footwear, lower clothing | 32/35/40 | 32/35/40 | 32/35/40 |
| upper clothing, belt/apron | 45/47 | 45/47 | 45/47 |
| armour, outer clothing front | 50/52 | 50/52 | 50/52 |
| back-item foreground | 55 | 55 | 55; nearer straps/pack |
| hair-front | 60 | 60 | 60 |
| headgear | 70 | 70 | 70 |
| held-front / near-hand equipment | 80 | 80 | 80 |
| hand-front/body-front fragments | 85 | 85 | 85; fingers over grip |

Each design declares direction/frame-specific visible fragments, anchor bindings,
allowed support, seam witnesses and occludes/hides tags. A south pack normally
uses rear pixels; north uses foreground pack pixels. Cloaks split behind body
and front fastener. Hats hide only declared hair zones using full-grid masks;
hands above sleeves/grips use extracted body fragments. No whole-body reorder
to fix a finger. Armour declares incompatible outer garments; layers never edit
one another. Clothing tiers are design/palette presets (peasant, working,
merchant, noble, guard), independent of body geometry and simulation wealth.

### Palette, files and manifest

Use discrete material indices: transparent 0, protected outline, skin shades,
hair shades, cloth/metal/leather ramps, protected eyes/underwear. Six skin,
six hair and eight cloth ramps are the target. First use offline exact ramp
lookup exports with identical alpha/geometry; no new inference for colour swaps.
Keep semantic material mask and lookup table alongside each design. Never
recolour eyes, outlines or clothes by a global hue shift. Later optional shader
must match the offline references; it is outside this asset task.

Naming: pd-<rig>-<slot>-<design>-<palette>-<action>-<grid>-h004-v<N>.png;
rig includes age, sex/silhouette, build and version; grid e.g. swen4x4 or s1x1.
IDs use underscores. Full transparent frame margins are mandatory. Standalone
manifest, no root-catalog or client imports in this task.

Compatibility-resolution example (master doubles frame size and pivot):

```json
{
  "schema": "paperdoll-modular-v1",
  "frame_size": [128,128], "pivot": [64,112],
  "assets": [{
    "id": "adult_average_v1_upper_peasant_v1",
    "path": "layers/pd-example.png", "sha256": "...",
    "rig_version": "adult-average-v1", "guide_sha256": "...",
    "slot": "upper", "design": "peasant", "fragment": "front",
    "action": "walk", "directions": ["s","w","e","n"],
    "grid": [4,4], "frames": 16, "fps": 6,
    "anchors_by_frame": "anchors.json",
    "support_mask": "masks/upper.png", "support_sha256": "...",
    "material_mask": "masks/upper-material.png",
    "palette_table": "palettes.json", "palette": "moss",
    "z_by_direction": {"s":45,"w":45,"e":45,"n":45},
    "occludes": ["torso"], "hides": [], "incompatible": [],
    "seam_witnesses": "seams.json", "provenance_id": "gen-002",
    "status": "candidate", "license_status": "release-unresolved"
  }]
}
```

Appearance record selects render_mode, compatible rig/body, skin palette,
face feature IDs, hair style/colour, clothing IDs, headgear, held left/right
and back item IDs. Baked mode instead selects existing baked catalog ID/grid/
clock/pivot and hides all modular slots. Preserve existing resident identities;
legacy three-column and rural four-column sheets retain original animation
metadata. Baked characters cover unfilled roles while modular rigs mature.

### Production and validation

Use built-in imagegen only for new generated art: generate base, freeze approved
anatomy, use it as edit registration reference for isolated layers, inspect and
retarget candidate output before admission. Independent garment concepts are
not registered layers. Keep every raw output and explicit transforms; extraction,
palette lookup and preview stacking are derivatives, not generated artwork.
No local model inference. Existing art is visual comparison only; no licensed
pack pixels supplied to the generator.

Validation adapts H003's support XOR/leakage, anchor coverage and stack tests.
Reopen all PNGs; check dimensions, RGBA/binary alpha, border clipping, exact
rig/action/grid/pivot/hash agreement and every manifest path. Against reviewed
frozen per-design masks, check support XOR and alpha outside allowances, then
independent neck/waist/crown/grip/sole witnesses and seam coverage. Palette
variants must have identical alpha and zero changed protected pixels. Compare
on-disk stacking with separately replayed stack; preview provenance lists inputs.
Shift EVERY layer 4px and require rejection, including body and palette variants.
Passing a self-frozen support mask proves file integrity/translation detection,
not anatomical fit: semantic witnesses and visual review remain mandatory.
Assess gait/contact drift across frames, silhouette/outline/light consistency,
long-hair/cloak/weapon occlusion and native-scale readability separately.

To add a layer: select existing compatible rig/action; copy frozen guides without
editing them; generate isolated design with imagegen; inspect fit and author its
own allowances/material metadata; export full canvas; add a new manifest entry,
anchors and occlusion rules; run all-layer and shifted-negative validation and
combination previews. New item must not alter other layers. New rig geometry
requires a new rig version and all compatible garments revalidated/refitted.

### Scaling plan

Adult minimum: 19 designs (body, underwear, 2 lower, 6 upper, 2 outer, 3 hair,
2 headgear, 2 equipment), plus 6-12 rear/front/hand fragments. Child and elder
mini-kits: eight refitted designs each, total 35 designs before fragments.
Four direction edit outputs/design/action imply 140 imagegen calls for one
movement action; idle + walk separately implies 280, plus 24-48 split-fragment
outputs per action if generated separately. Later face/features, sex/build
families and weapons multiply fit work; palettes add zero generation calls.
These are planning estimates, not authorization for volume or guarantees of
registration. Start with accepted adult south idle, then south/east walk, then
full four directions before expansion. Per-layer timings and actual acceptance
are in H004's report; API prices are not exposed by the tool.

Licence unresolved: the user must check imagegen output terms before public
distribution. No commercial clearance is asserted. Existing source-art notices
remain applicable separately. Provenance records tool, returned model identity
(unknown if not exposed), exact prompt, seed=null if unavailable, references,
timestamps, wall time, raw/export hashes and all derivative operations.


## (b) Species and hostile creatures

Target **18 species/designs** = 14 requested fauna designs (birds split into
songbird and crow), existing goat, and 3 hostiles. Each row's count is designs,
with one base coat per design; later two masked coat variants for dog/cat/horse
are six derivatives, not six new species. All pivots fixed per frame.

| Designs | Count | Frame canvas / pivot | Stored movement sheet |
| --- | ---: | --- | --- |
| Wolf, boar, fox, sheep, dog, cat, goat | 7 | 128x128 / [64,112] | 512x512; 16 frames |
| Rabbit, songbird, crow, chicken | 4 | 64x64 / [32,56] | 256x256; 16 frames |
| Fish, submerged silhouette | 1 | 64x64 / [32,56] | 256x256; 16 swim frames; water surface contact anchor |
| Deer (retain A4 size), cow, horse | 3 | 160x160 / [80,144] | 640x640; 16 frames |
| Goblin, skeleton | 2 | 128x128 / [64,112] | 512x512; 16 frames |
| Giant spider | 1 | 128x128 / [64,112] | 512x512; 16 frames |
| **Total** | **18** | | |

The requested list has 13 named fauna groups; splitting birds adds one and goat
adds one: **15 fauna + 3 hostiles = 18**.

Directions/idle/walk match humans; fly/swim loop at 6fps. Future hostile attack
sheet: same grid, 16 frames, nonlooping; future down sheet: four directions, one
frame each. Static A4 deer/goat/sheep remain references/reusable idle candidates;
do not claim static pictures can yield believable animated gaits procedurally.
Wolf first for S-1; boar/rabbit/deer for S-1/S-2 forage landscapes; livestock for
S-4/S-5 farm scenes; fox/birds/fish/cat/dog later. Hostile fantasy species P5 are accepted as an art direction; specific designs
and motion still need pilot review. No new gameplay species implied by files.

Cost: 72 direction jobs for 18 moving designs; 12 more if three hostile attack
sheets are approved. Coat variants zero inference after mask QA. First review
wolf/one small/one large static specimen, then a quadruped cycle before bulk.
Pilot: wolf only, 128x128 [64,112], one south-facing idle/three-quarter pose.

### Creative creature bible ? expanded art roadmap

Keep the 15 grounded fauna and goblin/skeleton/spider above, then add **10 invented
species**: **28 base designs total**. Also plan **12 curated variants**, not new
species. No invented creature is generated in H003. All hooks below are **mechanics
suggestions for `1008expandtools_instincts.md`**, not implemented behaviour, spawn
weights, tools, loot promises or additions to that file. Temperament is an art
brief; hostile/nonhostile encounters must be chosen by simulation owners.

| Existing grounded group | Readable art cue / suggested behaviour hook |
| --- | --- |
| Wolf | Grey winter coat or scarred pack leader; pack pursuit, avoid fire |
| Boar, rabbit | Bristled charging silhouette / alert ears; crop raider / crop pest, flee threat |
| Fox, crow | Red low-slung tail / dark beak; scavenging, pantry theft, carcass discovery |
| Deer, songbird | Antlers/spotted fawn / tiny bright wing; grazing/fleeing, seasonal migration |
| Fish | Submerged silver silhouette; seasonal fishing abundance; ripple marker remains separate |
| Chicken, sheep, cow, goat | Comb / wool / broad muzzle / horns; eggs, wool, milk, browsing are proposed hooks only |
| Horse, dog, cat | Saddle blanket / collared alert ears / curled tail; merchant transport, warning/bond, pest control |
| Goblin | Small wiry humanoid, patched scavenged kit; raider vs barter-capable scavenger variants |
| Skeleton | Clear bones and dull salvaged gear; ruin guardian, dormant until disturbed |
| Giant spider | Eight-leg silhouette, low abdomen, no humanoid hands; ambush/web territory |

Invented species: each frame/sheet uses S/W/E/N and four columns, idle 1,
walk [0,1,2,3] at 6fps; flying/swimming also 6fps. Sizes/pivots are native, fixed
through the 16-frame sheet. Attack/work designs are separate sheets if needed.

| New design | Frame / pivot; full sheet | Art identity and suggested hook |
| --- | --- | --- |
| Brambleback | 128x128 / [64,112]; 512x512 | Hedgehog-like boar with thorny woody ridges; orchard pest, defensive curled posture; avoid making it a recoloured boar |
| Mire lantern | 64x64 / [32,56]; 256x256 | Frog-sized swamp amphibian with luminous throat sac, reed-coloured limbs; nocturnal insect hunter, lure/omen sightings; ground pivot, glow exported separately later |
| Cinder moth | 64x64 / [32,56]; 256x256 | Broad charcoal wings with ember eye spots; scavenger near hearths, rare fire-risk suggestion; pivot is projected ground position, flight height recorded separately |
| Cairn keeper | 160x160 / [80,144]; 640x640 | Stocky stone-bodied guardian, stacked shoulder slabs and moss joints; shrine guardian, tolerates respectful visitors; articulated legs rather than a static boulder |
| Thread thief | 64x64 / [32,56]; 256x256 | Six-limbed weasel-like imp carrying tangled yarn, long angular ears; workshop/pantry pest, steals scraps; clearly distinct from cat |
| Bellhorn | 160x160 / [80,144]; 640x640 | Calm shaggy caravan beast with curled hollow horns and harness; merchants' pack animal, load fatigue/bonding suggestions; harness is a separate compatible overlay later |
| Glassfin | 64x64 / [32,56]; 256x256 | Translucent-looking river fish with hard cyan pixel facets; rare fish/omen, water-quality association; limited alpha, not blurry glass |
| Moonhart | 160x160 / [80,144]; 640x640 | Pale deer-like creature with crescent antlers and dark mask, subtle markings; rare nonhostile omen, distant watch/flee hook; no promised magical buff |
| Rootling | 128x128 / [64,112]; 512x512 | Small knotted-root walker, leaf collar, seedpod satchel; grove guardian/forager or barter visitor; woodland friendly and drought-irritable art moods |
| Hollow rook | 128x128 / [64,112]; 512x512 | Large raven-like walking creature, bone-white face plate and twig crown; scavenger, alarm caller, ruin omen; separate perched/walking vs flying cycle later |

Twelve variant designs: winter wolf and pack leader; bristle boar; red/grey fox;
goblin barterer and scrap raider; armoured skeleton; cave and orchard spider;
moss and frost cairn keeper; autumn rootling. Count: wolf2 + boar1 + fox1 +
goblin2 + skeleton1 + spider2 + cairn2 + rootling1 = **12**. Each inherits its
species frame/pivot/grid. Colour-only coat variants use material masks; armour,
antlers, thorns, harness or body changes need authored fit/new poses and review.
Keep silhouettes legible against snow, grass and swamp; rarity does not justify
unreadable low contrast. No glow baked into opaque backgrounds.

Production: grounded wolf/boar/rabbit gait first (S-1/S-2), livestock (S-4/S-5),
goblin/skeleton/spider pilot, then Brambleback/Rootling/Bellhorn, then rare omen
and guardian designs. Cost: original 18 designs 72 direction jobs; invented ten
add **40 direction jobs** if imagegen generation is used; variants **0-24 jobs**
depending on mask reuse/new geometry. A full 28-design movement set is **112
jobs / 448 stored frames**, plus 12 variant sheets/192 frames. Up to 12 extra
jobs for original three hostile attack sheets; no mass attack-sheet scope for
new creatures until mechanics owners choose actions. Each creature family gets
user pilot review followed by one accepted animated cycle before expansion.

## (c) Buildings, material variants and interiors

Target **26 exterior components/designs**, one static frame each, except castle
gate open/closed (two). All pivots below are contact centres, never roof centres.
For facades, principal doorway floor lies on pivot Y; portal approaches remain
separate map anchors. Target 60px clear main door art; buildings native scale 1.

| Building(s) | Count | Canvas / pivot | Tier, first use |
| --- | ---: | --- | --- |
| Hut | 1 | 192x192 / [96,176] | T1; S-1 |
| Cottage, farmhouse | 2 | 288x336 / [144,312] | T1/T2; S-1/S-4 |
| Longhouse, inn, tavern | 3 | 384x384 / [192,360] | T2; S-2/S-5 |
| Shop | 1 | 288x336 / [144,312] | T2; S-2/S-3 |
| Market stall | 1 | 192x192 / [96,176] | T1; S-1/S-2 |
| Smith, carpenter, weaver, potter workshops | 4 | 288x336 / [144,312] | T2; S-3 |
| Barn, granary | 2 | 336x336 / [168,312] | T2; S-4/S-5 |
| Mill | 1 | 384x432 / [192,408] | T2; S-4; static wheel first |
| Watchtower | 1 | 192x384 / [96,360] | T3; S-2 enrichment |
| Chapel, temple | 2 | 384x432 / [192,408] | T3; P5 |
| Manor | 1 | 480x432 / [240,408] | T3; P5 |
| Town hall / grand hall | 1 | 576x480 / [288,448] | T3; P5 scale pilot |
| Castle gate | 1 | 384x384 / [192,360] | T4; two states |
| Castle straight wall N/S, E/W, corner, end cap | 4 | 192x192 / [96,176] | T4; modular |
| Castle keep | 1 | 576x624 / [288,592] | T4; P5 |
| **Total** | **26** | | |

Use **26 designs, 27 state PNGs** as the exterior budget. Modular walls have a
separate ground footprint/connection metadata; a whole castle is not one giant
sprite. Avoid roofs crossing walkable areas without an occlusion plan.

Materials: wood, stone, brick wall sets; thatch, timber-shingle, slate roofs.
Existing plaster stays an additional option. Wood/thatch huts; wood/stone cottage,
farm/barn; brick/slate shop/workshop; stone/slate civic/castle. These are curated
pairings, not physically implausible every-material variants. Initial variant
budget: two additional palettes/material compositions for cottage, farmhouse,
inn, shop, smith workshop, barn, manor, hall = **16 extra exteriors**, all same
per-design canvas/pivot. Recolour wood/brick is not a new stone/thatch texture.
Derive compatible wall/roof assemblies from existing Hypnobius crops; generate
thatch/hut/longhouse/mill/grand silhouettes and new architectural features.
Match existing steep roofs and restrained pixel detail, not isometric diamond
ground planes. No pack pixels used as model reference/training input.

Interior kit **32 furniture designs**, eight per tier: each tier has bed, hearth,
table, chair, storage, counter, light and one signature item (T1 stool, T2 pantry,
T3 bookcase, T4 throne). Beds 96x96 [48,84]; hearth 128x144 [64,134]; tables and
counters 128x96 [64,86]; chairs/stools/storage/light 64x96 [32,86]; pantry/bookcase
96x144 [48,134]; throne 96x128 [48,118]. One static frame each. Tier treatment:
T1 straw cot/rough wood/open hearth; T2 timber bed/pantry/tiled hearth; T3 dressed
stone/fireplace/dyed textiles; T4 carved furniture/grand hearth/ornament. Reuse
existing cot/crate/barrel/forge/anvil where role fits, keeping source pivots.
Two 48x48 floors and north/east/south/west wall modules per tier = **24 room
modules**, floors [0,0], walls 48x96 [24,96], one frame. Room layouts remain map
author work; different canvas art does not implement building interiors.

Cost: 26 base concept jobs + gate-open 1 + up to 16 material jobs + up to 32
furniture jobs = **27-75 jobs**, fewer when compatible crop/composition works;
24 room modules derived (zero inference). Review hut/cottage/grand hall first,
then one furnishable T1/T2 room, then castle wall junctions before each expansion.
Pilot uses **grand hall only**, 576x480 [288,448], one closed facade frame; hut
and cottage are planned review samples, not generated in this bounded run.

## (d) H-001 items 5–10: props and resources

One frame per state unless specified. Fixed pivots survive state changes; depleted
art must still indicate the same node. Resource labels/art cannot determine stock:
choose from authoritative depletion/regrowth state. Do not mistake ore for an
ingot, or decorations for resources; village trees remain decorative.

| Group / individual specifications | Count | Derivation / need / first scenarios |
| --- | ---: | --- |
| Birch, dead tree, palm, sapling, thicket: 224x208 [112,193]; cut stump: 64x64 [32,56] | 6 | New silhouettes; stump/thicket can be composed with source records; S-2, S-1 depleted wood |
| Bare/snow-covered oak, pine, apple: source canvases 224x208 [112,193], 176x240 [88,227], 192x224 [96,208] respectively | 6 | Masks/branch edits; bare foliage may need manual art; S-5 |
| Stone, iron, copper, coal, clay: full + depleted, each 96x96 [48,86] | 10 | Existing rock facets + ore colour masks; clay needs distinct low bank; S-3 then S-1 |
| Wheat, turnip: sprout/half/ripe/harvested + one tilled plot; 48x48 [0,0] | 9 | New crop shape then procedural stage composition; S-1/S-4/S-5 |
| Ruin wall straight + corner 96x96 [48,86]; pillar 64x96 [32,86]; shrine 96x128 [48,118]; cave 144x112 [72,104]; tent 144x128 [72,118]; bedroll 96x64 [48,56] | 7 | Ruin crops/compositions; new shrine/cave/tent; S-2 |
| Fish ripple 4-frame 192x48 strip (48x48 cells [0,0], 4fps); bare berry 80x96 [40,87]; picked mushrooms 64x64 [32,56]; cut reeds 80x112 [40,100] | 4 assets / 7 frames | Procedural ripple and masked states; S-1/S-5 |

Total **42 asset files / 45 stored frames** (animals item 8 counted in (b), not
again). Estimate **10-18 imagegen jobs**, remaining copies/masks/crops
zero inference. Review three tree/ore/crop examples, then depletion pair and
native-scale plots before expansion. No props generated in this pilot.

## (e) Biomes beyond H-001

Reuse H001 bases as comparison, not new claims of original snow/desert/swamp art.
Propose nine distinct 48x48 [0,0] opaque periodic bases: powder snow, packed snow,
ice; dune sand, gravel desert, cracked dry ground; peat mud, shallow swamp water,
wet leaf litter. Two extra visual variants each = **27 base PNGs**. Derive packed
snow/ice/gravel/water variants where credible; generate actual dune/peat/snow
texture motifs when simple tints fail. Six directed transition pairs (grass→snow,
snow→ice, sand→gravel, sand→dry ground, grass→peat, peat→swamp water), **282**
48x48 blob tiles using H001's 47-mask semantics; no unsupported 16-mask shortcut.
Nine overlays: footprints, snow clumps, frost grass, dune crest, desert pebbles,
dry scrub, puddles, cattails, wet stones, 48x48 [0,0], one frame each. Total **318
PNG files**. Snow and depth have no current payload selector; biome identity,
season rule and three-material junction precedence require client/backend owner
decisions. Seed art **3-9 inference jobs**, edges/variants procedural. S-5 snow
first, S-2 desert/swamp later. Review 3x3 repeats, all inner/outer corners and
cross-chunk seams before expansion. No biome generation in this pilot.

## (f) Cheap UI and emotes

Eight emotes: talk, hungry, cold, question, happy, angry, trade, danger. Eight
32x32 [16,32] world bubble images, one frame each; world attachment above head
is renderer configuration. Twelve inventory/resource icons: wood, stone, iron
ore, copper ore, coal, clay, wheat, turnip, berry, mushroom, reed, fish; 32x32
[0,0], one frame each. **20 files**, derive downsampled reviewed items or draw
simple project geometry, zero inference expected. S-1 hunger/trade, S-3 materials,
S-4 talk, S-5 cold. No hidden resident state exposed through emotes. Review one
native-size icon row against current HUD; skip if it duplicates working effects.

## Generation budget, gates and provenance

All new generation uses the built-in imagegen tool, serially and in bounded
volume. No local-model inference is authorized. Tool-selected model/version,
seed and monetary cost may not be exposed; record them as unknown/null rather
than invent values. Record measured call wall time separately from total art/QA
time. Raw output sizes are observed, not assumed from prompts; approved exports
retain fixed native canvases and a documented shared transform/retarget step.
Palette swaps and stacked previews require zero new generation. Category job
budgets below/above are imagegen planning estimates, not measured throughput or
approval for bulk. H004's measured count and limits are in its report.

Every category has an independent gate: small appearance samples → **user review**
→ one complete reusable/animated example → **user review** → named/count-limited
expansion. Approval for this pilot is not approval for those later batches.
Contact sheets show checkerboard, native scale, dimensions and contact crosses.
Reject clipped bodies, baked grounds, wrong facing, changing anatomy/materials,
sliding feet, unreadable states or mismatched architectural style. Machine QA:
reopen PNG, exact canvas/frame grid, alpha/pivot bounds, hashes and manifest
references. Later Godot QA checks gait, scale, Y-sorting, door reach and roof
occlusion; no Godot import or live acceptance in this task.

Preserve raw output, full prompt/negative prompt, seed, tool/model/settings,
timestamps, exit status, reference list, raw/export hashes and transforms. Record
runtime/weight hashes if measured, distinguish historical hashes from current
measurements. Never substitute filename for licence evidence. New output records
inherit LOCAL EVALUATION / release-unresolved status from A3. Imagegen output terms must be checked by the user before public distribution;
this is unresolved and no blanket commercial clearance is asserted.
Existing Hypnobius derivatives retain project-use/no raw-pack redistribution
terms; GoatBoy derivatives retain game credit/source association. Do not feed
licensed pack artwork to generation as a reference. H002/H003 had no image references. H004 uses its own generated base as a
registration edit reference; existing game art is inspection-only comparison. Review licences as a
separate release task against source receipts; no fresh legal clearance here.

## Open decisions for the user

Settled: paperdolls with reusable baked characters; grounded fauna plus fantasy
hostiles and creative new creatures. Those are not permission to run bulk art.

1. Settled: production detail follows existing A3 art, not H003's coarse style.
   Review H004's assembled candidates for anatomy, fit and outline acceptance.
2. Prioritise adult average then child/elder mini-kits, or fund adult slim/sturdy
   variants before child/elder refits? Choose the first garment/hair presets.
3. Rank invented creatures in the bible below for the next reviewed art pilot;
   proposed behaviour hooks remain suggestions, not mechanics to implement here.
4. Choose hall civic/church identity and material/architecture priorities from H002.
5. Prioritise scenario readability or grandeur after the registration gate.
6. Client/backend owners must decide appearance storage/version fallback,
   winter/depth/resource-state selectors, overlay placement and biome junctions.
7. Check imagegen output terms before public distribution; unresolved. Historical
   local-model candidates and licensed source art need separate release review.

## Pilot results

Completed after this plan was written: **three local generations total**, one
farmer, one wolf, one grand hall; three transparent static PNG exports and three
category contact-sheet previews under `myassets/h002_pilot/`. No further inference.

| Generated item | Export / pivot | Frames / seed | Result |
| --- | --- | --- | --- |
| Female farmer, work apron | 128x128 / [64,112] | 1 / 1008201 | Readable appearance; head turns east, body slimmer and skin lighter than requested; not approved south animation art |
| Grey wolf | 128x128 / [64,112] | 1 / 1008202 | Southwest pose despite south request; export named idle-sw; not a movement sheet |
| Stone/slate grand hall | 576x480 / [288,448] | 1 / 1008203 | Cross/bell turret reads chapel-like; unintended steps; doorway threshold pivot reviewed |

Successful serial wall times 46.14/45.64/102.87 s, total **194.66 s** (not total
session time). Historical H002 local-model workflow (not used or authorized for H004),
Euler32/CFG6, offload/FA/q8_0,
two CPU threads, empty references. One initial PowerShell stderr handling stop
produced no image; corrected new runner then completed all three jobs, exit 0.
No paid API calls or downloads. Runtime checksum measured; diffusion checksum
labelled historical A3; current model/encoder/VAE checksums not remeasured.
Planning allowance remains conservative; full-set QA/manual work is unmeasured.

Exact canvas/RGBA/pivot/contact-transform/no-clipping/hash checks pass. All three
previews visually reviewed; **user acceptance pending**. No generation replacements
were attempted for the direction/style deviations. Manifest/provenance, logs,
contacts/transforms, notices, checks and findings: `myassets/h002_pilot/manifest.json`,
`verification.json`, `environment_receipt.json`, `PILOT_REPORT.md`; prompts in
`local_jobs.json` and raw sidecars. Review previews in `myassets/h002_pilot/previews/`.

Not generated: extra looks, hut/cottage/castle, interiors/material variants,
overlays, full directions/animations, resources, biomes or UI. No Godot import,
code/map/catalog edits, Git mutation or full test suite. Existing art stays intact.
**Public distribution licence remains uncleared.** H002 is historical; subsequent paperdoll and fantasy decisions supersede its
full-sheet preference question. Specific appearance corrections remain open.

## Paperdoll pilot results

H003 completed: **four authored layer sheets**, neutral modest adult body,
work tunic, work trousers, short hair; **two QA PNGs**; exactly **six images**.
Each layer is 256x128, two south 128x128 frames, fixed [64,112] pivot. Serial
Python/Pillow shared-pose/mask authoring, no inference/model/seed/references;
provenance explicitly records model=null and seed=null. No existing art pixels.

Technical registration **PASS**: six garment/hair frame checks have zero alpha
leakage/support XOR, attachments covered; exported-layer stack versus authored
reference has zero pixel differences, exposed skin is unchanged, planted sole
y111 adjacent to pivot plane y112. Reopen checks validate sheet grids/hashes,
ankles and waist overlap. **All six intentional 4px-shift negative controls are
rejected.** Contact and diagnostic sheets viewed. Checks validate this geometry,
not artistic quality or independent AI output registration.

Honest limitation: coarse blocky anatomy/detail differs from A3; only a minimal
two-pose south stride, no idle, child/elder, side/back directions, equipment,
long-hair occlusion or production-style/gait acceptance. **AI registration remains
unproven**; deterministic authoring avoids its drift rather than testing it.
No runtime compositing/client implementation, Godot import, full suite or creature
art/mechanics. Public distribution licence remains uncleared.

Evidence: `myassets/h003_pilot/PILOT_REPORT.md`, `manifest.json`, `provenance.json`,
`pose_guide.json`, `validation.json`, `reopen_checks.json`; previews in
`myassets/h003_pilot/previews/`. User review of production style/rig priority and
one complete adult four-direction cycle is required before wardrobe expansion.

### h007 result

H007 delivers eight static buildings from shelter to grand hall, plus two
procedural roof treatments each for hut and farmhouse (12 designs, 24 exports).
Shadow-free transparent 2x masters have exact nearest 1x derivatives, authored
48px-tile footprint rectangles, ground pivots, door and south approach anchors.
Doors are 80–90px beside H005 1x idle at .80 (~64px adult); this supersedes the
older 60px building-door target for this batch. Eight serial built-in imagegen
calls took 310.653s; tool model/version and dollar cost were not exposed.
All exports and master/display contact sheets plus H001 mock village were
visually reviewed; technical checks pass. Hall bell turret and stair flight are
absent; broad hut, taller farmhouse and institutional hall-window caveats remain.
Evidence: `myassets/h007_buildings/PILOT_REPORT.md`, manifest, prompts/receipts,
transforms, validation and previews. No game code, maps/catalogs, Godot import,
Git operations or local Qwen. Public distribution licence remains unresolved;
user must check imagegen output terms. No motion or interiors delivered.

### h008 result

H008 delivers static wolf, boar, deer, fox, sheep (redone for detailed style),
goblin, skeleton, giant_spider, brambleback and bellhorn: south/east idle,
mirrored west, and wolf/boar/deer lying dead candidates. 33 poses yield 66
transparent PNGs with exact frozen creature ids/names/frame/pivot/footprint,
2x masters and nearest 1x derivatives. Ten successful serial built-in imagegen
calls took 310.510s; one rootling output was service-blocked with no image.
Native display/master sheets beside the ~64px H005 adult and an H001 meadow/
forest composition were viewed; integrity checks pass. Camera mismatch,
mirrored lighting, skeleton plate side and dead/rest ambiguity remain caveats.
Evidence and movement options: `myassets/h008_creatures/PILOT_REPORT.md` and
`ANIMATION_OPTIONS.md`. No gait, game code, Git operations, Godot import or
local Qwen. Public distribution licence remains unresolved; user must check
imagegen output terms.

## H004 modular imagegen results

Bounded follow-up: eight serial built-in imagegen calls, 337.605s measured call
wall time. Eight raw designs become eleven registered south-idle layer exports:
body in two skin palettes, three hair styles, peasant tunic, trousers, rear cloak,
hammer and two skin-matched extracted hand fragments. Exactly 33 PNGs including
twelve support/material masks and two stacked contact sheets; four combinations.
All eleven exports use 128x128/[64,112]. H003 validator operations adapted in
H004 pass integrity/sparse witnesses; 22/22 intentional 4px shifts rejected.
Both on-disk previews replay from layer PNGs at zero pixel difference.

Raw generation did not preserve requested positions; documented offline fitting
was necessary. Art is substantially more detailed than H003 but production
acceptance remains pending: native microtexture, outline consistency and relaxed
hammer grip need review. South idle only; every walk frame and east/west/north
direction are missing. No claim of animation drift or gait quality. Briefs remain
baked in the base for this bounded proof, unlike the full modular specification.
No local-model inference, game changes, Git operations or Godot import.
Evidence: `myassets/h004_modular/PILOT_REPORT.md`, `manifest.json`,
`provenance.json`, `transforms.json`, `validation.json`, `file_inventory.json`,
and `previews/`. Imagegen output terms require user review before public
distribution; unresolved. Creature bible and broader plans remain planning only.
