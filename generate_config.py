import requests
import re
import json
from urllib.parse import urlparse

# ---------- HELPER FUNCTIONS ----------
def fetch_json(url, params=None, method="GET", json_data=None):
    try:
        if method == "GET":
            resp = requests.get(url, params=params, timeout=10)
        else:
            resp = requests.post(url, json=json_data, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None

def get_user_id_by_username(username):
    data = fetch_json("https://users.roblox.com/v1/usernames/users", method="POST",
                      json_data={"usernames": [username]})
    if data and "data" in data and len(data["data"]) > 0:
        return data["data"][0]["id"]
    return None

def get_game_creator(game_id):
    data = fetch_json(f"https://games.roblox.com/v1/games/{game_id}")
    if data and "creator" in data:
        return data["creator"]["id"], data["creator"]["type"]
    return None, None

def get_group_roles(group_id):
    data = fetch_json(f"https://groups.roblox.com/v1/groups/{group_id}/roles")
    if data and "data" in data:
        return {role["name"]: role["rank"] for role in data["data"]}
    return {}

# ---------- PARSE Games.txt ----------
def parse_games_txt(filename="Games.txt"):
    with open(filename, "r", encoding="utf-8") as f:
        lines = f.readlines()

    game_ids = []
    badge_ids = []
    user_profile_ids = []
    myth_usernames = []
    group_data = []

    current_section = None
    current_group = None
    group_ranks = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith("Games:"):
            current_section = "games"
            continue
        elif line.startswith("Myths for online:"):
            current_section = "myths"
            continue
        elif line.startswith("Groups:"):
            current_section = "groups"
            continue
        elif line.startswith("New game myths:"):
            continue

        if current_section == "games":
            if "roblox.com/games/" in line:
                match = re.search(r"roblox\.com/games/(\d+)", line)
                if match:
                    game_ids.append(int(match.group(1)))
            elif "roblox.com/badges/" in line:
                match = re.search(r"roblox\.com/badges/(\d+)", line)
                if match:
                    badge_ids.append(int(match.group(1)))
            elif "roblox.com/users/" in line:
                match = re.search(r"roblox\.com/users/(\d+)", line)
                if match:
                    user_profile_ids.append(int(match.group(1)))

        elif current_section == "myths":
            username = line.lstrip("-").strip()
            if username and not username.startswith("https"):
                myth_usernames.append(username)

        elif current_section == "groups":
            if "roblox.com/communities/" in line:
                if current_group and group_ranks:
                    group_data.append((current_group, group_ranks))
                    group_ranks = []
                match = re.search(r"communities/(\d+)", line)
                if match:
                    current_group = int(match.group(1))
            else:
                rank_name = line.lstrip("-").strip()
                if rank_name and current_group:
                    group_ranks.append(rank_name)

    if current_group and group_ranks:
        group_data.append((current_group, group_ranks))

    return game_ids, badge_ids, user_profile_ids, myth_usernames, group_data

# ---------- MAIN GENERATION ----------
def main():
    game_ids, badge_ids, user_profile_ids, myth_usernames, group_data = parse_games_txt()

    print("Parsed:", len(game_ids), "games,", len(badge_ids), "badges,", len(user_profile_ids), "user profiles,",
          len(myth_usernames), "myths,", len(group_data), "groups")

    # 1. Watch these games for new badges
    badge_watch_games = game_ids

    # 2. Collect game owners (creators) to watch for online status and new games
    owner_ids = set()
    for gid in game_ids:
        creator_id, creator_type = get_game_creator(gid)
        if creator_type == "User" and creator_id:
            owner_ids.add(creator_id)

    # 3. Build online watch list: myths + game owners + user profile IDs
    online_user_ids = set()
    for username in myth_usernames:
        uid = get_user_id_by_username(username)
        if uid:
            online_user_ids.add(uid)
        else:
            print(f"Could not find user: {username}")

    online_user_ids.update(owner_ids)
    online_user_ids.update(user_profile_ids)

    # 4. Watch these accounts (game owners) for new games
    game_watch_accounts = [{"type": "user", "id": uid} for uid in owner_ids]

    # 5. Convert group ranks
    group_rank_watch = []
    for group_id, rank_names in group_data:
        roles = get_group_roles(group_id)
        for rank_name in rank_names:
            rank_num = roles.get(rank_name)
            if rank_num is None:
                for name, num in roles.items():
                    if name.lower() == rank_name.lower():
                        rank_num = num
                        break
            if rank_num is not None:
                group_rank_watch.append({"groupId": group_id, "rank": rank_num})
            else:
                print(f"Rank '{rank_name}' not found in group {group_id}. Available: {list(roles.keys())}")

    online_watch_users = list(online_user_ids)

    print("\n--- COPY THESE VALUES INTO GITHUB SECRETS ---\n")
    print(f"GAME_WATCH_ACCOUNTS={json.dumps(game_watch_accounts)}")
    print(f"BADGE_WATCH_GAMES={json.dumps(badge_watch_games)}")
    print(f"GROUP_RANK_WATCH={json.dumps(group_rank_watch)}")
    print(f"ONLINE_WATCH_USERS={json.dumps(online_watch_users)}")
    print("\n--- END ---")

if __name__ == "__main__":
    main()
