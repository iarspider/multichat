import asyncio
import datetime
import json
import logging
import os
import random
import string
import uuid
import webbrowser
from urllib.parse import urlparse, parse_qs

import requests
from dotenv import load_dotenv
from websockets.client import connect # noqa

trovo_redirect_url = "https://fr.iarazumov.com/trovo"

import http.client as http_client

http_client.HTTPConnection.debuglevel = 1


def random_string(size):
    letters = string.ascii_lowercase + string.ascii_uppercase + string.digits
    return "".join(random.choice(letters) for i in range(size))


def parse_message(message):
    parsed_message = {"tags": None, "source": None, "command": None, "parameters": None}

    idx = 0
    raw_tags_component = None
    raw_source_component = None
    raw_command_component = None
    raw_parameters_component = None

    if message[idx] == "@":
        end_idx = message.index(" ")
        raw_tags_component = message[1:end_idx]
        idx = end_idx + 1

    if message[idx] == ":":
        idx += 1
        end_idx = message.index(" ", idx)
        raw_source_component = message[idx:end_idx]
        idx = end_idx + 1

    end_idx = message.index(":", idx) if -1 != message.find(":", idx) else len(message)
    raw_command_component = message[idx:end_idx].strip()

    if end_idx != len(message):
        idx = end_idx + 1
        raw_parameters_component = message[idx:]

    parsed_message["command"] = parse_command(raw_command_component)

    if parsed_message["command"] is None:
        return None
    else:
        if raw_tags_component is not None:
            parsed_message["tags"] = parse_tags(raw_tags_component)

        parsed_message["source"] = parse_source(raw_source_component)
        parsed_message["parameters"] = raw_parameters_component

        if raw_parameters_component and raw_parameters_component[0] == "!":
            parsed_message["command"] = parse_parameters(
                raw_parameters_component, parsed_message["command"]
            )

    return parsed_message


def parse_tags(tags):
    tags_to_ignore = {"client-nonce": None, "flags": None}

    dict_parsed_tags = {}
    parsed_tags = tags.split(";")

    for tag in parsed_tags:
        parsed_tag = tag.split("=")
        tag_value = parsed_tag[1] if parsed_tag[1] != "" else None

        match parsed_tag[0]:
            case "badges" | "badge-info":
                if tag_value:
                    dict_badges = {}
                    badges = tag_value.split(",")
                    for pair in badges:
                        badge_parts = pair.split("/")
                        dict_badges[badge_parts[0]] = badge_parts[1]
                    dict_parsed_tags[parsed_tag[0]] = dict_badges
                else:
                    dict_parsed_tags[parsed_tag[0]] = None

            case "emotes":
                if tag_value:
                    dict_emotes = {}
                    emotes = tag_value.split("/")
                    for emote in emotes:
                        emote_parts = emote.split(":")
                        text_positions = []
                        positions = emote_parts[1].split(",")
                        for position in positions:
                            position_parts = position.split("-")
                            text_positions.append(
                                {
                                    "startPosition": position_parts[0],
                                    "endPosition": position_parts[1],
                                }
                            )
                        dict_emotes[emote_parts[0]] = text_positions
                    dict_parsed_tags[parsed_tag[0]] = dict_emotes
                else:
                    dict_parsed_tags[parsed_tag[0]] = None

            case "emote-sets":
                emote_set_ids = tag_value.split(",")
                dict_parsed_tags[parsed_tag[0]] = emote_set_ids

            case _:
                if parsed_tag[0] not in tags_to_ignore:
                    dict_parsed_tags[parsed_tag[0]] = tag_value

    return dict_parsed_tags


def parse_command(raw_command_component):
    parsed_command = None
    command_parts = raw_command_component.split(" ")

    match command_parts[0]:
        case "JOIN" | "PART" | "NOTICE" | "CLEARCHAT" | "HOSTTARGET" | "PRIVMSG":
            parsed_command = {"command": command_parts[0], "channel": command_parts[1]}

        case "PING":
            parsed_command = {"command": command_parts[0]}

        case "CAP":
            parsed_command = {
                "command": command_parts[0],
                "isCapRequestEnabled": True if command_parts[2] == "ACK" else False,
            }

        case "GLOBALUSERSTATE":
            parsed_command = {"command": command_parts[0]}

        case "USERSTATE" | "ROOMSTATE":
            parsed_command = {"command": command_parts[0], "channel": command_parts[1]}

        case "RECONNECT":
            print(
                "The Twitch IRC server is about to terminate the connection for "
                "maintenance."
            )
            parsed_command = {"command": command_parts[0]}

        case "421":
            print(f"Unsupported IRC command: {command_parts[2]}")
            return None

        case "001":
            parsed_command = {"command": command_parts[0], "channel": command_parts[1]}

        case "002" | "003" | "004" | "353" | "366" | "372" | "375" | "376":
            print(f"Numeric message: {command_parts[0]}")
            return None

        case _:
            print(f"\nUnexpected command: {command_parts[0]}\n")
            return None

    return parsed_command


def parse_source(raw_source_component):
    if raw_source_component is None:
        return None
    else:
        source_parts = raw_source_component.split("!")
        return {
            "nick": source_parts[0] if len(source_parts) == 2 else None,
            "host": source_parts[1] if len(source_parts) == 2 else source_parts[0],
        }


def parse_parameters(raw_parameters_component, command):
    idx = 0
    command_parts = raw_parameters_component[idx + 1 :].strip()
    params_idx = command_parts.find(" ")

    if params_idx == -1:
        command["botCommand"] = command_parts[:]
    else:
        command["botCommand"] = command_parts[:params_idx].strip()
        command["botCommandParams"] = command_parts[params_idx:].strip()

    return command


async def hello_twitch():
    async with connect("wss://irc-ws.chat.twitch.tv:443") as websocket:
        await websocket.send(f"PASS {os.getenv('TWITCH_PASSWORD')}\r\n")
        await websocket.send(f"NICK {os.getenv('TWITCH_USER')}\r\n")
        await websocket.send(f"JOIN #{os.getenv('TWITCH_CHANNEL')}\r\n")
        async for message in websocket:
            for msg_ in message.splitlines():
                msg_data = parse_message(msg_)
                if not msg_data:
                    continue

                if msg_data["command"]["command"] == "PING":
                    await websocket.send(f"PONG {msg_data['parameters']}")
                elif msg_data["command"]["command"] == "PRIVMSG":
                    print(
                        f"{msg_data['source']['nick']} sent message "
                        f"{msg_data['parameters']}"
                    )


async def trovo_send_ping(socket, nonce):
    await socket.send(f'{{"type": "PING", "nonce": "{nonce}"}}')


def trovo_refresh_token(old_token):
    now = datetime.datetime.now()
    res = requests.post(
        "https://open-api.trovo.live/openplatform/refreshtoken",
        headers={
            "Accept": "application/json",
            "client-id": os.getenv("TROVO_CLIENT_ID"),
        },
        json={
            "client_secret": os.getenv("TROVO_CLIENT_SECRET"),
            "grant_type": "refresh_token",
            "refresh_token": old_token,
        },
    )
    res.raise_for_status()
    new_token = res.json()
    new_token["expires"] = int(
        round((now + datetime.timedelta(seconds=new_token["expires_in"])).timestamp())
    )
    with open("trovo.json", "w") as f:
        json.dump(res.json(), f)

    return new_token


def trovo_get_token():
    now = datetime.datetime.now()
    if os.path.exists("trovo.json"):
        token = json.load(open("trovo.json", "r"))
        if token.get("expires", 0) < int(round(now.timestamp())):
            return trovo_refresh_token(token["refresh_token"])
        else:
            return token

    trovo_redirect_url = "https%3A%2F%2Ffr.iarazumov.com%2Ftrovo"
    webbrowser.open(
        f"https://open.trovo.live/page/login.html?client_id="
        f"{os.getenv('trovo_client_id')}"
        f"&response_type=code&scope=chat_connect+send_to_my_channel+chat_send_self"
        f"+manage_messages&redirect_uri="
        f"{trovo_redirect_url}&state={random_string(30)}"
    )

    ans = input("Please input redirection URL\n> ")

    ans = ans.strip()
    qs = urlparse(ans).query
    qps = parse_qs(qs)
    temp_token = qps["code"][0]

    res = requests.post(
        "https://open-api.trovo.live/openplatform/exchangetoken",
        headers={
            "Accept": "application/json",
            "client-id": os.getenv("TROVO_CLIENT_ID"),
            "Content-Type": "application/json",
        },
        json={
            "client_secret": os.getenv("TROVO_CLIENT_SECRET"),
            "grant_type": "authorization_code",
            "code": temp_token,
            "redirect_uri": trovo_redirect_url,
        },
    )

    res.raise_for_status()
    ans = res.json()
    ans["expires"] = int(
        round((now + datetime.timedelta(seconds=ans["expires_in"])).timestamp())
    )
    with open("trovo.json", "w") as f:
        json.dump(ans, f)

    return ans


async def hello_trovo():
    token = trovo_get_token()["access_token"]

    res = requests.get(
        "https://open-api.trovo.live/openplatform/chat/token",
        headers={
            "Accept": "application/json",
            "Client-ID": os.getenv("TROVO_CLIENT_ID"),
            "Authorization": f"OAuth {token}",
        },
    )
    res.raise_for_status()

    resj = res.json()
    chat_token = resj["token"]
    print("Got chat token", chat_token)

    nonce = str(uuid.uuid4())

    async with connect("wss://open-chat.trovo.live/chat") as websocket:
        await websocket.send(
            f'{{"type": "AUTH","nonce": "{nonce}","data": {{"token": "'
            f'{chat_token}"}}}}\r\n'
        )

        resp = await websocket.recv()
        print("response from AUTH", resp)
        await trovo_send_ping(websocket, nonce)

        async for message in websocket:
            now = datetime.datetime.now()
            print(f"Received: {message}")
            msg = json.loads(message)
            if msg["type"] == "PONG":
                asyncio.get_running_loop().call_later(
                    msg["data"]["gap"],
                    lambda: asyncio.ensure_future(trovo_send_ping(websocket, nonce)),
                )
            elif msg["type"] == "CHAT":
                for chatmsg in msg["data"].get("chats", []):
                    if chatmsg["type"] != 0:
                        continue

                    send_time = datetime.datetime.fromtimestamp(chatmsg["send_time"])
                    if (now - send_time).seconds > 5:
                        continue

                    print(f"User {chatmsg['nick_name']} says: {chatmsg['content']}")


async def main():
    logging.basicConfig()
    logging.getLogger().setLevel(logging.DEBUG)
    requests_log = logging.getLogger("requests.packages.urllib3")
    requests_log.setLevel(logging.DEBUG)
    requests_log.propagate = True

    async with asyncio.TaskGroup() as tg:
        tg.create_task(hello_twitch())
        tg.create_task(hello_trovo())

    # await asyncio.gather(asyncio.create_task())
    # await asyncio.ensure_future(hello_trovo())


if __name__ == "__main__":
    load_dotenv()

    asyncio.run(main(), debug=False)
