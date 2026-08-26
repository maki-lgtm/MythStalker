import requests
import json
import os
import time
from datetime import datetime

# ---------- CONFIGURATION (from secrets) ----------
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
GAME_WATCH_ACCOUNTS = json.loads(os.getenv("GAME_WATCH_ACCOUNTS", "[]"))
BADGE_WATCH_GAMES = json.loads(os.getenv("BADGE_WATCH_GAMES", "[]"))
GROUP_RANK_WATCH = json.loads(os.getenv("GROUP_RANK_WATCH", "[]"))
ONLINE_WATCH_USERS = json.loads(os.getenv("ONLINE_WATCH_USERS", "[]"))

STATE_FILE = "state.json"

# ---------- ROBLOX API HELPERS ----------
def fetch_json(url, params=None, headers=None, method="GET", json_data=None):
    time.sleep(0.2)
    try:
        if method == "GET":
            resp = requests.get(url, params=params, headers=headers, timeout=10)
        else:
            resp = requests.post(url, json=json_data, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None

def get_user_games(user_id):
    data = fetch_json(f"https://games.roblox.com/v2/users/{user_id}/games")
    if data and "data" in data:
        return [g["id"] for g in data["data"] if g.get("id")]
    return []

def get_group_games(group_id):
    data = fetch_json(f"https://games.roblox.com/v2/groups/{group_id}/games")
    if data and "data" in data:
        return [g["id"] for g in data["data"] if g.get("id")]
    return []

def get_game_badges(game_id):
    data = fetch_json(f"https://badges.roblox.com/v1/games/{game_id}/badges", params={"limit": 100})
    if data and "data" in data:
        return [b["id"] for b in data["data"]]
    return []

def get_group_members(group_id, rank):
    members = []
    cursor = ""
    while True:
        url = f"https://groups.roblox.com/v1/groups/{group_id}/roles/{rank}/users"
        params = {"limit": 100, "cursor": cursor} if cursor else {"limit": 100}
        data = fetch_json(url, params=params)
        if not data or "data" not in data:
            break
        for user in data["data"]:
            members.append(user["user"]["id"])
        cursor = data.get("nextPageCursor")
        if not cursor:
            break
    return members

def get_user_presence(user_ids):
    url = "https://presence.roblox.com/v1/presence/users"
    payload = {"userIds": user_ids}
    data = fetch_json(url, method="POST", json_data=payload)
    if data:
        presence = {}
        for user in data.get("userPresences", []):
            presence[user["userId"]] = {
                "online": user["userPresenceType"] == 1,
                "last_online": user.get("lastOnline", None)
            }
        return presence
    return {}

# ---------- STATE MANAGEMENT ----------
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"games": {}, "badges": {}, "members": {}, "online": {}}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ---------- NOTIFICATION ----------
def send_discord(message):
    if not DISCORD_WEBHOOK:
        print("No Discord webhook; printing message:")
        print(message)
        return
    data = {"content": message}
    try:
        requests.post(DISCORD_WEBHOOK, json=data, timeout=5)
    except Exception as e:
        print(f"Discord send error: {e}")

# ---------- MAIN CHECKS ----------
def main():
    first_run = not os.path.exists(STATE_FILE)
    state = load_state()
    changes = []

    # 1. New games from watched accounts
    for acc in GAME_WATCH_ACCOUNTS:
        acc_id = acc["id"]
        acc_type = acc["type"]
        key = f"{acc_type}_{acc_id}"
        current_games = set()
        if acc_type == "user":
            current_games = set(get_user_games(acc_id))
        elif acc_type == "group":
            current_games = set(get_group_games(acc_id))
        else:
            continue

        previous_games = set(state["games"].get(key, []))
        new_games = current_games - previous_games
        if new_games:
            names = []
            for gid in new_games:
                info = fetch_json(f"https://games.roblox.com/v1/games/{gid}")
                name = info.get("name", f"ID {gid}") if info else f"ID {gid}"
                names.append(f"[{name}](https://www.roblox.com/games/{gid})")
            changes.append(f"**New game(s) from {acc_type} {acc_id}**: {', '.join(names)}")
            state["games"][key] = list(current_games)

    # 2. New badges from watched games
    for game_id in BADGE_WATCH_GAMES:
        current_badges = set(get_game_badges(game_id))
        previous_badges = set(state["badges"].get(str(game_id), []))
        new_badges = current_badges - previous_badges
        if new_badges:
            names = []
            for bid in new_badges:
                info = fetch_json(f"https://badges.roblox.com/v1/badges/{bid}")
                name = info.get("name", f"ID {bid}") if info else f"ID {bid}"
                names.append(f"{name} (ID {bid})")
            changes.append(f"**New badge(s) in game {game_id}**: {', '.join(names)}")
            state["badges"][str(game_id)] = list(current_badges)

    # 3. New members in group ranks
    for watch in GROUP_RANK_WATCH:
        group_id = watch["groupId"]
        rank = watch["rank"]
        key = f"{group_id}_{rank}"
        current_members = set(get_group_members(group_id, rank))
        previous_members = set(state["members"].get(key, []))
        new_members = current_members - previous_members
        if new_members:
            usernames = []
            for uid in new_members:
                info = fetch_json(f"https://users.roblox.com/v1/users/{uid}")
                name = info.get("name", f"ID {uid}") if info else f"ID {uid}"
                usernames.append(f"{name} ({uid})")
            changes.append(f"**New member(s) in group {group_id}, rank {rank}**: {', '.join(usernames)}")
            state["members"][key] = list(current_members)

    # 4. Online status of watched users
    if ONLINE_WATCH_USERS:
        presence = get_user_presence(ONLINE_WATCH_USERS)
        for uid in ONLINE_WATCH_USERS:
            prev = state["online"].get(str(uid), False)
            curr = presence.get(uid, {}).get("online", False)
            if curr != prev:
                if curr and not prev:
                    info = fetch_json(f"https://users.roblox.com/v1/users/{uid}")
                    name = info.get("name", f"ID {uid}") if info else f"ID {uid}"
                    changes.append(f"**{name} ({uid}) is now ONLINE!**")
                state["online"][str(uid)] = curr

    save_state(state)

    # Only send notifications if this is NOT the first run (to avoid spam)
    if changes and not first_run:
        message = "🔔 **Roblox Updates**\n" + "\n".join(changes)
        send_discord(message)
        print(f"Sent {len(changes)} updates.")
    elif first_run:
        print("First run - state seeded. No notifications sent.")
    else:
        print(f"No changes at {datetime.now().isoformat()}.")

if __name__ == "__main__":
    main()
  
