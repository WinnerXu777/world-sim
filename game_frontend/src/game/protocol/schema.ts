import { z } from "zod";
import type {
  ActorView,
  BootstrapPayload,
  ControlSessionView,
  EventView,
  FramePayload,
  MapDeltaPayload,
  MapEntityView,
  StatusSnapshot,
} from "./types";

const numberish = z.coerce.number();

const mapEntitySchema = z
  .object({
    id: z.coerce.string(),
    name: z.coerce.string().optional(),
    type: z.coerce.string().optional(),
    type_label: z.coerce.string().optional(),
    anchor: z
      .object({
        x: numberish.catch(0),
        y: numberish.catch(0),
      })
      .optional(),
    x: numberish.optional(),
    y: numberish.optional(),
    scale: numberish.optional(),
    shape: z
      .object({
        kind: z.coerce.string().optional(),
      })
      .optional(),
  })
  .transform(
    (value): MapEntityView => ({
      id: value.id,
      name: value.name ?? value.type_label ?? value.type ?? value.id,
      type: value.type ?? value.type_label,
      typeLabel: value.type_label ?? value.type,
      x: value.x ?? value.anchor?.x ?? 0,
      y: value.y ?? value.anchor?.y ?? 0,
      radius: value.scale,
      shapeKind: value.shape?.kind,
    }),
  );

const actorSchema = z
  .object({
    id: z.coerce.string(),
    name: z.coerce.string().optional(),
    x: numberish.catch(0),
    y: numberish.catch(0),
    hp: numberish.optional(),
    max_hp: numberish.optional(),
    action: z.coerce.string().optional(),
    locomotion: z.coerce.string().optional(),
    controlled: z.coerce.boolean().optional(),
    player_avatar: z.coerce.boolean().optional(),
    controller_id: z.coerce.string().nullable().optional(),
    control_mode: z.coerce.string().nullable().optional(),
    render: z
      .object({
        action: z.coerce.string().optional(),
        locomotion: z.coerce.string().optional(),
      })
      .optional(),
  })
  .transform(
    (value): Omit<ActorView, "kind"> => ({
      id: value.id,
      name: value.name,
      x: value.x,
      y: value.y,
      hp: value.hp,
      maxHp: value.max_hp,
      action: value.action ?? value.render?.action,
      locomotion: value.locomotion ?? value.render?.locomotion,
      controlled: value.controlled,
      playerAvatar: value.player_avatar,
      controllerId: value.controller_id ?? null,
      controlMode: value.control_mode ?? null,
    }),
  );

const controlSchema = z
  .object({
    controller_id: z.coerce.string().catch("local_player"),
    target_id: z.coerce.string().catch(""),
    target_kind: z.coerce.string().catch(""),
    target_name: z.coerce.string().optional(),
    mode: z.coerce.string().optional(),
  })
  .transform(
    (value): ControlSessionView => ({
      controllerId: value.controller_id,
      targetId: value.target_id,
      targetKind: value.target_kind,
      targetName: value.target_name,
      mode: value.mode,
    }),
  );

const eventSchema = z
  .union([z.coerce.string(), z.record(z.string(), z.unknown())])
  .transform((value, ctx): EventView => {
    if (typeof value === "string") {
      return {
        id: crypto.randomUUID(),
        text: value,
      };
    }

    const textCandidate = value.text ?? value.message ?? value.summary ?? value.event;
    if (typeof textCandidate !== "string" || textCandidate.trim().length === 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Event payload missing readable text",
      });
      return z.NEVER;
    }

    return {
      id: typeof value.id === "string" ? value.id : crypto.randomUUID(),
      text: textCandidate,
      tick: typeof value.tick === "number" ? value.tick : undefined,
      category: typeof value.category === "string" ? value.category : undefined,
    };
  });

export const bootstrapSchema = z
  .object({
    world: z.object({
      width: numberish.catch(1200),
      height: numberish.catch(900),
      agent_frame_hz: numberish.catch(5),
      map_delta_hz: numberish.catch(1),
    }),
    map: z.object({
      entities: z.array(mapEntitySchema).catch([]),
      state_version: numberish.catch(-1),
      geo_version: numberish.catch(-1),
    }),
  })
  .transform(
    (value): BootstrapPayload => ({
      world: value.world,
      map: {
        entities: value.map.entities,
        stateVersion: value.map.state_version,
        geoVersion: value.map.geo_version,
      },
    }),
  );

export const frameSchema = z
  .object({
    frame_id: numberish.catch(0),
    tick: numberish.optional(),
    agents: z.array(actorSchema).catch([]),
    animals: z.array(actorSchema).catch([]),
    controls: z.array(controlSchema).catch([]),
    events: z.array(eventSchema).catch([]),
  })
  .transform(
    (value): FramePayload => ({
      frameId: value.frame_id,
      tick: value.tick,
      humans: value.agents.map((actor) => ({ ...actor, kind: "human" })),
      animals: value.animals.map((actor) => ({ ...actor, kind: "animal" })),
      controls: value.controls,
      events: value.events,
    }),
  );

export const mapDeltaSchema = z
  .object({
    state_version: numberish.catch(-1),
    geo_version: numberish.catch(-1),
    replace_all: z.coerce.boolean().catch(false),
    upserts: z.array(mapEntitySchema).catch([]),
    removed: z.array(z.coerce.string()).catch([]),
  })
  .transform(
    (value): MapDeltaPayload => ({
      stateVersion: value.state_version,
      geoVersion: value.geo_version,
      replaceAll: value.replace_all,
      upserts: value.upserts,
      removed: value.removed,
    }),
  );

export const statusSchema = z
  .object({
    protocol: z.coerce.string().catch("unknown"),
    tick: numberish.catch(0),
    running: z.coerce.boolean().catch(false),
    pop: numberish.catch(0),
    entity_count: numberish.catch(0),
    map_name: z.coerce.string().catch("unknown"),
  })
  .transform(
    (value): StatusSnapshot => ({
      protocol: value.protocol,
      tick: value.tick,
      running: value.running,
      pop: value.pop,
      entityCount: value.entity_count,
      mapName: value.map_name,
    }),
  );
