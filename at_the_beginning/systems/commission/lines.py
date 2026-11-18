"""Outcome-driven wording: the line is chosen from the DECIDED outcome, never the other way round (design §10).

``choose_line(role, code, resident_id, order_id)`` is deterministic: the variant is ``sha256(resident|order) % n``.
Every refusal line states the true reason because the options it came from were legal by construction.
"""
import hashlib

LINES = {
    "smith": {
        "accepted": ["I can make that. Two ingots and a bundle of wood, and thirty coin. Come back when the forge has cooled.",
                     "A blade? Aye, I have the iron. Leave the coin and give me the morning.",
                     "Done. The price is set aside; I will start at the forge."],
        "accepted_waiting": ["I'm short of iron right now, but I'll start once it arrives. I'll hold your coin until then."],
        "refused_no_materials": ["I have no iron to spare. Bring me ingots and I will forge it.",
                                 "Not without iron. My stock is empty."],
        "refused_no_forge": ["The forge is wrecked. I cannot work metal until it is mended.",
                             "No forge, no sword. Repair it first."],
        "refused_cannot_afford": ["That is thirty coin, and you do not have it.",
                                  "Come back when you can pay for it."],
        "refused_busy": ["My hands are full with other orders. Ask me again later."],
        "refused_distrust": ["I'll not forge for you. Not after what has passed between us.",
                             "Find another smith."],
        "refused_smith_unavailable": ["I am not able to take work right now."],
        "refused_unknown_recipe": ["I do not make that."],
        "refused_cannot_commission_yourself": ["You cannot commission yourself."],
        "duplicate_open_order": ["You already have an order with me. Be patient."],
        "ready": ["Your sword is finished. Come to the counter and collect it.",
                  "It is done. It's on the counter whenever you want it."],
        "delivered": ["Here it is. Treat it well.", "There. It will serve you."],
        "already_delivered": ["You already took that one."],
        "canceled": ["Very well. Your coin is returned."],
        "failed_forge_unavailable": ["The forge is wrecked and work has stopped. Your coin is returned."],
        "failed_no_materials": ["The iron never came. I have returned your coin."],
        "failed_smith_unavailable": ["The smith cannot finish this. Your coin is returned."],
        "blocked_customer_inventory_full": ["Your pack is full. Make room and I will hand it over."],
        "followup_gift": ["Iron fell out of a clear sky into my hands. I do not forget a thing like that.",
                          "Whatever blessed my forge, I am grateful. What can I make for you?"],
        "followup_delivered": ["How does the blade sit in your hand? No chips, I hope.",
                               "Back again? How is the sword treating you?"],
    },
}
GENERIC = {"accepted": "Agreed.", "refused": "No.", "ready": "It is ready.", "delivered": "Here you are."}


def choose_line(role, code, resident_id="", order_id=""):
    variants = LINES.get(role, {}).get(code)
    if not variants:
        base = code.split("_")[0]
        return GENERIC.get(base, "")
    digest = int(hashlib.sha256(f"{resident_id}|{order_id}".encode("utf-8")).hexdigest()[:8], 16)
    return variants[digest % len(variants)]


def known_codes(role="smith"):
    return sorted(LINES.get(role, {}))
