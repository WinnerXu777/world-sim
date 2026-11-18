"""
genesis.py
==========
Eden simulation server.

This module serves the simulation to frontend clients using a semantic JSON
protocol built around:

- `/bootstrap`  : static-ish world metadata and full map state
- `/frame`      : live human/animal state for interpolation
- `/map_delta`  : slower map/entity updates for geometry/state changes
- `/status`     : debug/status metadata

The tensors remain internal simulation state. Frontends should consume the
exported protocol, not tensor columns directly.
"""

import asyncio
import importlib
import importlib.util
import math
import random
import time
import uuid
from contextlib import suppress
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import torch
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

import agent_runtime as ar
from launch_config import LaunchConfig
from simulation.scheduler import FixedStepScheduler
from systems.movement.spatial import world_contract, map_wall_boxes, slide as spatial_slide, standable_spawn_point, starter_storage_spot
from systems.movement.map_contract import (get_map_contract, get_map_file, load_from_environment as load_map_contracts_from_environment,
                                           maps_block)
from simulation.commands import CommandInbox
from simulation.inventory_commands import execute as execute_inventory_command  # kept for importers
from simulation.dispatch import DISPATCH
from systems.roster.apply import has_roster, world_has_roster
from systems.god.pause import pause_step as god_pause_step
from systems.god.state import set_paused as god_set_paused
from systems.god.inspect import inspect_resident
from systems.god.powers import time_state as god_time_state
from systems.roster.motion import move_task_actor
from systems.roster.driver import is_agent_driven
from systems.commission.engine import (commission_state_payload, decision_service)
from systems.roster.install import install_smith_loop
from persistence.sessions import GameSessions
from api.local_session import LocalSessionBoundary
from api.model_routes import build_model_router
from api.chunk_routes import build_chunk_router, enabled as chunk_routes_enabled
from harness.numerics import spaces_enabled
from harness import calendar as _calendar
from harness import dormancy as _dormancy
from harness import human_query as _human_query
from harness import restraint as _restraint
from harness.limits import world_limits as _world_limits
from harness import calendar_wire, window_wire
from systems.creatures import enabled as creatures_enabled, frame as creature_frame
from harness.spaces import space_table
from genesis_config import (
    MAP_WIDTH,
    MAP_HEIGHT,
    TILE_SIZE,
    MAX_ENTITIES,
    MAX_HUMANS,
    HUMAN_TENSOR_COLS,
    MAP_TENSOR_COLS,
    TICKS_PER_YEAR,
    TICK_RATE_HZ,
    TICK_SLEEP,
    AGENT_FRAME_EVERY,
    MAP_DELTA_EVERY,
    PROTOCOL_VERSION,
    X,
    Y,
    TYPE,
    HP,
    H_SEX,
    H_SPACE,
    H_AGE,
    H_LIFE_EXP,
    H_COOLDOWN,
    H_STAMINA,
    H_SHELTER,
    H_CARRYING,
    H_SKILL,
    H_AGGRESSION,
    H_TRIBE,
    HUNGER,
    THIRST,
    THREAT,
    MOOD,
    ESCALATION_FLAG,
    ACQUIRED_INSTINCT_MASK,
    CX,
    CY,
    M_TYPE,
    M_HP,
    M_SPACE,
    SCALE,
    S_DURABILITY,
    S_SHELTER_CAP,
    S_BUILD_PROGRESS,
    ANIMAL_TYPES,
    AGENT_TYPE_HUMAN,
    ADAM_LIFE_EXP,
    EVE_LIFE_EXP,
    GENESIS_AGE,
    MAP_SCHEMA,
    M_STORAGE_CASE,
    M_FOREST,
    M_GRASS,
    M_FARM,
    M_RESOURCE_NODE,
    M_BEACH,
    M_LAKE,
    M_WELL,
    M_HOUSE,
    M_VILLAGE,
    M_MOUNTAIN,
    M_BARREN,
    M_WALL,
    M_RESOURCE_FOOD,
    M_RESOURCE_WATER,
    FOOD_SEEK_THRESHOLD,
    WATER_SEEK_THRESHOLD,
    SHELTER_SEEK_THREAT,
    EAT_HUNGER_RESTORE,
    EAT_RESOURCE_COST,
    DRINK_THIRST_RESTORE,
    DRINK_RESOURCE_COST,
    SAFE_REPRO_HUNGER_MAX,
    SAFE_REPRO_THIRST_MAX,
    SAFE_REPRO_THREAT_MAX,
    SAFE_REPRO_HP_MIN,
    SAFE_REPRO_STAMINA_MIN,
    PROXIMITY_MATE_RADIUS,
    MATURE_AGE,
    LIFE_EXP_MIN,
    LIFE_EXP_MAX,
    MOVE_STEP,
    AGGRESSION_THRESHOLD,
    ATTACK_RANGE,
    ATTACK_DAMAGE,
    ATTACK_STAMINA_COST,
    BUILD_MATERIAL_USE,
    BUILD_PROGRESS_PER_HUMAN,
    BUILD_RADIUS,
    BUILD_STAMINA_COST,
)

import instincts_and_tools as iat
import map_geo
from initial_map_design import MAP_REGISTRY, pick_map
from systems.map.authored import instantiate_authored_entities

try:
    from harness import gcpolicy, instinct_bits
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness import gcpolicy, instinct_bits

try:
    from systems.construction import (
        build_construction_project,
        construction_blueprint,
        construction_prompt_summary,
        designate_site as construction_designate_site,
        evaluate_occupation_building_needs,
        evaluate_personal_building_needs,
        rank_construction_needs,
        advance_build as construction_advance_build,
        gather_construction_materials,
    )
    from systems.crafting import (
        crafting_prompt_summary,
        crafting_output_kind,
        crafting_recipe_def,
        crafting_recipe_ingredients,
        crafting_recipe_ids,
        review_resident_baseline_provisioning,
    )
    from systems.map import CameraChunkWindow, chunk_coord_for_world_point, chunk_origin, chunks_for_camera_window, diff_chunk_windows, world_to_chunk_local
    from systems.memory import (
        build_or_load_default_memory_rag,
        BackgroundGraphWriter,
        build_human_memory_bundle,
        sync_all_residents_to_memory_graph,
        sync_resident_batch_to_memory_graph,
        sync_resident_to_memory_graph,
    )
    from orchestrator import (
        OrchestratorRuntime,
        packet_from_manual_action,
        packet_from_reasoning_output,
        packet_from_task_outcome,
        packet_from_world_event,
    )
    from systems.inventory import (
        add_item as inventory_add_item,
        build_inventory_state,
        can_add_item,
        container_prompt_payload,
        ensure_house_storage_inventory,
        ensure_owner_inventory,
        ensure_storage_case_inventory,
        equip_main_hand_item,
        has_item,
        get_inventory,
        get_container_inventory,
        get_owner_inventory,
        grant_currency,
        inventory_prompt_payload,
        remove_item as inventory_remove_item,
        spend_currency,
        summarize_inventory,
        total_quantity,
        total_weight,
        transfer_item as inventory_transfer_item,
    )
    from systems.occupation.ops import occupation_prompt_summary
    from systems.perception import best_resource_entity, best_safe_entity, nearest_geo_entity
    from systems.schedule.ops import schedule_prompt_summary
    from systems.combat.hunting import nearest_huntable_animal, huntable_animal_slots
    from systems.combat.manual import collect_manual_attack_intents
    from systems.combat.resolver import resolve_human_attack_intents
    from systems.tasks import (
        TaskWorldBridge,
        active_task_payload,
        baseline_provisioning_task_specs,
        builder_work_task_specs,
        build_task_execution_context,
        combat_task_specs,
        construction_task_specs,
        ensure_resident_tasks,
        execute_active_task_step,
        farmer_work_task_specs,
        fisherman_work_task_specs,
        gatherer_work_task_specs,
        guard_work_task_specs,
        healer_work_task_specs,
        hunter_work_task_specs,
        replace_resident_tasks,
        routine_task_specs,
        social_task_specs,
        strategic_task_specs,
        should_activate_builder_work,
        should_activate_farmer_work,
        should_activate_fisherman_work,
        should_activate_gatherer_work,
        should_activate_guard_work,
        should_activate_healer_work,
        should_activate_hunter_work,
        should_activate_trader_work,
        should_activate_woodcutter_work,
        survival_task_specs,
        task_prompt_summary,
        trader_work_task_specs,
        woodcutter_work_task_specs,
    )
    from tools_execution import DecreeExecutionDispatcher, PlotExecutionDispatcher
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.construction import (
        advance_build as construction_advance_build,
        build_construction_project,
        construction_blueprint,
        construction_prompt_summary,
        designate_site as construction_designate_site,
        evaluate_occupation_building_needs,
        evaluate_personal_building_needs,
        gather_construction_materials,
        rank_construction_needs,
    )
    from at_the_beginning.systems.crafting import (
        crafting_prompt_summary,
        crafting_output_kind,
        crafting_recipe_def,
        crafting_recipe_ingredients,
        crafting_recipe_ids,
        review_resident_baseline_provisioning,
    )
    from at_the_beginning.systems.map import CameraChunkWindow, chunk_coord_for_world_point, chunk_origin, chunks_for_camera_window, diff_chunk_windows, world_to_chunk_local
    from at_the_beginning.systems.memory import (
        build_or_load_default_memory_rag,
        BackgroundGraphWriter,
        build_human_memory_bundle,
        sync_all_residents_to_memory_graph,
        sync_resident_batch_to_memory_graph,
        sync_resident_to_memory_graph,
    )
    from at_the_beginning.orchestrator import (
        OrchestratorRuntime,
        packet_from_manual_action,
        packet_from_reasoning_output,
        packet_from_task_outcome,
        packet_from_world_event,
    )
    from at_the_beginning.systems.inventory import (
        add_item as inventory_add_item,
        build_inventory_state,
        can_add_item,
        container_prompt_payload,
        ensure_house_storage_inventory,
        ensure_owner_inventory,
        ensure_storage_case_inventory,
        equip_main_hand_item,
        has_item,
        get_inventory,
        get_container_inventory,
        get_owner_inventory,
        grant_currency,
        inventory_prompt_payload,
        remove_item as inventory_remove_item,
        spend_currency,
        summarize_inventory,
        total_quantity,
        total_weight,
        transfer_item as inventory_transfer_item,
    )
    from at_the_beginning.systems.occupation.ops import occupation_prompt_summary
    from at_the_beginning.systems.perception import best_resource_entity, best_safe_entity, nearest_geo_entity
    from at_the_beginning.systems.schedule.ops import schedule_prompt_summary
    from at_the_beginning.systems.combat.hunting import nearest_huntable_animal, huntable_animal_slots
    from at_the_beginning.systems.combat.manual import collect_manual_attack_intents
    from at_the_beginning.systems.combat.resolver import resolve_human_attack_intents
    from at_the_beginning.systems.tasks import (
        TaskWorldBridge,
        active_task_payload,
        baseline_provisioning_task_specs,
        builder_work_task_specs,
        build_task_execution_context,
        combat_task_specs,
        construction_task_specs,
        ensure_resident_tasks,
        execute_active_task_step,
        farmer_work_task_specs,
        fisherman_work_task_specs,
        gatherer_work_task_specs,
        guard_work_task_specs,
        healer_work_task_specs,
        hunter_work_task_specs,
        replace_resident_tasks,
        routine_task_specs,
        social_task_specs,
        strategic_task_specs,
        should_activate_builder_work,
        should_activate_farmer_work,
        should_activate_fisherman_work,
        should_activate_gatherer_work,
        should_activate_guard_work,
        should_activate_healer_work,
        should_activate_hunter_work,
        should_activate_trader_work,
        should_activate_woodcutter_work,
        survival_task_specs,
        task_prompt_summary,
        trader_work_task_specs,
        woodcutter_work_task_specs,
    )
    from at_the_beginning.tools_execution import DecreeExecutionDispatcher, PlotExecutionDispatcher


ROOT_DIR   = Path(__file__).resolve().parent.parent
LAUNCH_CONFIG = LaunchConfig.from_env()
load_map_contracts_from_environment()  # EDEN_MAP_FILES; unset means legacy maps only
if LAUNCH_CONFIG.map_name not in MAP_REGISTRY and get_map_contract(LAUNCH_CONFIG.map_name) is None:
    raise SystemExit(f"EDEN_MAP={LAUNCH_CONFIG.map_name!r} is neither a built-in map nor a registered authored map (EDEN_MAP_FILES)")
MODULE_DIR = Path(__file__).resolve().parent
DYNAMIC_DIR = MODULE_DIR
LIGHTRAG_PATH = ROOT_DIR / "Data_Storage" / "LightRAG" / "state_lightrag.py"
LIGHTRAG_GRAPH_PATH = LAUNCH_CONFIG.data_root / "LightRAG" / "eden_graph.pkl"
MEMORY_RAG_GRAPH_PATH = LAUNCH_CONFIG.data_root / "MemoryRAG" / "memory_graph.pkl"
EXECUTION_STATE_PATH = LAUNCH_CONFIG.data_root / "ExecutionAgent" / "state.json"
MEMORY_RAG_FLUSH_INTERVAL_SEC = 2.0
MEMORY_RAG_BACKGROUND_SAVE_INTERVAL_SEC = 15.0  # tick-path graph saves are written on a worker thread, at most this often
HUMAN_VIEW_CHUNK_PX_W = 240.0
HUMAN_VIEW_CHUNK_PX_H = 240.0
BASELINE_GATHER_RADIUS = 24.0
BASELINE_GATHER_MOVE_STEP = 2.4
BASELINE_PROVISION_ACTION_COOLDOWN_TICKS = max(1, int(round(TICK_RATE_HZ * 1.0)))


def _load_lightrag_module():
    if not LIGHTRAG_PATH.exists():
        return None
    spec = importlib.util.spec_from_file_location("eden_lightrag", LIGHTRAG_PATH)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WorldState:
    def __init__(self, device: str = "cuda" if torch.cuda.is_available() else "cpu"):
        self.device   = device
        self.h_tensor = torch.zeros((MAX_HUMANS, HUMAN_TENSOR_COLS), device=device)
        self.m_tensor = torch.zeros((MAX_ENTITIES, MAP_TENSOR_COLS), device=device)


install_smith_loop(DISPATCH)  # roster / commission hooks (all no-ops on legacy maps)
try:
    from harness import engine_hooks as harness_hooks
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness import engine_hooks as harness_hooks
harness_hooks.install(DISPATCH)  # harness world / event mirror / powers command: does nothing unless EDEN_HARNESS=1


class Engine:
    def __init__(self):
        self.command_inbox = CommandInbox()
        self.world_epoch = str(uuid.uuid4())
        self.world_loaded = False
        self.state             = WorldState()
        self.scheduler = FixedStepScheduler(TICK_RATE_HZ)
        self.tick              = 0
        self.running           = False
        self._pop_count        = [0]
        self._entity_count_ref = [0]
        self._map_name         = "unknown"
        self._runtime_profile  = "full"

        self._registry: list[dict] = []
        self._register_defaults()

        resident_root = LAUNCH_CONFIG.data_root / "ResidentAgents"
        self.resident_store = ar.ResidentAgentStore(resident_root)
        self.world_agent = ar.WorldAgentRuntime(self.resident_store)
        self.player_control = ar.PlayerControlRuntime()
        self.orchestrator = OrchestratorRuntime()
        self.execution_agent = ar.ExecutionAgentRuntime(EXECUTION_STATE_PATH)
        self.decree_execution = DecreeExecutionDispatcher(self.execution_agent)
        self.plot_execution = PlotExecutionDispatcher()
        self.human_agent = ar.HumanAgentRuntime(self.resident_store)
        self.talk_agent = ar.TalkAgentRuntime(self.resident_store)
        self.tiny_model_runtime = ar.TinyModelRuntime()
        self.tiny_model_handler = None
        self.resident_model_handler = None
        self.world_model_handler = None
        self.mock_tiny_model_enabled = True
        self.mock_reasoning_enabled = True
        self._lightrag_module = _load_lightrag_module()
        self.light_rag = None
        self.memory_rag = None
        self.inventory_state = build_inventory_state()

        self._schema_payload = {
            "protocol": PROTOCOL_VERSION,
            "map_schema": {str(k): v for k, v in MAP_SCHEMA.items()},
        }

        self.reset_protocol_state()

    # ------------------------------------------------------------------
    # Lifecycle / reset
    # ------------------------------------------------------------------

    def reset_protocol_state(self) -> None:
        device = self.state.device
        self._frame_id                  = 0
        self._map_state_version         = 0
        self._map_geo_version_sent      = 0
        self._latest_delta_base_geo     = 0
        self._latest_delta_base_state   = 0
        self._next_human_uid            = 1
        self._next_entity_uid           = 1
        self._event_seq                 = 1
        self._human_uid_by_slot         = [None] * MAX_HUMANS
        self._entity_uid_by_slot        = [None] * MAX_ENTITIES
        self._pending_human_names_by_slot: dict[int, str] = {}
        self._pending_birth_links_by_slot: dict[int, dict[str, Any]] = {}
        self._incarnated_human_by_controller: dict[str, dict[str, str]] = {}
        self._pending_events: list[dict[str, Any]]   = []
        self._pending_despawns: list[str]            = []
        self._frontier_state           = {"edge_ticks": {}}
        self._view_window_state: dict[str, Any] = {}
        self._nature_state: dict[str, Any] = {}
        self._inventory_seeded_humans: set[str] = set()
        self._inventory_seeded_containers: set[str] = set()
        self._starter_storage_case_entity_id: str | None = None
        self._teleport_seq: dict[str, int] = {}   # human id -> teleports so far (wire only; not saved)
        self._tick_teleports: list[tuple[int, float, float]] = []
        self._memory_graph_last_flush_ts = 0.0
        self._memory_graph_writer = BackgroundGraphWriter()
        self._memory_graph_dirty = False
        self._memory_graph_last_write_ts = 0.0
        self._actor_prev_positions: dict[str, tuple[float, float]] = {}
        self._actor_prev_facing_yaw: dict[str, float] = {}
        self._actor_render_hints: dict[str, dict[str, Any]] = {}
        self._actor_render_actions: dict[str, dict[str, Any]] = {}
        self._prev_h_mask               = torch.zeros(MAX_HUMANS, dtype=torch.bool, device=device)
        self._prev_a_mask               = torch.zeros(MAX_ENTITIES, dtype=torch.bool, device=device)
        self._prev_entity_mask          = torch.zeros(MAX_ENTITIES, dtype=torch.bool, device=device)
        self._force_frame_refresh       = False
        self._force_map_refresh         = False
        self._last_exported_map_entities: dict[str, dict[str, Any]] = {}
        if window_wire.window_enabled():
            self._export_window = {"window": {"integrated": []}}
            self._last_exported_window = self._export_window
            self._latest_window_delta_payload = None
        self._bootstrap_payload         = self._empty_bootstrap_payload()
        self._frame_payload             = self._empty_frame_payload()
        self._map_delta_payload         = self._empty_map_delta_payload()
        self._legacy_map_payload        = self._empty_legacy_map_payload()
        self._legacy_agent_payload      = self._empty_legacy_agent_payload()

    def reset_world(self) -> None:
        gcpolicy.thaw_before_reset()  # a frozen world is never collected: thaw it so the old world can be reclaimed
        self.command_inbox = CommandInbox()
        self.world_epoch = str(uuid.uuid4())
        self.world_loaded = False
        self.state.h_tensor.zero_()
        self.state.m_tensor.zero_()
        self._pop_count[0]        = 0
        self._entity_count_ref[0] = 0
        self.tick                 = 0
        self._map_name            = "unknown"
        self._teleport_seq        = {}
        self._tick_teleports      = []
        self._runtime_profile     = "full"
        god_set_paused(self, False)  # a new or restored world runs; the pause and the speed are not part of a save
        self.scheduler.set_time_scale(1.0)
        map_geo.MAP_GEO.clear()
        map_geo.TILE_TO_ENTITY.clear()
        map_geo.geo_version = 0
        self.resident_store.reset_world()
        self.world_agent._queue.clear()
        self.world_agent._reasoning_queue.clear()
        self.world_agent._queued_reasoning_by_human.clear()
        self.world_agent._next_decree_id = 1
        self.world_agent._next_reasoning_id = 1
        self.world_agent.history.clear()
        self.world_agent.reasoning_history.clear()
        self.player_control = ar.PlayerControlRuntime()
        self.orchestrator = OrchestratorRuntime()
        self.execution_agent.clear_history()
        self.decree_execution = DecreeExecutionDispatcher(self.execution_agent)
        self.plot_execution = PlotExecutionDispatcher()
        self.human_agent.reset()
        self.talk_agent.reset()
        self.tiny_model_runtime.reset()
        self.mock_tiny_model_enabled = True
        self.mock_reasoning_enabled = True
        self.memory_rag = None
        self.inventory_state = build_inventory_state()
        self._memory_graph_writer.discard()
        self._memory_graph_dirty = False
        MEMORY_RAG_GRAPH_PATH.unlink(missing_ok=True)
        self.reset_protocol_state()

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------

    def _register_defaults(self) -> None:
        for fn, priority, kwargs in iat.default_registry_entries():
            self.register(fn, priority=priority, **kwargs)

    def register(self, fn: callable, priority: int = 99, **kwargs) -> None:
        self._registry.append({"fn": fn, "priority": priority, "kwargs": kwargs})
        self._registry.sort(key=lambda e: e["priority"])

    def unregister(self, fn: callable) -> None:
        self._registry = [e for e in self._registry if e["fn"] is not fn]

    def ensure_light_rag(self):
        if self.light_rag is not None:
            return self.light_rag
        if self._lightrag_module is None:
            return None
        self.light_rag = self._lightrag_module.build_or_load_default(
            graph_path=LIGHTRAG_GRAPH_PATH,
            max_retrieved=20,
        )
        return self.light_rag

    def ensure_memory_rag(self):
        if self.memory_rag is not None:
            return self.memory_rag
        self.memory_rag = build_or_load_default_memory_rag(
            graph_path=MEMORY_RAG_GRAPH_PATH,
            max_retrieved=12,
        )
        return self.memory_rag

    def warm_up_world(self) -> None:
        """Pay a new or restored world's first-use costs now: load the memory graph and sync every resident into it.

        Without this the first game tick after New Game or Continue does it (about 45 ms, over the 50 ms budget on a busy machine).
        """
        if self._runtime_profile == "render_test":
            return
        self.ensure_memory_rag()
        self.flush_memory_graph_queue(force=True, save=False)

    def warm_up_process(self) -> None:
        """Once per process, before the tick loop starts: import the index library (about 30 ms the first time)."""
        from systems.memory.state_memoryrag import FaissIndex
        FaissIndex()

    def set_world_model_handler(self, handler: Any) -> None:
        self.world_model_handler = handler

    def set_tiny_model_handler(self, handler: Any) -> None:
        self.tiny_model_handler = handler
        self.resident_model_handler = handler

    def set_resident_model_handler(self, handler: Any) -> None:
        self.set_tiny_model_handler(handler)

    def run_world_model_mode_batch(
        self,
        *,
        mode: str,
        cases: list[dict[str, Any]],
        engine: Any | None = None,
    ) -> Any:
        handler = self.world_model_handler
        if handler is None:
            return None
        if callable(handler):
            return handler(mode=mode, cases=cases, engine=self if engine is None else engine)
        run_mode_batch = getattr(handler, "run_mode_batch", None)
        if callable(run_mode_batch):
            return run_mode_batch(mode=mode, cases=cases, engine=self if engine is None else engine)
        infer_mode_batch = getattr(handler, "infer_mode_batch", None)
        if callable(infer_mode_batch):
            return infer_mode_batch(mode=mode, cases=cases, engine=self if engine is None else engine)
        return None

    def run_tiny_model_mode_batch(
        self,
        *,
        mode: str,
        cases: list[dict[str, Any]],
        engine: Any | None = None,
    ) -> Any:
        handler = self.tiny_model_handler if self.tiny_model_handler is not None else self.resident_model_handler
        if handler is None:
            return None
        if callable(handler):
            return handler(mode=mode, cases=cases, engine=self if engine is None else engine)
        run_mode_batch = getattr(handler, "run_mode_batch", None)
        if callable(run_mode_batch):
            return run_mode_batch(mode=mode, cases=cases, engine=self if engine is None else engine)
        infer_mode_batch = getattr(handler, "infer_mode_batch", None)
        if callable(infer_mode_batch):
            return infer_mode_batch(mode=mode, cases=cases, engine=self if engine is None else engine)
        return None

    def run_resident_model_mode_batch(
        self,
        *,
        mode: str,
        cases: list[dict[str, Any]],
        engine: Any | None = None,
    ) -> Any:
        return self.run_tiny_model_mode_batch(mode=mode, cases=cases, engine=engine)

    def sync_memory_graph(self, *, human_id: str | None = None, save: bool = False) -> dict[str, Any]:
        rag = self.ensure_memory_rag()
        if save:
            self._memory_graph_writer.discard()  # an older background blob must not land after this explicit save
            self._memory_graph_dirty = False
        if human_id:
            synced = sync_resident_to_memory_graph(rag, self.resident_store, human_id, save=save)
            if synced:
                self.resident_store.clear_memory_dirty_ids([human_id])
                self._memory_graph_last_flush_ts = time.monotonic()
            return {
                "synced": int(bool(synced)),
                "human_id": human_id,
                "graph_path": str(MEMORY_RAG_GRAPH_PATH),
                "pending_dirty": self.resident_store.memory_dirty_count(),
            }
        pending_ids = self.resident_store.pending_memory_dirty_ids()
        result = sync_all_residents_to_memory_graph(rag, self.resident_store, save=save)
        if result.get("synced", 0):
            self.resident_store.clear_memory_dirty_ids(pending_ids)
            self._memory_graph_last_flush_ts = time.monotonic()
        result["graph_path"] = str(MEMORY_RAG_GRAPH_PATH)
        result["pending_dirty"] = self.resident_store.memory_dirty_count()
        return result

    def flush_memory_graph_queue(
        self,
        *,
        human_id: str | None = None,
        human_ids: list[str] | tuple[str, ...] | set[str] | None = None,
        save: bool = False,
        force: bool = False,
        background: bool = False,
    ) -> dict[str, Any]:
        """``background=True`` (the tick path): ``save`` only marks the graph dirty; a debounced worker thread writes it."""
        rag = self.ensure_memory_rag()
        now = time.monotonic()
        if background:
            self._poll_memory_graph_write(rag, now)
        elif save:
            self._memory_graph_writer.discard()  # an older background blob must not land after this explicit save
            self._memory_graph_dirty = False
        inline_save = save and not background
        pending_ids = self.resident_store.pending_memory_dirty_ids()
        pending_set = set(pending_ids)

        target_ids: list[str] | None = None
        if human_ids is not None:
            target_ids = sorted({str(uid) for uid in human_ids if uid})
        elif human_id is not None:
            target_ids = [human_id]

        if target_ids is not None:
            sync_ids = [
                uid
                for uid in target_ids
                if force or uid in pending_set or f"resident:{uid}" not in rag.nodes
            ]
            if not sync_ids:
                return {
                    "synced": 0,
                    "human_id": human_id if human_ids is None else None,
                    "human_ids": target_ids if human_ids is not None else None,
                    "graph_path": str(MEMORY_RAG_GRAPH_PATH),
                    "pending_dirty": len(pending_ids),
                    "deferred": False,
                }
            result = sync_resident_batch_to_memory_graph(rag, self.resident_store, sync_ids, save=inline_save)
            if background and result.get("synced", 0):
                self._memory_graph_dirty = True  # written by the worker thread, at most every MEMORY_RAG_BACKGROUND_SAVE_INTERVAL_SEC
            if result.get("synced", 0):
                self.resident_store.clear_memory_dirty_ids(sync_ids)
                self._memory_graph_last_flush_ts = now
            result["human_id"] = human_id if human_ids is None else None
            result["human_ids"] = sync_ids if human_ids is not None else None
            result["graph_path"] = str(MEMORY_RAG_GRAPH_PATH)
            result["pending_dirty"] = self.resident_store.memory_dirty_count()
            return result

        if not pending_ids:
            return {
                "synced": 0,
                "graph_path": str(MEMORY_RAG_GRAPH_PATH),
                "pending_dirty": 0,
                "deferred": False,
            }

        if not force and (now - self._memory_graph_last_flush_ts) < MEMORY_RAG_FLUSH_INTERVAL_SEC:
            return {
                "synced": 0,
                "graph_path": str(MEMORY_RAG_GRAPH_PATH),
                "pending_dirty": len(pending_ids),
                "deferred": True,
            }

        result = sync_resident_batch_to_memory_graph(rag, self.resident_store, pending_ids, save=inline_save)
        if background and result.get("synced", 0):
            self._memory_graph_dirty = True
        if result.get("synced", 0):
            self.resident_store.clear_memory_dirty_ids(pending_ids)
            self._memory_graph_last_flush_ts = now
        result["graph_path"] = str(MEMORY_RAG_GRAPH_PATH)
        result["pending_dirty"] = self.resident_store.memory_dirty_count()
        result["deferred"] = False
        return result

    def _poll_memory_graph_write(self, rag, now: float, *, force: bool = False) -> bool:
        """Hand the current graph to the writer thread when it is dirty and the debounce window has passed."""
        if not self._memory_graph_dirty:
            return False
        if not force and (now - self._memory_graph_last_write_ts) < MEMORY_RAG_BACKGROUND_SAVE_INTERVAL_SEC:
            return False
        self._memory_graph_writer.submit(MEMORY_RAG_GRAPH_PATH, rag.serialize(), len(rag.nodes))
        self._memory_graph_dirty = False
        self._memory_graph_last_write_ts = now
        return True

    def queue_memory_graph_write(self) -> bool:
        """Session save: bring the graph up to date and queue its write now (does not block on the disk)."""
        if self.memory_rag is None:
            return False
        self.flush_memory_graph_queue(force=True, save=False)
        self._memory_graph_dirty = True
        return self._poll_memory_graph_write(self.memory_rag, time.monotonic(), force=True)

    def finalize_memory_graph(self) -> bool:
        """Clean shutdown: sync every pending resident and leave the graph file current on disk (blocking)."""
        if self.memory_rag is None:
            return False
        self.flush_memory_graph_queue(force=True, save=False)
        self._memory_graph_writer.discard()
        self._memory_graph_dirty = False
        self.memory_rag.save(MEMORY_RAG_GRAPH_PATH)
        return True

    def retrieve_memory_bundle(
        self,
        *,
        human_id: str,
        query: str | None = None,
        case: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rag = self.ensure_memory_rag()
        self.flush_memory_graph_queue(human_id=human_id, save=False, force=True)
        return build_human_memory_bundle(
            rag,
            self.resident_store,
            human_id,
            query=query,
            case=case,
        )

    def retrieve_light_rag_bundle(
        self,
        query: str,
        sub_queries: list[str] | None = None,
    ) -> dict[str, Any]:
        rag = self.ensure_light_rag()
        if rag is None:
            return {
                "enabled": False,
                "query": query,
                "tools": [],
                "context": "",
                "error": "lightrag_module_missing",
            }
        bundle = rag.retrieve_bundle(query, sub_queries=sub_queries)
        bundle["enabled"] = True
        bundle["max_retrieved"] = rag.max_retrieved
        return bundle

    def register_light_rag_tool(
        self,
        *,
        name: str,
        tier: str,
        signature: str,
        description: str,
        handles_events: list[str] | None = None,
        edges: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        rag = self.ensure_light_rag()
        if rag is None:
            return {"ok": False, "error": "lightrag_module_missing"}
        rag.upsert_tool(
            name=name,
            tier=tier,
            signature=signature,
            description=description,
            handles_events=handles_events,
            edges=edges,
        )
        rag.save(str(LIGHTRAG_GRAPH_PATH))
        return {"ok": True, "name": name, "graph_path": str(LIGHTRAG_GRAPH_PATH)}

    def _human_projection_hint(self, type_label: str) -> dict[str, Any]:
        lower = str(type_label or "").strip().lower()
        if "lake" in lower or "sea" in lower or "well" in lower:
            return {"kind": "water", "height": 0.08, "color_hint": "water"}
        if "forest" in lower or "tree" in lower:
            return {"kind": "forest", "height": 5.0, "color_hint": "forest"}
        if "mountain" in lower or "ridge" in lower:
            return {"kind": "mountain", "height": 9.0, "color_hint": "mountain"}
        if "beach" in lower:
            return {"kind": "sand", "height": 0.14, "color_hint": "sand"}
        if "grass" in lower or "plain" in lower:
            return {"kind": "grass", "height": 0.18, "color_hint": "grass"}
        if "farm" in lower or "field" in lower:
            return {"kind": "field", "height": 0.22, "color_hint": "field"}
        if "house" in lower or "village" in lower or "wall" in lower or "storage" in lower or "chest" in lower or "case" in lower:
            return {"kind": "structure", "height": 3.4, "color_hint": "structure"}
        if "lava" in lower or "volcano" in lower:
            return {"kind": "lava", "height": 1.0, "color_hint": "lava"}
        if "barren" in lower or "crater" in lower:
            return {"kind": "barren", "height": 0.28, "color_hint": "barren"}
        return {"kind": "terrain", "height": 0.2, "color_hint": "terrain"}

    def _human_actor_projection(self, actor_kind: str, type_label: str = "") -> dict[str, Any]:
        lower = str(type_label or "").strip().lower()
        if actor_kind == "human":
            return {"kind": "human", "height": 1.8, "radius": 0.36, "color_hint": "human"}
        if "wolf" in lower or "tiger" in lower:
            return {"kind": "predator", "height": 1.25, "radius": 0.42, "color_hint": "predator"}
        if "fish" in lower:
            return {"kind": "fish", "height": 0.45, "radius": 0.28, "color_hint": "fish"}
        return {"kind": "animal", "height": 1.05, "radius": 0.38, "color_hint": "animal"}

    def _human_ground_hint(self, entities: list[dict[str, Any]]) -> str:
        counts: dict[str, int] = {}
        for entity in entities:
            projection = entity.get("projection", {})
            kind = str(projection.get("color_hint", projection.get("kind", "terrain")))
            counts[kind] = counts.get(kind, 0) + 1
        if not counts:
            return "terrain"
        return max(counts.items(), key=lambda item: item[1])[0]

    def get_human_view_window(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        center_x = float(payload.get("center_x", MAP_WIDTH * 0.5))
        center_y = float(payload.get("center_y", MAP_HEIGHT * 0.5))
        view_world_w = max(float(payload.get("view_world_w", 180.0)), 1.0)
        view_world_h = max(float(payload.get("view_world_h", 140.0)), 1.0)
        preload_margin = max(float(payload.get("preload_margin", 80.0)), 0.0)
        margin_chunks = max(0, int(math.ceil(preload_margin / min(HUMAN_VIEW_CHUNK_PX_W, HUMAN_VIEW_CHUNK_PX_H))))
        window = CameraChunkWindow(
            center_x=center_x,
            center_y=center_y,
            view_world_w=view_world_w,
            view_world_h=view_world_h,
            margin_chunks=margin_chunks,
        )
        desired_chunks = chunks_for_camera_window(
            window,
            chunk_px_w=HUMAN_VIEW_CHUNK_PX_W,
            chunk_px_h=HUMAN_VIEW_CHUNK_PX_H,
        )
        loaded_chunk_ids = payload.get("loaded_chunk_ids", [])
        if not isinstance(loaded_chunk_ids, list):
            loaded_chunk_ids = []
        diff = diff_chunk_windows(loaded_chunk_ids, [coord.chunk_id for coord in desired_chunks])

        desired_chunk_ids = {coord.chunk_id for coord in desired_chunks}
        chunk_payloads: dict[str, dict[str, Any]] = {}
        for coord in desired_chunks:
            origin_x, origin_y = chunk_origin(coord, chunk_px_w=HUMAN_VIEW_CHUNK_PX_W, chunk_px_h=HUMAN_VIEW_CHUNK_PX_H)
            chunk_payloads[coord.chunk_id] = {
                "chunk_id": coord.chunk_id,
                "coord": [coord.x, coord.y],
                "origin": [round(origin_x, 2), round(origin_y, 2)],
                "size": [HUMAN_VIEW_CHUNK_PX_W, HUMAN_VIEW_CHUNK_PX_H],
                "entities": [],
                "ground_hint": "terrain",
            }

        current_map_entities = self._export_map_entities()
        for entity in current_map_entities.values():
            anchor = dict(entity.get("anchor", {}))
            world_x = float(anchor.get("x", 0.0))
            world_y = float(anchor.get("y", 0.0))
            coord, local_x, local_y = world_to_chunk_local(
                world_x,
                world_y,
                chunk_px_w=HUMAN_VIEW_CHUNK_PX_W,
                chunk_px_h=HUMAN_VIEW_CHUNK_PX_H,
            )
            chunk_id = coord.chunk_id
            if chunk_id not in desired_chunk_ids:
                continue
            enriched = dict(entity)
            enriched["chunk_local"] = {"x": round(local_x, 2), "y": round(local_y, 2)}
            enriched["projection"] = self._human_projection_hint(enriched.get("type_label", ""))
            chunk_payloads[chunk_id]["entities"].append(enriched)

        for chunk_payload in chunk_payloads.values():
            chunk_payload["ground_hint"] = self._human_ground_hint(chunk_payload["entities"])

        half_w = (view_world_w * 0.5) + preload_margin
        half_h = (view_world_h * 0.5) + preload_margin
        min_x = center_x - half_w
        max_x = center_x + half_w
        min_y = center_y - half_h
        max_y = center_y + half_h

        humans: list[dict[str, Any]] = []
        animals: list[dict[str, Any]] = []
        h_mask = self.state.h_tensor[:, TYPE] == AGENT_TYPE_HUMAN
        animal_type_ids = torch.tensor(
            list(ANIMAL_TYPES),
            device=self.state.device,
            dtype=self.state.m_tensor.dtype,
        )
        a_mask = torch.isin(self.state.m_tensor[:, M_TYPE], animal_type_ids)

        for slot in torch.where(h_mask)[0].tolist():
            actor = self._export_human(slot)
            world_x = float(actor.get("x", 0.0))
            world_y = float(actor.get("y", 0.0))
            if world_x < min_x or world_x > max_x or world_y < min_y or world_y > max_y:
                continue
            actor["projection"] = self._human_actor_projection("human")
            humans.append(actor)

        for slot in torch.where(a_mask)[0].tolist():
            actor = self._export_animal(slot)
            world_x = float(actor.get("x", 0.0))
            world_y = float(actor.get("y", 0.0))
            if world_x < min_x or world_x > max_x or world_y < min_y or world_y > max_y:
                continue
            actor["projection"] = self._human_actor_projection("animal", actor.get("type_label", ""))
            animals.append(actor)

        return {
            "ok": True,
            "protocol": PROTOCOL_VERSION,
            "mode": "human_3d",
            "tick": self.tick,
            "world": {
                "map_name": self._map_name,
                "width": MAP_WIDTH,
                "height": MAP_HEIGHT,
                "chunk_px_w": HUMAN_VIEW_CHUNK_PX_W,
                "chunk_px_h": HUMAN_VIEW_CHUNK_PX_H,
            },
            "projection": {
                "world_axes": {"x": "x", "y": "z"},
                "height_axis": "y",
                "default_ground_y": 0.0,
                "human_eye_height": 1.68,
                "third_person_distance": 8.5,
            },
            "camera": {
                "center_x": round(center_x, 2),
                "center_y": round(center_y, 2),
                "view_world_w": round(view_world_w, 2),
                "view_world_h": round(view_world_h, 2),
                "preload_margin": round(preload_margin, 2),
                "camera_mode": str(payload.get("camera_mode", "human")),
                "view_style": str(payload.get("view_style", "third_person")),
                "controller_id": str(payload.get("controller_id", "")),
            },
            "chunk_stream": {
                "desired_chunk_ids": [coord.chunk_id for coord in desired_chunks],
                "load": [coord.chunk_id for coord in diff.load],
                "keep": [coord.chunk_id for coord in diff.keep],
                "unload": [coord.chunk_id for coord in diff.unload],
            },
            "chunk_upserts": [chunk_payloads[coord.chunk_id] for coord in desired_chunks],
            "actors": {
                "humans": humans,
                "animals": animals,
            },
            "spatial": world_contract(self),
            "controls": self.player_control.status_snapshot()["sessions"],
            "inventory": {"focus": self._inventory_focus_payload(str(payload.get("controller_id", "local_player")))},
            "talk": self._talk_feed_payload(str(payload.get("controller_id", "local_player"))),
            "nature": dict(self._nature_state),
        }

    # ------------------------------------------------------------------
    # Inventory helpers
    # ------------------------------------------------------------------

    def _human_inventory_record(
        self,
        human_id: str,
        *,
        capacity_slots: int | None = None,
        capacity_weight: float | None = None,
    ) -> dict:
        label = f"Loadout {human_id}"
        record = ensure_owner_inventory(
            self.inventory_state,
            "human",
            human_id,
            label=label,
            capacity_slots=capacity_slots,
            capacity_weight=capacity_weight,
        )
        if capacity_slots is not None and (record.get("capacity_slots") is None or int(record.get("capacity_slots", 0)) < int(capacity_slots)):
            record["capacity_slots"] = int(capacity_slots)
        if capacity_weight is not None and (
            record.get("capacity_weight") is None or float(record.get("capacity_weight", 0.0)) < float(capacity_weight)
        ):
            record["capacity_weight"] = float(capacity_weight)
        return record

    def _storage_case_inventory_record(self, entity_id: str) -> dict:
        return ensure_storage_case_inventory(
            self.inventory_state,
            entity_id,
            label="Storage Case",
        )

    def _nearby_accessible_storage_records(
        self,
        center_x: float,
        center_y: float,
        *,
        radius: float = 72.0,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        storage_mask = self.state.m_tensor[:, M_TYPE] == M_STORAGE_CASE
        for slot in torch.where(storage_mask)[0].tolist():
            entity_id = self._entity_uid_by_slot[slot]
            if not entity_id:
                continue
            dx = float(self.state.m_tensor[slot, CX]) - float(center_x)
            dy = float(self.state.m_tensor[slot, CY]) - float(center_y)
            distance = math.sqrt(dx * dx + dy * dy)
            if distance > float(radius):
                continue
            inventory = get_container_inventory(self.inventory_state, entity_id)
            if inventory is None:
                continue
            records.append(
                {
                    "container_id": entity_id,
                    "distance": round(distance, 2),
                    "inventory": inventory,
                    "summary": summarize_inventory(inventory, limit=4),
                }
            )
        records.sort(
            key=lambda entry: (
                float(entry.get("distance", 10**9)),
                str(entry.get("container_id", "")),
            )
        )
        return records

    def _resident_home_structure_record(self, human_id: str, resident: dict[str, Any]) -> dict[str, Any] | None:
        needle = str(human_id or "").strip()
        if not needle or not isinstance(resident, dict):
            return None
        for project in list(resident.get("construction_projects", [])):
            if not isinstance(project, dict):
                continue
            if str(project.get("building_kind", "")).strip() != "personal_shelter":
                continue
            metadata = dict(project.get("metadata", {}))
            if str(metadata.get("owner_human_id", needle)).strip() != needle:
                continue
            site = dict(project.get("site", {}))
            entity_id = str(site.get("entity_id", "")).strip()
            if not entity_id:
                continue
            entity_ref = self._resolve_task_entity_target(entity_id)
            if entity_ref is None:
                continue
            entity_slot = int(entity_ref["slot"])
            progress = float(self.state.m_tensor[entity_slot, S_BUILD_PROGRESS])
            if progress < 99.9 and str(project.get("status", "")).strip() != "completed":
                continue
            return {
                "project_id": str(project.get("id", "")),
                "entity_id": entity_id,
                "slot": entity_slot,
                "x": float(self.state.m_tensor[entity_slot, CX]),
                "y": float(self.state.m_tensor[entity_slot, CY]),
                "distance": 0.0,
            }
        return None

    def _resident_house_inventory_record(self, human_id: str, resident: dict[str, Any]) -> dict[str, Any] | None:
        home = self._resident_home_structure_record(human_id, resident)
        if home is None:
            return None
        entity_id = str(home.get("entity_id", "")).strip()
        if not entity_id:
            return None
        return ensure_house_storage_inventory(
            self.inventory_state,
            entity_id,
            metadata={
                "owner_human_id": str(human_id),
                "project_id": str(home.get("project_id", "")),
            },
        )

    def _resident_accessible_storage_records(
        self,
        human_id: str,
        resident: dict[str, Any],
        slot: int,
        *,
        include_nearby: bool = False,
        radius: float = 72.0,
    ) -> list[dict[str, Any]]:
        px = float(self.state.h_tensor[slot, X])
        py = float(self.state.h_tensor[slot, Y])
        records: list[dict[str, Any]] = []
        home = self._resident_home_structure_record(human_id, resident)
        if home is not None:
            inventory = self._resident_house_inventory_record(human_id, resident)
            if isinstance(inventory, dict):
                dx = float(home.get("x", px)) - px
                dy = float(home.get("y", py)) - py
                distance = math.sqrt(dx * dx + dy * dy)
                records.append(
                    {
                        "container_id": str(home.get("entity_id", "")),
                        "x": float(home.get("x", px)),
                        "y": float(home.get("y", py)),
                        "distance": round(distance, 2),
                        "inventory": inventory,
                        "summary": summarize_inventory(inventory, limit=4),
                        "storage_scope": "house",
                    }
                )
        if include_nearby:
            for entry in self._nearby_accessible_storage_records(px, py, radius=radius):
                candidate = dict(entry)
                candidate.setdefault("x", float(self.state.m_tensor[self._resolve_task_entity_target(str(candidate.get("container_id", "")))["slot"], CX]) if self._resolve_task_entity_target(str(candidate.get("container_id", ""))) else px)
                candidate.setdefault("y", float(self.state.m_tensor[self._resolve_task_entity_target(str(candidate.get("container_id", "")))["slot"], CY]) if self._resolve_task_entity_target(str(candidate.get("container_id", ""))) else py)
                candidate.setdefault("storage_scope", "nearby")
                records.append(candidate)
        records.sort(
            key=lambda entry: (
                float(entry.get("distance", 10**9)),
                str(entry.get("container_id", "")),
            )
        )
        return records

    @staticmethod
    def _nearest_accessible_storage_record(
        accessible_records: list[dict[str, Any]],
        center_x: float,
        center_y: float,
        *,
        radius: float = 0.0,
    ) -> dict[str, Any] | None:
        best: dict[str, Any] | None = None
        for entry in list(accessible_records or []):
            if not isinstance(entry, dict) or not isinstance(entry.get("inventory"), dict):
                continue
            distance = float(entry.get("distance", 10**9))
            if radius > 0.0 and distance > float(radius):
                continue
            if best is None or distance < float(best.get("distance", 10**9)):
                best = dict(entry)
        return best

    def _refresh_resident_carry_manifest(self, resident: dict[str, Any], personal_inventory: dict) -> None:
        manifest: dict[str, int] = {}
        for item in list(personal_inventory.get("items", [])):
            item_kind = str(item.get("kind", "")).strip()
            quantity = max(int(item.get("quantity", 0)), 0)
            if not item_kind or quantity <= 0:
                continue
            manifest[item_kind] = manifest.get(item_kind, 0) + quantity
        task_state = resident.setdefault("task_state", {})
        task_state["carry_manifest"] = manifest
        task_state["carry_weight"] = round(total_weight(personal_inventory), 3)
        task_state["carry_capacity_weight"] = float(personal_inventory.get("capacity_weight", 0.0) or 0.0)

    def _seed_human_inventory(self, human_id: str, slot: int, *, controlled: bool = False) -> None:
        if not human_id or human_id in self._inventory_seeded_humans:
            return
        capacity = 12 if controlled else 4
        capacity_weight = 28.0 if controlled else 8.0
        record = self._human_inventory_record(human_id, capacity_slots=capacity, capacity_weight=capacity_weight)
        grant_currency(record, 24 if controlled else 10)
        weapon_kind = "spear" if controlled or slot == 0 else ("knife" if slot % 2 else "club")
        add_result = inventory_add_item(record, weapon_kind, 1)
        created_item_ids = list(add_result.get("created_item_ids", []))
        if created_item_ids:
            equip_main_hand_item(record, created_item_ids[0])
        if controlled:
            inventory_add_item(record, "rations", 2)
            inventory_add_item(record, "bandage", 1)
        self._inventory_seeded_humans.add(human_id)

    def _spawn_storage_case_at(self, center_x: float, center_y: float, *, seed_contents: bool = True) -> str | None:
        eid = iat.instinct_create_object(
            self.state.m_tensor,
            self._entity_count_ref,
            M_STORAGE_CASE,
            center_x,
            center_y,
            hp=90.0,
            scale=14.0,
            shape="circle",
            register_geo=True,
            device=self.state.device,
            col_vals={
                S_DURABILITY: 90.0,
                S_SHELTER_CAP: 16.0,
                S_BUILD_PROGRESS: 100.0,
            },
        )
        if eid == -1:
            return None
        h_mask, _, entity_mask = self._current_masks()
        self._assign_missing_ids(h_mask, entity_mask)
        entity_id = self._entity_uid_by_slot[eid]
        if not entity_id:
            return None
        container = self._storage_case_inventory_record(entity_id)
        if seed_contents and entity_id not in self._inventory_seeded_containers:
            grant_currency(container, 40)
            inventory_add_item(container, "rations", 4)
            inventory_add_item(container, "bandage", 2)
            self._inventory_seeded_containers.add(entity_id)
        self._force_map_refresh = True
        return entity_id

    def _ensure_controlled_inventory_upgrade(self, human_id: str) -> None:
        record = self._human_inventory_record(human_id, capacity_slots=12, capacity_weight=28.0)
        if not has_item(record, "rations", 1):
            inventory_add_item(record, "rations", 2)
        if not has_item(record, "bandage", 1):
            inventory_add_item(record, "bandage", 1)

    def _ensure_map_container(self, entity_id: str, *, seed_contents: bool = False) -> None:
        """Container inventory for a map-provided storage entity (optionally seeded like the starter case)."""
        container = self._storage_case_inventory_record(entity_id)
        if seed_contents and entity_id not in self._inventory_seeded_containers:
            grant_currency(container, 40)
            inventory_add_item(container, "rations", 4)
            inventory_add_item(container, "bandage", 2)
            self._inventory_seeded_containers.add(entity_id)

    def _spawn_starter_storage_case(self, h_mask: torch.Tensor) -> None:
        if self._starter_storage_case_entity_id is not None:
            return
        live_slots = torch.where(h_mask)[0].tolist()
        if not live_slots:
            return
        if get_map_contract(self._map_name) is not None:
            # Authored map: never "beside the first resident" (that can land in a wall or off the map). Use the
            # map's own storage entity if it has one, otherwise no starter case.
            spot = starter_storage_spot(self)
            if spot is None:
                return
            center_x, center_y = spot
        else:
            anchor_slot = int(live_slots[0])
            center_x = min(float(self.state.h_tensor[anchor_slot, X]) + 26.0, MAP_WIDTH - 18.0)
            center_y = min(float(self.state.h_tensor[anchor_slot, Y]) + 18.0, MAP_HEIGHT - 18.0)
        entity_id = self._spawn_storage_case_at(center_x, center_y, seed_contents=True)
        if entity_id:
            self._starter_storage_case_entity_id = entity_id

    def _sync_inventory_defaults(self, h_mask: torch.Tensor) -> None:
        self._spawn_starter_storage_case(h_mask)
        controlled_ids = {
            str(session.get("target_id", ""))
            for session in self.player_control.status_snapshot().get("sessions", [])
            if str(session.get("target_kind", "")) == "human"
        }
        for slot in torch.where(h_mask)[0].tolist():
            human_id = self._human_uid_by_slot[slot]
            if not human_id:
                continue
            self._human_inventory_record(
                human_id,
                capacity_slots=12 if human_id in controlled_ids else 4,
                capacity_weight=28.0 if human_id in controlled_ids else 8.0,
            )
            self._seed_human_inventory(human_id, slot, controlled=human_id in controlled_ids)
            if human_id in controlled_ids:
                self._ensure_controlled_inventory_upgrade(human_id)

    def _sync_occupation_provisioning(
        self,
        h_mask: torch.Tensor,
        *,
        manual_control: dict[str, Any] | None = None,
    ) -> None:
        controlled_ids = {
            str(session.get("target_id", ""))
            for session in self.player_control.status_snapshot().get("sessions", [])
            if str(session.get("target_kind", "")) == "human"
        }
        manual_control = (
            manual_control
            if isinstance(manual_control, dict)
            else self.player_control.build_tick_context(self)
        )
        for slot in torch.where(h_mask)[0].tolist():
            human_id = self._human_uid_by_slot[slot]
            if not human_id:
                continue
            resident = self.resident_store.get(human_id)
            if resident is None:
                continue
            inventory = self._human_inventory_record(human_id)
            accessible_records = self._resident_accessible_storage_records(
                human_id,
                resident,
                slot,
            )
            self._refresh_resident_carry_manifest(resident, inventory)
            changed = review_resident_baseline_provisioning(
                resident,
                self.tick,
                personal_inventory=inventory,
                accessible_inventories=accessible_records,
                allow_auto=human_id not in controlled_ids,
            )
            changed = self._sync_resident_construction(
                slot,
                human_id,
                resident,
                allow_auto=human_id not in controlled_ids,
            ) or changed
            changed = self._sync_managed_resident_tasks(
                slot,
                resident,
                inventory,
                allow_auto=human_id not in controlled_ids,
                manual_control=manual_control,
            ) or changed
            changed = self._execute_resident_task_step(
                slot,
                human_id,
                resident,
                inventory,
                accessible_records,
            ) or changed
            if changed:
                self.resident_store.touch_resident(human_id)

    def _sync_managed_resident_tasks(
        self,
        slot: int,
        resident: dict[str, Any],
        personal_inventory: dict,
        *,
        allow_auto: bool,
        manual_control: dict[str, Any] | None = None,
    ) -> bool:
        ensure_resident_tasks(resident, self.tick)
        crafting_state = dict(resident.get("crafting_state", {}))
        active_need = crafting_state.get("active_need")
        task_state = resident.setdefault("task_state", {})
        social_signal = dict(task_state.get("pending_social_signal") or {})
        combat_signal = dict(task_state.get("pending_combat_signal") or {})
        help_target = self._resolve_nearby_help_target(slot, radius=72.0)
        desired_specs: list[dict[str, Any]] = []
        reason = "managed_task_sync"
        consumed_social_signal = False
        consumed_combat_signal = False
        if not bool(allow_auto):
            desired_specs = []
            reason = "manual_control"
        elif is_agent_driven(resident.get("roster")):
            desired_specs = []  # D-008: an agent-driven roster resident gets tasks from actions only; its needs are Tier 1 goals (agent_driver)
            reason = "roster_agent_driven"
        elif (
            desired_specs := survival_task_specs(
                resident,
                hunger=float(self.state.h_tensor[slot, HUNGER]),
                thirst=float(self.state.h_tensor[slot, THIRST]),
                threat=float(self.state.h_tensor[slot, THREAT]),
                stamina=float(self.state.h_tensor[slot, H_STAMINA]),
                hp=float(self.state.h_tensor[slot, HP]),
                sheltered=float(self.state.h_tensor[slot, H_SHELTER]) > 0.0,
                personal_inventory=personal_inventory,
            )
        ):
            reason = "survival"
        elif resident.get("roster"):
            desired_specs = []  # roster residents live on anchors (driver); no construction, trade or occupation task families
            reason = "roster_anchor_driven"
        elif (
            desired_specs := combat_task_specs(
                signal=combat_signal or None,
                human_target=self._resolve_autonomous_human_attack_target(slot),
                entity_target=self._resolve_autonomous_hunt_target(slot),
                protect_target=help_target
                if str(resident.get("occupation", {}).get("kind", "")).strip() == "guard" and isinstance(help_target, dict)
                else None,
                guard_place="settlement" if str(resident.get("occupation", {}).get("kind", "")).strip() == "guard" else "",
            )
        ):
            reason = "combat"
            consumed_combat_signal = bool(combat_signal)
        elif (
            desired_specs := social_task_specs(
                resident,
                age=float(self.state.h_tensor[slot, H_AGE]),
                cooldown=float(self.state.h_tensor[slot, H_COOLDOWN]),
                hunger=float(self.state.h_tensor[slot, HUNGER]),
                thirst=float(self.state.h_tensor[slot, THIRST]),
                threat=float(self.state.h_tensor[slot, THREAT]),
                hp=float(self.state.h_tensor[slot, HP]),
                stamina=float(self.state.h_tensor[slot, H_STAMINA]),
                candidate=self._resolve_mate_candidate(slot, radius=72.0),
                signal=social_signal or None,
                help_target=help_target,
            )
        ):
            reason = "social"
            consumed_social_signal = bool(social_signal)
        elif (
            desired_specs := strategic_task_specs(
                resident,
                tick=int(self.tick),
                personal_inventory=personal_inventory,
            )
        ):
            reason = "strategic"
        elif desired_specs := construction_task_specs(resident):
            reason = "construction"
        elif (
            bool(crafting_state.get("baseline_ready", False))
            and bool(crafting_state.get("auto_allowed", False))
            and isinstance(active_need, dict)
        ):
            desired_specs = baseline_provisioning_task_specs(resident)
            reason = "occupation_provision"
        elif should_activate_woodcutter_work(
            resident,
            has_required_tool=has_item(personal_inventory, "axe", 1),
        ):
            desired_specs = woodcutter_work_task_specs(resident, carry_quantity=2)
            reason = "occupation_work"
        elif should_activate_fisherman_work(
            resident,
            has_required_tool=has_item(personal_inventory, "fishing_rod", 1),
        ):
            desired_specs = fisherman_work_task_specs(resident, carry_quantity=2)
            reason = "occupation_work"
        elif should_activate_farmer_work(
            resident,
            has_required_tool=has_item(personal_inventory, "hoe", 1),
        ):
            desired_specs = farmer_work_task_specs(resident, carry_quantity=2)
            reason = "occupation_work"
        elif should_activate_guard_work(
            resident,
            has_required_tool=has_item(personal_inventory, "spear", 1),
        ):
            desired_specs = guard_work_task_specs(resident, patrol_radius=18.0)
            reason = "occupation_work"
        elif should_activate_builder_work(
            resident,
            has_required_tool=has_item(personal_inventory, "hammer", 1),
        ):
            desired_specs = builder_work_task_specs(resident, carry_quantity=2)
            reason = "occupation_work"
        elif should_activate_gatherer_work(
            resident,
            has_required_tool=has_item(personal_inventory, "basket", 1),
        ):
            desired_specs = gatherer_work_task_specs(resident, carry_quantity=2)
            reason = "occupation_work"
        elif should_activate_hunter_work(
            resident,
            has_required_tool=has_item(personal_inventory, "spear", 1),
        ):
            desired_specs = hunter_work_task_specs(resident, carry_quantity=2)
            reason = "occupation_work"
        elif should_activate_healer_work(
            resident,
            has_required_tool=has_item(personal_inventory, "bandage", 1),
            help_target=help_target,
        ):
            desired_specs = healer_work_task_specs(
                resident,
                target_human_id=str((help_target or {}).get("human_id", "")),
                target_name=str((help_target or {}).get("name", "")),
            )
            reason = "occupation_work"
        elif should_activate_trader_work(
            resident,
            has_required_tool=has_item(personal_inventory, "pack", 1),
            has_coin=has_item(personal_inventory, "coin", 1),
        ):
            desired_specs = trader_work_task_specs(resident)
            reason = "occupation_work"
        elif desired_specs := routine_task_specs(resident):
            reason = "routine"

        current_task = active_task_payload(resident)
        current_task_kind = str(current_task.get("task_kind", "")).strip()
        current_source = str(current_task.get("source", "")).strip()
        if desired_specs and current_task_kind and current_source in {"occupation_work", "survival", "social", "combat", "routine", "strategic", "construction"}:
            desired_sources = {str(spec.get("source", "")) for spec in desired_specs if str(spec.get("source", "")).strip()}
            desired_kinds = [str(spec.get("task_kind", "")) for spec in desired_specs]
            if current_source in desired_sources and current_task_kind in desired_kinds:
                desired_specs = desired_specs[desired_kinds.index(current_task_kind):]

        changed = replace_resident_tasks(
            resident,
            desired_specs,
            tick=self.tick,
            reason=reason,
        )
        if changed and consumed_social_signal:
            resident.setdefault("task_state", {}).pop("pending_social_signal", None)
        if changed and consumed_combat_signal:
            resident.setdefault("task_state", {}).pop("pending_combat_signal", None)
        return changed

    @staticmethod
    def _clamp_world_point(x: float, y: float) -> tuple[float, float]:
        x0, y0, x1, y1 = _world_limits()
        return (
            max(x0, min(x1, float(x))),
            max(y0, min(y1, float(y))),
        )

    def _construction_project_ref(self, resident: dict[str, Any], project_id: str) -> dict[str, Any] | None:
        needle = str(project_id or "").strip()
        if not needle:
            return None
        for project in list(resident.get("construction_projects", [])):
            if isinstance(project, dict) and str(project.get("id", "")) == needle:
                return project
        return None

    def _construction_project_for_need(self, resident: dict[str, Any], need_id: str) -> dict[str, Any] | None:
        needle = str(need_id or "").strip()
        if not needle:
            return None
        for project in list(resident.get("construction_projects", [])):
            if isinstance(project, dict) and str(project.get("need_id", "")) == needle:
                return project
        return None

    def _nearest_structure_slot(
        self,
        center_x: float,
        center_y: float,
        *,
        type_ids: set[int],
        radius: float,
    ) -> int:
        return int(
            nearest_geo_entity(
                self.state.m_tensor,
                float(center_x),
                float(center_y),
                type_filter=set(type_ids),
                radius=float(radius),
            )
        )

    def _construction_ready(self, slot: int) -> bool:
        row = self.state.h_tensor[slot]
        return (
            float(row[HUNGER]) <= 62.0
            and float(row[THIRST]) <= 62.0
            and float(row[THREAT]) <= 42.0
            and float(row[HP]) >= 28.0
            and float(row[H_STAMINA]) >= 24.0
        )

    def _sync_resident_construction(
        self,
        slot: int,
        human_id: str,
        resident: dict[str, Any],
        *,
        allow_auto: bool,
    ) -> bool:
        changed = False
        construction_state = resident.setdefault("construction_state", {})
        resident.setdefault("construction_profile", {})
        resident.setdefault("construction_needs", [])
        resident.setdefault("construction_projects", [])

        px = float(self.state.h_tensor[slot, X])
        py = float(self.state.h_tensor[slot, Y])
        occupation_kind = str(resident.get("occupation", {}).get("kind", "")).strip()
        auto_allowed = bool(allow_auto) and self._construction_ready(slot)
        if bool(construction_state.get("auto_allowed", True)) != auto_allowed:
            construction_state["auto_allowed"] = auto_allowed
            changed = True
        construction_state["last_need_review_tick"] = int(self.tick)
        construction_state["last_project_review_tick"] = int(self.tick)
        construction_state["review_reason"] = "live_sync"

        active_projects_by_kind: set[str] = set()
        unfinished_projects: list[dict[str, Any]] = []
        for project in list(resident.get("construction_projects", [])):
            if not isinstance(project, dict):
                continue
            status = str(project.get("status", "planned")).strip()
            site = dict(project.get("site", {}))
            entity_id = str(site.get("entity_id", "")).strip()
            entity_ref = self._resolve_task_entity_target(entity_id) if entity_id else None
            if isinstance(entity_ref, dict):
                progress = float(self.state.m_tensor[int(entity_ref["slot"]), S_BUILD_PROGRESS])
                if round(float(project.get("progress", 0.0)), 2) != round(progress, 2):
                    project["progress"] = round(progress, 2)
                    project["last_update_tick"] = int(self.tick)
                    changed = True
                if progress >= 99.9 and status != "completed":
                    project["status"] = "completed"
                    project["last_update_tick"] = int(self.tick)
                    changed = True
                    if str(project.get("building_kind", "")).strip() == "personal_shelter":
                        self._resident_house_inventory_record(human_id, resident)
                    elif int(self.state.m_tensor[int(entity_ref["slot"]), M_TYPE]) == int(M_STORAGE_CASE):
                        self._storage_case_inventory_record(entity_id)
            if str(project.get("status", "planned")).strip() in {"planned", "designated", "building"}:
                active_projects_by_kind.add(str(project.get("building_kind", "")).strip())
                unfinished_projects.append(project)

        home_structure = self._resident_home_structure_record(human_id, resident)
        home_inventory = self._resident_house_inventory_record(human_id, resident)
        has_house_storage = home_inventory is not None
        has_shelter = bool(home_structure) or self._nearest_structure_slot(px, py, type_ids={M_HOUSE, M_VILLAGE, M_WELL}, radius=132.0) != -1
        has_farm_plot = self._nearest_structure_slot(px, py, type_ids={M_FARM}, radius=144.0) != -1
        construction_state["has_house_storage"] = bool(has_house_storage)
        construction_state["house_entity_id"] = str((home_structure or {}).get("entity_id", ""))
        construction_state["house_inventory_id"] = str((home_inventory or {}).get("inventory_id", "")) if isinstance(home_inventory, dict) else ""

        needs = evaluate_personal_building_needs(
            resident,
            tick=int(self.tick),
            has_shelter=has_shelter or "personal_shelter" in active_projects_by_kind,
            owner_human_id=human_id,
        )
        needs.extend(
            evaluate_occupation_building_needs(
                resident,
                tick=int(self.tick),
                occupation_kind=occupation_kind,
                has_farm_plot=has_farm_plot or "farm_plot" in active_projects_by_kind,
                owner_human_id=human_id,
            )
        )
        ranked_needs = [
            dict(need)
            for need in rank_construction_needs(needs)
            if str(need.get("building_kind", "")).strip() not in active_projects_by_kind
        ]
        if ranked_needs != list(resident.get("construction_needs", [])):
            resident["construction_needs"] = ranked_needs
            changed = True

        active_need = ranked_needs[0] if ranked_needs else None
        active_need_id = str((active_need or {}).get("id", "")).strip() or None
        if construction_state.get("active_need_id") != active_need_id:
            construction_state["active_need_id"] = active_need_id
            changed = True

        active_project_id: str | None = None
        if auto_allowed and isinstance(active_need, dict):
            project = self._construction_project_for_need(resident, str(active_need.get("id", "")))
            if project is None:
                blueprint = construction_blueprint(str(active_need.get("building_kind", "")))
                project = build_construction_project(
                    f"project_{active_need['id']}",
                    str(active_need.get("building_kind", "")),
                    tick=int(self.tick),
                    need_id=str(active_need.get("id", "")),
                    status="planned",
                    metadata={
                        "priority": float(active_need.get("priority", 0.5)),
                        "scope": str(active_need.get("scope", "")),
                        "source": str(active_need.get("source", "")),
                        "owner_human_id": human_id,
                        "place_tag": str(next(iter(blueprint.get("place_tags", ()) or ()), "settlement")),
                    },
                )
                resident.setdefault("construction_projects", []).append(project)
                changed = True
            assigned = [str(candidate) for candidate in list(project.get("assigned_human_ids", [])) if str(candidate).strip()]
            if human_id not in assigned:
                assigned.append(human_id)
                project["assigned_human_ids"] = assigned[:4]
                project["last_update_tick"] = int(self.tick)
                changed = True
            active_project_id = str(project.get("id", "")).strip() or None
        elif unfinished_projects:
            active_project_id = str(unfinished_projects[0].get("id", "")).strip() or None

        if construction_state.get("active_project_id") != active_project_id:
            construction_state["active_project_id"] = active_project_id
            changed = True

        return changed

    def _designate_resident_construction_project(
        self,
        slot: int,
        human_id: str,
        resident: dict[str, Any],
        project_id: str,
    ) -> dict[str, Any]:
        project = self._construction_project_ref(resident, project_id)
        if project is None:
            return {"ok": False, "reason": "project_missing"}
        status = str(project.get("status", "planned")).strip()
        if status == "completed":
            return {"ok": True, "reason": "already_completed", "completed": True}
        if status in {"designated", "building"} and dict(project.get("site", {})):
            return {"ok": True, "reason": "already_designated"}

        blueprint = construction_blueprint(str(project.get("building_kind", "")))
        if not blueprint or not bool(blueprint.get("supported", True)):
            return {"ok": False, "reason": "unsupported_blueprint"}

        px = float(self.state.h_tensor[slot, X])
        py = float(self.state.h_tensor[slot, Y])
        settlement_anchor = self._resolve_task_place_target(px, py, "settlement", radius=196.0)
        anchor_x = float((settlement_anchor or {}).get("x", px))
        anchor_y = float((settlement_anchor or {}).get("y", py))
        ctx = dict(self._build_kwargs())
        h_mask, _, _ = self._current_masks()
        ctx["h_mask"] = h_mask
        result = construction_designate_site(
            ctx,
            self.state.m_tensor,
            self._entity_count_ref,
            structure_type=int(blueprint.get("structure_type", M_HOUSE)),
            center_x=anchor_x,
            center_y=anchor_y,
            clamp_point_fn=self._clamp_world_point,
            create_object_fn=iat.instinct_create_object,
            build_progress=0.0,
            device=self.state.device,
        )
        entity_slot = int(result.get("entity_id", -1))
        if entity_slot < 0:
            return {"ok": False, "reason": "no_build_site"}

        h_mask, _, entity_mask = self._current_masks()
        self._assign_missing_ids(h_mask, entity_mask)
        entity_id = str(self._entity_uid_by_slot[entity_slot] or "").strip()
        project["site"] = {
            "entity_slot": entity_slot,
            "entity_id": entity_id,
            "x": float(result.get("site_x", self.state.m_tensor[entity_slot, CX])),
            "y": float(result.get("site_y", self.state.m_tensor[entity_slot, CY])),
            "base_entity_id": int(result.get("base_entity_id", -1)),
            "structure_type": int(self.state.m_tensor[entity_slot, M_TYPE]),
        }
        project["status"] = "designated"
        project["progress"] = round(float(self.state.m_tensor[entity_slot, S_BUILD_PROGRESS]), 2)
        project["last_update_tick"] = int(self.tick)
        resident.setdefault("task_state", {})["last_task_action"] = f"designated {project.get('building_kind', 'build')} site"
        resident.setdefault("status", {})["current_intent"] = "designate_build_site"
        self._force_map_refresh = True
        return {"ok": True, "site": dict(project["site"]), "entity_id": entity_id}

    def _advance_resident_construction_project(
        self,
        slot: int,
        human_id: str,
        resident: dict[str, Any],
        project_id: str,
    ) -> dict[str, Any]:
        project = self._construction_project_ref(resident, project_id)
        if project is None:
            return {"ok": False, "reason": "project_missing"}
        site = dict(project.get("site", {}))
        entity_id = str(site.get("entity_id", "")).strip()
        entity_ref = self._resolve_task_entity_target(entity_id) if entity_id else None
        if entity_ref is None:
            return {"ok": False, "reason": "site_missing"}

        entity_slot = int(entity_ref["slot"])
        building_kind = str(project.get("building_kind", "")).strip()
        if float(self.state.m_tensor[entity_slot, S_BUILD_PROGRESS]) >= 99.9:
            project["status"] = "completed"
            project["progress"] = round(float(self.state.m_tensor[entity_slot, S_BUILD_PROGRESS]), 2)
            project["last_update_tick"] = int(self.tick)
            if building_kind == "personal_shelter":
                self._resident_house_inventory_record(human_id, resident)
            elif int(self.state.m_tensor[entity_slot, M_TYPE]) == int(M_STORAGE_CASE):
                self._storage_case_inventory_record(entity_id)
            self._force_map_refresh = True
            return {"ok": True, "completed": True, "reason": "already_completed"}
        personal_inventory = self._human_inventory_record(human_id)
        accessible_records = self._resident_accessible_storage_records(human_id, resident, slot)
        house_storage = self._first_accessible_inventory(accessible_records)
        home_structure = self._resident_home_structure_record(human_id, resident)
        blueprint = construction_blueprint(building_kind)
        requirements = {
            str(item_kind): max(int(quantity), 1)
            for item_kind, quantity in tuple(blueprint.get("material_requirements", ()))
            if str(item_kind).strip()
        }
        metadata = project.setdefault("metadata", {})
        delivered = {
            str(item_kind): max(int(quantity), 0)
            for item_kind, quantity in dict(metadata.get("delivered_materials", {})).items()
            if str(item_kind).strip()
        }
        metadata["delivered_materials"] = delivered

        px = float(self.state.h_tensor[slot, X])
        py = float(self.state.h_tensor[slot, Y])
        site_x = float(site.get("x", self.state.m_tensor[entity_slot, CX]))
        site_y = float(site.get("y", self.state.m_tensor[entity_slot, CY]))

        for item_kind, required_quantity in requirements.items():
            delivered_quantity = max(int(delivered.get(item_kind, 0)), 0)
            if delivered_quantity >= required_quantity:
                continue

            carried_quantity = total_quantity(personal_inventory, item_kind)
            if carried_quantity > 0:
                distance_to_site = math.hypot(site_x - px, site_y - py)
                if distance_to_site > float(BUILD_RADIUS):
                    self._move_human_toward_point(slot, site_x, site_y, BASELINE_GATHER_MOVE_STEP)
                    resident.setdefault("task_state", {})["last_task_action"] = f"carrying {item_kind} to construction site"
                    resident.setdefault("status", {})["current_intent"] = "deliver_build_materials"
                    return {"ok": True, "gathered": True, "reason": "moving_to_build_site"}
                deliver_quantity = min(carried_quantity, required_quantity - delivered_quantity)
                removed = inventory_remove_item(personal_inventory, item_kind=item_kind, quantity=deliver_quantity)
                moved = int(removed.get("removed", 0))
                if moved > 0:
                    delivered[item_kind] = delivered_quantity + moved
                    metadata["delivered_materials"] = delivered
                    project["status"] = "building"
                    project["last_update_tick"] = int(self.tick)
                    resident.setdefault("task_state", {})["last_task_action"] = f"delivered {moved}x {item_kind} to {building_kind}"
                    resident.setdefault("status", {})["current_intent"] = "deliver_build_materials"
                    self._refresh_resident_carry_manifest(resident, personal_inventory)
                    return {"ok": True, "gathered": True, "reason": "delivered_materials"}

            if isinstance(house_storage, dict) and total_quantity(house_storage, item_kind) > 0:
                if isinstance(home_structure, dict):
                    home_x = float(home_structure.get("x", px))
                    home_y = float(home_structure.get("y", py))
                    if math.hypot(home_x - px, home_y - py) > BASELINE_GATHER_RADIUS:
                        self._move_human_toward_point(slot, home_x, home_y, BASELINE_GATHER_MOVE_STEP)
                        resident.setdefault("task_state", {})["last_task_action"] = f"returning home for {item_kind}"
                        resident.setdefault("status", {})["current_intent"] = f"fetch_{item_kind}"
                        return {"ok": True, "gathered": True, "reason": "moving_to_house_storage"}
                withdraw_quantity = min(required_quantity - delivered_quantity, max(int(personal_inventory.get("capacity_slots", 1)), 1))
                moved = inventory_transfer_item(
                    house_storage,
                    personal_inventory,
                    item_kind=item_kind,
                    quantity=withdraw_quantity,
                )
                moved_count = int(moved.get("moved", 0))
                if moved_count > 0:
                    resident.setdefault("task_state", {})["last_task_action"] = f"withdrew {moved_count}x {item_kind} from house storage"
                    resident.setdefault("status", {})["current_intent"] = f"fetch_{item_kind}"
                    self._refresh_resident_carry_manifest(resident, personal_inventory)
                    return {"ok": True, "gathered": True, "reason": "withdrew_house_materials"}

            progressed = self._progress_toward_item_kind(
                slot,
                resident,
                personal_inventory,
                accessible_records,
                item_kind=item_kind,
                required_quantity=1,
            )
            self._refresh_resident_carry_manifest(resident, personal_inventory)
            if progressed:
                return {"ok": True, "gathered": True, "reason": f"progressed_{item_kind}"}
            resident.setdefault("status", {})["current_intent"] = f"prepare_{building_kind}"
            resident.setdefault("task_state", {})["blocked_reason"] = f"missing_build_material:{item_kind}"
            return {"ok": False, "reason": f"missing_{item_kind}"}

        distance_to_site = math.hypot(site_x - px, site_y - py)
        if distance_to_site > float(BUILD_RADIUS):
            self._move_human_toward_point(slot, site_x, site_y, BASELINE_GATHER_MOVE_STEP)
            resident.setdefault("task_state", {})["last_task_action"] = f"moving to build {building_kind}"
            resident.setdefault("status", {})["current_intent"] = "build_project"
            return {"ok": True, "gathered": True, "reason": "moving_to_build_site"}

        crafting_state = resident.setdefault("crafting_state", {})
        if int(self.tick) < int(crafting_state.get("next_action_tick", 0)):
            resident.setdefault("status", {})["current_intent"] = "build_project"
            return {"ok": False, "reason": "build_cooldown"}

        progress_before = float(self.state.m_tensor[entity_slot, S_BUILD_PROGRESS])
        progress_after = min(100.0, progress_before + float(BUILD_PROGRESS_PER_HUMAN))
        self.state.m_tensor[entity_slot, S_BUILD_PROGRESS] = progress_after
        self.state.m_tensor[entity_slot, M_HP] = max(float(self.state.m_tensor[entity_slot, M_HP]), progress_after)
        self.state.h_tensor[slot, H_STAMINA] = max(0.0, float(self.state.h_tensor[slot, H_STAMINA]) - float(BUILD_STAMINA_COST))
        self.state.h_tensor[slot, MOOD] = max(0.0, min(100.0, float(self.state.h_tensor[slot, MOOD]) + 0.08))
        project["progress"] = round(progress_after, 2)
        project["last_update_tick"] = int(self.tick)
        project["status"] = "completed" if progress_after >= 99.9 else "building"
        if project["status"] == "completed":
            if building_kind == "personal_shelter":
                self._resident_house_inventory_record(human_id, resident)
            elif int(self.state.m_tensor[entity_slot, M_TYPE]) == int(M_STORAGE_CASE):
                self._storage_case_inventory_record(entity_id)
        resident.setdefault("task_state", {})["last_task_action"] = f"built {building_kind}"
        resident.setdefault("status", {})["current_intent"] = "build_project"
        self._force_map_refresh = True
        return {
            "ok": True,
            "gathered": False,
            "progressed": progress_after > progress_before,
            "completed": project["status"] == "completed",
            "progress": float(project.get("progress", 0.0)),
        }

    def _nearest_storage_case_record(
        self,
        center_x: float,
        center_y: float,
        *,
        radius: float = 0.0,
    ) -> dict[str, Any] | None:
        best: dict[str, Any] | None = None
        for slot, entity_id in enumerate(self._entity_uid_by_slot):
            if not entity_id:
                continue
            if int(self.state.m_tensor[slot, M_TYPE]) != int(M_STORAGE_CASE):
                continue
            dx = float(self.state.m_tensor[slot, CX]) - float(center_x)
            dy = float(self.state.m_tensor[slot, CY]) - float(center_y)
            distance = math.sqrt(dx * dx + dy * dy)
            if radius > 0.0 and distance > float(radius):
                continue
            inventory = get_container_inventory(self.inventory_state, entity_id)
            if inventory is None:
                continue
            candidate = {
                "slot": slot,
                "container_id": entity_id,
                "x": float(self.state.m_tensor[slot, CX]),
                "y": float(self.state.m_tensor[slot, CY]),
                "distance": round(distance, 2),
                "inventory": inventory,
                "summary": summarize_inventory(inventory, limit=4),
            }
            if best is None or float(candidate["distance"]) < float(best["distance"]):
                best = candidate
        return best

    def _resolve_task_place_target(
        self,
        center_x: float,
        center_y: float,
        place_tag: str,
        *,
        radius: float = 240.0,
    ) -> dict[str, Any] | None:
        normalized = str(place_tag or "").strip()
        target_types = {
            "home": {M_HOUSE, M_VILLAGE, M_WELL},
            "hearth": {M_HOUSE, M_VILLAGE, M_WELL},
            "forest": {M_FOREST},
            "grove": {M_FOREST, M_GRASS},
            "wild": {M_FOREST, M_GRASS, M_BEACH},
            "trail": {M_FOREST, M_GRASS, M_BEACH, M_VILLAGE},
            "water": {M_LAKE, M_WELL, M_BEACH, M_FARM},
            "shore": {M_LAKE, M_BEACH, M_FARM},
            "dock": {M_LAKE, M_BEACH, M_VILLAGE},
            "farm": {M_FARM, M_GRASS},
            "field": {M_FARM, M_GRASS},
            "worksite": {M_HOUSE, M_VILLAGE, M_FARM, M_WALL, M_MOUNTAIN},
            "quarry": {M_MOUNTAIN, M_BARREN, M_VILLAGE},
            "market": {M_VILLAGE, M_HOUSE, M_WELL},
            "road": {M_VILLAGE, M_HOUSE, M_BEACH},
            "settlement": {M_STORAGE_CASE, M_FARM, M_WALL, M_HOUSE, M_VILLAGE, M_WELL},
            "wall": {M_WALL},
            "gate": {M_WALL, M_STORAGE_CASE},
        }.get(normalized, set())
        target_eid = nearest_geo_entity(
            self.state.m_tensor,
            center_x,
            center_y,
            type_filter=target_types or None,
            radius=float(radius),
        )
        if target_eid == -1:
            return None
        return {
            "slot": int(target_eid),
            "x": float(self.state.m_tensor[target_eid, CX]),
            "y": float(self.state.m_tensor[target_eid, CY]),
            "place_tag": normalized,
            "entity_type": int(self.state.m_tensor[target_eid, M_TYPE]),
        }

    @staticmethod
    def _task_resource_type_ids(resource_kind: str) -> tuple[set[int], int] | None:
        normalized = str(resource_kind or "").strip()
        if normalized == "food":
            return ({M_GRASS, M_FOREST, M_BEACH, M_LAKE, M_FARM, M_HOUSE, M_VILLAGE, M_RESOURCE_NODE}, M_RESOURCE_FOOD)
        if normalized == "water":
            return ({M_LAKE, M_WELL, M_FARM, M_VILLAGE}, M_RESOURCE_WATER)
        return None

    def _resolve_task_resource_target(
        self,
        center_x: float,
        center_y: float,
        resource_kind: str,
        *,
        radius: float = 220.0,
    ) -> dict[str, Any] | None:
        resource_spec = self._task_resource_type_ids(resource_kind)
        if resource_spec is None:
            return None
        target_types, resource_col = resource_spec
        target_eid = best_resource_entity(
            self.state.m_tensor,
            center_x,
            center_y,
            type_filter=target_types,
            resource_col=resource_col,
            radius=float(radius),
        )
        if target_eid == -1:
            return None
        dx = float(self.state.m_tensor[target_eid, CX]) - float(center_x)
        dy = float(self.state.m_tensor[target_eid, CY]) - float(center_y)
        return {
            "slot": int(target_eid),
            "uid": self._entity_uid_by_slot[int(target_eid)],
            "x": float(self.state.m_tensor[target_eid, CX]),
            "y": float(self.state.m_tensor[target_eid, CY]),
            "resource_kind": str(resource_kind),
            "entity_type": int(self.state.m_tensor[target_eid, M_TYPE]),
            "distance": round(math.hypot(dx, dy), 2),
        }

    def _resolve_task_safe_target(
        self,
        center_x: float,
        center_y: float,
        *,
        radius: float = 240.0,
    ) -> dict[str, Any] | None:
        target_eid = best_safe_entity(
            self.state.m_tensor,
            center_x,
            center_y,
            radius=float(radius),
        )
        if target_eid == -1:
            return None
        dx = float(self.state.m_tensor[target_eid, CX]) - float(center_x)
        dy = float(self.state.m_tensor[target_eid, CY]) - float(center_y)
        return {
            "slot": int(target_eid),
            "x": float(self.state.m_tensor[target_eid, CX]),
            "y": float(self.state.m_tensor[target_eid, CY]),
            "entity_type": int(self.state.m_tensor[target_eid, M_TYPE]),
            "distance": round(math.hypot(dx, dy), 2),
        }

    def _slot_ready_for_mating(self, slot: int) -> bool:
        if int(self.state.h_tensor[slot, TYPE]) != int(AGENT_TYPE_HUMAN):
            return False
        if float(self.state.h_tensor[slot, H_AGE]) < float(MATURE_AGE):
            return False
        if float(self.state.h_tensor[slot, H_COOLDOWN]) > 0.0:
            return False
        if float(self.state.h_tensor[slot, HUNGER]) > float(SAFE_REPRO_HUNGER_MAX):
            return False
        if float(self.state.h_tensor[slot, THIRST]) > float(SAFE_REPRO_THIRST_MAX):
            return False
        if float(self.state.h_tensor[slot, THREAT]) > float(SAFE_REPRO_THREAT_MAX):
            return False
        if float(self.state.h_tensor[slot, HP]) < float(SAFE_REPRO_HP_MIN):
            return False
        if float(self.state.h_tensor[slot, H_STAMINA]) < float(SAFE_REPRO_STAMINA_MIN):
            return False
        return True

    def _resolve_mate_candidate(
        self,
        slot: int,
        *,
        radius: float = 72.0,
    ) -> dict[str, Any] | None:
        if not self._slot_ready_for_mating(slot):
            return None
        seeker_id = self._human_uid_by_slot[slot]
        seeker_sex = float(self.state.h_tensor[slot, H_SEX])
        seeker_x = float(self.state.h_tensor[slot, X])
        seeker_y = float(self.state.h_tensor[slot, Y])
        best: dict[str, Any] | None = None
        for other_slot in _human_query.humans_within(
            self.state.h_tensor, seeker_x, seeker_y, radius, type_col=TYPE, x_col=X, y_col=Y, human_type=AGENT_TYPE_HUMAN,
            extra_cols=_human_query.MATE_COLS, keep=_human_query.keep_mate(seeker_sex),
        ):
            if other_slot == slot:
                continue
            if not self._slot_ready_for_mating(other_slot):
                continue
            if float(self.state.h_tensor[other_slot, H_SEX]) == seeker_sex:
                continue
            other_id = self._human_uid_by_slot[other_slot]
            if not other_id or other_id == seeker_id:
                continue
            dx = float(self.state.h_tensor[other_slot, X]) - seeker_x
            dy = float(self.state.h_tensor[other_slot, Y]) - seeker_y
            distance = math.hypot(dx, dy)
            if distance > float(radius):
                continue
            other_resident = self.resident_store.get(other_id)
            candidate = {
                "slot": int(other_slot),
                "human_id": str(other_id),
                "name": str((other_resident or {}).get("profile", {}).get("name", other_id)),
                "x": float(self.state.h_tensor[other_slot, X]),
                "y": float(self.state.h_tensor[other_slot, Y]),
                "distance": round(distance, 2),
            }
            if best is None or float(candidate["distance"]) < float(best["distance"]):
                best = candidate
        return best

    def _resolve_task_human_target(self, human_id: str) -> dict[str, Any] | None:
        needle = str(human_id or "").strip()
        if not needle:
            return None
        for slot, candidate_id in enumerate(self._human_uid_by_slot):
            if str(candidate_id or "") != needle:
                continue
            if int(self.state.h_tensor[slot, TYPE]) != int(AGENT_TYPE_HUMAN):
                return None
            resident = self.resident_store.get(needle)
            return {
                "slot": int(slot),
                "human_id": needle,
                "name": str((resident or {}).get("profile", {}).get("name", needle)),
                "x": float(self.state.h_tensor[slot, X]),
                "y": float(self.state.h_tensor[slot, Y]),
                "hp": float(self.state.h_tensor[slot, HP]),
                "threat": float(self.state.h_tensor[slot, THREAT]),
                "stamina": float(self.state.h_tensor[slot, H_STAMINA]),
                "occupation_kind": str((resident or {}).get("occupation", {}).get("kind", "")),
            }
        return None

    def _resolve_task_entity_target(self, entity_id: str) -> dict[str, Any] | None:
        needle = str(entity_id or "").strip()
        if not needle:
            return None
        for slot, candidate_id in enumerate(self._entity_uid_by_slot):
            if str(candidate_id or "") != needle:
                continue
            if int(self.state.m_tensor[slot, M_TYPE]) <= 0 or float(self.state.m_tensor[slot, M_HP]) <= 0.0:
                return None
            return {
                "slot": int(slot),
                "entity_id": needle,
                "name": needle,
                "x": float(self.state.m_tensor[slot, CX]),
                "y": float(self.state.m_tensor[slot, CY]),
                "entity_type": int(self.state.m_tensor[slot, M_TYPE]),
                "hp": float(self.state.m_tensor[slot, M_HP]),
            }
        return None

    def _resolve_nearby_help_target(
        self,
        slot: int,
        *,
        radius: float = 72.0,
    ) -> dict[str, Any] | None:
        seeker_id = str(self._human_uid_by_slot[slot] or "").strip()
        if not seeker_id:
            return None
        px = float(self.state.h_tensor[slot, X])
        py = float(self.state.h_tensor[slot, Y])
        best: dict[str, Any] | None = None
        for other_slot in _human_query.humans_within(
            self.state.h_tensor, px, py, radius, type_col=TYPE, x_col=X, y_col=Y, human_type=AGENT_TYPE_HUMAN,
            extra_cols=_human_query.HELP_COLS, keep=_human_query.keep_help,
        ):
            if int(other_slot) == int(slot):
                continue
            other_id = str(self._human_uid_by_slot[other_slot] or "").strip()
            if not other_id or other_id == seeker_id:
                continue
            dx = float(self.state.h_tensor[other_slot, X]) - px
            dy = float(self.state.h_tensor[other_slot, Y]) - py
            distance = math.hypot(dx, dy)
            if distance > float(radius):
                continue
            hp = float(self.state.h_tensor[other_slot, HP])
            threat = float(self.state.h_tensor[other_slot, THREAT])
            if hp >= 78.0 and threat < 42.0:
                continue
            resident = self.resident_store.get(other_id)
            candidate = {
                "slot": int(other_slot),
                "human_id": other_id,
                "name": str((resident or {}).get("profile", {}).get("name", other_id)),
                "x": float(self.state.h_tensor[other_slot, X]),
                "y": float(self.state.h_tensor[other_slot, Y]),
                "distance": round(distance, 2),
                "hp": hp,
                "threat": threat,
            }
            if best is None or (float(candidate["hp"]) < float(best["hp"])) or (
                float(candidate["hp"]) == float(best["hp"]) and float(candidate["distance"]) < float(best["distance"])
            ):
                best = candidate
        return best

    def _resolve_support_target(
        self,
        slot: int,
        *,
        radius: float = 96.0,
    ) -> dict[str, Any] | None:
        seeker_id = str(self._human_uid_by_slot[slot] or "").strip()
        if not seeker_id:
            return None
        px = float(self.state.h_tensor[slot, X])
        py = float(self.state.h_tensor[slot, Y])
        best: dict[str, Any] | None = None
        best_score = -10**9
        for other_slot in _human_query.humans_within(
            self.state.h_tensor, px, py, radius, type_col=TYPE, x_col=X, y_col=Y, human_type=AGENT_TYPE_HUMAN,
            extra_cols=_human_query.SUPPORT_COLS, keep=_human_query.keep_support,
        ):
            if int(other_slot) == int(slot):
                continue
            other_id = str(self._human_uid_by_slot[other_slot] or "").strip()
            if not other_id or other_id == seeker_id:
                continue
            if float(self.state.h_tensor[other_slot, HP]) <= 0.0:
                continue
            dx = float(self.state.h_tensor[other_slot, X]) - px
            dy = float(self.state.h_tensor[other_slot, Y]) - py
            distance = math.hypot(dx, dy)
            if distance > float(radius):
                continue
            resident = self.resident_store.get(other_id)
            occupation_kind = str((resident or {}).get("occupation", {}).get("kind", "")).strip()
            hp = float(self.state.h_tensor[other_slot, HP])
            threat = float(self.state.h_tensor[other_slot, THREAT])
            if hp < 45.0 or threat > 68.0:
                continue
            score = 100.0 - distance
            if occupation_kind == "guard":
                score += 18.0
            elif occupation_kind == "healer":
                score += 8.0
            score += max(0.0, hp - 60.0) * 0.1
            if best is None or score > best_score:
                best = {
                    "slot": int(other_slot),
                    "human_id": other_id,
                    "name": str((resident or {}).get("profile", {}).get("name", other_id)),
                    "x": float(self.state.h_tensor[other_slot, X]),
                    "y": float(self.state.h_tensor[other_slot, Y]),
                    "distance": round(distance, 2),
                    "occupation_kind": occupation_kind,
                }
                best_score = score
        return best

    def _queue_resident_task_signal(
        self,
        human_id: str,
        signal_family: str,
        signal: dict[str, Any],
    ) -> bool:
        needle = str(human_id or "").strip()
        family = str(signal_family or "").strip().lower()
        if not needle or family not in {"social", "combat"} or not isinstance(signal, dict) or not signal:
            return False
        resident = self.resident_store.get(needle)
        if not isinstance(resident, dict):
            return False
        task_state = resident.setdefault("task_state", {})
        key = "pending_social_signal" if family == "social" else "pending_combat_signal"
        task_state[key] = dict(signal)
        self.resident_store.touch_resident(needle)
        return True

    def _attempt_task_heal(
        self,
        slot: int,
        personal_inventory: dict,
        accessible_records: list[dict[str, Any]],
        target_human_id: str,
        item_kind: str,
    ) -> dict[str, Any]:
        target = self._resolve_task_human_target(target_human_id)
        if target is None:
            return {"ok": False, "reason": "target_missing"}
        if not has_item(personal_inventory, item_kind, 1):
            for entry in accessible_records:
                record = entry.get("inventory")
                if not isinstance(record, dict) or not has_item(record, item_kind, 1):
                    continue
                moved = inventory_transfer_item(record, personal_inventory, item_kind=item_kind, quantity=1)
                if moved.get("ok"):
                    break
        removed = inventory_remove_item(personal_inventory, item_kind=item_kind, quantity=1)
        if int(removed.get("removed", 0)) <= 0:
            return {"ok": False, "reason": "missing_supplies"}
        target_slot = int(target.get("slot", -1))
        self.state.h_tensor[target_slot, HP] = max(0.0, min(100.0, float(self.state.h_tensor[target_slot, HP]) + 18.0))
        self.state.h_tensor[target_slot, THREAT] = max(0.0, float(self.state.h_tensor[target_slot, THREAT]) - 8.0)
        return {"ok": True, "target_alive": True}

    def _attempt_task_delivery(
        self,
        slot: int,
        personal_inventory: dict,
        target_human_id: str,
        item_kind: str,
        quantity: int,
    ) -> dict[str, Any]:
        target_inventory = ensure_owner_inventory(self.inventory_state, target_human_id, owner_kind="resident")
        if target_inventory is None:
            return {"ok": False, "reason": "target_inventory_missing"}
        moved = inventory_transfer_item(
            personal_inventory,
            target_inventory,
            item_kind=item_kind,
            quantity=max(int(quantity), 1),
        )
        if not moved.get("ok"):
            return {"ok": False, "reason": "delivery_failed"}
        return {"ok": True, "delivered": int(moved.get("moved", 0))}

    def _attempt_task_steal(
        self,
        personal_inventory: dict,
        container_id: str,
        item_kind: str,
        quantity: int,
    ) -> dict[str, Any]:
        inventory = get_container_inventory(self.inventory_state, container_id)
        if inventory is None:
            return {"ok": False, "reason": "container_missing"}
        moved = inventory_transfer_item(
            inventory,
            personal_inventory,
            item_kind=str(item_kind or ""),
            quantity=max(int(quantity), 1),
        )
        if not moved.get("ok"):
            return {"ok": False, "reason": "steal_failed"}
        return {"ok": True, "moved": int(moved.get("moved", 0))}

    def _manual_attack_target_for_slot(
        self,
        slot: int,
        manual_control: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not isinstance(manual_control, dict):
            return None
        control = dict((manual_control.get("by_slot") or {}).get(int(slot)) or {})
        if not control:
            return None
        pending_action = str(control.get("pending_action", "")).strip().lower()
        pending_semantic_action = str(control.get("pending_semantic_action", "")).strip().lower()
        attack_button = bool(control.get("attack", False))
        if pending_action != "attack" and pending_semantic_action != "attack_target":
            return None
        attacker_id = str(self._human_uid_by_slot[int(slot)] or "").strip()
        target_kind = str(control.get("selected_target_kind", "")).strip().lower()
        target_id = str(control.get("selected_target_id", "")).strip()
        if not target_kind or not target_id:
            print(
                f"[ManualAttack] attacker={attacker_id} slot={int(slot)} "
                f"pending={pending_action} semantic={pending_semantic_action} "
                f"attack_button={attack_button} target_missing"
            )
            return None
        if target_kind == "human":
            target = self._resolve_task_human_target(target_id)
            if target is None:
                print(
                    f"[ManualAttack] attacker={attacker_id} slot={int(slot)} "
                    f"target_kind=human target_id={target_id} resolved=False"
                )
                return None
            distance = math.hypot(
                float(target.get("x", 0.0)) - float(self.state.h_tensor[slot, X]),
                float(target.get("y", 0.0)) - float(self.state.h_tensor[slot, Y]),
            )
            stamina = float(self.state.h_tensor[slot, H_STAMINA])
            print(
                f"[ManualAttack] attacker={attacker_id} slot={int(slot)} "
                f"target={target_id} kind=human dist={float(distance):.2f} "
                f"range={float(ATTACK_RANGE):.2f} stamina={stamina:.1f} "
                f"pending={pending_action} semantic={pending_semantic_action} "
                f"attack_button={attack_button}"
            )
            return {
                "target_kind": "human",
                "target_id": target_id,
                "name": str(target.get("name", target_id)),
                "distance": round(distance, 2),
                "reason": "manual_attack",
            }
        if target_kind == "entity":
            target = self._resolve_task_entity_target(target_id)
            if target is None:
                print(
                    f"[ManualAttack] attacker={attacker_id} slot={int(slot)} "
                    f"target_kind=entity target_id={target_id} resolved=False"
                )
                return None
            distance = math.hypot(
                float(target.get("x", 0.0)) - float(self.state.h_tensor[slot, X]),
                float(target.get("y", 0.0)) - float(self.state.h_tensor[slot, Y]),
            )
            stamina = float(self.state.h_tensor[slot, H_STAMINA])
            print(
                f"[ManualAttack] attacker={attacker_id} slot={int(slot)} "
                f"target={target_id} kind=entity dist={float(distance):.2f} "
                f"range={float(ATTACK_RANGE):.2f} stamina={stamina:.1f} "
                f"pending={pending_action} semantic={pending_semantic_action} "
                f"attack_button={attack_button}"
            )
            return {
                "target_kind": "entity",
                "target_id": target_id,
                "name": str(target.get("name", target_id)),
                "distance": round(distance, 2),
                "reason": "manual_attack",
            }
        return None

    def _clear_manual_attack_pending_for_slot(self, slot: int) -> None:
        if self.player_control is None:
            return
        for session in self.player_control.sessions_by_controller.values():
            if str(session.get("target_kind", "")).strip().lower() != "human":
                continue
            if int(session.get("slot", -1)) != int(slot):
                continue
            command_state = dict(session.get("command_state", self.player_control._empty_command_state()))
            pending_action = str(command_state.get("pending_action", "")).strip().lower()
            pending_semantic_action = str(command_state.get("pending_semantic_action", "")).strip().lower()
            if pending_action == "attack" or pending_semantic_action == "attack_target":
                command_state["pending_action"] = None
                command_state["pending_semantic_action"] = None
                command_state["pending_action_family"] = None
                session["command_state"] = command_state
            break

    def _resolve_autonomous_human_attack_target(
        self,
        slot: int,
        *,
        radius: float = 28.0,
    ) -> dict[str, Any] | None:
        aggression = float(self.state.h_tensor[slot, H_AGGRESSION])
        threat = float(self.state.h_tensor[slot, THREAT])
        stamina = float(self.state.h_tensor[slot, H_STAMINA])
        if stamina < float(ATTACK_STAMINA_COST):
            return None
        if aggression < max(float(AGGRESSION_THRESHOLD) + 0.15, 0.65) and threat < 55.0:
            return None
        px = float(self.state.h_tensor[slot, X])
        py = float(self.state.h_tensor[slot, Y])
        best: dict[str, Any] | None = None
        for other_slot in _human_query.humans_within(
            self.state.h_tensor, px, py, radius, type_col=TYPE, x_col=X, y_col=Y, human_type=AGENT_TYPE_HUMAN,
            extra_cols=_human_query.ATTACK_COLS, keep=_human_query.keep_attack,
        ):
            if other_slot == slot:
                continue
            if float(self.state.h_tensor[other_slot, HP]) <= 0.0:
                continue
            human_id = self._human_uid_by_slot[other_slot]
            if not human_id:
                continue
            dx = float(self.state.h_tensor[other_slot, X]) - px
            dy = float(self.state.h_tensor[other_slot, Y]) - py
            distance = math.hypot(dx, dy)
            if distance > float(radius):
                continue
            resident = self.resident_store.get(human_id)
            candidate = {
                "target_kind": "human",
                "target_id": str(human_id),
                "name": str((resident or {}).get("profile", {}).get("name", human_id)),
                "distance": round(distance, 2),
                "reason": "aggression",
            }
            if best is None or float(candidate["distance"]) < float(best["distance"]):
                best = candidate
        return best

    def _resolve_autonomous_hunt_target(
        self,
        slot: int,
        *,
        radius: float = 32.0,
    ) -> dict[str, Any] | None:
        aggression = float(self.state.h_tensor[slot, H_AGGRESSION])
        hunger = float(self.state.h_tensor[slot, HUNGER])
        stamina = float(self.state.h_tensor[slot, H_STAMINA])
        if aggression < float(AGGRESSION_THRESHOLD):
            return None
        if hunger < float(FOOD_SEEK_THRESHOLD):
            return None
        if stamina < float(ATTACK_STAMINA_COST):
            return None
        animal_slots = huntable_animal_slots(self.state.m_tensor, M_TYPE)
        if animal_slots.numel() <= 0:
            return None
        target_slot, distance = nearest_huntable_animal(
            self.state.m_tensor,
            float(self.state.h_tensor[slot, X]),
            float(self.state.h_tensor[slot, Y]),
            animal_slots,
            max_distance=float(radius),
        )
        if target_slot < 0:
            return None
        target_id = self._entity_uid_by_slot[int(target_slot)]
        if not target_id:
            return None
        return {
            "target_kind": "entity",
            "target_id": str(target_id),
            "name": str(target_id),
            "distance": round(float(distance), 2),
            "reason": "hunt_food",
        }

    def _attempt_task_mating(self, slot: int, target_human_id: str) -> dict[str, Any]:
        source_info = self._resolve_task_human_target(self._human_uid_by_slot[slot] or "")
        target_info = self._resolve_task_human_target(target_human_id)
        if source_info is None or target_info is None:
            return {"ok": False, "reason": "target_missing"}
        target_slot = int(target_info.get("slot", -1))
        if target_slot < 0 or target_slot == slot:
            return {"ok": False, "reason": "target_invalid"}
        if world_has_roster(self):
            return {"ok": False, "reason": "population_fixed"}  # a roster map's population is its roster
        if not self._slot_ready_for_mating(slot) or not self._slot_ready_for_mating(target_slot):
            return {"ok": False, "reason": "not_ready"}
        if float(self.state.h_tensor[slot, H_SEX]) == float(self.state.h_tensor[target_slot, H_SEX]):
            return {"ok": False, "reason": "incompatible"}
        distance = math.hypot(
            float(self.state.h_tensor[target_slot, X]) - float(self.state.h_tensor[slot, X]),
            float(self.state.h_tensor[target_slot, Y]) - float(self.state.h_tensor[slot, Y]),
        )
        if distance > float(PROXIMITY_MATE_RADIUS):
            return {"ok": False, "reason": "too_far"}
        free = torch.where(self.state.h_tensor[:, TYPE] == 0)[0]
        child_slot = int(free[0].item()) if len(free) else -1
        if child_slot < 0:
            return {"ok": False, "reason": "population_full"}
        mother_slot = slot if float(self.state.h_tensor[slot, H_SEX]) == 1.0 else target_slot
        father_slot = target_slot if mother_slot == slot else slot
        px = float(self.state.h_tensor[mother_slot, X]) + random.uniform(-4.0, 4.0)
        py = float(self.state.h_tensor[mother_slot, Y]) + random.uniform(-4.0, 4.0)
        spawned = iat.instinct_born(
            self.state.h_tensor,
            self._pop_count,
            max(_world_limits()[0], min(_world_limits()[2], px)),
            max(_world_limits()[1], min(_world_limits()[3], py)),
            sex=0.0 if random.random() < 0.5 else 1.0,
            life_exp=random.uniform(LIFE_EXP_MIN, LIFE_EXP_MAX),
            parent_instincts=float(self.state.h_tensor[mother_slot, ACQUIRED_INSTINCT_MASK]),
            tribe=float(self.state.h_tensor[mother_slot, H_TRIBE]),
        )
        if not spawned:
            return {"ok": False, "reason": "birth_failed"}
        instinct_bits.inherit_words(self.state.h_tensor, child_slot, mother_slot)   # bits 24..63 of the mother's mask (G-D0-2)
        self.state.h_tensor[mother_slot, H_COOLDOWN] = 1.0
        mother_id = self._human_uid_by_slot[mother_slot]
        father_id = self._human_uid_by_slot[father_slot]
        parent_ids = [str(parent_id) for parent_id in [mother_id, father_id] if str(parent_id or "").strip()]
        self._pending_birth_links_by_slot[child_slot] = {
            "tick": self.tick,
            "parent_ids": parent_ids,
        }
        return {
            "ok": True,
            "child_slot": int(child_slot),
            "mother_slot": int(mother_slot),
            "father_slot": int(father_slot),
        }

    def _run_orchestration_packet(self, packet: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(packet, dict):
            return None
        orchestrator = getattr(self, "orchestrator", None)
        if orchestrator is None:
            return None
        return orchestrator.run_packet(packet, engine=self)

    @staticmethod
    def _orchestration_talk_target_id(result: dict[str, Any]) -> str:
        if not isinstance(result, dict):
            return ""
        for key in ("target_id", "primary_listener_id"):
            value = str(result.get(key, "")).strip()
            if value:
                return value
        if str(result.get("mode", "")).strip().lower() == "direct_talk":
            speaker_id = str(result.get("speaker_id", "")).strip()
            if speaker_id:
                return speaker_id
        return str(result.get("listener_id", "")).strip()

    def _orchestrate_manual_semantic_outcome(
        self,
        *,
        slot: int,
        human_id: str,
        semantic_action: str,
        target_kind: str,
        target_id: str,
        target_tag: str = "",
        result: dict[str, Any] | None = None,
    ) -> None:
        normalized_action = str(semantic_action or "").strip().lower()
        if not normalized_action:
            return
        packet = packet_from_manual_action(
            packet_id=self.orchestrator.next_packet_id(),
            tick=int(self.tick),
            actor_kind="human",
            actor_id=str(human_id),
            semantic_action=normalized_action,
            action_family="manual_interaction",
            target_kind=str(target_kind or "").strip().lower(),
            target_id=str(target_id or "").strip(),
            payload=dict(result or {}),
            metadata={
                "origin": "manual_semantic_result",
                "target_tag": str(target_tag or "").strip().lower(),
            },
            facts={"immediate_effect_applied": True},
        )
        packet["world_refs"] = {
            "actor_slot": int(slot),
        }
        if str(target_kind or "").strip().lower() != "human":
            packet["facts"]["requires_reflex"] = False
            packet["facts"]["emit_urgent_ticket"] = False
            packet["facts"]["emit_consequence_ticket"] = False
            packet["facts"]["emit_reasoning_ticket"] = False
        self._run_orchestration_packet(packet)

    def _orchestrate_talk_outcome(self, talk_outcome: dict[str, Any] | None) -> None:
        if not isinstance(talk_outcome, dict):
            return
        result = dict(talk_outcome.get("result") or {})
        if not result:
            return
        speaker_id = str(result.get("speaker_id", "")).strip()
        target_id = self._orchestration_talk_target_id(result)
        packet = packet_from_world_event(
            packet_id=self.orchestrator.next_packet_id(),
            tick=int(self.tick),
            event_kind="talk_result",
            actor_kind="human" if speaker_id else "",
            actor_id=speaker_id,
            target_kind="human" if target_id else "",
            target_id=target_id,
            semantic_action="talk_command",
            action_family="talk",
            payload={
                "mode": str(result.get("mode", "")),
                "speech_text": str(result.get("speech_text", "")),
                "speech_act": str(result.get("speech_act", "")),
                "tone": str(result.get("tone", "")),
                "physical_intent": str(result.get("physical_intent", "")),
                "danger_upgrade": bool(result.get("danger_upgrade", False)),
                "reasoning_followup": bool(result.get("reasoning_followup", False)),
                "memory_salience": float(result.get("memory_salience", 0.0)),
            },
            metadata={
                "origin": "talk_runtime",
                "talk_kind": str(talk_outcome.get("kind", "")),
                "controller_id": str(talk_outcome.get("controller_id", "local_player")),
            },
            facts={
                "immediate_effect_applied": True,
                "requires_reflex": bool(result.get("danger_upgrade", False))
                or str(result.get("physical_intent", "")).strip().lower() in {"counterattack", "scan_and_prepare", "call_help", "stay_alert"},
                "emit_urgent_ticket": bool(result.get("danger_upgrade", False))
                or str(result.get("physical_intent", "")).strip().lower() in {"counterattack", "scan_and_prepare", "call_help", "stay_alert"},
                "emit_consequence_ticket": bool(target_id),
                "emit_reasoning_ticket": bool(result.get("reasoning_followup", False) or result.get("danger_upgrade", False)),
            },
        )
        self._run_orchestration_packet(packet)

    def _emit_mock_reasoning_output(
        self,
        resident_id: str,
        *,
        counterparty_id: str = "",
        reason: str = "",
        strategy_hint: str = "",
    ) -> dict[str, Any] | None:
        resident_uid = str(resident_id or "").strip()
        if not resident_uid:
            return None
        packet = packet_from_reasoning_output(
            packet_id=self.orchestrator.next_packet_id(),
            tick=int(self.tick),
            actor_kind="human",
            actor_id=resident_uid,
            target_kind="human" if str(counterparty_id or "").strip() else "",
            target_id=str(counterparty_id or "").strip(),
            semantic_action="reasoning_output",
            action_family="reasoning",
            payload={
                "resident_id": resident_uid,
                "counterparty_id": str(counterparty_id or "").strip(),
                "reason": str(reason or "mock_reasoning_output").strip(),
                "mock_strategy": str(strategy_hint or "").strip().lower(),
                "mock_output": True,
            },
            metadata={"origin": "manual_mock_reasoning", "mock_output": True},
        )
        return self._run_orchestration_packet(packet)

    def _orchestrate_task_completion(
        self,
        *,
        human_id: str,
        completed_task: dict[str, Any] | None,
    ) -> None:
        if not isinstance(completed_task, dict) or not completed_task:
            return
        task_kind = str(completed_task.get("task_kind", "")).strip().lower()
        if not task_kind:
            return
        if task_kind == "attack_target":
            return
        target_kind = str(completed_task.get("target_kind", "")).strip().lower()
        target_id = str(completed_task.get("target_id") or "").strip()
        semantic_action = ""
        facts: dict[str, Any] = {"immediate_effect_applied": True}
        if task_kind == "attack_target":
            semantic_action = "attack_target"
        elif task_kind in {"talk_to_target", "warn_target", "challenge_target", "call_for_help"}:
            semantic_action = "talk_command"
        elif task_kind in {"deliver_item", "help_target", "escort_target", "follow_target"}:
            semantic_action = "interact_target"
        if target_kind == "human":
            facts["emit_consequence_ticket"] = True
            facts["emit_reasoning_ticket"] = bool(task_kind in {"attack_target", "warn_target", "challenge_target"})
            if task_kind == "attack_target":
                facts["requires_reflex"] = True
                facts["emit_urgent_ticket"] = True
        packet = packet_from_task_outcome(
            packet_id=self.orchestrator.next_packet_id(),
            tick=int(self.tick),
            actor_kind="human",
            actor_id=str(human_id),
            task_kind=task_kind,
            semantic_action=semantic_action,
            action_family=str((completed_task.get("source") or "task")).strip().lower(),
            target_kind=target_kind,
            target_id=target_id,
            outcome={
                "status": str(completed_task.get("status", "")),
                "summary": str(completed_task.get("summary", "")),
                "completion_reason": str(dict(completed_task.get("metadata", {})).get("completion_reason", "")),
                "metadata": dict(completed_task.get("metadata", {})),
            },
            metadata={"origin": "task_completion"},
            facts=facts,
        )
        self._run_orchestration_packet(packet)

    def _orchestrate_combat_outcome(
        self,
        *,
        attacker_id: str,
        attacker_slot: int,
        target_kind: str,
        target_id: str,
        target_slot: int,
        damage: float,
        killed: bool,
        target_hp_after: float,
        source: str,
    ) -> None:
        normalized_source = str(source or "").strip().lower()
        normalized_target_kind = str(target_kind or "").strip().lower()
        packet_payload = {
            "source": normalized_source,
            "damage": round(float(damage), 3),
            "killed": bool(killed),
            "target_hp_after": round(float(target_hp_after), 3),
        }
        packet_metadata = {
            "origin": "combat_outcome",
            "source": normalized_source,
        }
        if normalized_source == "manual":
            packet = packet_from_manual_action(
                packet_id=self.orchestrator.next_packet_id(),
                tick=int(self.tick),
                actor_kind="human",
                actor_id=str(attacker_id),
                semantic_action="attack_target",
                action_family="combat",
                target_kind=normalized_target_kind,
                target_id=str(target_id or "").strip(),
                payload=packet_payload,
                metadata=packet_metadata,
                facts={"immediate_effect_applied": True},
            )
        else:
            packet = packet_from_task_outcome(
                packet_id=self.orchestrator.next_packet_id(),
                tick=int(self.tick),
                actor_kind="human",
                actor_id=str(attacker_id),
                task_kind="attack_target",
                semantic_action="attack_target",
                action_family="combat",
                target_kind=normalized_target_kind,
                target_id=str(target_id or "").strip(),
                outcome=packet_payload,
                metadata=packet_metadata,
                facts={"immediate_effect_applied": True},
            )
        packet["facts"]["immediate_effect_applied"] = True
        if normalized_target_kind != "human":
            packet["facts"]["requires_reflex"] = False
            packet["facts"]["emit_urgent_ticket"] = False
            packet["facts"]["emit_consequence_ticket"] = False
            packet["facts"]["emit_reasoning_ticket"] = False
        packet["world_refs"] = {
            "attacker_slot": int(attacker_slot),
            "target_slot": int(target_slot),
        }
        self._run_orchestration_packet(packet)

    def _record_combat_outcomes(
        self,
        combat_outcome: dict[str, Any],
        pre_h_hp: torch.Tensor,
        pre_m_hp: torch.Tensor,
    ) -> None:
        if combat_outcome.get("resolved", 0) <= 0:
            return
        resident_store = self.resident_store
        human_ids = self._human_uid_by_slot
        entity_ids = self._entity_uid_by_slot
        for outcome in combat_outcome.get("outcomes", []):
            attacker_slot = int(outcome["attacker_slot"])
            target_slot = int(outcome["target_slot"])
            target_kind = str(outcome["target_kind"]).strip().lower()
            source = str(outcome.get("source", "")).strip().lower()
            attacker_id = human_ids[attacker_slot] if 0 <= attacker_slot < len(human_ids) else None
            if not attacker_id:
                continue
            if target_kind == "human":
                target_id = human_ids[target_slot] if 0 <= target_slot < len(human_ids) else None
                if not target_id:
                    continue
                damage = max(0.0, float(pre_h_hp[target_slot]) - float(self.state.h_tensor[target_slot, HP]))
                killed = float(pre_h_hp[target_slot]) > 0.0 and float(self.state.h_tensor[target_slot, HP]) <= 0.0
                self._set_actor_render_action(str(attacker_id), "attack", duration_ticks=4)
                self._set_actor_render_action(str(target_id), "down" if killed else "pain", duration_ticks=12 if killed else 6)
                self._queue_event(
                    "attack_kill" if killed else "attack_hit",
                    str(attacker_id),
                    int(attacker_slot),
                    attacker_id=str(attacker_id),
                    target_kind="human",
                    target_id=str(target_id),
                    target_slot=int(target_slot),
                    damage=round(float(damage), 1),
                    hp_after=round(float(self.state.h_tensor[target_slot, HP]), 1),
                    source=source,
                )
                resident_store.record_event(
                    attacker_id,
                    self.tick,
                    "attack",
                    note=f"attacked {target_id} for {round(damage, 1)} damage",
                    other_human_id=target_id,
                )
                resident_store.record_event(
                    target_id,
                    self.tick,
                    "attacked",
                    note=f"attacked by {attacker_id} for {round(damage, 1)} damage",
                    other_human_id=attacker_id,
                )
                resident_store.update_relationship(attacker_id, target_id, "rival", -0.12, self.tick)
                resident_store.update_relationship(target_id, attacker_id, "rival", -0.18, self.tick)
                if killed:
                    resident_store.record_event(
                        attacker_id,
                        self.tick,
                        "killed_human",
                        note=f"killed {target_id}",
                        other_human_id=target_id,
                    )
                    resident_store.record_event(
                        target_id,
                        self.tick,
                        "killed_by",
                        note=f"killed by {attacker_id}",
                        other_human_id=attacker_id,
                    )
                self._orchestrate_combat_outcome(
                    attacker_id=str(attacker_id),
                    attacker_slot=int(attacker_slot),
                    target_kind="human",
                    target_id=str(target_id),
                    target_slot=int(target_slot),
                    damage=float(damage),
                    killed=bool(killed),
                    target_hp_after=float(self.state.h_tensor[target_slot, HP]),
                    source=source,
                )
            elif target_kind == "entity":
                target_uid = entity_ids[target_slot] if 0 <= target_slot < len(entity_ids) else None
                damage = max(0.0, float(pre_m_hp[target_slot]) - float(self.state.m_tensor[target_slot, M_HP]))
                killed = float(pre_m_hp[target_slot]) > 0.0 and float(self.state.m_tensor[target_slot, M_HP]) <= 0.0
                event_kind = "hunt_kill" if killed else "hunt_attack"
                self._set_actor_render_action(str(attacker_id), "attack", duration_ticks=4)
                if target_uid:
                    self._set_actor_render_action(str(target_uid), "down" if killed else "pain", duration_ticks=12 if killed else 6)
                self._queue_event(
                    "hunt_kill" if killed else "hunt_hit",
                    str(attacker_id),
                    int(attacker_slot),
                    attacker_id=str(attacker_id),
                    target_kind="entity",
                    target_id=str(target_uid or ""),
                    target_slot=int(target_slot),
                    damage=round(float(damage), 1),
                    hp_after=round(float(self.state.m_tensor[target_slot, M_HP]), 1),
                    source=source,
                )
                note = f"{event_kind.replace('_', ' ')} on {target_uid or ('entity_slot_' + str(target_slot))} for {round(damage, 1)} damage"
                resident_store.record_event(
                    attacker_id,
                    self.tick,
                    event_kind,
                    note=note,
                    other_entity_id=target_slot,
                )
                self._orchestrate_combat_outcome(
                    attacker_id=str(attacker_id),
                    attacker_slot=int(attacker_slot),
                    target_kind="entity",
                    target_id=str(target_uid or ""),
                    target_slot=int(target_slot),
                    damage=float(damage),
                    killed=bool(killed),
                    target_hp_after=float(self.state.m_tensor[target_slot, M_HP]),
                    source=source,
                )

    def _attempt_task_attack(self, slot: int, target_kind: str, target_id: str) -> dict[str, Any]:
        target_kind_normalized = str(target_kind or "").strip().lower()
        if target_kind_normalized == "human":
            target_info = self._resolve_task_human_target(target_id)
        elif target_kind_normalized == "entity":
            target_info = self._resolve_task_entity_target(target_id)
        else:
            return {"ok": False, "reason": "target_invalid"}
        if target_info is None:
            return {"ok": False, "reason": "target_missing"}
        target_slot = int(target_info.get("slot", -1))
        if target_slot < 0:
            return {"ok": False, "reason": "target_invalid"}
        pre_h_hp = self.state.h_tensor[:, HP].clone()
        pre_m_hp = self.state.m_tensor[:, M_HP].clone()
        try:
            from systems.combat.intents import CombatIntent  # local import to avoid import-cycle churn
        except ImportError:  # pragma: no cover - package import fallback
            from at_the_beginning.systems.combat.intents import CombatIntent
        intent = CombatIntent(
            source="task",
            action="attack",
            attacker_kind="human",
            attacker_slot=int(slot),
            target_kind=target_kind_normalized,
            target_slot=target_slot,
            target_id=str(target_id),
        )
        combat_outcome = resolve_human_attack_intents(
            [intent],
            self.state.h_tensor,
            self.state.m_tensor,
            self.state.device,
            attack_damage=ATTACK_DAMAGE,
            attack_range=ATTACK_RANGE,
            stamina_cost=ATTACK_STAMINA_COST,
            walls=map_wall_boxes(self),
        )
        if combat_outcome.get("resolved", 0) <= 0:
            rejected = combat_outcome.get("rejections", [])
            return {"ok": False, "reason": rejected[0]["reason"] if rejected else "out_of_range"}
        self._record_combat_outcomes(combat_outcome, pre_h_hp, pre_m_hp)
        target_alive = True
        if target_kind_normalized == "human":
            target_alive = float(self.state.h_tensor[target_slot, HP]) > 0.0
        else:
            target_alive = float(self.state.m_tensor[target_slot, M_HP]) > 0.0
        return {
            "ok": True,
            "target_alive": bool(target_alive),
            "target_slot": int(target_slot),
        }

    def _attempt_manual_interact(
        self,
        slot: int,
        human_id: str,
        resident: dict[str, Any],
        target_kind: str,
        target_id: str,
        target_tag: str,
    ) -> dict[str, Any]:
        target_kind_normalized = str(target_kind or "").strip().lower()
        target_tag_normalized = str(target_tag or "").strip().lower()
        if target_kind_normalized == "entity":
            entity_ref = self._resolve_task_entity_target(target_id)
            if entity_ref is None:
                return {"ok": False, "reason": "target_missing"}
            entity_slot = int(entity_ref.get("slot", -1))
            if entity_slot < 0:
                return {"ok": False, "reason": "target_invalid"}
            if math.hypot(
                float(self.state.m_tensor[entity_slot, CX]) - float(self.state.h_tensor[slot, X]),
                float(self.state.m_tensor[entity_slot, CY]) - float(self.state.h_tensor[slot, Y]),
            ) > max(float(BUILD_RADIUS), float(ATTACK_RANGE) * 1.5):
                return {"ok": False, "reason": "out_of_range"}
            if target_tag_normalized == "container" or int(self.state.m_tensor[entity_slot, M_TYPE]) == int(M_STORAGE_CASE):
                resident.setdefault("status", {})["current_intent"] = "inspect_container"
                resident.setdefault("task_state", {})["last_manual_action"] = "interact_container"
                return {"ok": True, "changed": False, "reason": "container_selected"}
            resident.setdefault("status", {})["current_intent"] = "inspect_structure"
            resident.setdefault("task_state", {})["last_manual_action"] = "interact_entity"
            return {"ok": True, "changed": False, "reason": "entity_selected"}
        if target_kind_normalized == "human":
            target = self._resolve_task_human_target(target_id)
            if target is None:
                return {"ok": False, "reason": "target_missing"}
            resident.setdefault("status", {})["current_intent"] = "interact_human"
            resident.setdefault("task_state", {})["last_manual_action"] = "interact_human"
            return {"ok": True, "changed": False, "reason": "human_selected"}
        return {"ok": False, "reason": "target_invalid"}

    def _attempt_manual_work(
        self,
        slot: int,
        human_id: str,
        resident: dict[str, Any],
        target_id: str,
        target_tag: str,
    ) -> dict[str, Any]:
        entity_ref = self._resolve_task_entity_target(target_id)
        if entity_ref is None:
            return {"ok": False, "reason": "target_missing"}
        entity_slot = int(entity_ref.get("slot", -1))
        if entity_slot < 0:
            return {"ok": False, "reason": "target_invalid"}

        entity_type = int(self.state.m_tensor[entity_slot, M_TYPE])
        target_tag_normalized = str(target_tag or "").strip().lower()
        required_tool = ""
        output_kind = ""
        intent = ""
        last_action = ""
        mood_delta = 0.0
        stamina_delta = 0.0

        if target_tag_normalized == "tree" or entity_type in {int(M_FOREST)}:
            required_tool = "axe"
            output_kind = "wood_bundle"
            intent = "manual_lumber"
            last_action = "manually chopped wood"
            mood_delta = 0.08
            stamina_delta = -1.2
        elif target_tag_normalized == "stone" or entity_type in {int(M_MOUNTAIN), int(M_BARREN)}:
            required_tool = "hammer"
            output_kind = "stone_chunk"
            intent = "manual_mine"
            last_action = "manually mined stone"
            mood_delta = 0.06
            stamina_delta = -1.3
        else:
            return {"ok": False, "reason": "work_target_unsupported"}

        if math.hypot(
            float(self.state.m_tensor[entity_slot, CX]) - float(self.state.h_tensor[slot, X]),
            float(self.state.m_tensor[entity_slot, CY]) - float(self.state.h_tensor[slot, Y]),
        ) > max(float(BUILD_RADIUS), float(ATTACK_RANGE) * 1.5):
            return {"ok": False, "reason": "out_of_range"}

        personal_inventory = self._human_inventory_record(human_id)
        accessible_records = self._resident_accessible_storage_records(human_id, resident, slot)
        if not has_item(personal_inventory, required_tool, 1):
            resident.setdefault("status", {})["current_intent"] = f"obtain_{required_tool}"
            resident.setdefault("task_state", {})["last_manual_action"] = f"missing_{required_tool}"
            return {"ok": False, "reason": f"missing_{required_tool}"}
        if self.tick < int((resident.get("crafting_state", {}) or {}).get("next_action_tick", 0)):
            resident.setdefault("status", {})["current_intent"] = intent
            return {"ok": False, "reason": "cooldown"}
        added = inventory_add_item(
            personal_inventory,
            output_kind,
            1,
            metadata={
                "source": "manual_work",
                "target_entity_id": str(target_id),
                "target_tag": target_tag_normalized,
            },
        )
        if int(added.get("added", 0)) <= 0:
            resident.setdefault("status", {})["current_intent"] = f"store_{output_kind}"
            resident.setdefault("task_state", {})["last_manual_action"] = f"carry_full:{output_kind}"
            return {"ok": False, "reason": f"carry_full:{output_kind}"}

        self._commit_provision_action(
            resident,
            slot,
            personal_inventory,
            accessible_records,
            last_action=last_action,
            intent=intent,
            mood_delta=mood_delta,
            stamina_delta=stamina_delta,
            review=False,
        )
        self._refresh_resident_carry_manifest(resident, personal_inventory)
        return {"ok": True, "changed": True, "output_kind": output_kind}

    def _dispatch_manual_semantic_action(
        self,
        slot: int,
        control: dict[str, Any],
    ) -> bool:
        semantic_action = str(control.get("pending_semantic_action", "")).strip().lower()
        if semantic_action not in {"interact_target", "work_on_target"}:
            return False
        human_id = str(self._human_uid_by_slot[slot] or "").strip()
        if not human_id:
            return False
        resident = self.resident_store.get(human_id)
        if resident is None:
            return False
        target_kind = str(control.get("selected_target_kind", "")).strip().lower()
        target_id = str(control.get("selected_target_id", "")).strip()
        target_tag = str(control.get("selected_target_tag", "")).strip().lower()
        if not target_kind or not target_id:
            return False

        if semantic_action == "interact_target":
            result = self._attempt_manual_interact(slot, human_id, resident, target_kind, target_id, target_tag)
        else:
            if target_kind != "entity":
                return False
            result = self._attempt_manual_work(slot, human_id, resident, target_id, target_tag)
        if bool(result.get("ok", False)):
            self._orchestrate_manual_semantic_outcome(
                slot=int(slot),
                human_id=str(human_id),
                semantic_action=semantic_action,
                target_kind=target_kind,
                target_id=target_id,
                target_tag=target_tag,
                result=result,
            )
            self.resident_store.touch_resident(human_id)
        return bool(result.get("changed", False))

    def _apply_manual_control_human_actions(
        self,
        manual_control: dict[str, Any] | None,
    ) -> bool:
        if not isinstance(manual_control, dict):
            return False
        controlled_mask = manual_control.get("controlled_mask")
        if not isinstance(controlled_mask, torch.Tensor) or controlled_mask.shape[0] != self.state.h_tensor.shape[0]:
            return False

        changed = False
        controlled_slots = torch.where(controlled_mask & (self.state.h_tensor[:, TYPE] == AGENT_TYPE_HUMAN))[0]
        # instinct_move already applies the controlled displacement once.
        # This phase owns semantic actions/combat, not a second movement step.

        manual_by_slot = manual_control.get("by_slot", {})
        manual_attack_requests: list[dict[str, Any]] = []
        for slot in controlled_slots.tolist():
            control = dict(manual_by_slot.get(int(slot)) or {})
            changed = self._dispatch_manual_semantic_action(int(slot), control) or changed
            attack_request = self._manual_attack_target_for_slot(int(slot), manual_control)
            if attack_request is not None:
                attack_request["attacker_slot"] = int(slot)
                attack_request["attacker_id"] = str(self._human_uid_by_slot[int(slot)] or "")
                manual_attack_requests.append(attack_request)

        intents = collect_manual_attack_intents(manual_control, self.state.h_tensor, self.state.m_tensor)
        if manual_attack_requests or intents:
            print(
                f"[ManualAttack] requests={len(manual_attack_requests)} "
                f"intents={len(intents)} controlled_slots={controlled_slots.tolist()}"
            )
        resolved_attackers: set[int] = set()
        attack_rejections: dict[int, str] = {}
        if intents:
            pre_h_hp = self.state.h_tensor[:, HP].clone()
            pre_m_hp = self.state.m_tensor[:, M_HP].clone()
            combat_outcome = resolve_human_attack_intents(
                intents,
                self.state.h_tensor,
                self.state.m_tensor,
                self.state.device,
                attack_damage=ATTACK_DAMAGE,
                attack_range=ATTACK_RANGE,
                stamina_cost=ATTACK_STAMINA_COST,
                walls=map_wall_boxes(self),
            )
            print(
                f"[ManualAttack] resolved={int(combat_outcome.get('resolved', 0))} "
                f"human_hits={int(combat_outcome.get('human_hits', 0))} "
                f"entity_hits={int(combat_outcome.get('entity_hits', 0))}"
            )
            resolved_attackers = {
                int(outcome.get("attacker_slot", -1))
                for outcome in combat_outcome.get("outcomes", [])
                if int(outcome.get("attacker_slot", -1)) >= 0
            }
            attack_rejections.update({int(item["attacker_slot"]): item["reason"]
                                      for item in combat_outcome.get("rejections", [])})
            if combat_outcome.get("resolved", 0) > 0:
                self._record_combat_outcomes(combat_outcome, pre_h_hp, pre_m_hp)
                changed = True
        for request in manual_attack_requests:
            attacker_slot = int(request.get("attacker_slot", -1))
            if attacker_slot < 0 or attacker_slot in resolved_attackers:
                if attacker_slot >= 0:
                    self._clear_manual_attack_pending_for_slot(attacker_slot)
                continue
            attacker_id = str(request.get("attacker_id", "")).strip()
            if not attacker_id:
                continue
            distance = float(request.get("distance", 0.0))
            event_type = "attack_no_hit"
            event_reason = "target_invalid"
            if float(self.state.h_tensor[attacker_slot, H_STAMINA]) < float(ATTACK_STAMINA_COST):
                event_type = "attack_no_stamina"
                event_reason = "stamina"
            elif distance > float(ATTACK_RANGE):
                event_type = "attack_out_of_range"
                event_reason = "range"
            elif attack_rejections.get(attacker_slot) == "blocked":
                event_type = "attack_blocked"
                event_reason = "blocked"
            attack_rejections[attacker_slot] = event_reason
            self._queue_event(
                event_type,
                str(attacker_id),
                int(attacker_slot),
                attacker_id=str(attacker_id),
                target_kind=str(request.get("target_kind", "")),
                target_id=str(request.get("target_id", "")),
                target_name=str(request.get("name", request.get("target_id", ""))),
                distance=round(distance, 1),
                attack_range=round(float(ATTACK_RANGE), 1),
                reason=event_reason,
            )
            self._clear_manual_attack_pending_for_slot(attacker_slot)
        for session in self.player_control.sessions_by_controller.values():
            event_id = session.pop("tick_attack_event_id", None)
            if event_id is None:
                continue
            slot = int(session["slot"])
            applied = session["target_kind"] == "human" and slot in resolved_attackers
            receipt = session["event_receipts"][event_id]["result"]
            receipt.update(status="applied" if applied else "rejected", resolved_tick=self.tick,
                           reason="hit" if applied else attack_rejections.get(slot, "target_invalid"))
            if session["target_kind"] == "human":
                self._clear_manual_attack_pending_for_slot(slot)
        return changed

    def _consume_task_resource(
        self,
        resource_kind: str,
        entity_id: int,
        *,
        quantity: int = 1,
        uid: str | None = None,
    ) -> int:
        if int(entity_id) < 0 or int(entity_id) >= self.state.m_tensor.shape[0]:
            return 0
        if uid and self._entity_uid_by_slot[int(entity_id)] != uid:      # the caller's source is gone: this row now holds another entity
            return 0
        resource_spec = self._task_resource_type_ids(resource_kind)
        if resource_spec is None:
            return 0
        _, resource_col = resource_spec
        unit_cost = float(EAT_RESOURCE_COST if str(resource_kind).strip() == "food" else DRINK_RESOURCE_COST)
        available = float(self.state.m_tensor[int(entity_id), resource_col])
        if available < unit_cost:
            return 0
        consumed = min(max(int(quantity), 1), int(available // unit_cost))
        if consumed <= 0:
            return 0
        self.state.m_tensor[int(entity_id), resource_col] = max(0.0, available - unit_cost * consumed)
        return consumed

    @staticmethod
    def _crafting_source_type_ids(item_kind: str) -> set[int]:
        return {
            "wood_bundle": {M_FOREST, M_GRASS, M_FARM},
            "wood_log": {M_FOREST, M_GRASS},
            "fiber_bundle": {M_FOREST, M_GRASS, M_BEACH, M_FARM},
            "stone_chunk": {M_MOUNTAIN, M_BARREN, M_BEACH},
            "herb_bundle": {M_FOREST, M_GRASS, M_FARM},
        }.get(str(item_kind).strip(), set())

    def _move_human_toward_point(self, slot: int, tx: float, ty: float, magnitude: float) -> None:
        if get_map_contract(self._map_name) is not None and move_task_actor(self, slot, tx, ty, magnitude):
            return  # authored map: one bounded, sliding mover (roster residents are moved by the roster driver)
        px = float(self.state.h_tensor[slot, X])
        py = float(self.state.h_tensor[slot, Y])
        dx = float(tx) - px
        dy = float(ty) - py
        norm = max(math.sqrt(dx * dx + dy * dy), 1e-6)
        x0, y0, x1, y1 = _world_limits()
        self.state.h_tensor[slot, X] = max(x0, min(x1, px + (dx / norm) * float(magnitude)))
        self.state.h_tensor[slot, Y] = max(y0, min(y1, py + (dy / norm) * float(magnitude)))

    @staticmethod
    def _first_item_id_by_kind(record: dict, item_kind: str) -> str:
        for item in list(record.get("items", [])):
            if str(item.get("kind", "")) == str(item_kind) and int(item.get("quantity", 0)) > 0:
                return str(item.get("id", ""))
        return ""

    @staticmethod
    def _recipe_id_for_output_kind(item_kind: str) -> str:
        needle = str(item_kind or "").strip()
        if not needle:
            return ""
        for recipe_id in crafting_recipe_ids():
            if crafting_output_kind(recipe_id) == needle:
                return recipe_id
        return ""

    def _ensure_room_for_tool(
        self,
        record: dict,
        tool_kind: str,
        accessible_records: list[dict[str, Any]] | None = None,
    ) -> bool:
        if can_add_item(record, tool_kind, 1):
            return True
        for item in list(record.get("items", [])):
            item_kind = str(item.get("kind", "")).strip()
            if not item_kind or item_kind in {"coin", str(tool_kind).strip()}:
                continue
            for entry in list(accessible_records or []):
                target_record = entry.get("inventory")
                if not isinstance(target_record, dict):
                    continue
                moved = inventory_transfer_item(
                    record,
                    target_record,
                    item_id=str(item.get("id", "")),
                    quantity=int(item.get("quantity", 1)),
                )
                if int(moved.get("moved", 0)) > 0 and can_add_item(record, tool_kind, 1):
                    return True
        return can_add_item(record, tool_kind, 1)

    def _equip_first_matching_tool(self, record: dict, item_kind: str) -> bool:
        item_id = self._first_item_id_by_kind(record, item_kind)
        if not item_id:
            return False
        return equip_main_hand_item(record, item_id) is not None

    def _commit_provision_action(
        self,
        resident: dict[str, Any],
        slot: int,
        personal_inventory: dict,
        accessible_records: list[dict[str, Any]],
        *,
        last_action: str,
        intent: str,
        mood_delta: float = 0.0,
        stamina_delta: float = 0.0,
        hunger_delta: float = 0.0,
        thirst_delta: float = 0.0,
        threat_delta: float = 0.0,
        shelter_value: float | None = None,
        review: bool = True,
    ) -> None:
        crafting_state = resident.setdefault("crafting_state", {})
        tick = int(self.tick)
        crafting_state["last_action_tick"] = tick
        crafting_state["next_action_tick"] = tick + BASELINE_PROVISION_ACTION_COOLDOWN_TICKS
        crafting_state["last_action"] = str(last_action)
        resident.setdefault("task_state", {})["last_task_action"] = str(last_action)
        if mood_delta:
            self.state.h_tensor[slot, MOOD] = max(
                0.0,
                min(100.0, float(self.state.h_tensor[slot, MOOD]) + float(mood_delta)),
            )
        if stamina_delta:
            self.state.h_tensor[slot, H_STAMINA] = max(
                0.0,
                min(100.0, float(self.state.h_tensor[slot, H_STAMINA]) + float(stamina_delta)),
            )
        if hunger_delta:
            self.state.h_tensor[slot, HUNGER] = max(
                0.0,
                min(100.0, float(self.state.h_tensor[slot, HUNGER]) + float(hunger_delta)),
            )
        if thirst_delta:
            self.state.h_tensor[slot, THIRST] = max(
                0.0,
                min(100.0, float(self.state.h_tensor[slot, THIRST]) + float(thirst_delta)),
            )
        if threat_delta:
            self.state.h_tensor[slot, THREAT] = max(
                0.0,
                min(100.0, float(self.state.h_tensor[slot, THREAT]) + float(threat_delta)),
            )
        if shelter_value is not None:
            self.state.h_tensor[slot, H_SHELTER] = max(0.0, min(1.0, float(shelter_value)))
        if review:
            review_resident_baseline_provisioning(
                resident,
                tick,
                personal_inventory=personal_inventory,
                accessible_inventories=accessible_records,
                allow_auto=True,
                force=True,
            )
        resident.setdefault("status", {})["current_intent"] = str(intent)

    def _available_ingredient_quantity(
        self,
        item_kind: str,
        personal_inventory: dict,
        accessible_records: list[dict[str, Any]],
        material_cache: dict[str, Any],
    ) -> int:
        total = total_quantity(personal_inventory, item_kind)
        for entry in accessible_records:
            record = entry.get("inventory")
            if not isinstance(record, dict):
                continue
            total += total_quantity(record, item_kind)
        return total

    def _consume_ingredient_quantity(
        self,
        item_kind: str,
        quantity: int,
        personal_inventory: dict,
        accessible_records: list[dict[str, Any]],
        material_cache: dict[str, Any],
    ) -> bool:
        remaining = max(int(quantity), 0)
        if remaining <= 0:
            return True

        personal_available = total_quantity(personal_inventory, item_kind)
        if personal_available > 0:
            step = min(personal_available, remaining)
            removed = inventory_remove_item(personal_inventory, item_kind=item_kind, quantity=step)
            remaining -= int(removed.get("removed", 0))

        for entry in accessible_records:
            if remaining <= 0:
                break
            record = entry.get("inventory")
            if not isinstance(record, dict):
                continue
            available = total_quantity(record, item_kind)
            if available <= 0:
                continue
            step = min(available, remaining)
            removed = inventory_remove_item(record, item_kind=item_kind, quantity=step)
            remaining -= int(removed.get("removed", 0))
        return remaining <= 0

    @staticmethod
    def _first_accessible_inventory(accessible_records: list[dict[str, Any]]) -> dict[str, Any] | None:
        for entry in list(accessible_records or []):
            record = entry.get("inventory")
            if isinstance(record, dict):
                return record
        return None

    def _add_item_to_person_or_house(
        self,
        personal_inventory: dict,
        accessible_records: list[dict[str, Any]],
        item_kind: str,
        quantity: int,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        added = inventory_add_item(personal_inventory, item_kind, quantity, metadata=metadata)
        moved = int(added.get("added", 0))
        remaining = max(int(quantity) - moved, 0)
        if remaining <= 0:
            return moved
        house_inventory = self._first_accessible_inventory(accessible_records)
        if not isinstance(house_inventory, dict):
            return moved
        added_house = inventory_add_item(house_inventory, item_kind, remaining, metadata=metadata)
        return moved + int(added_house.get("added", 0))

    def _withdraw_baseline_tool(
        self,
        personal_inventory: dict,
        accessible_records: list[dict[str, Any]],
        need: dict[str, Any],
    ) -> bool:
        tool_kind = str(need.get("tool_kind", "")).strip()
        if not tool_kind or not self._ensure_room_for_tool(personal_inventory, tool_kind, accessible_records):
            return False
        for entry in accessible_records:
            record = entry.get("inventory")
            if not isinstance(record, dict) or not has_item(record, tool_kind, 1):
                continue
            moved = inventory_transfer_item(
                record,
                personal_inventory,
                item_kind=tool_kind,
                quantity=1,
            )
            if moved.get("ok"):
                self._equip_first_matching_tool(personal_inventory, tool_kind)
                return True
        return False

    def _craft_baseline_tool(
        self,
        resident: dict[str, Any],
        personal_inventory: dict,
        accessible_records: list[dict[str, Any]],
        need: dict[str, Any],
    ) -> bool:
        recipe_id = str(need.get("recipe_id", "")).strip()
        output_kind = str(need.get("tool_kind", "")).strip()
        if not recipe_id or not output_kind:
            return False
        if not self._ensure_room_for_tool(personal_inventory, output_kind, accessible_records):
            return False

        requirements = list(crafting_recipe_ingredients(recipe_id))
        for entry in requirements:
            item_kind = str(entry.get("item_kind", "")).strip()
            quantity = max(int(entry.get("quantity", 1)), 1)
            if self._available_ingredient_quantity(item_kind, personal_inventory, accessible_records, {}) < quantity:
                return False

        for entry in requirements:
            item_kind = str(entry.get("item_kind", "")).strip()
            quantity = max(int(entry.get("quantity", 1)), 1)
            if not self._consume_ingredient_quantity(
                item_kind,
                quantity,
                personal_inventory,
                accessible_records,
                {},
            ):
                return False

        added = inventory_add_item(
            personal_inventory,
            output_kind,
            max(int(crafting_recipe_def(recipe_id).get("output_quantity", 1)), 1),
            metadata={"crafted_from": recipe_id, "source": "occupation_baseline"},
        )
        if not added.get("ok"):
            return False
        self._equip_first_matching_tool(personal_inventory, output_kind)
        return True

    def _craft_cached_component(
        self,
        resident: dict[str, Any],
        personal_inventory: dict,
        accessible_records: list[dict[str, Any]],
        *,
        item_kind: str,
        recipe_id: str,
    ) -> bool:
        recipe_def = crafting_recipe_def(recipe_id)
        output_kind = str(recipe_def.get("output_kind", "")).strip()
        if not output_kind or output_kind != str(item_kind).strip():
            return False
        requirements = list(crafting_recipe_ingredients(recipe_id))
        for entry in requirements:
            required_kind = str(entry.get("item_kind", "")).strip()
            quantity = max(int(entry.get("quantity", 1)), 1)
            if self._available_ingredient_quantity(
                required_kind,
                personal_inventory,
                accessible_records,
                {},
            ) < quantity:
                return False

        for entry in requirements:
            required_kind = str(entry.get("item_kind", "")).strip()
            quantity = max(int(entry.get("quantity", 1)), 1)
            if not self._consume_ingredient_quantity(
                required_kind,
                quantity,
                personal_inventory,
                accessible_records,
                {},
            ):
                return False

        output_quantity = max(int(recipe_def.get("output_quantity", 1)), 1)
        added = self._add_item_to_person_or_house(
            personal_inventory,
            accessible_records,
            output_kind,
            output_quantity,
            metadata={"crafted_from": recipe_id, "source": "occupation_component"},
        )
        return added >= output_quantity

    def _progress_toward_item_kind(
        self,
        slot: int,
        resident: dict[str, Any],
        personal_inventory: dict,
        accessible_records: list[dict[str, Any]],
        *,
        item_kind: str,
        required_quantity: int,
        depth: int = 0,
    ) -> bool:
        needle = str(item_kind or "").strip()
        target_quantity = max(int(required_quantity), 1)
        if not needle:
            return False
        if self._available_ingredient_quantity(
            needle,
            personal_inventory,
            accessible_records,
            {},
        ) >= target_quantity:
            return False
        if depth >= 4:
            return False

        source_types = self._crafting_source_type_ids(needle)
        tick = int(self.tick)
        px = float(self.state.h_tensor[slot, X])
        py = float(self.state.h_tensor[slot, Y])
        crafting_state = resident.setdefault("crafting_state", {})

        if source_types:
            target_eid = nearest_geo_entity(
                self.state.m_tensor,
                px,
                py,
                type_filter=source_types,
                radius=220.0,
            )
            if target_eid == -1:
                resident.setdefault("status", {})["current_intent"] = f"search_{needle}"
                crafting_state["last_action"] = f"searching_for {needle}"
                return False
            tx = float(self.state.m_tensor[target_eid, CX])
            ty = float(self.state.m_tensor[target_eid, CY])
            distance = math.hypot(tx - px, ty - py)
            if distance > BASELINE_GATHER_RADIUS:
                self._move_human_toward_point(slot, tx, ty, BASELINE_GATHER_MOVE_STEP)
                resident.setdefault("status", {})["current_intent"] = f"gather_{needle}"
                crafting_state["last_action"] = f"moving_to_gather {needle}"
                return True
            if tick < int(crafting_state.get("next_action_tick", 0)):
                resident.setdefault("status", {})["current_intent"] = f"gather_{needle}"
                return False
            added = self._add_item_to_person_or_house(
                personal_inventory,
                accessible_records,
                needle,
                1,
                metadata={"source": "gathered_material"},
            )
            if added <= 0:
                resident.setdefault("status", {})["current_intent"] = f"carry_{needle}"
                crafting_state["last_action"] = f"carry_full_for {needle}"
                return False
            self._commit_provision_action(
                resident,
                slot,
                personal_inventory,
                accessible_records,
                last_action=f"gathered {needle}",
                intent=f"gather_{needle}",
                mood_delta=0.1,
                stamina_delta=-1.0,
            )
            return True

        recipe_id = self._recipe_id_for_output_kind(needle)
        if not recipe_id:
            resident.setdefault("status", {})["current_intent"] = f"acquire_{needle}"
            crafting_state["last_action"] = f"blocked_on {needle}"
            return False

        for entry in crafting_recipe_ingredients(recipe_id):
            required_kind = str(entry.get("item_kind", "")).strip()
            quantity = max(int(entry.get("quantity", 1)), 1)
            if self._available_ingredient_quantity(
                required_kind,
                personal_inventory,
                accessible_records,
                {},
            ) >= quantity:
                continue
            if self._progress_toward_item_kind(
                slot,
                resident,
                personal_inventory,
                accessible_records,
                item_kind=required_kind,
                required_quantity=quantity,
                depth=depth + 1,
            ):
                return True
            if self._available_ingredient_quantity(
                required_kind,
                personal_inventory,
                accessible_records,
                {},
            ) < quantity:
                return False

        if tick < int(crafting_state.get("next_action_tick", 0)):
            resident.setdefault("status", {})["current_intent"] = f"craft_{needle}"
            return False
        if not self._craft_cached_component(
            resident,
            personal_inventory,
            accessible_records,
            item_kind=needle,
            recipe_id=recipe_id,
        ):
            return False
        self._commit_provision_action(
            resident,
            slot,
            personal_inventory,
            accessible_records,
            last_action=f"crafted {needle}",
            intent=f"craft_{needle}",
            mood_delta=0.1,
            stamina_delta=-1.2,
        )
        return True

    def _execute_resident_task_step(
        self,
        slot: int,
        human_id: str,
        resident: dict[str, Any],
        personal_inventory: dict,
        accessible_records: list[dict[str, Any]],
    ) -> bool:
        px = float(self.state.h_tensor[slot, X])
        py = float(self.state.h_tensor[slot, Y])
        bridge = TaskWorldBridge(
            gather_radius=BASELINE_GATHER_RADIUS,
            move_step=BASELINE_GATHER_MOVE_STEP,
            map_width=MAP_WIDTH,
            map_height=MAP_HEIGHT,
            resolve_place_target=lambda place_tag, x, y, radius=240.0: self._resolve_task_place_target(
                x,
                y,
                place_tag,
                radius=radius,
            ),
            resolve_resource_target=lambda resource_kind, x, y, radius=220.0: self._resolve_task_resource_target(
                x,
                y,
                resource_kind,
                radius=radius,
            ),
            resolve_safe_target=lambda x, y, radius=240.0: self._resolve_task_safe_target(
                x,
                y,
                radius=radius,
            ),
            resolve_human_target=lambda target_human_id: self._resolve_task_human_target(target_human_id),
            resolve_entity_target=lambda target_entity_id: self._resolve_task_entity_target(target_entity_id),
            resolve_help_target=lambda x, y, radius=72.0: self._resolve_nearby_help_target(slot, radius=radius),
            resolve_support_target=lambda x, y, radius=96.0: self._resolve_support_target(slot, radius=radius),
            move_toward_point=lambda tx, ty, magnitude: self._move_human_toward_point(slot, tx, ty, magnitude),
            commit_action=lambda **kwargs: self._commit_provision_action(
                resident,
                slot,
                personal_inventory,
                accessible_records,
                **kwargs,
            ),
            withdraw_tool=lambda tool_kind, need: self._withdraw_baseline_tool(
                personal_inventory,
                accessible_records,
                need or {"tool_kind": tool_kind},
            ),
            available_ingredient_quantity=lambda item_kind, material_cache: self._available_ingredient_quantity(
                item_kind,
                personal_inventory,
                accessible_records,
                material_cache,
            ),
            progress_toward_item_kind=lambda item_kind, required_quantity: self._progress_toward_item_kind(
                slot,
                resident,
                personal_inventory,
                accessible_records,
                item_kind=item_kind,
                required_quantity=required_quantity,
            ),
            craft_tool=lambda tool_kind, need: self._craft_baseline_tool(
                resident,
                personal_inventory,
                accessible_records,
                need or {"tool_kind": tool_kind, "recipe_id": self._recipe_id_for_output_kind(tool_kind)},
            ),
            nearest_storage_case=lambda x, y, radius=0.0: self._nearest_accessible_storage_record(
                accessible_records,
                x,
                y,
                radius=radius,
            ),
            consume_resource_amount=lambda resource_kind, entity_id, quantity=1, **extra: self._consume_task_resource(
                resource_kind,
                entity_id,
                quantity=quantity,
                **extra,
            ),
            mate_with_target_action=lambda target_human_id: self._attempt_task_mating(slot, target_human_id),
            attack_target_action=lambda target_kind, target_id: self._attempt_task_attack(slot, target_kind, target_id),
            heal_target_action=lambda target_human_id, item_kind="bandage": self._attempt_task_heal(
                slot,
                personal_inventory,
                accessible_records,
                target_human_id,
                item_kind,
            ),
            deliver_item_action=lambda target_human_id, item_kind, quantity=1: self._attempt_task_delivery(
                slot,
                personal_inventory,
                target_human_id,
                item_kind,
                quantity,
            ),
            steal_from_container_action=lambda container_id, item_kind="", quantity=1: self._attempt_task_steal(
                personal_inventory,
                container_id,
                item_kind or "coin",
                quantity,
            ),
            queue_social_signal_action=lambda target_human_id, signal: self._queue_resident_task_signal(
                target_human_id,
                "social",
                signal,
            ),
            queue_combat_signal_action=lambda target_human_id, signal: self._queue_resident_task_signal(
                target_human_id,
                "combat",
                signal,
            ),
            designate_construction_project_action=lambda project_id: self._designate_resident_construction_project(
                slot,
                human_id,
                resident,
                project_id,
            ),
            advance_construction_project_action=lambda project_id: self._advance_resident_construction_project(
                slot,
                human_id,
                resident,
                project_id,
            ),
        )
        context = build_task_execution_context(
            resident,
            tick=int(self.tick),
            px=px,
            py=py,
            personal_inventory=personal_inventory,
            accessible_records=accessible_records,
            bridge=bridge,
        )
        task_state_before = dict((resident.get("task_state", {}) or {}).get("last_completed_task", {}) or {})
        changed = execute_active_task_step(context)
        task_state_after = dict((resident.get("task_state", {}) or {}).get("last_completed_task", {}) or {})
        completed_task_id_before = str(task_state_before.get("id", "")).strip()
        completed_task_id_after = str(task_state_after.get("id", "")).strip()
        if completed_task_id_after and completed_task_id_after != completed_task_id_before:
            self._orchestrate_task_completion(
                human_id=str(human_id),
                completed_task=task_state_after,
            )
        self._refresh_resident_carry_manifest(resident, personal_inventory)
        return changed

    def _execute_baseline_provisioning_step(
        self,
        slot: int,
        human_id: str,
        resident: dict[str, Any],
        personal_inventory: dict,
        accessible_records: list[dict[str, Any]],
    ) -> bool:
        crafting_state = resident.get("crafting_state", {}) or {}
        if not bool(crafting_state.get("baseline_ready", False)):
            return False
        if not bool(crafting_state.get("auto_allowed", False)):
            return False

        active_need = crafting_state.get("active_need")
        if not isinstance(active_need, dict):
            return False

        tick = int(self.tick)
        action_changed = False
        h_tensor = self.state.h_tensor
        status = str(active_need.get("status", "")).strip()
        tool_kind = str(active_need.get("tool_kind", "")).strip()

        if status == "withdraw" and tick >= int(crafting_state.get("next_action_tick", 0)):
            if self._withdraw_baseline_tool(personal_inventory, accessible_records, active_need):
                self._commit_provision_action(
                    resident,
                    slot,
                    personal_inventory,
                    accessible_records,
                    last_action=f"withdrew {tool_kind}",
                    intent=f"equip_{tool_kind}",
                    mood_delta=0.2,
                )
                return True
            return False

        if status == "gather_then_craft":
            missing_ingredients = list(active_need.get("missing_ingredients", []))
            material_cache = crafting_state.setdefault("material_cache", {})
            for target in missing_ingredients:
                ingredient_kind = str(target.get("item_kind", "")).strip()
                required_quantity = max(int(target.get("required_quantity", 1)), 1)
                if self._available_ingredient_quantity(
                    ingredient_kind,
                    personal_inventory,
                    accessible_records,
                    material_cache,
                ) >= required_quantity:
                    continue
                if self._progress_toward_item_kind(
                    slot,
                    resident,
                    personal_inventory,
                    accessible_records,
                    item_kind=ingredient_kind,
                    required_quantity=required_quantity,
                ):
                    return True
                resident.setdefault("status", {})["current_intent"] = f"prepare_{tool_kind}"
                break

            active_need = (resident.get("crafting_state", {}) or {}).get("active_need") or active_need
            status = str(active_need.get("status", "")).strip()

        if status == "craft" and tick >= int(crafting_state.get("next_action_tick", 0)):
            if self._craft_baseline_tool(resident, personal_inventory, accessible_records, active_need):
                self._commit_provision_action(
                    resident,
                    slot,
                    personal_inventory,
                    accessible_records,
                    last_action=f"crafted {tool_kind}",
                    intent=f"use_{tool_kind}",
                    mood_delta=0.2,
                    stamina_delta=-2.0,
                )
                action_changed = True

        return action_changed

    def _inventory_focus_payload(self, controller_id: str = "local_player") -> dict[str, Any] | None:
        sessions = self.player_control.status_snapshot().get("sessions", [])
        for session in sessions:
            if str(session.get("controller_id", "")) != str(controller_id):
                continue
            if str(session.get("target_kind", "")) != "human":
                return None
            owner_id = str(session.get("target_id", ""))
            inventory = get_owner_inventory(self.inventory_state, "human", owner_id)
            if inventory is None:
                return None
            focus: dict[str, Any] = {
                "owner_kind": "human",
                "owner_id": owner_id,
                "owner_name": str(session.get("target_name", owner_id)),
                "inventory": inventory_prompt_payload(inventory),
                "summary": summarize_inventory(inventory),
            }
            selected_kind = str(session.get("selected_target_kind") or "")
            selected_id = str(session.get("selected_target_id") or "")
            pending_action = str(session.get("pending_action") or "")
            pending_semantic_action = str(session.get("pending_semantic_action") or "")
            if (
                pending_action == "interact"
                or pending_semantic_action == "interact_target"
            ) and selected_kind == "entity" and selected_id:
                container = get_container_inventory(self.inventory_state, selected_id)
                if container is not None:
                    focus["selected_container"] = container_prompt_payload(container)
            return focus
        return None

    def _talk_feed_payload(self, controller_id: str = "local_player") -> dict[str, Any]:
        return {
            "recent_lines": self.talk_agent.recent_feed_for_controller(controller_id),
            "recent_tts_requests": [
                dict(item)
                for item in self.talk_agent.recent_tts_requests
                if str(item.get("metadata", {}).get("controller_id", controller_id)) == str(controller_id)
            ][-6:],
        }

    # ------------------------------------------------------------------
    # Dynamic instinct loading
    # ------------------------------------------------------------------

    def load_dynamic_instinct(self, name: str, bit: int, priority: int = 80) -> bool:
        module_path = DYNAMIC_DIR / f"{name}.py"
        if not module_path.exists():
            print(f"[Engine] Dynamic instinct not found: {module_path}")
            return False
        try:
            spec = importlib.util.spec_from_file_location(name, module_path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"Could not create import spec for {module_path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            fn = getattr(module, name)
        except Exception as e:
            print(f"[Engine] Failed to load {name}: {e}")
            return False
        iat.ACQUIRED_INSTINCTS[bit] = fn
        self.register(fn, priority=priority)
        self.execution_agent.register_instinct_bit(name, bit)
        print(f"[Engine] Loaded: {name} (bit={bit}, priority={priority})")
        return True

    # ------------------------------------------------------------------
    # Shared kwargs
    # ------------------------------------------------------------------

    def _build_kwargs(self) -> dict:
        return {
            "h_tensor":         self.state.h_tensor,
            "m_tensor":         self.state.m_tensor,
            "device":           self.state.device,
            "pop_count_ref":    self._pop_count,
            "entity_count_ref": self._entity_count_ref,
            "h_tensor_ref":     self.state.h_tensor,
            "engine":           self,
            "player_control_runtime": self.player_control,
        }

    # ------------------------------------------------------------------
    # ID helpers
    # ------------------------------------------------------------------

    def _make_human_id(self) -> str:
        uid = f"h_{self._next_human_uid:06d}"
        self._next_human_uid += 1
        return uid

    def _make_entity_id(self) -> str:
        uid = f"e_{self._next_entity_uid:06d}"
        self._next_entity_uid += 1
        return uid

    def _queue_event(self, event_type: str, obj_id: str, slot: int, **extra: Any) -> None:
        event = {
            "seq":  self._event_seq,
            "tick": self.tick,
            "type": event_type,
            "id":   obj_id,
            "slot": slot,
        }
        event.update(extra)
        self._event_seq += 1
        self._pending_events.append(event)

    # ------------------------------------------------------------------
    # Mask helpers
    # ------------------------------------------------------------------

    def _current_masks(self) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        h_mask = self.state.h_tensor[:, TYPE] == AGENT_TYPE_HUMAN
        m = self.state.m_tensor
        entity_mask = m[:, M_TYPE] > 0
        a_mask = _human_query.animal_mask(m[:, M_TYPE], ANIMAL_TYPES)
        return h_mask, a_mask, entity_mask

    def _assign_missing_ids(self, h_mask: torch.Tensor, entity_mask: torch.Tensor) -> None:
        for slot in torch.where(h_mask)[0].tolist():
            if self._human_uid_by_slot[slot] is None:
                human_id = self._make_human_id()
                self._human_uid_by_slot[slot] = human_id
                preferred_name = self._pending_human_names_by_slot.pop(slot, None)
                self.resident_store.ensure_resident(
                    human_id,
                    slot,
                    self.state.h_tensor,
                    self.tick,
                    preferred_name=preferred_name,
                )
        for slot in torch.where(entity_mask)[0].tolist():
            if self._entity_uid_by_slot[slot] is None:
                self._entity_uid_by_slot[slot] = self._make_entity_id()

    def _sync_slot_ids_and_events(
        self,
        h_mask: torch.Tensor,
        a_mask: torch.Tensor,
        entity_mask: torch.Tensor,
        *,
        manual_control: dict[str, Any] | None = None,
    ) -> None:
        self._assign_missing_ids(h_mask, entity_mask)

        # Human births / deaths
        new_humans = torch.where(~self._prev_h_mask & h_mask)[0].tolist()
        dead_humans = torch.where(self._prev_h_mask & ~h_mask)[0].tolist()

        for slot in new_humans:
            uid = self._human_uid_by_slot[slot]
            if uid is not None:
                self._queue_event("human_born", uid, slot)
                link = self._pending_birth_links_by_slot.pop(slot, None)
                if link:
                    parent_ids = [str(parent_id) for parent_id in link.get("parent_ids", []) if str(parent_id).strip()]
                    for parent_id in parent_ids:
                        self.resident_store.update_relationship(parent_id, uid, "child", 0.25, self.tick)
                        self.resident_store.update_relationship(uid, parent_id, "parent", 0.35, self.tick)
                        self.resident_store.record_event(
                            parent_id,
                            self.tick,
                            "child_birth",
                            note=f"new child {uid}",
                            other_human_id=uid,
                        )
                        self.resident_store.record_event(
                            uid,
                            self.tick,
                            "born_to_parent",
                            note=f"born to parent {parent_id}",
                            other_human_id=parent_id,
                        )
                    if len(parent_ids) >= 2:
                        first_parent, second_parent = parent_ids[:2]
                        self.resident_store.update_relationship(first_parent, second_parent, "mate", 0.08, self.tick)
                        self.resident_store.update_relationship(second_parent, first_parent, "mate", 0.08, self.tick)

        for slot in dead_humans:
            uid = self._human_uid_by_slot[slot]
            if uid is not None:
                deceased = self.resident_store.get(uid)
                death_snapshot = deceased.get("snapshot", {}) if deceased else {}
                death_x = death_snapshot.get("x")
                death_y = death_snapshot.get("y")
                if death_x is not None and death_y is not None:
                    for witness_slot in torch.where(h_mask)[0].tolist():
                        witness_uid = self._human_uid_by_slot[witness_slot]
                        if not witness_uid or witness_uid == uid:
                            continue
                        dx = float(self.state.h_tensor[witness_slot, X]) - float(death_x)
                        dy = float(self.state.h_tensor[witness_slot, Y]) - float(death_y)
                        distance = (dx * dx + dy * dy) ** 0.5
                        if distance > 80.0:
                            continue
                        self.resident_store.record_event(
                            witness_uid,
                            self.tick,
                            "witnessed_death",
                            note=f"witnessed death of {uid}",
                            other_human_id=uid,
                            pos=(float(death_x), float(death_y)),
                        )
                        self.resident_store.remember_threat(
                            witness_uid,
                            "death_site",
                            (float(death_x), float(death_y)),
                            self.tick,
                            distance,
                        )
                self._pending_despawns.append(uid)
                self._queue_event("human_died", uid, slot)
                self.resident_store.mark_dead(uid, self.tick)
            self._human_uid_by_slot[slot] = None

        # Animal births / despawns are frame-relevant. Non-animal entity
        # changes are handled by map deltas.
        new_animals = torch.where(~self._prev_a_mask & a_mask)[0].tolist()
        dead_animals = torch.where(self._prev_a_mask & ~a_mask)[0].tolist()

        for slot in new_animals:
            uid = self._entity_uid_by_slot[slot]
            if uid is not None:
                self._queue_event("animal_spawned", uid, slot, type_id=int(self.state.m_tensor[slot, M_TYPE]))

        for slot in dead_animals:
            uid = self._entity_uid_by_slot[slot]
            if uid is not None:
                self._pending_despawns.append(uid)
                self._queue_event("animal_despawned", uid, slot)

        # Clear entity IDs only when the slot truly became empty.
        removed_entities = torch.where(self._prev_entity_mask & ~entity_mask)[0].tolist()
        for slot in removed_entities:
            self._entity_uid_by_slot[slot] = None

        self._prev_h_mask = h_mask.clone()
        self._prev_a_mask = a_mask.clone()
        self._prev_entity_mask = entity_mask.clone()
        self.resident_store.sync_live_population(
            self._human_uid_by_slot,
            h_mask,
            self.state.h_tensor,
            self.tick,
        )
        self._sync_inventory_defaults(h_mask)
        self._sync_occupation_provisioning(h_mask, manual_control=manual_control)
        if self._runtime_profile != "render_test":
            self.flush_memory_graph_queue(save=(self.tick % 20 == 0), force=False, background=True)

    # ------------------------------------------------------------------
    # Render-state helpers
    # ------------------------------------------------------------------

    def _set_actor_render_action(self, actor_id: str | None, action: str, *, duration_ticks: int = 4) -> None:
        normalized_id = str(actor_id or "").strip()
        normalized_action = str(action or "").strip().lower()
        if not normalized_id or not normalized_action:
            return
        self._actor_render_actions[normalized_id] = {
            "action": normalized_action,
            "started_tick": int(self.tick),
            "until_tick": int(self.tick) + max(int(duration_ticks), 1),
        }

    def _current_actor_render_action_payload(self, actor_id: str | None) -> dict[str, Any]:
        normalized_id = str(actor_id or "").strip()
        if not normalized_id:
            return {}
        payload = self._actor_render_actions.get(normalized_id)
        if not isinstance(payload, dict):
            return {}
        if int(payload.get("until_tick", -1)) < int(self.tick):
            self._actor_render_actions.pop(normalized_id, None)
            return {}
        return payload

    def _current_actor_render_action(self, actor_id: str | None) -> str:
        payload = self._current_actor_render_action_payload(actor_id)
        if not payload:
            return ""
        return str(payload.get("action", "")).strip().lower()

    def _refresh_actor_render_hints(self, h_mask: torch.Tensor, a_mask: torch.Tensor) -> None:
        live_actor_ids: set[str] = set()
        human_controls = self.player_control.build_tick_context(self).get("human_by_slot", {})

        for slot in torch.where(h_mask)[0].tolist():
            actor_id = self._human_uid_by_slot[slot]
            if not actor_id:
                continue
            actor_id = str(actor_id)
            live_actor_ids.add(actor_id)
            row = self.state.h_tensor[slot]
            x = float(row[X])
            y = float(row[Y])
            prev_x, prev_y = self._actor_prev_positions.get(actor_id, (x, y))
            vx = (x - prev_x) * float(TICK_RATE_HZ)
            vy = (y - prev_y) * float(TICK_RATE_HZ)
            speed = (vx * vx + vy * vy) ** 0.5
            direction_x = 0.0
            direction_y = 0.0
            if speed > 1e-4:
                direction_x = vx / speed
                direction_y = vy / speed
            facing_yaw = float(self._actor_prev_facing_yaw.get(actor_id, 0.0))
            control = human_controls.get(slot, {})
            look_yaw = control.get("look_yaw")
            if speed > 0.15:
                facing_yaw = math.atan2(-direction_x, -direction_y)
            elif look_yaw is not None:
                facing_yaw = float(look_yaw)
            locomotion = "idle"
            if speed > 0.15:
                locomotion = "walk"
                sprinting = bool(control.get("intent_state", {}).get("sprinting", False)) or bool(control.get("sprint", False))
                threat = float(row[THREAT])
                if threat >= 12.0:
                    locomotion = "flee"
                elif sprinting or speed >= 7.5:
                    locomotion = "run"
            action_payload = self._current_actor_render_action_payload(actor_id)
            action = str(action_payload.get("action", "")).strip().lower()
            if not action:
                pending_semantic = str(control.get("pending_semantic_action", "")).strip().lower()
                if pending_semantic == "talk_command":
                    action = "talk"
            self._actor_render_hints[actor_id] = {
                "server_tick": int(self.tick),
                "server_time": round(float(self.tick) / float(TICK_RATE_HZ), 4),
                "velocity_world": {"x": round(vx, 3), "y": round(vy, 3)},
                "speed": round(float(speed), 3),
                "moving": bool(speed > 0.15),
                "direction_world": {"x": round(direction_x, 4), "y": round(direction_y, 4)},
                "facing_yaw": round(float(facing_yaw), 4),
                "locomotion": locomotion,
                "action": action,
                "action_started_tick": int(action_payload.get("started_tick", -1)) if action else -1,
            }
            self._actor_prev_positions[actor_id] = (x, y)
            self._actor_prev_facing_yaw[actor_id] = facing_yaw

        for slot in torch.where(a_mask)[0].tolist():
            actor_id = self._entity_uid_by_slot[slot]
            if not actor_id:
                continue
            actor_id = str(actor_id)
            live_actor_ids.add(actor_id)
            row = self.state.m_tensor[slot]
            x = float(row[CX])
            y = float(row[CY])
            prev_x, prev_y = self._actor_prev_positions.get(actor_id, (x, y))
            vx = (x - prev_x) * float(TICK_RATE_HZ)
            vy = (y - prev_y) * float(TICK_RATE_HZ)
            speed = (vx * vx + vy * vy) ** 0.5
            direction_x = 0.0
            direction_y = 0.0
            if speed > 1e-4:
                direction_x = vx / speed
                direction_y = vy / speed
            facing_yaw = float(self._actor_prev_facing_yaw.get(actor_id, 0.0))
            if speed > 0.15:
                facing_yaw = math.atan2(-direction_x, -direction_y)
            action_payload = self._current_actor_render_action_payload(actor_id)
            locomotion = "idle"
            if speed > 0.15:
                locomotion = "run" if speed >= 8.0 else "walk"
            self._actor_render_hints[actor_id] = {
                "server_tick": int(self.tick),
                "server_time": round(float(self.tick) / float(TICK_RATE_HZ), 4),
                "velocity_world": {"x": round(vx, 3), "y": round(vy, 3)},
                "speed": round(float(speed), 3),
                "moving": bool(speed > 0.15),
                "direction_world": {"x": round(direction_x, 4), "y": round(direction_y, 4)},
                "facing_yaw": round(float(facing_yaw), 4),
                "locomotion": locomotion,
                "action": str(action_payload.get("action", "")).strip().lower(),
                "action_started_tick": int(action_payload.get("started_tick", -1)) if action_payload else -1,
            }
            self._actor_prev_positions[actor_id] = (x, y)
            self._actor_prev_facing_yaw[actor_id] = facing_yaw

        stale_ids = set(self._actor_render_hints.keys()) - live_actor_ids
        for actor_id in stale_ids:
            self._actor_render_hints.pop(actor_id, None)
            self._actor_prev_positions.pop(actor_id, None)
            self._actor_prev_facing_yaw.pop(actor_id, None)
            self._actor_render_actions.pop(actor_id, None)

    # ------------------------------------------------------------------
    # Export helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_value(value: float, dtype_name: str) -> Any:
        if dtype_name == "int":
            return int(round(value))
        return round(value, 1)

    @staticmethod
    def _schema_for(type_id: int) -> dict[str, Any]:
        return MAP_SCHEMA.get(type_id, {})

    def _type_label(self, type_id: int) -> str:
        return self._schema_for(type_id).get("label", f"type_{type_id}")

    def _schema_state(self, slot: int, type_id: int) -> dict[str, Any]:
        row = self.state.m_tensor[slot]
        state: dict[str, Any] = {}
        for attr in self._schema_for(type_id).get("attrs", []):
            col = int(attr["col"])
            state[attr["name"]] = self._coerce_value(
                float(row[col]), attr.get("dtype", "float")
            )
        return state

    def _export_human(self, slot: int) -> dict[str, Any]:
        exported = self._export_human_base(slot)
        seq = self._teleport_seq.get(str(self._human_uid_by_slot[slot] or ""), 0)
        if seq:  # absent means "never teleported"; legacy frames are unchanged
            exported["teleport_seq"] = seq
        roster_key = ((self.resident_store.get(self._human_uid_by_slot[slot]) or {}).get("roster") or {}).get("key")
        if roster_key:  # roster residents only; legacy frames are unchanged
            exported["roster_key"] = roster_key
        if spaces_enabled():  # 1008 P3 (EDEN_SPACES=1): the space the resident is in; absent with the flag off
            exported["space"] = int(self.state.h_tensor[slot, H_SPACE])
        return exported

    def _export_human_base(self, slot: int) -> dict[str, Any]:
        row = self.state.h_tensor[slot]
        human_id = self._human_uid_by_slot[slot]
        resident = self.resident_store.get(human_id)
        control = self.player_control.describe_human_slot(slot)
        avatar_controller_id = next(
            (
                controller_id
                for controller_id, avatar in self._incarnated_human_by_controller.items()
                if str(avatar.get("human_id", "")).strip() == str(human_id or "").strip()
            ),
            None,
        )
        intent = "player_controlled" if control is not None else (resident["status"]["current_intent"] if resident else "observe")
        inventory = get_owner_inventory(self.inventory_state, "human", human_id) if human_id else None
        render = dict(self._actor_render_hints.get(str(human_id or ""), {}))
        return {
            "id":   human_id,
            "slot": slot,
            "x":    round(float(row[X]), 1),
            "y":    round(float(row[Y]), 1),
            "sex":  int(row[H_SEX]),
            "age":  round(float(row[H_AGE]), 1),
            "name": resident["profile"]["name"] if resident else human_id,
            "intent": intent,
            "occupation": occupation_prompt_summary(resident) if resident else "no occupation",
            "schedule": schedule_prompt_summary(resident) if resident else "schedule not assigned",
            "crafting": crafting_prompt_summary(resident) if resident else "crafting not reviewed",
            "construction": construction_prompt_summary(resident) if resident else "no construction pressure",
            "tasks": task_prompt_summary(resident) if resident else "no active tasks",
            "controlled": control is not None,
            "player_controlled": control is not None,
            "player_avatar": avatar_controller_id is not None,
            "avatar_controller_id": avatar_controller_id,
            "controller_id": control["controller_id"] if control is not None else None,
            "control_mode": control["mode"] if control is not None else None,
            "control_target_kind": control["target_kind"] if control is not None else None,
            "control_target_id": control["target_id"] if control is not None else None,
            "control_target_name": control["target_name"] if control is not None else None,
            "inventory_summary": summarize_inventory(inventory) if inventory is not None else "empty",
            "inventory": inventory_prompt_payload(inventory, limit=4) if inventory is not None else None,
            "hp": round(float(row[HP]), 1),
            "threat": round(float(row[THREAT]), 1),
            "render": render,
            "state": {
                "hp":         round(float(row[HP]), 1),
                "stamina":    round(float(row[H_STAMINA]), 1),
                "hunger":     round(float(row[HUNGER]), 1),
                "thirst":     round(float(row[THIRST]), 1),
                "carrying":   round(float(row[H_CARRYING]), 1),
                "skill":      round(float(row[H_SKILL]), 1),
                "mood":       round(float(row[MOOD]), 1),
                "threat":     round(float(row[THREAT]), 1),
                "escalated":  bool(row[ESCALATION_FLAG]),
                "instincts":  int(row[ACQUIRED_INSTINCT_MASK]),
                **instinct_bits.high_payload(row),   # "instincts_hi": bits 24..63 as a decimal string; absent when none are set
                "life_exp":   round(float(row[H_LIFE_EXP]), 1),
            },
        }

    def _export_animal(self, slot: int) -> dict[str, Any]:
        row = self.state.m_tensor[slot]
        type_id = int(row[M_TYPE])
        control = self.player_control.describe_entity_slot(slot)
        actor_id = self._entity_uid_by_slot[slot]
        exported = {
            "id":         actor_id,
            "slot":       slot,
            "type_id":    type_id,
            "type_label": self._type_label(type_id),
            "x":          round(float(row[CX]), 1),
            "y":          round(float(row[CY]), 1),
            "hp":         round(float(row[M_HP]), 1),
            "render":     dict(self._actor_render_hints.get(str(actor_id or ""), {})),
            "controlled": control is not None,
            "controller_id": control["controller_id"] if control is not None else None,
            "control_mode": control["mode"] if control is not None else None,
            "control_target_kind": control["target_kind"] if control is not None else None,
            "control_target_id": control["target_id"] if control is not None else None,
            "control_target_name": control["target_name"] if control is not None else None,
            "state":      self._schema_state(slot, type_id),
        }
        if spaces_enabled():  # 1008 P3 (EDEN_SPACES=1): absent with the flag off
            exported["space"] = int(row[M_SPACE])
        if creatures_enabled():  # 1008 Phase 2 (EDEN_CREATURES=1): species, sprite, footprint, state, variant; absent with the flag off
            creature = creature_frame.keys(row)
            if creature is not None:
                exported["creature"] = creature
        return exported

    def _export_map_entity(self, slot: int) -> dict[str, Any]:
        row = self.state.m_tensor[slot]
        type_id = int(row[M_TYPE])
        geo = map_geo.MAP_GEO[slot]
        control = self.player_control.describe_entity_slot(slot)
        entity_id = self._entity_uid_by_slot[slot]
        container = get_container_inventory(self.inventory_state, entity_id) if entity_id else None
        exported = {
            "id":         entity_id,
            "slot":       slot,
            "type_id":    type_id,
            "type_label": self._type_label(type_id),
            "mobile":     bool(self._schema_for(type_id).get("mobile", False)),
            "controlled": control is not None,
            "controller_id": control["controller_id"] if control is not None else None,
            "control_mode": control["mode"] if control is not None else None,
            "control_target_kind": control["target_kind"] if control is not None else None,
            "control_target_id": control["target_id"] if control is not None else None,
            "control_target_name": control["target_name"] if control is not None else None,
            "anchor": {
                "x": round(float(row[CX]), 1),
                "y": round(float(row[CY]), 1),
            },
            "scale": round(float(row[SCALE]), 1),
            "hp":    round(float(row[M_HP]), 1),
            "shape": {
                "kind":   geo["shape"],
                "r":      round(float(geo["r"]), 1),
                "points": [[round(p[0], 1), round(p[1], 1)] for p in geo["points"]],
            },
            "state": self._schema_state(slot, type_id),
            "inventory_container": container_prompt_payload(container, limit=6) if container is not None else None,
        }
        if spaces_enabled():  # 1008 P3 (EDEN_SPACES=1): absent with the flag off
            exported["space"] = int(row[M_SPACE])
        return exported

    def _export_map_entities(self) -> dict[str, dict[str, Any]]:
        self._export_stamp = window_wire.stamp(self)      # EDEN_WINDOW: the origin and epoch the exported positions are local to ({} otherwise)
        if window_wire.window_enabled():
            self._export_window = window_wire.integrated_block(self)
        entities: dict[str, dict[str, Any]] = {}
        for slot in sorted(map_geo.MAP_GEO.keys()):
            payload = self._export_map_entity(slot)
            entities[payload["id"]] = payload
        return entities

    # ------------------------------------------------------------------
    # Payload builders
    # ------------------------------------------------------------------

    def _world_payload(self) -> dict[str, Any]:
        return {
            "map_name":           self._map_name,
            "width":              MAP_WIDTH,
            "height":             MAP_HEIGHT,
            "tile_size":          TILE_SIZE,
            "sim_tick_hz":        TICK_RATE_HZ,
            "ticks_per_year":     _calendar.ticks_per_year(),
            "agent_frame_every":  AGENT_FRAME_EVERY,
            "map_delta_every":    MAP_DELTA_EVERY,
            "agent_frame_hz":     round(TICK_RATE_HZ / AGENT_FRAME_EVERY, 3),
            "map_delta_hz":       round(TICK_RATE_HZ / MAP_DELTA_EVERY, 3),
            "agent_cap":          MAX_HUMANS,
            "entity_cap":         MAX_ENTITIES,
            **window_wire.world_block(self),
            **calendar_wire.world_block(self),
        }

    def _empty_bootstrap_payload(self) -> dict[str, Any]:
        return {
            "protocol": PROTOCOL_VERSION,
            "world":    self._world_payload(),
            "schema":   self._schema_payload,
            "map": {
                "geo_version":   self._map_geo_version_sent,
                "state_version": self._map_state_version,
                "entities":      [],
            },
            "inventory": {"focus": None},
            "talk": {"recent_lines": [], "recent_tts_requests": []},
        }

    def _empty_frame_payload(self) -> dict[str, Any]:
        return {
            **window_wire.stamp(self),
            **calendar_wire.time_block(self),
            "protocol":  PROTOCOL_VERSION,
            "frame_id":  self._frame_id,
            "tick":      self.tick,
            "year":      round(self.tick / _calendar.ticks_per_year(), 2),
            "pop":       self.pop_count,
            "cap":       MAX_HUMANS,
            "map_name":  self._map_name,
            "agents":    [],
            "animals":   [],
            "controls":  [],
            "inventory": {"focus": None},
            "talk": {"recent_lines": [], "recent_tts_requests": []},
            "despawned": [],
            "events":    [],
        }

    def _empty_map_delta_payload(self) -> dict[str, Any]:
        return {
            **window_wire.stamp(self),
            "protocol":      PROTOCOL_VERSION,
            "map_name":      self._map_name,
            "geo_version":   self._map_geo_version_sent,
            "state_version": self._map_state_version,
            "replace_all":   False,
            "upserts":       [],
            "removed":       [],
        }

    def _empty_legacy_map_payload(self) -> dict[str, Any]:
        return {
            "width":       MAP_WIDTH,
            "height":      MAP_HEIGHT,
            "tile_size":   TILE_SIZE,
            "map_name":    self._map_name,
            "geo_version": self._map_geo_version_sent,
            "entities":    [],
        }

    def _empty_legacy_agent_payload(self) -> dict[str, Any]:
        return {
            "tick":    self.tick,
            "year":    round(self.tick / _calendar.ticks_per_year(), 2),
            "pop":     self.pop_count,
            "cap":     MAX_HUMANS,
            "map":     self._map_name,
            "agents":  [],
            "animals": [],
        }

    def _refresh_bootstrap_payload(self, current_map_entities: dict[str, dict[str, Any]]) -> None:
        self._bootstrap_payload = {
            **(getattr(self, "_export_stamp", None) or {}),
            "protocol": PROTOCOL_VERSION,
            "world":    self._world_payload(),
            "schema":   self._schema_payload,
            "map": {
                "geo_version":   self._map_geo_version_sent,
                "state_version": self._map_state_version,
                "entities":      list(current_map_entities.values()),
            },
            "inventory": {"focus": self._inventory_focus_payload()},
            "talk": self._talk_feed_payload(),
        }

    def _refresh_legacy_map_payload(self, current_map_entities: dict[str, dict[str, Any]]) -> None:
        def state_value(state: dict[str, Any], *names: str, default: Any = 0) -> Any:
            for name in names:
                if name in state:
                    return state[name]
            return default

        self._legacy_map_payload = {
            "width":       MAP_WIDTH,
            "height":      MAP_HEIGHT,
            "tile_size":   TILE_SIZE,
            "map_name":    self._map_name,
            "geo_version": self._map_geo_version_sent,
            "entities": [
                {
                    "id":        payload["slot"],
                    "type":      payload["type_id"],
                    "cx":        payload["anchor"]["x"],
                    "cy":        payload["anchor"]["y"],
                    "scale":     payload["scale"],
                    "hp":        payload["hp"],
                    "food":      state_value(payload["state"], "food", "fish_count", "tree_density", "food_stock"),
                    "fertility": state_value(payload["state"], "fertility"),
                    "burning":   state_value(payload["state"], "burning", "fire_ticks"),
                    "flooded":   state_value(payload["state"], "flooded"),
                    "shape":     payload["shape"]["kind"],
                    "r":         payload["shape"]["r"],
                    "points":    payload["shape"]["points"],
                }
                for payload in current_map_entities.values()
            ],
        }

    def _refresh_legacy_agent_payload(self) -> None:
        self._legacy_agent_payload = {
            "tick":    self._frame_payload["tick"],
            "year":    self._frame_payload["year"],
            "pop":     self._frame_payload["pop"],
            "cap":     self._frame_payload["cap"],
            "map":     self._frame_payload["map_name"],
            "agents": [
                {
                    "x":         payload["x"],
                    "y":         payload["y"],
                    "sex":       payload["sex"],
                    "age":       payload["age"],
                    "escalated": payload["state"]["escalated"],
                    "instincts": payload["state"]["instincts"],
                }
                for payload in self._frame_payload["agents"]
            ],
            "animals": [
                {
                    "x":       payload["x"],
                    "y":       payload["y"],
                    "species": payload["type_id"],
                }
                for payload in self._frame_payload["animals"]
            ],
        }

    def _build_frame_payload(self, h_mask: torch.Tensor, a_mask: torch.Tensor) -> None:
        human_slots = torch.where(h_mask)[0].tolist()
        animal_slots = torch.where(a_mask)[0].tolist()

        self._frame_id += 1
        self._frame_payload = {
            **window_wire.stamp(self),
            **calendar_wire.time_block(self),
            "protocol":  PROTOCOL_VERSION,
            "frame_id":  self._frame_id,
            "tick":      self.tick,
            "year":      round(self.tick / _calendar.ticks_per_year(), 2),
            "pop":       self.pop_count,
            "cap":       MAX_HUMANS,
            "map_name":  self._map_name,
            "nature":    dict(self._nature_state),
            "agents":    [self._export_human(slot) for slot in human_slots],
            "animals":   [self._export_animal(slot) for slot in animal_slots],
            "controls":  self.player_control.status_snapshot()["sessions"],
            "inventory": {"focus": self._inventory_focus_payload()},
            "talk":      self._talk_feed_payload(),
            "despawned": list(self._pending_despawns),
            "events":    list(self._pending_events),
        }
        self._pending_despawns.clear()
        self._pending_events.clear()
        self._refresh_legacy_agent_payload()

    def _build_bootstrap_payload(self, current_map_entities: dict[str, dict[str, Any]] | None = None) -> None:
        if current_map_entities is None:
            current_map_entities = self._export_map_entities()
        self._refresh_bootstrap_payload(current_map_entities)
        self._refresh_legacy_map_payload(current_map_entities)

    def _build_map_delta_payload(self) -> None:
        current_map_entities = self._export_map_entities()
        current_geo_version = map_geo.geo_version
        window_changed = False
        if window_wire.window_enabled():
            window_changed = getattr(self, "_last_exported_window", None) != self._export_window

        upserts = [
            payload
            for uid, payload in current_map_entities.items()
            if self._last_exported_map_entities.get(uid) != payload
        ]
        removed = sorted(
            uid for uid in self._last_exported_map_entities.keys()
            if uid not in current_map_entities
        )

        if not upserts and not removed and current_geo_version == self._map_geo_version_sent and not window_changed:
            self._map_delta_payload = self._empty_map_delta_payload()
            self._refresh_bootstrap_payload(current_map_entities)
            self._refresh_legacy_map_payload(current_map_entities)
            return

        self._latest_delta_base_geo = self._map_geo_version_sent
        self._latest_delta_base_state = self._map_state_version
        self._map_state_version += 1
        self._map_geo_version_sent = current_geo_version
        self._last_exported_map_entities = current_map_entities

        self._map_delta_payload = {
            **(getattr(self, "_export_stamp", None) or {}),
            "protocol":      PROTOCOL_VERSION,
            "map_name":      self._map_name,
            "geo_version":   self._map_geo_version_sent,
            "state_version": self._map_state_version,
            "replace_all":   False,
            "upserts":       upserts,
            "removed":       removed,
        }
        if window_wire.window_enabled():
            if window_changed:
                self._map_delta_payload.update(self._export_window)
            self._last_exported_window = self._export_window
            # Retain the last versioned delta across unchanged ticks for all consumers.
            self._latest_window_delta_payload = self._map_delta_payload
        self._refresh_bootstrap_payload(current_map_entities)
        self._refresh_legacy_map_payload(current_map_entities)

    def get_map_delta_for(
        self,
        since_state_version: int | None = None,
        since_geo_version: int | None = None,
    ) -> dict[str, Any]:
        if since_state_version is None or since_geo_version is None:
            return {
                **(getattr(self, "_export_stamp", None) or {}),
                **(window_wire.exported_integrated_block(self)),
                "protocol":      PROTOCOL_VERSION,
                "map_name":      self._map_name,
                "geo_version":   self._map_geo_version_sent,
                "state_version": self._map_state_version,
                "replace_all":   True,
                "upserts":       list(self._last_exported_map_entities.values()),
                "removed":       [],
            }

        if (
            since_state_version == self._map_state_version
            and since_geo_version == self._map_geo_version_sent
        ):
            return self._empty_map_delta_payload()

        if (
            since_state_version == self._latest_delta_base_state
            and since_geo_version == self._latest_delta_base_geo
        ):
            if window_wire.window_enabled():
                return getattr(self, "_latest_window_delta_payload", None) or self._map_delta_payload
            return self._map_delta_payload

        return {
            **(getattr(self, "_export_stamp", None) or {}),
            **(window_wire.exported_integrated_block(self)),
            "protocol":      PROTOCOL_VERSION,
            "map_name":      self._map_name,
            "geo_version":   self._map_geo_version_sent,
            "state_version": self._map_state_version,
            "replace_all":   True,
            "upserts":       list(self._last_exported_map_entities.values()),
            "removed":       [],
        }

    # ------------------------------------------------------------------
    # Tick loop
    # ------------------------------------------------------------------

    def step(self) -> None:
        """Advance one authoritative tick; scheduling and transport are separate."""
        if not self.world_loaded:
            return
        gcpolicy.ensure_frozen(self.world_epoch)  # load paths other than create_genesis (save restore)
        if god_pause_step(self):
            return  # paused: no simulation tick, but commands (god powers included) still apply
        movement_starts = self.state.h_tensor[:, :2].clone()
        movement_start_ids = list(self._human_uid_by_slot)
        for slot in range(min(len(movement_start_ids), movement_starts.shape[0])):
            uid = movement_start_ids[slot]
            if uid and uid in self._actor_prev_positions:
                px, py = self._actor_prev_positions[uid]
                movement_starts[slot, 0] = px
                movement_starts[slot, 1] = py
        spatial = world_contract(self)
        lightweight_runtime = self._runtime_profile == "render_test"
        self.player_control.tick_maintenance(self)
        self.player_control.begin_tick_inputs(self)
        self.command_inbox.drain(self, DISPATCH.execute)
        for slot, tx, ty in self._tick_teleports:  # a teleport is not movement: no slide from the old position
            movement_starts[slot, 0], movement_starts[slot, 1] = tx, ty
            uid = self._human_uid_by_slot[slot] if 0 <= slot < len(self._human_uid_by_slot) else None
            if uid:
                self._actor_prev_positions[uid] = (tx, ty)
        self._tick_teleports = []
        kwargs = self._build_kwargs()
        if lightweight_runtime:
            world_changes = {"frame_dirty": False, "map_dirty": False}
        else:
            world_changes = self.world_agent.process_queues(self, self.decree_execution, self.plot_execution)
        self.player_control.tick_maintenance(self)
        self._force_frame_refresh = self._force_frame_refresh or world_changes["frame_dirty"]
        self._force_map_refresh = self._force_map_refresh or world_changes["map_dirty"]

        h_mask, a_mask, _ = self._current_masks()
        dormant_h, dormant_a = _dormancy.refresh(self)  # EDEN_WINDOW_DORMANCY: residents/animals in chunks that are not integrated do nothing
        frozen = _dormancy.freeze(self, dormant_h, dormant_a)
        restrained = _restraint.capture(self)  # EDEN_RESTRAINT: restrained humans stand where they stood

        if h_mask.any() or a_mask.any():
            ctx: dict[str, Any] = {"h_mask": h_mask, "a_mask": a_mask, "engine": self}
            if dormant_h is not None:
                ctx["h_mask"], ctx["a_mask"] = h_mask & ~dormant_h, a_mask & ~dormant_a
            for entry in self._registry:
                result = entry["fn"](ctx, **{**kwargs, **entry["kwargs"]})
                if result is not None:
                    ctx.update(result)
                h_mask = ctx["h_mask"]
                a_mask = ctx.get("a_mask", a_mask)
            if dormant_h is not None:  # the id sync and the death check must still see them alive
                h_mask, a_mask = h_mask | dormant_h, a_mask | dormant_a
        else:
            ctx = {"h_mask": h_mask, "a_mask": a_mask, "engine": self}

        if not lightweight_runtime:
            talk_outcomes = self.talk_agent.process_tick(self)
            if talk_outcomes:
                for talk_outcome in talk_outcomes:
                    self._orchestrate_talk_outcome(talk_outcome)
                self._force_frame_refresh = True
                h_mask, a_mask, _ = self._current_masks()

            human_outcomes = self.human_agent.process_escalations(self)
            if human_outcomes:
                self._force_frame_refresh = True
                h_mask, a_mask, _ = self._current_masks()

        manual_control = self.player_control.build_tick_context(self)
        if self._apply_manual_control_human_actions(manual_control):
            self._force_frame_refresh = True
            h_mask, a_mask, _ = self._current_masks()

        if self.player_control.has_active_sessions():
            self._force_frame_refresh = True
        if self.player_control.has_active_entity_sessions():
            self._force_map_refresh = True

        # Reconcile every living resident before publishing positions and velocities.
        window = getattr(self, "_window", None) if (window_wire.window_enabled() or getattr(self, "_window", None) is not None) else None
        controlled_slots = set(window.controlled_slots()) if (window is not None and hasattr(window, "controlled_slots")) else set()
        for slot in torch.where(self.state.h_tensor[:, TYPE] == AGENT_TYPE_HUMAN)[0].tolist():
            if not movement_start_ids[slot] or movement_start_ids[slot] != self._human_uid_by_slot[slot]:
                continue
            start = movement_starts[slot].tolist()
            desired = self.state.h_tensor[slot, :2].tolist()
            if window is not None:
                if abs(desired[0] - start[0]) < 1e-9 and abs(desired[1] - start[1]) < 1e-9:
                    continue
                resolved, diag = spatial_slide(start, desired, spatial, diagnostics=True)
                is_player = (slot in controlled_slots) or (
                    getattr(self, "player_control", None) is not None
                    and self.player_control.describe_human_slot(slot) is not None
                )
                if diag["void_hit"]:
                    window.record_void_hit(is_player=is_player)
                if diag["wall_hit"]:
                    window.record_wall_hit(is_player=is_player)
            else:
                resolved = spatial_slide(start, desired, spatial)
            self.state.h_tensor[slot, X] = resolved[0]
            self.state.h_tensor[slot, Y] = resolved[1]
        DISPATCH.run_step_hooks(self)  # ordered per-tick extension point after the reconcile (default: none)
        entity_mask = self.state.m_tensor[:, M_TYPE] > 0
        self._sync_slot_ids_and_events(h_mask, a_mask, entity_mask, manual_control=manual_control)
        _restraint.pin(self, restrained)  # before the motion limits record where everyone ended the tick
        DISPATCH.run_post_step_hooks(self)  # after resident task movement: motion limits, commission tick
        _dormancy.thaw(self, frozen)  # a dormant row is bit-identical from tick to tick, whatever touched it
        self._refresh_actor_render_hints(h_mask, a_mask)

        self.player_control.commit_tick_inputs(self)
        if self.tick % AGENT_FRAME_EVERY == 0 or self._force_frame_refresh:
            self._build_frame_payload(h_mask, a_mask)
            self._force_frame_refresh = False

        if self.tick % MAP_DELTA_EVERY == 0 or self._force_map_refresh:
            self._build_map_delta_payload()
            self._force_map_refresh = False

        self.tick += 1

    async def run_loop(self) -> None:
        self.running = True
        try:
            await self.scheduler.run(self.step, lambda: self.running)
        finally:
            self.running = False

    # ------------------------------------------------------------------
    # Convenience wrappers
    # ------------------------------------------------------------------

    def spawn(
        self,
        x: float,
        y: float,
        sex: float,
        life_exp: float,
        age: float = 0.0,
        preferred_name: str | None = None,
    ) -> bool:
        point = standable_spawn_point(self, x, y)  # unchanged on legacy maps; snapped or rejected on authored maps
        if point is None:
            return False
        x, y = point
        free = torch.where(self.state.h_tensor[:, TYPE] == 0)[0]
        target_slot = int(free[0].item()) if len(free) else -1
        spawned = iat.instinct_born(
            self.state.h_tensor,
            self._pop_count,
            x,
            y,
            sex,
            life_exp,
            age=age,
        )
        if spawned and preferred_name and target_slot != -1:
            self._pending_human_names_by_slot[target_slot] = preferred_name
        return spawned

    def _human_slot_for_id(self, human_id: str | None) -> int:
        wanted_id = str(human_id or "").strip()
        if not wanted_id:
            return -1
        for slot, candidate_id in enumerate(self._human_uid_by_slot):
            if str(candidate_id or "") == wanted_id:
                return int(slot)
        return -1

    def _refresh_control_payloads(self, *, sync_occupations: bool = True) -> None:
        h_mask, a_mask, entity_mask = self._current_masks()
        self._assign_missing_ids(h_mask, entity_mask)
        self.resident_store.sync_live_population(
            self._human_uid_by_slot,
            h_mask,
            self.state.h_tensor,
            self.tick,
        )
        self._sync_inventory_defaults(h_mask)
        if sync_occupations:
            self._sync_occupation_provisioning(h_mask)
        self._build_frame_payload(h_mask, a_mask)

    def _player_incarnation_spawn_point(self, controller_id: str) -> tuple[float, float]:
        live_slots = torch.where(self.state.h_tensor[:, TYPE] == AGENT_TYPE_HUMAN)[0].tolist()
        if live_slots:
            anchor_slot = int(live_slots[0])
            base_x = float(self.state.h_tensor[anchor_slot, X]) + 18.0
            base_y = float(self.state.h_tensor[anchor_slot, Y]) + 12.0
        else:
            base_x = MAP_WIDTH * 0.5
            base_y = MAP_HEIGHT * 0.5

        seed = sum(ord(ch) for ch in str(controller_id or "local_player"))
        rng = random.Random((seed * 17) + int(self.tick))
        offset_x = rng.uniform(-12.0, 12.0)
        offset_y = rng.uniform(-10.0, 10.0)
        spawn_x = min(max(base_x + offset_x, 20.0), MAP_WIDTH - 20.0)
        spawn_y = min(max(base_y + offset_y, 20.0), MAP_HEIGHT - 20.0)
        return spawn_x, spawn_y

    def incarnate_controller_human(
        self,
        *,
        controller_id: str = "local_player",
        preferred_name: str | None = None,
        sex: float | None = None,
        age: float | None = None,
        life_exp: float | None = None,
    ) -> dict[str, Any]:
        controller_key = str(controller_id or "local_player").strip() or "local_player"
        avatar_record = dict(self._incarnated_human_by_controller.get(controller_key, {}))
        avatar_id = str(avatar_record.get("human_id", "")).strip()
        remembered_name = str(avatar_record.get("preferred_name", "")).strip()
        desired_name = str(preferred_name or remembered_name or "").strip()

        if avatar_id:
            avatar_slot = self._human_slot_for_id(avatar_id)
            if 0 <= avatar_slot < self.state.h_tensor.shape[0] and int(self.state.h_tensor[avatar_slot, TYPE]) == AGENT_TYPE_HUMAN:
                resident = self.resident_store.get(avatar_id)
                target_name = str((resident or {}).get("profile", {}).get("name", desired_name or avatar_id))
                result = self.player_control.claim_target(
                    self,
                    controller_id=controller_key,
                    target_kind="human",
                    target_id=avatar_id,
                    target_name=target_name,
                    human_id=avatar_id,
                    human_name=target_name,
                    mode="incarnate",
                )
                if result.get("ok"):
                    self._incarnated_human_by_controller[controller_key] = {
                        "human_id": avatar_id,
                        "preferred_name": target_name,
                    }
                    self._refresh_control_payloads()
                    result["spawned"] = False
                    result["incarnation"] = "rejoined"
                return result

        if not desired_name:
            return {
                "ok": False,
                "reason": "missing_avatar_name",
                "requires_name": True,
                "controller_id": controller_key,
            }

        free_slots = torch.where(self.state.h_tensor[:, TYPE] == 0)[0]
        if len(free_slots) == 0:
            return {
                "ok": False,
                "reason": "human_capacity_reached",
                "controller_id": controller_key,
            }

        target_slot = int(free_slots[0].item())
        spawn_x, spawn_y = self._player_incarnation_spawn_point(controller_key)
        spawn_sex = float(random.randint(0, 1) if sex is None else sex)
        spawn_age = float(max(float(MATURE_AGE), 18.0) if age is None else age)
        spawn_life_exp = float(
            random.uniform(max(LIFE_EXP_MIN + 4, 48), LIFE_EXP_MAX) if life_exp is None else life_exp
        )
        spawned = self.spawn(
            spawn_x,
            spawn_y,
            spawn_sex,
            spawn_life_exp,
            age=spawn_age,
            preferred_name=desired_name,
        )
        if not spawned:
            return {
                "ok": False,
                "reason": "spawn_failed",
                "controller_id": controller_key,
            }

        h_mask, _, entity_mask = self._current_masks()
        self._assign_missing_ids(h_mask, entity_mask)
        human_id = self._human_uid_by_slot[target_slot]
        if human_id is None:
            return {
                "ok": False,
                "reason": "spawn_missing_human_id",
                "controller_id": controller_key,
            }

        resident = self.resident_store.get(human_id)
        target_name = str((resident or {}).get("profile", {}).get("name", desired_name or human_id))
        self._incarnated_human_by_controller[controller_key] = {
            "human_id": str(human_id),
            "preferred_name": target_name,
        }
        result = self.player_control.claim_target(
            self,
            controller_id=controller_key,
            target_kind="human",
            target_id=str(human_id),
            target_name=target_name,
            human_id=str(human_id),
            human_name=target_name,
            mode="incarnate",
        )
        if not result.get("ok"):
            return result

        self._queue_event(
            "player_incarnated",
            str(human_id),
            target_slot,
            controller_id=controller_key,
            human_name=target_name,
        )
        self._refresh_control_payloads()
        result["spawned"] = True
        result["incarnation"] = "created"
        result["spawn"] = {
            "x": round(spawn_x, 1),
            "y": round(spawn_y, 1),
            "slot": int(target_slot),
            "human_id": str(human_id),
            "human_name": target_name,
        }
        return result

    def prime_protocol_state(self) -> None:
        h_mask, a_mask, entity_mask = self._current_masks()
        self._spawn_starter_storage_case(h_mask)
        h_mask, a_mask, entity_mask = self._current_masks()
        self._assign_missing_ids(h_mask, entity_mask)
        self.resident_store.sync_live_population(
            self._human_uid_by_slot,
            h_mask,
            self.state.h_tensor,
            self.tick,
        )
        self._sync_inventory_defaults(h_mask)
        self._sync_occupation_provisioning(h_mask)
        self.sync_memory_graph(save=True)
        self._prev_h_mask = h_mask.clone()
        self._prev_a_mask = a_mask.clone()
        self._prev_entity_mask = entity_mask.clone()
        self._pending_events.clear()
        self._pending_despawns.clear()
        self._map_geo_version_sent = map_geo.geo_version
        self._map_state_version = 0
        current_map_entities = self._export_map_entities()
        self._last_exported_map_entities = current_map_entities
        if window_wire.window_enabled():
            self._last_exported_window = self._export_window
            self._latest_window_delta_payload = None
        self._latest_delta_base_geo = self._map_geo_version_sent
        self._latest_delta_base_state = self._map_state_version
        self._build_bootstrap_payload(current_map_entities)
        self._build_frame_payload(h_mask, a_mask)
        self._map_delta_payload = self._empty_map_delta_payload()
        self._force_frame_refresh = False
        self._force_map_refresh = False

    @property
    def pop_count(self) -> int:
        return self._pop_count[0]

    @property
    def entity_count(self) -> int:
        return self._entity_count_ref[0]


_SPAWN_RING = ((0, 0), (1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, 1), (-1, -1), (1, -1), (2, 0), (0, 2), (-2, 0), (0, -2))


def _spawn_villagers_at_anchors(engine: Engine, villagers: list[dict[str, Any]], anchors: list[dict[str, Any]],
                                radius: float) -> None:
    """Starter villagers at the map's spawn anchors, round-robin, fanned out on a ring of 2*radius steps.

    Engine.spawn snaps or rejects non-standable points, so a candidate that fails is skipped for the next one.
    """
    used = [0] * len(anchors)
    for index, villager in enumerate(villagers):
        slot = index % len(anchors)
        ax, ay = anchors[slot]["position"]
        for attempt in range(used[slot], len(_SPAWN_RING)):
            dx, dy = _SPAWN_RING[attempt]
            used[slot] = attempt + 1
            if engine.spawn(ax + dx * 2.0 * radius, ay + dy * 2.0 * radius, float(villager["sex"]),
                            float(villager["life_exp"]), age=float(villager["age"]),
                            preferred_name=str(villager["name"])):
                break


async def create_genesis(engine: Engine, map_name: str | None = None) -> None:
    DYNAMIC_DIR.mkdir(parents=True, exist_ok=True)

    init_file = DYNAMIC_DIR / "__init__.py"
    if not init_file.exists():
        init_file.write_text(
            "# Dynamic instincts loaded at runtime by Engine.load_dynamic_instinct()\n",
            encoding="utf-8",
        )

    dev = engine.state.device

    authored = get_map_contract(map_name)
    if authored is not None and map_name not in MAP_REGISTRY:
        chosen_name, generator = map_name, (lambda m_tensor, entity_count_ref, device: None)  # authored map: no generator
    else:
        chosen_name, generator = pick_map(map_name)
    engine._map_name = chosen_name
    # A small map is content, not permission to bypass the simulation.
    engine._runtime_profile = "full"
    print(f"[Genesis] Generating map: {chosen_name}")

    generator(engine.state.m_tensor, engine._entity_count_ref, dev)

    dummy_ctx = {"h_mask": torch.zeros(MAX_HUMANS, dtype=torch.bool, device=dev)}
    iat.tool_seed_world(dummy_ctx, m_tensor=engine.state.m_tensor)

    cx_px = MAP_WIDTH / 2.0
    cy_px = MAP_HEIGHT / 2.0
    if authored is not None and map_name not in MAP_REGISTRY:
        instantiate_authored_entities(engine, chosen_name)  # map-file ids become backend entity ids
    spawn_anchors = [a for a in (get_map_contract(chosen_name) or {}).get("anchors", []) if a["kind"] == "spawn"]
    if authored is not None and not spawn_anchors and map_name not in MAP_REGISTRY:
        bounds = authored["bounds"]  # no spawn anchor authored: start around the map centre (the validator warns)
        spawn_anchors = [{"id": "map_centre", "kind": "spawn", "position": [(bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2]}]
    if has_roster(chosen_name):
        pass  # the roster's post-genesis hook spawns the named residents
    elif chosen_name in {"render_test_village", "playable_village"} or spawn_anchors:
        test_villagers = [
            {"name": "Mara", "x": cx_px - 12.0, "y": cy_px + 10.0, "sex": 1.0, "life_exp": 74.0, "age": 24.0},
            {"name": "Iven", "x": cx_px + 10.0, "y": cy_px + 12.0, "sex": 0.0, "life_exp": 76.0, "age": 28.0},
            {"name": "Toma", "x": cx_px - 6.0, "y": cy_px - 18.0, "sex": 0.0, "life_exp": 71.0, "age": 21.0},
            {"name": "Elsa", "x": cx_px + 18.0, "y": cy_px - 16.0, "sex": 1.0, "life_exp": 79.0, "age": 26.0},
        ]
        if spawn_anchors:
            _spawn_villagers_at_anchors(engine, test_villagers, spawn_anchors, get_map_contract(chosen_name)["actor_radius"])
        else:
            for villager in test_villagers:
                engine.spawn(
                    float(villager["x"]),
                    float(villager["y"]),
                    float(villager["sex"]),
                    float(villager["life_exp"]),
                    age=float(villager["age"]),
                    preferred_name=str(villager["name"]),
                )
    else:
        engine.spawn(cx_px,     cy_px, 0.0, ADAM_LIFE_EXP, age=GENESIS_AGE, preferred_name="Adam")
        engine.spawn(cx_px + 5, cy_px, 1.0, EVE_LIFE_EXP,  age=GENESIS_AGE, preferred_name="Eve")
    engine.prime_protocol_state()
    engine.world_loaded = True
    DISPATCH.run_genesis_hooks(engine, chosen_name)  # ordered post-genesis extension point (default: none)
    gcpolicy.freeze_after_load(engine.world_epoch)  # keep the loaded world out of every later full collection

    print(
        f"[Genesis] '{chosen_name}' ready — "
        f"{engine.entity_count} entities, device={dev}."
    )


async def load_render_test_village(
    engine: Engine,
    *,
    controller_id: str = "local_player",
    auto_claim: bool = True,
) -> dict[str, Any]:
    engine.reset_world()
    await create_genesis(engine, map_name="render_test_village")
    engine._runtime_profile = "full"
    result: dict[str, Any] = {
        "ok": True,
        "map_name": engine._map_name,
        "runtime_profile": engine._runtime_profile,
        "persistence": {"pending_residents": len(engine.resident_store._dirty),
                        "errors": dict(engine.resident_store.save_errors)},
        "human_ids": [uid for uid in engine._human_uid_by_slot if uid][:8],
        "entity_count": int(engine.entity_count),
        "human_count": int(engine.pop_count),
    }
    if auto_claim:
        first_human_id = next((uid for uid in engine._human_uid_by_slot if uid), None)
        if first_human_id is None:
            result["claim"] = {"ok": False, "reason": "no_humans_available"}
        else:
            resident = engine.resident_store.get(first_human_id)
            claim_result = engine.player_control.claim_target(
                engine,
                controller_id=str(controller_id or "local_player"),
                target_kind="human",
                target_id=str(first_human_id),
                target_name=str((resident or {}).get("profile", {}).get("name", first_human_id)),
                mode="possess",
            )
            result["claim"] = dict(claim_result)
            if claim_result.get("ok"):
                current_map_entities = engine._export_map_entities()
                h_mask, a_mask, _ = engine._current_masks()
                engine._last_exported_map_entities = current_map_entities
                engine._build_bootstrap_payload(current_map_entities)
                engine._build_frame_payload(h_mask, a_mask)
                engine._build_map_delta_payload()
                engine._force_frame_refresh = True
                engine._force_map_refresh = True
    return result


engine = Engine()
engine._decision_log_root = LAUNCH_CONFIG.data_root / "decisions"  # outside saves
game_sessions = GameSessions(engine, map_geo, ar.PlayerControlRuntime,
                             LAUNCH_CONFIG.data_root / "Saves", create_genesis, LAUNCH_CONFIG.seed, LAUNCH_CONFIG.map_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from persistence.resident_writer import ResidentWriter
    random.seed(LAUNCH_CONFIG.seed)
    torch.manual_seed(LAUNCH_CONFIG.seed)
    if LAUNCH_CONFIG.development:
        await create_genesis(engine, map_name=LAUNCH_CONFIG.map_name)
    resident_task = None
    if not LAUNCH_CONFIG.development:
        engine.resident_store.background_writes = True
        resident_task = asyncio.create_task(ResidentWriter(game_sessions).run(), name="eden-resident-writer")
    app.state.resident_writer_task = resident_task
    with suppress(Exception):  # never block startup on a warm-up
        engine.warm_up_process()
    loop_task = asyncio.create_task(engine.run_loop(), name="eden-simulation")
    app.state.simulation_task = loop_task
    autosave_task = asyncio.create_task(game_sessions.autosave_loop(), name="eden-autosave")
    app.state.autosave_task = autosave_task
    try:
        yield
    finally:
        engine.running = False
        loop_task.cancel()
        with suppress(asyncio.CancelledError):
            await loop_task
        autosave_task.cancel()
        with suppress(asyncio.CancelledError):
            await autosave_task
        if resident_task is not None:
            resident_task.cancel()
            with suppress(asyncio.CancelledError):
                await resident_task
        engine.resident_store.background_writes = False
        with suppress(Exception):  # EDEN_WINDOW: stop the chunk generator workers
            window_wire.close_chunk_service()
        await game_sessions.shutdown()
        with suppress(Exception):  # a derived index: never block or fail the shutdown
            engine.finalize_memory_graph()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


local_session_boundary = LocalSessionBoundary()
SESSION_CAPABILITY = local_session_boundary.capability
app.middleware("http")(local_session_boundary.dispatch)
app.include_router(build_model_router(lambda: engine))  # model plane: GET /model_status, POST /control/models; every role defaults to off
if chunk_routes_enabled():  # 1008 D8: GET /chunks, GET /chunk/{cx}/{cy}; engine independent, EDEN_CHUNK_ROUTES=1, default off
    app.include_router(build_chunk_router(lambda: engine, service_factory=window_wire.chunk_service_factory()))


@app.get("/bootstrap")
async def bootstrap():
    payload = {**engine._bootstrap_payload, "world_epoch": engine.world_epoch, "spatial": world_contract(engine),
               "launch": LAUNCH_CONFIG.status(), "session": game_sessions.status(),
               "session_capability": SESSION_CAPABILITY}
    maps = maps_block(engine)
    if maps is not None:  # authored maps only; legacy bootstrap keeps its exact key set
        payload["maps"] = maps
    if spaces_enabled() and maps is not None:  # 1008 P3 (EDEN_SPACES=1): additive; the spaces of the authored world
        payload["spaces"] = space_table(engine)
    return JSONResponse(payload)


def _etag_matches(header: str | None, sha256: str) -> bool:
    if not header:
        return False
    tags = [part.strip() for part in header.split(",")]
    return "*" in tags or any(tag.removeprefix("W/").strip('"') == sha256 for tag in tags)


@app.get("/map_file/{map_id}")
async def map_file(map_id: str, request: Request):
    """The exact bytes of a registered authored map file; ETag is the quoted sha256 of those bytes."""
    found = get_map_file(map_id)
    if found is None:
        return JSONResponse({"ok": False, "reason": "unknown_map"}, status_code=404)
    raw, sha256 = found
    headers = {"ETag": f'"{sha256}"', "Cache-Control": "no-cache"}
    if _etag_matches(request.headers.get("if-none-match"), sha256):
        return Response(status_code=304, headers=headers)
    return Response(content=raw, media_type="application/json", headers=headers)


@app.get("/session")
async def session_state():
    saves = await asyncio.to_thread(game_sessions.store.list_saves)
    return {**game_sessions.status(), "saves": saves}


async def _session_operation(operation, *args):
    try:
        return await operation(*args)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(503, f"Save storage unavailable: {exc}") from exc


@app.post("/session/new")
async def session_new(request: Request):
    payload = await request.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("name"), str):
        raise HTTPException(400, "A world name is required")
    return await _session_operation(game_sessions.new, payload["name"])


@app.post("/session/continue")
async def session_continue(request: Request):
    payload = await request.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("save_id"), str):
        raise HTTPException(400, "A save ID is required")
    return await _session_operation(game_sessions.continue_world, payload["save_id"])


@app.post("/session/save")
async def session_save():
    return await _session_operation(game_sessions.save)


@app.get("/frame")
async def frame():
    return JSONResponse(engine._frame_payload)


@app.get("/map_delta")
async def map_delta(
    since_state_version: int | None = None,
    since_geo_version: int | None = None,
):
    return JSONResponse(engine.get_map_delta_for(since_state_version, since_geo_version))


@app.get("/status")
async def status():
    return {
        "session": game_sessions.status(),
        "launch": LAUNCH_CONFIG.status(),
        "timing": engine.scheduler.status(),
        "world_epoch": engine.world_epoch,
        "decision": decision_service(engine).status(),
        "god": {**god_time_state(engine), "weather": str(engine._nature_state.get("weather", "clear"))},
        "runtime_profile": engine._runtime_profile,
        "persistence": {"pending_residents": len(engine.resident_store._dirty),
                        "errors": dict(engine.resident_store.save_errors)},
        "protocol":        PROTOCOL_VERSION,
        "tick":            engine.tick,
        "year":            round(engine.tick / _calendar.ticks_per_year(), 2),
        "pop":             engine.pop_count,
        "cap":             MAX_HUMANS,
        "entity_count":    engine.entity_count,
        "entity_cap":      MAX_ENTITIES,
        "running":         engine.running,
        "device":          engine.state.device,
        "map_name":        engine._map_name,
        "frame_id":        engine._frame_id,
        "geo_version":     engine._map_geo_version_sent,
        "state_version":   engine._map_state_version,
        "instincts":       list(iat.ACQUIRED_INSTINCTS.keys()),
        "agents": {
            "world_pending_decrees": engine.world_agent.pending_count(),
            "world_pending_reasoning": engine.world_agent.pending_reasoning_count(),
            "recent_world_decrees": engine.world_agent.history[-5:],
            "recent_world_reasoning": engine.world_agent.reasoning_history[-5:],
            "world_model_handler_configured": engine.world_model_handler is not None,
            "world_model_handler_type": None if engine.world_model_handler is None else type(engine.world_model_handler).__name__,
            "tiny_model_handler_configured": bool(
                engine.tiny_model_handler is not None or engine.resident_model_handler is not None
            ),
            "tiny_model_handler_type": None
            if (engine.tiny_model_handler is None and engine.resident_model_handler is None)
            else type(engine.tiny_model_handler if engine.tiny_model_handler is not None else engine.resident_model_handler).__name__,
            "mock_tiny_model_enabled": bool(getattr(engine, "mock_tiny_model_enabled", False)),
            "mock_reasoning_enabled": bool(getattr(engine, "mock_reasoning_enabled", False)),
            "recent_execution_runs": engine.execution_agent.history[-5:],
            "recent_human_decisions": engine.human_agent.history[-8:],
            "human_batching": engine.human_agent.status_snapshot(),
            "talk_runtime": engine.talk_agent.status_snapshot(),
            "tiny_model_runtime": engine.tiny_model_runtime.status_snapshot(),
            "orchestrator": engine.orchestrator.status_snapshot(),
            "resident_files": engine.resident_store.resident_count(),
            "player_control_sessions": engine.player_control.status_snapshot()["active_sessions"],
        },
        "lightrag": {
            "loaded": engine.light_rag is not None,
            "graph_path": str(LIGHTRAG_GRAPH_PATH),
            "max_retrieved": getattr(engine.light_rag, "max_retrieved", 20) if engine.light_rag is not None else 20,
        },
        "memory_rag": {
            "loaded": engine.memory_rag is not None,
            "graph_path": str(MEMORY_RAG_GRAPH_PATH),
            "max_retrieved": getattr(engine.memory_rag, "max_retrieved", 12) if engine.memory_rag is not None else 12,
            "pending_dirty": engine.resident_store.memory_dirty_count(),
            "stats": engine.memory_rag.stats() if engine.memory_rag is not None else None,
        },
        "inventory": {
            "inventory_count": len(engine.inventory_state.get("inventories", {})),
            "starter_storage_case_entity_id": engine._starter_storage_case_entity_id,
            "focus": engine._inventory_focus_payload(),
        },
        "execution": {
            "state_path": str(EXECUTION_STATE_PATH),
            "known_instinct_bits": engine.execution_agent.status_snapshot()["known_instinct_bits"],
            "last_error": engine.execution_agent.last_error,
            "limits": engine.execution_agent.limits_snapshot(),
        },
        "frontier": engine._frontier_state,
        "view_window": engine._view_window_state,
        "nature": engine._nature_state,
        "talk": engine.talk_agent.status_snapshot(),
        "control_runtime": engine.player_control.status_snapshot(),
        "player_control": engine.player_control.status_snapshot(),
    }


@app.post("/god_decree")
async def god_decree(request: Request):
    raw = await request.body()
    payload: Any
    try:
        payload = await request.json()
    except Exception:
        payload = {"god_decree": raw.decode("utf-8").strip()}
    queued = engine.world_agent.queue_decree(payload)
    query_text = ""
    sub_queries = None
    if isinstance(payload, dict):
        query_text = str(payload.get("god_decree") or payload.get("text") or payload.get("command") or "").strip()
        sq = payload.get("sub_queries")
        if isinstance(sq, list):
            sub_queries = [str(item) for item in sq if str(item).strip()]
    validation = None
    preview_follow_ups = None
    if isinstance(payload, dict) and "map_actions" in payload and "human_actions" in payload:
        validation = engine.execution_agent.validate_packet(payload, reserve_instinct_bits=False)
        preview_packet = validation.get("packet") or {
            "map_actions": list(payload.get("map_actions") or []),
            "human_actions": list(payload.get("human_actions") or []),
            "new_entities": list(payload.get("new_entities") or []),
            "new_instincts": list(payload.get("new_instincts") or []),
        }
        preview_follow_ups = engine.execution_agent._build_follow_up_plan(
            engine,
            preview_packet,
            validation.get("instinct_assignments", []),
            execution_ready=False,
            stage="preview",
        )
    retrieval = (
        engine.retrieve_light_rag_bundle(query_text, sub_queries=sub_queries)
        if query_text
        else None
    )
    return {
        **queued,
        "tick": engine.tick,
        "retrieval": retrieval,
        "validation": validation,
        "preview_follow_ups": preview_follow_ups,
    }


@app.post("/action_plan/validate")
async def action_plan_validate(request: Request):
    payload = await request.json()
    validation = engine.execution_agent.validate_packet(payload, reserve_instinct_bits=False)
    preview_packet = validation.get("packet") or {
        "map_actions": list(payload.get("map_actions") or []),
        "human_actions": list(payload.get("human_actions") or []),
        "new_entities": list(payload.get("new_entities") or []),
        "new_instincts": list(payload.get("new_instincts") or []),
    }
    validation["preview_follow_ups"] = engine.execution_agent._build_follow_up_plan(
        engine,
        preview_packet,
        validation.get("instinct_assignments", []),
        execution_ready=False,
        stage="preview",
    )
    return JSONResponse(validation)


@app.post("/rag/retrieve")
async def rag_retrieve(request: Request):
    payload = await request.json()
    query = str(payload.get("query", "")).strip()
    sub_queries = payload.get("sub_queries")
    if isinstance(sub_queries, list):
        sub_queries = [str(item) for item in sub_queries if str(item).strip()]
    else:
        sub_queries = None
    return JSONResponse(engine.retrieve_light_rag_bundle(query, sub_queries=sub_queries))


@app.post("/rag/register_tool")
async def rag_register_tool(request: Request):
    payload = await request.json()
    return JSONResponse(
        engine.register_light_rag_tool(
            name=str(payload["name"]),
            tier=str(payload.get("tier", "B")),
            signature=str(payload.get("signature", payload["name"])),
            description=str(payload.get("description", "")),
            handles_events=[
                str(item) for item in payload.get("handles_events", []) if str(item).strip()
            ],
            edges=list(payload.get("edges", [])),
        )
    )


@app.post("/memory/retrieve")
async def memory_retrieve(request: Request):
    payload = await request.json()
    human_id = str(payload.get("human_id", "")).strip()
    if not human_id:
        return JSONResponse({"ok": False, "reason": "missing_human_id"}, status_code=400)
    query = str(payload.get("query", "")).strip() or None
    return JSONResponse(engine.retrieve_memory_bundle(human_id=human_id, query=query))


@app.post("/memory/resync")
async def memory_resync(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    human_id = str(payload.get("human_id", "")).strip() or None
    save = bool(payload.get("save", True))
    return JSONResponse(engine.sync_memory_graph(human_id=human_id, save=save))


@app.get("/agent_status")
async def agent_status():
    return {
        "tick": engine.tick,
        "world_agent": {
            "pending": engine.world_agent.pending_count(),
            "pending_reasoning": engine.world_agent.pending_reasoning_count(),
            "history": engine.world_agent.history[-10:],
            "reasoning_history": engine.world_agent.reasoning_history[-10:],
            "mock_tiny_model_enabled": bool(getattr(engine, "mock_tiny_model_enabled", False)),
            "mock_reasoning_enabled": bool(getattr(engine, "mock_reasoning_enabled", False)),
        },
        "execution_agent": engine.execution_agent.status_snapshot(),
        "control_runtime": engine.player_control.status_snapshot(),
        "player_control": engine.player_control.status_snapshot(),
        "human_agent": {
            **engine.human_agent.status_snapshot(),
        },
        "talk_agent": engine.talk_agent.status_snapshot(),
        "tiny_model_runtime": engine.tiny_model_runtime.status_snapshot(),
        "orchestrator": engine.orchestrator.status_snapshot(),
        "memory_rag": engine.memory_rag.stats() if engine.memory_rag is not None else {
            "graph_path": str(MEMORY_RAG_GRAPH_PATH),
            "total_nodes": 0,
            "total_edges": 0,
            "type_counts": {},
        },
        "memory_rag_pending_dirty": engine.resident_store.memory_dirty_count(),
        "nature": engine._nature_state,
        "resident_count": engine.resident_store.resident_count(),
    }


@app.post("/control/claim")
async def control_claim(request: Request):
    payload = await request.json()
    controller_id = str(payload.get("controller_id", "local_player"))
    mode = str(payload.get("mode", "possess"))
    if str(mode).strip().lower() == "incarnate" or bool(payload.get("enter_world")):
        result = engine.incarnate_controller_human(
            controller_id=controller_id,
            preferred_name=str(
                payload.get("preferred_name")
                or payload.get("human_name")
                or payload.get("target_name")
                or ""
            ).strip()
            or None,
            sex=float(payload["sex"]) if payload.get("sex") is not None else None,
            age=float(payload["age"]) if payload.get("age") is not None else None,
            life_exp=float(payload["life_exp"]) if payload.get("life_exp") is not None else None,
        )
        if result.get("ok"):
            engine._force_frame_refresh = True
        return JSONResponse(
            result,
            status_code=200 if result.get("ok") or result.get("requires_name") else 400,
        )
    target_kind = str(payload.get("target_kind") or ("entity" if payload.get("entity_id") else "human"))
    result = engine.player_control.claim_target(
        engine,
        controller_id=controller_id,
        target_kind=target_kind,
        target_id=str(payload["target_id"]) if payload.get("target_id") else None,
        target_name=str(payload["target_name"]) if payload.get("target_name") else None,
        mode=mode,
        human_id=str(payload["human_id"]) if payload.get("human_id") else None,
        human_name=str(payload["human_name"]) if payload.get("human_name") else None,
        entity_id=str(payload["entity_id"]) if payload.get("entity_id") else None,
        entity_name=str(payload["entity_name"]) if payload.get("entity_name") else None,
    )
    if result.get("ok"):
        engine._force_frame_refresh = True
        if str(result.get("target_kind", "")) == "entity":
            engine._force_map_refresh = True
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


@app.post("/control/incarnate")
async def control_incarnate(request: Request):
    payload = await request.json()
    result = engine.incarnate_controller_human(
        controller_id=str(payload.get("controller_id", "local_player")),
        preferred_name=str(payload.get("preferred_name") or payload.get("human_name") or "").strip() or None,
        sex=float(payload["sex"]) if payload.get("sex") is not None else None,
        age=float(payload["age"]) if payload.get("age") is not None else None,
        life_exp=float(payload["life_exp"]) if payload.get("life_exp") is not None else None,
    )
    if result.get("ok"):
        engine._force_frame_refresh = True
    return JSONResponse(
        result,
        status_code=200 if result.get("ok") or result.get("requires_name") else 400,
    )


@app.post("/control/release")
async def control_release(request: Request):
    payload = await request.json()
    target_kind = str(payload.get("target_kind") or ("entity" if payload.get("entity_id") else "human"))
    result = engine.player_control.release_target(
        engine,
        controller_id=str(payload["controller_id"]) if payload.get("controller_id") else None,
        target_kind=target_kind if payload.get("target_kind") or payload.get("target_id") or payload.get("entity_id") or payload.get("human_id") else None,
        target_id=str(payload["target_id"]) if payload.get("target_id") else None,
        human_id=str(payload["human_id"]) if payload.get("human_id") else None,
        entity_id=str(payload["entity_id"]) if payload.get("entity_id") else None,
    )
    if result.get("ok"):
        engine._force_frame_refresh = True
        if str(result.get("target_kind", "")) == "entity":
            engine._force_map_refresh = True
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


@app.post("/control/input")
async def control_input(request: Request):
    payload = await request.json()
    stale = window_wire.stale_epoch(engine, payload)
    if stale is not None:
        return JSONResponse(stale, status_code=409)
    result = engine.player_control.submit_input(
        engine,
        controller_id=str(payload.get("controller_id", "local_player")),
        payload=payload,
    )
    if result.get("ok"):
        engine._force_frame_refresh = True
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


@app.post("/control/event")
async def control_event(request: Request):
    payload = await request.json()
    result = engine.player_control.submit_event(
        engine,
        controller_id=str(payload.get("controller_id", "local_player")),
        payload=payload,
    )
    if result.get("ok"):
        engine._force_frame_refresh = True
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


@app.get("/control/state")
async def control_state():
    return JSONResponse(engine.player_control.status_snapshot())


@app.get("/control/event_result")
async def control_event_result(controller_id: str, event_id: str, world_epoch: str, possession_epoch: str):
    result = engine.player_control.event_result(engine, controller_id, event_id, world_epoch, possession_epoch)
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


@app.get("/talk/state")
async def talk_state(controller_id: str = "local_player"):
    return JSONResponse(
        {
            "ok": True,
            "controller_id": controller_id,
            "feed": engine._talk_feed_payload(controller_id),
            "runtime": engine.talk_agent.status_snapshot(),
        }
    )


def _resolve_inventory_record_from_payload(payload: dict[str, Any], prefix: str) -> dict | None:
    inventory_id = str(payload.get(f"{prefix}_inventory_id", "")).strip()
    if inventory_id:
        return get_inventory(engine.inventory_state, inventory_id)
    owner_kind = str(payload.get(f"{prefix}_owner_kind", "")).strip()
    owner_id = str(payload.get(f"{prefix}_owner_id", "")).strip()
    if owner_kind and owner_id:
        return get_owner_inventory(engine.inventory_state, owner_kind, owner_id)
    container_id = str(payload.get(f"{prefix}_container_id", "")).strip()
    if container_id:
        return get_container_inventory(engine.inventory_state, container_id)
    return None


@app.get("/inventory/focus")
async def inventory_focus(controller_id: str = "local_player"):
    return JSONResponse({"ok": True, "focus": engine._inventory_focus_payload(controller_id)})


@app.get("/inventory/owner/{owner_kind}/{owner_id}")
async def inventory_owner(owner_kind: str, owner_id: str):
    record = get_owner_inventory(engine.inventory_state, owner_kind, owner_id)
    if record is None:
        return JSONResponse({"ok": False, "reason": "inventory_not_found"}, status_code=404)
    return JSONResponse(
        {
            "ok": True,
            "inventory": inventory_prompt_payload(record, limit=12),
            "summary": summarize_inventory(record, limit=8),
        }
    )


@app.get("/inventory/container/{container_id}")
async def inventory_container(container_id: str):
    record = get_container_inventory(engine.inventory_state, container_id)
    if record is None:
        return JSONResponse({"ok": False, "reason": "container_not_found"}, status_code=404)
    return JSONResponse(
        {
            "ok": True,
            "inventory": container_prompt_payload(record, limit=12),
            "summary": summarize_inventory(record, limit=8),
        }
    )


@app.get("/commands/{command_id}")
async def command_result(command_id: str):
    result = engine.command_inbox.result(command_id)
    return JSONResponse(result or {"ok": False, "reason": "command_not_found"}, status_code=200 if result else 404)


def _submit_inventory_command(action, payload):
    result = engine.command_inbox.submit(engine, action, payload)
    return JSONResponse(result, status_code=202 if result.get("status") == "received" else 200 if result.get("ok") else 400)


@app.post("/control/portal")
async def control_portal(request: Request):
    return _submit_inventory_command("portal", await request.json())


@app.post("/god/heal")
async def god_heal(request: Request):
    return _submit_inventory_command("god_heal", await request.json())


@app.post("/god/spawn_resource")
async def god_spawn_resource(request: Request):
    return _submit_inventory_command("god_spawn_resource", await request.json())


@app.post("/god/weather")
async def god_weather(request: Request):
    return _submit_inventory_command("god_weather", await request.json())


@app.post("/god/time")
async def god_time(request: Request):
    return _submit_inventory_command("god_time", await request.json())


@app.get("/god/inspect/{resident_id}")
async def god_inspect(resident_id: str):
    result = inspect_resident(engine, resident_id)
    return JSONResponse(result, status_code=200 if result.get("ok") else 404)


@app.post("/commission/request")
async def commission_request(request: Request):
    return _submit_inventory_command("commission_request", await request.json())


@app.post("/commission/cancel")
async def commission_cancel(request: Request):
    return _submit_inventory_command("commission_cancel", await request.json())


@app.post("/commission/collect")
async def commission_collect(request: Request):
    return _submit_inventory_command("commission_collect", await request.json())


@app.get("/commission/state")
async def commission_state_route(controller_id: str = "local_player"):
    payload = commission_state_payload(engine, controller_id)
    return JSONResponse(payload, status_code=200 if payload.get("ok") else 404)


@app.post("/inventory/transfer")
async def inventory_transfer(request: Request):
    return _submit_inventory_command("transfer", await request.json())


@app.post("/inventory/equip_main_hand")
async def inventory_equip_main_hand(request: Request):
    return _submit_inventory_command("equip", await request.json())


@app.post("/inventory/spend")
async def inventory_spend(request: Request):
    payload = await request.json()
    owner_kind = str(payload.get("owner_kind", "human")).strip() or "human"
    owner_id = str(payload.get("owner_id", "")).strip()
    amount = int(payload.get("amount", 0))
    record = get_owner_inventory(engine.inventory_state, owner_kind, owner_id)
    if record is None:
        return JSONResponse({"ok": False, "reason": "inventory_not_found"}, status_code=404)
    result = spend_currency(record, amount)
    engine._force_frame_refresh = True
    return JSONResponse({**result, "inventory": inventory_prompt_payload(record, limit=12)}, status_code=200 if result.get("ok") else 400)


@app.post("/inventory/spawn_storage_case")
async def inventory_spawn_storage_case(request: Request):
    payload = await request.json()
    center_x = payload.get("x")
    center_y = payload.get("y")
    if center_x is None or center_y is None:
        focus = engine._inventory_focus_payload(str(payload.get("controller_id", "local_player")))
        if focus is not None:
            owner_id = str(focus.get("owner_id", ""))
            for slot, human_id in enumerate(engine._human_uid_by_slot):
                if human_id == owner_id:
                    center_x = float(engine.state.h_tensor[slot, X]) + 18.0
                    center_y = float(engine.state.h_tensor[slot, Y]) + 12.0
                    break
    if center_x is None or center_y is None:
        center_x = MAP_WIDTH * 0.5
        center_y = MAP_HEIGHT * 0.5
    entity_id = engine._spawn_storage_case_at(float(center_x), float(center_y), seed_contents=bool(payload.get("seed_contents", True)))
    if entity_id is None:
        return JSONResponse({"ok": False, "reason": "spawn_failed"}, status_code=400)
    engine._force_map_refresh = True
    engine._force_frame_refresh = True
    return JSONResponse({"ok": True, "entity_id": entity_id})


@app.post("/view/window")
async def view_window(request: Request):
    payload = await request.json()
    stale = window_wire.stale_epoch(engine, payload)
    if stale is not None:
        return JSONResponse(stale, status_code=409)
    center_x = float(payload.get("center_x", MAP_WIDTH / 2.0))
    center_y = float(payload.get("center_y", MAP_HEIGHT / 2.0))
    view_world_w = float(payload.get("view_world_w", 0.0))
    view_world_h = float(payload.get("view_world_h", 0.0))
    if view_world_w <= 0.0 or view_world_h <= 0.0:
        return JSONResponse(
            {
                "ok": False,
                "reason": "invalid_view_window",
                "view_world_w": view_world_w,
                "view_world_h": view_world_h,
            },
            status_code=400,
        )

    engine._view_window_state = {
        "center_x": round(center_x, 2),
        "center_y": round(center_y, 2),
        "view_world_w": round(view_world_w, 2),
        "view_world_h": round(view_world_h, 2),
        "preload_margin": round(float(payload.get("preload_margin", 160.0)), 2),
        "source": str(payload.get("source", "client_view")),
        "controller_id": str(payload.get("controller_id", "")),
        "zoom": round(float(payload.get("zoom", 1.0)), 4),
        "updated_tick": engine.tick,
    }
    return JSONResponse({"ok": True, **engine._view_window_state, **window_wire.stamp(engine)})


@app.get("/view/state")
async def view_state():
    return JSONResponse(engine._view_window_state)


@app.post("/human_view/window")
async def human_view_window(request: Request):
    payload = await request.json()
    stale = window_wire.stale_epoch(engine, payload)
    if stale is not None:
        return JSONResponse(stale, status_code=409)
    result = engine.get_human_view_window(payload)
    maps = maps_block(engine)
    if maps is not None and isinstance(result, dict) and result.get("ok"):
        result = {**result, "maps": maps}
    if isinstance(result, dict):
        result = {**result, **window_wire.stamp(engine)}
    return JSONResponse(result)


@app.post("/control/claim_target")
async def control_claim_target(request: Request):
    return await control_claim(request)


@app.post("/control/release_target")
async def control_release_target(request: Request):
    return await control_release(request)


@app.get("/resident/{human_id}")
async def resident(human_id: str):
    payload = engine.resident_store.get(human_id)
    if payload is None:
        return JSONResponse({"error": "resident_not_found", "id": human_id}, status_code=404)
    return JSONResponse(payload)


# ----------------------------------------------------------------------
# Compatibility endpoints
# ----------------------------------------------------------------------

@app.get("/get_map")
async def get_map():
    return JSONResponse(engine._legacy_map_payload)


@app.get("/get_schema")
async def get_schema():
    return JSONResponse(engine._schema_payload["map_schema"])


@app.get("/get_agents")
async def get_agents():
    return JSONResponse(engine._legacy_agent_payload)


@app.get("/map_version")
async def map_version():
    return {
        "version": engine._map_state_version,
        "map_name": engine._map_name,
        "geo_version": engine._map_geo_version_sent,
    }


@app.post("/load_instinct/{name}/{bit}")
async def load_instinct(name: str, bit: int, priority: int = 80):
    if not LAUNCH_CONFIG.development:
        raise HTTPException(403, "Dynamic code loading requires a development profile")
    success = engine.load_dynamic_instinct(name, bit, priority)
    return {"success": success, "name": name, "bit": bit}


@app.post("/set_map/{name}")
async def set_map(name: str):
    if not LAUNCH_CONFIG.development:
        raise HTTPException(403, "Map reset requires a development profile")
    engine.reset_world()
    await create_genesis(engine, map_name=name)
    return {"success": True, "map_name": name}


@app.post("/testing/render_test_village")
async def testing_render_test_village(request: Request):
    if not LAUNCH_CONFIG.development:
        raise HTTPException(403, "Render fixtures require a development profile")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    result = await load_render_test_village(
        engine,
        controller_id=str(payload.get("controller_id", "local_player")),
        auto_claim=bool(payload.get("auto_claim", True)),
    )
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


if __name__ == "__main__":
    uvicorn.run(app, host=LAUNCH_CONFIG.host, port=LAUNCH_CONFIG.port, access_log=False)
