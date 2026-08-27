import requests
import json
import os
import time
from datetime import datetime

# ---------- CONFIGURATION (from secrets) ----------
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
GAME_WATCH_ACCOUNTS = json.loads(os.getenv("GAME_WATCH_ACCOUNTS", "[]"))
BADGE_WATCH_GAMES = json.loads(os.getenv("BADGE_WATCH_GAMES", "[]"))  # these are PLACE ids
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

def get_universe_id(place_id, state):
    """Roblox game URLs give you a PLACE id, but the game/badge APIs need a
    UNIVERSE id. This converts once and caches the result in state.json so
    we don't re-fetch it every single run."""
    key = str(place_id)
    cache = state.setdefault("universe_ids", {})
    if key in cache:
        return cache[key]
    data = fetch_json(f"https://apis.roblox.com/universes/v1/places/{place_id}/universe")
    if data and "universeId" in data:
        cache[key] = data["universeId"]
        return data["universeId"]
    print(f"Could not resolve universe id for place {place_id}")
    return None

def get_game_info(universe_id):
    """Batch-friendly endpoint; used here for a single universe at a time."""
    data = fetch_json("https://games.roblox.com/v1/games", params={"universeIds": universe_id})
    if data and data.get("data"):
        return data["data"][0]
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

def get_game_badges(universe_id):
    # Correct endpoint: badges are looked up by UNIVERSE id, not place id.
    data = fetch_json(
        f"https://badges.roblox.com/v1/universes/{universe_id}/badges",
        params={"limit": 100},
    )
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
    return {"games": {}, "badges": {}, "members": {}, "online": {}, "universe_ids": {}}

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
    state.setdefault("universe_ids", {})
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
                info = get_game_info(gid)
                name = info.get("name", f"ID {gid}") if info else f"ID {gid}"
                names.append(f"[{name}](https://www.roblox.com/games/{gid})")
            changes.append(f"**New game(s) from {acc_type} {acc_id}**: {', '.join(names)}")
        # Always update state, even with no new games, so removed games don't
        # get re-flagged as "new" later.
        state["games"][key] = list(current_games)

    # 2. New badges from watched games (BADGE_WATCH_GAMES holds PLACE ids)
    for place_id in BADGE_WATCH_GAMES:
        universe_id = get_universe_id(place_id, state)
        if not universe_id:
            continue
        current_badges = set(get_game_badges(universe_id))
        previous_badges = set(state["badges"].get(str(place_id), []))
        new_badges = current_badges - previous_badges
        if new_badges:
            names = []
            for bid in new_badges:
                info = fetch_json(f"https://badges.roblox.com/v1/badges/{bid}")
                name = info.get("name", f"ID {bid}") if info else f"ID {bid}"
                names.append(f"{name} (ID {bid})")
            changes.append(f"**New badge(s) in game {place_id}**: {', '.join(names)}")
        state["badges"][str(place_id)] = list(current_badges)

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
  
