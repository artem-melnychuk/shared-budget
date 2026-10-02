"""Made-up members and Telegram payloads. No real people, chats or receipts."""

from budget.members import Members

ALEX_ID = 1001
SAM_ID = 1002
STRANGER_ID = 9999
CHAT_ALEX = 1001  # private chat with the bot has the user's id

ENV = {
    "MEMBER_1_KEY": "alex",
    "MEMBER_1_TELEGRAM_ID": str(ALEX_ID),
    "MEMBER_1_NAMES": "Alex Example",
    "MEMBER_2_KEY": "sam",
    "MEMBER_2_TELEGRAM_ID": str(SAM_ID),
    "MEMBER_2_NAMES": "Sam Example, Sammy",
}

# 2026-03-14 10:15:00 UTC and a month later
T_ORIGINAL = 1773483300
T_FORWARD = 1776161700


def members() -> Members:
    return Members.from_env(ENV)


def user(user_id, first, last=None):
    u = {"id": user_id, "is_bot": False, "first_name": first}
    if last:
        u["last_name"] = last
    return u


ALEX = user(ALEX_ID, "Alex", "Example")
SAM = user(SAM_ID, "Sam", "Example")


def photo_sizes(unique):
    return [
        {"file_id": f"small-{unique}", "file_unique_id": f"s-{unique}", "width": 90, "height": 120, "file_size": 1500},
        {"file_id": f"big-{unique}", "file_unique_id": unique, "width": 960, "height": 1280, "file_size": 98000},
        {"file_id": f"mid-{unique}", "file_unique_id": f"m-{unique}", "width": 320, "height": 427, "file_size": 15000},
    ]


def update(message_id, *, sender=ALEX, origin=None, date=T_FORWARD, **content):
    message = {
        "message_id": message_id,
        "from": sender,
        "chat": {"id": sender["id"], "type": "private", "first_name": sender["first_name"]},
        "date": date,
        **content,
    }
    if origin is not None:
        message["forward_origin"] = origin
        message["forward_date"] = origin["date"]
    return {"update_id": 500000 + message_id, "message": message}


def from_user(u, date=T_ORIGINAL):
    return {"type": "user", "sender_user": u, "date": date}


def from_hidden(name, date=T_ORIGINAL):
    return {"type": "hidden_user", "sender_user_name": name, "date": date}
