extends SceneTree
const Game = preload("res://scripts/game/game.gd")
var failures := 0

func check(ok: bool, message: String) -> void:
	if not ok:
		failures += 1
		push_error(message)

func _initialize() -> void:
	call_deferred("verify")

func verify() -> void:
	var game := Game.new() # Source inspection only; no network _ready boot.
	var lock: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://data/import_lock.json"))
	var index: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://data/production_index.json"))
	check(index.get("local_evaluation_only") == true, "Local evaluation provenance required")
	game.asset_index = lock.entries
	game.production_assets = game._production_assets_from_lock(lock)
	check(game.production_assets.size() == 33, "Exactly 33 hash-bound real poses")
	for asset in game.production_assets.values():
		var visual: Dictionary = game._creature_asset(asset)
		check(not visual.is_empty(), "Actual resource failed to load: " + str(asset.resource_path))
		if not visual.is_empty():
			var frame: Array = asset.metadata.frame
			var pivot: Array = asset.metadata.pivot
			check(visual.texture.get_size() == Vector2(frame[0], frame[1]), "Actual canonical H008 frame size")
			check(visual.pivot == Vector2(pivot[0], pivot[1]) and visual.scale == 1.0, "Actual canonical contact pivot/scale")
	for species in ["wolf", "boar", "deer", "fox", "sheep", "goblin", "skeleton", "giant_spider", "brambleback", "bellhorn"]:
		var art: Dictionary = game._creature_art({"creature": {"species": species, "variant": null}})
		check(art.has("idle_s") and art.has("idle_e"), "Real south/east selection: " + species)
		check(art.has("dead_e") == (species in ["wolf", "boar", "deer"]), "Truthful real dead-art coverage: " + species)
	game.free()
	print("H008_PUBLISHED_PASS" if failures == 0 else "H008_PUBLISHED_FAIL")
	quit(0 if failures == 0 else 1)
