"""Function parameters the LLM sees for the action tools."""

from __future__ import annotations

from typing import Any


def action_function_parameters(definition: dict[str, Any]) -> tuple[dict, list[str]]:
    kind = definition.get("type")
    config = definition.get("config") or {}
    if kind == "book_appointment":
        actions = ["find_slots", "book", "my_appointments"]
        if config.get("allow_cancel", True):
            actions.append("cancel")
        return (
            {
                "action": {
                    "type": "string",
                    "enum": actions,
                    "description": (
                        "find_slots: free slots (optionally on 'date'); book: book 'start' "
                        "(only a start returned by find_slots); my_appointments: the "
                        "caller's upcoming appointments; cancel: cancel one of them."
                    ),
                },
                "date": {
                    "type": "string",
                    "description": "Day to search, YYYY-MM-DD (resolve 'demain', 'lundi'… first).",
                },
                "after_time": {
                    "type": "string",
                    "description": "Only slots from this local time, HH:MM (e.g. 14:00 for afternoon).",
                },
                "start": {
                    "type": "string",
                    "description": "Slot start to book, local YYYY-MM-DDTHH:MM, from find_slots.",
                },
                "name": {"type": "string", "description": "Caller's full name."},
                "email": {
                    "type": "string",
                    "description": "Caller's e-mail, if given.",
                },
                "reason": {
                    "type": "string",
                    "description": "Purpose of the appointment.",
                },
                "appointment_id": {
                    "type": "integer",
                    "description": "Appointment to cancel (from my_appointments).",
                },
            },
            ["action"],
        )
    if kind == "send_message":
        channel = config.get("channel") or "sms"
        properties: dict[str, Any] = {
            "message": {
                "type": "string",
                "description": (
                    "Text of the message, short and useful (address, link, reference…)."
                    if not config.get("template")
                    else "Details to insert in the message template ({{details}})."
                ),
            }
        }
        required = [] if config.get("template") else ["message"]
        if channel == "email":
            properties["email"] = {
                "type": "string",
                "description": "Recipient e-mail, spelled back to the caller first.",
            }
            properties["subject"] = {"type": "string", "description": "E-mail subject."}
            required.append("email")
        elif config.get("allow_other_recipient"):
            properties["to"] = {
                "type": "string",
                "description": "Mobile number to send to, only if not the caller's number.",
            }
        return properties, required
    if kind == "create_ticket":
        actions = ["create"] + (["lookup"] if config.get("allow_lookup", True) else [])
        properties = {
            "action": {
                "type": "string",
                "enum": actions,
                "description": "create: open a ticket; lookup: status of the caller's tickets.",
            },
            "subject": {
                "type": "string",
                "description": "Short summary of the request.",
            },
            "description": {
                "type": "string",
                "description": "Full details: what happened, what the caller expects, references.",
            },
            "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
            "name": {"type": "string", "description": "Caller's name."},
            "email": {"type": "string", "description": "Caller's e-mail, if given."},
            "ticket_number": {
                "type": "string",
                "description": "Ticket number given by the caller (lookup).",
            },
        }
        if config.get("categories"):
            properties["category"] = {
                "type": "string",
                "enum": list(config["categories"]),
            }
        return properties, ["action"]
    return {}, []
