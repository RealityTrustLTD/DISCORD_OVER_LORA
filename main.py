import asyncio
import threading
import time
import discord
from discord.ext import commands
from discord import app_commands, Embed, Color
from discord.ui import View, Button, Select, Modal, TextInput
import datetime
import requests
import json
import re

import meshtastic.tcp_interface
from pubsub import pub
from meshtastic.protobuf import channel_pb2  # Required for channel role checks

# --------------------------
# Configuration
# --------------------------
DISCORD_BOT_TOKEN = "YOUR_DISCORD_TOKEN"
DISCORD_CHANNEL_ID = YOUR_DISCORD_CHANNEL
MESHTASTIC_HOSTNAME = "YOUR_MESHTASTIC_API_URL" ##localhost will probably work if meshtastic is installed on the same machine as this script

# --------------------------
# Initialize Meshtastic Interface
# --------------------------
try:
    meshtastic_interface = meshtastic.tcp_interface.TCPInterface(hostname=MESHTASTIC_HOSTNAME)
except Exception as e:
    print(f"Error initializing Meshtastic TCP interface: {e}")
    exit(1)

# --------------------------
# Create Bot Client and Command Tree
# --------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# --------------------------
# Global Variables for Unattended Mode
# --------------------------
unattended_mode = False
conversation_history = {}  # Keyed by sender (discord user id or meshtastic node id)

# --------------------------
# Meshtastic Receive Callback
# --------------------------
def on_meshtastic_receive(packet, interface):
    try:
        decoded = packet.get("decoded", {})
        msg_channel = decoded.get("channel", 0)
        if msg_channel != 0:
            return
        text = decoded.get("text", "")
        sender = packet.get("fromId", "unknown node")
        if text:
            full_message = f"**[Mesh]** Message from {sender}: {text}"
            asyncio.run_coroutine_threadsafe(
                send_meshtastic_message(DISCORD_CHANNEL_ID, full_message),
                bot.loop
            )
            if unattended_mode:
                print(f"[DEBUG] Unattended mode active. Received message from node {sender}: {text}")
                asyncio.run_coroutine_threadsafe(
                    process_unattended_meshtastic_message(sender, text),
                    bot.loop
                )
    except Exception as ex:
        print(f"Error processing received Meshtastic message: {ex}")

async def send_meshtastic_message(channel_id, message):
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception as e:
            print(f"Could not fetch channel with ID {channel_id}: {e}")
            return
    await channel.send(message)

pub.subscribe(on_meshtastic_receive, "meshtastic.receive.text")

# --------------------------
# Helper Functions for Formatting
# --------------------------
def format_timestamp(ts: float) -> str:
    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def minutes_ago(ts: float) -> int:
    dt = datetime.datetime.fromtimestamp(ts)
    delta = datetime.datetime.now() - dt
    return int(delta.total_seconds() // 60)

def format_device_metrics(metrics: dict) -> str:
    parts = []
    if metrics.get("batteryLevel") is not None:
        parts.append(f"Battery: {metrics['batteryLevel']}%")
    if metrics.get("channelUtilization") is not None:
        parts.append(f"Channel Util: {metrics['channelUtilization']}%")
    if metrics.get("airUtilTx") is not None:
        parts.append(f"Tx Air Util: {metrics['airUtilTx']}%")
    return "\n".join(parts) if parts else "N/A"

# --------------------------
# Generic Dismiss View for Send Commands
# --------------------------
class DismissView(View):
    def __init__(self):
        super().__init__(timeout=180)
        btn = Button(label="Dismiss", style=discord.ButtonStyle.secondary, custom_id="dismiss_button")
        btn.callback = self.dismiss_callback
        self.add_item(btn)

    async def dismiss_callback(self, interaction: discord.Interaction):
        try:
            await interaction.message.delete()
        except Exception:
            await interaction.response.send_message("Could not dismiss message.", ephemeral=True)

# --------------------------
# Modal for Custom Direct Message Input (for node DM via /nodes detail, /info actions, or /dm)
# --------------------------
class DMModal(Modal, title="Send Direct Message"):
    message_input = TextInput(
        label="Message",
        placeholder="Enter the message to send",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=2000
    )

    def __init__(self, node_id: str):
        super().__init__()
        self.node_id = node_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            meshtastic_interface.sendText(
                self.message_input.value, destinationId=self.node_id, channelIndex=0
            )
            await interaction.response.send_message("Direct message sent to node.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error sending DM to node: {e}", ephemeral=True)

# --------------------------
# Refresh View for Read Commands (e.g. /info)
# --------------------------
class RefreshView(View):
    def __init__(self, refresh_callback):
        super().__init__(timeout=180)
        self.refresh_callback = refresh_callback
        btn = Button(label="Refresh", style=discord.ButtonStyle.primary, custom_id="refresh_button")
        btn.callback = self.refresh_button_callback
        self.add_item(btn)

    async def refresh_button_callback(self, interaction: discord.Interaction):
        new_embed, new_view = await self.refresh_callback(interaction)
        await interaction.response.edit_message(embed=new_embed, view=new_view)

# --------------------------
# Nodes Pagination and Detail Views
# --------------------------
class NodesPaginationView(View):
    def __init__(self, embeds: list[Embed], page_nodes: list[list[dict]]):
        super().__init__(timeout=180)
        self.embeds = embeds
        self.page_nodes = page_nodes
        self.current_page = 0
        self._build_components()

    def _build_components(self):
        self.clear_items()
        if len(self.embeds) > 1:
            if self.current_page > 0:
                btn_prev = Button(label="Previous", style=discord.ButtonStyle.primary, custom_id="pagination_prev")
                btn_prev.callback = self.prev_callback
                self.add_item(btn_prev)
            if self.current_page < len(self.embeds) - 1:
                btn_next = Button(label="Next", style=discord.ButtonStyle.primary, custom_id="pagination_next")
                btn_next.callback = self.next_callback
                self.add_item(btn_next)
        options = []
        for node in self.page_nodes[self.current_page]:
            user = node.get("user", {})
            label = user.get("longName", "Unknown")
            description = f"AKA: {user.get('shortName', 'N/A')}, {minutes_ago(node.get('lastHeard', 0))} mins ago"
            value = user.get("id", "N/A")
            options.append(discord.SelectOption(label=label, description=description, value=value))
        if options:
            select_menu = Select(placeholder="Select a node for details", min_values=1, max_values=1, options=options, custom_id="node_select")
            select_menu.callback = self.node_select_callback
            self.add_item(select_menu)

    async def prev_callback(self, interaction: discord.Interaction):
        self.current_page -= 1
        self._build_components()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    async def next_callback(self, interaction: discord.Interaction):
        self.current_page += 1
        self._build_components()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    async def node_select_callback(self, interaction: discord.Interaction):
        selected_id = interaction.data.get("values", [None])[0]
        if selected_id is None:
            await interaction.response.send_message("No node selected.", ephemeral=True)
            return
        current_nodes = self.page_nodes[self.current_page]
        node = next((n for n in current_nodes if n.get("user", {}).get("id") == selected_id), None)
        if node is None:
            await interaction.response.send_message("Node details not found.", ephemeral=True)
            return
        user = node.get("user", {})
        details = (
            f"**Long Name:** {user.get('longName', 'N/A')}\n"
            f"**ID:** {user.get('id', 'N/A')}\n"
            f"**AKA:** {user.get('shortName', 'N/A')}\n"
            f"**Last Heard:** {format_timestamp(node.get('lastHeard', 0))} ({minutes_ago(node.get('lastHeard', 0))} mins ago)\n"
            f"**SNR:** {node.get('snr', 'N/A')}\n"
            f"**Device Metrics:**\n{format_device_metrics(node.get('deviceMetrics', {}))}"
        )
        detail_view = NodeDetailView(user.get("id", "N/A"))
        embed = Embed(title=f"Details for {user.get('longName', 'Unknown')}", description=details, color=Color.green())
        await interaction.response.send_message(embed=embed, view=detail_view, ephemeral=True)

class NodeDetailView(View):
    def __init__(self, node_id: str):
        super().__init__(timeout=180)
        self.node_id = node_id
        btn = Button(label="Send Direct Message", style=discord.ButtonStyle.success, custom_id="send_dm_button")
        btn.callback = self.send_dm_callback
        self.add_item(btn)

    async def send_dm_callback(self, interaction: discord.Interaction):
        modal = DMModal(self.node_id)
        await interaction.response.send_modal(modal)

# --------------------------
# New: NodeActionView for /info node entries
# --------------------------
class NodeActionView(View):
    def __init__(self, node_id: str):
        super().__init__(timeout=180)
        self.node_id = node_id
        options = [
            discord.SelectOption(label="Traceroute", description="Perform a traceroute", value="trace"),
            discord.SelectOption(label="Request Location", description="Request node location", value="location"),
            discord.SelectOption(label="Message", description="Send a direct message", value="message")
        ]
        select = Select(placeholder="Choose an action", options=options, custom_id="node_action_select", min_values=1, max_values=1)
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        choice = interaction.data.get("values", [None])[0]
        if choice == "trace":
            try:
                meshtastic_interface.sendTraceRoute(self.node_id, hoplimit=10, channel_index=0)
                await interaction.response.send_message(f"Traceroute request sent to node {self.node_id}.", ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"Error sending traceroute: {e}", ephemeral=True)
        elif choice == "location":
            try:
                meshtastic_interface.sendText("Requesting location update", destinationId=self.node_id, channelIndex=0)
                await interaction.response.send_message(f"Location request sent to node {self.node_id}.", ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"Error requesting location: {e}", ephemeral=True)
        elif choice == "message":
            modal = DMModal(self.node_id)
            await interaction.response.send_modal(modal)
        else:
            await interaction.response.send_message("Invalid action selected.", ephemeral=True)

# --------------------------
# New: InfoPaginationView for the /info command
# --------------------------
class InfoPaginationView(View):
    def __init__(self, embeds: list[Embed], node_list: list[dict]):
        super().__init__(timeout=180)
        # Page 0 is the owner/my info/metadata embed; subsequent pages are node info pages.
        self.embeds = embeds
        self.node_list = node_list  # List of node dicts (one per page)
        self.current_page = 0
        self._build_components()

    def _build_components(self):
        self.clear_items()
        if len(self.embeds) > 1:
            if self.current_page > 0:
                btn_prev = Button(label="Previous", style=discord.ButtonStyle.primary, custom_id="info_prev")
                btn_prev.callback = self.prev_callback
                self.add_item(btn_prev)
            if self.current_page < len(self.embeds) - 1:
                btn_next = Button(label="Next", style=discord.ButtonStyle.primary, custom_id="info_next")
                btn_next.callback = self.next_callback
                self.add_item(btn_next)
        if self.current_page > 0:
            btn_action = Button(label="Actions", style=discord.ButtonStyle.secondary, custom_id="info_action")
            btn_action.callback = self.action_callback
            self.add_item(btn_action)

    async def prev_callback(self, interaction: discord.Interaction):
        self.current_page -= 1
        self._build_components()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    async def next_callback(self, interaction: discord.Interaction):
        self.current_page += 1
        self._build_components()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    async def action_callback(self, interaction: discord.Interaction):
        node = self.node_list[self.current_page - 1]  # page 0 is owner info
        node_id = node.get("user", {}).get("id", "N/A")
        await interaction.response.send_message("Select an action for this node:", view=NodeActionView(node_id), ephemeral=True)

# --------------------------
# Slash Commands
# --------------------------
@tree.command(name="nodes", description="Retrieves a sorted, paginated list of nodes in the mesh network.")
async def nodes(interaction: discord.Interaction):
    try:
        nodes_data = meshtastic_interface.nodes
        if not nodes_data:
            await interaction.response.send_message("No nodes found in the mesh network.")
            return

        sorted_nodes = sorted(nodes_data.values(), key=lambda n: n.get("lastHeard", 0), reverse=True)
        page_size = 7
        pages = [sorted_nodes[i:i + page_size] for i in range(0, len(sorted_nodes), page_size)]
        embeds = []
        for page in pages:
            embed = Embed(
                title="Mesh Network Nodes",
                description="Most recently active nodes:",
                color=Color.blurple()
            )
            for node in page:
                user = node.get("user", {})
                long_name = user.get("longName", "Unknown")
                node_id = user.get("id", "N/A")
                short_name = user.get("shortName", "N/A")
                ts = node.get("lastHeard", 0)
                embed.add_field(
                    name=long_name,
                    value=f"**ID:** {node_id}\n**AKA:** {short_name}\n**Last Heard:** {format_timestamp(ts)} ({minutes_ago(ts)} mins ago)",
                    inline=False
                )
            embeds.append(embed)
        view = NodesPaginationView(embeds, pages)
        await interaction.response.send_message(embed=embeds[0], view=view)
    except Exception as e:
        await interaction.response.send_message(f"Error retrieving nodes: {e}")

# Updated /info command with human readable output
@tree.command(name="info", description="Retrieves the device's configuration and status info in a human-readable format.")
async def info(interaction: discord.Interaction):
    try:
        info_str = meshtastic_interface.showInfo()
        owner_line = re.search(r'^Owner:\s*(.*)', info_str, re.MULTILINE)
        my_info_line = re.search(r'^My info:\s*(\{.*?\})', info_str, re.MULTILINE)
        metadata_line = re.search(r'^Metadata:\s*(\{.*?\})', info_str, re.MULTILINE)
        nodes_text = re.search(r'^Nodes in mesh:\s*(\{.*)', info_str, re.DOTALL | re.MULTILINE)

        owner_info = owner_line.group(1).strip() if owner_line else "Unknown"
        my_info_json = my_info_line.group(1).strip() if my_info_line else "{}"
        metadata_json = metadata_line.group(1).strip() if metadata_line else "{}"
        nodes_json_str = nodes_text.group(1).strip() if nodes_text else "{}"
        try:
            nodes_dict = json.loads(nodes_json_str)
        except Exception as e:
            nodes_dict = {}
            print(f"Error parsing nodes JSON: {e}")

        owner_embed = Embed(title="Owner Information", color=Color.gold())
        owner_embed.add_field(name="Owner", value=owner_info, inline=False)
        owner_embed.add_field(name="My Info", value=f"```json\n{json.dumps(json.loads(my_info_json), indent=2)}```", inline=False)
        owner_embed.add_field(name="Metadata", value=f"```json\n{json.dumps(json.loads(metadata_json), indent=2)}```", inline=False)
        owner_embed.set_footer(text="Page 1 of " + str(1 + len(nodes_dict)))
        
        node_embeds = []
        node_list = []
        for key, node in nodes_dict.items():
            node_list.append(node)
            node_title = f"Node: {node.get('user', {}).get('longName', 'Unknown')}"
            node_description = f"```json\n{json.dumps(node, indent=2)}```"
            embed = Embed(title=node_title, description=node_description, color=Color.blurple())
            embed.set_footer(text=f"Page {len(node_list)+1} of {1+len(nodes_dict)}")
            node_embeds.append(embed)
        
        all_embeds = [owner_embed] + node_embeds
        view = InfoPaginationView(all_embeds, node_list)
        await interaction.response.send_message(embed=all_embeds[0], view=view)
    except Exception as e:
        await interaction.response.send_message(f"Error retrieving info: {e}")

@tree.command(name="position", description="Sends a position packet (latitude, longitude, [altitude]).")
async def position(interaction: discord.Interaction, latitude: float, longitude: float, altitude: int = 0):
    try:
        meshtastic_interface.sendPosition(latitude=latitude, longitude=longitude, altitude=altitude)
        embed = Embed(title="Position Sent", description=f"lat: {latitude}, lon: {longitude}, alt: {altitude}", color=Color.green())
        await interaction.response.send_message(embed=embed, view=DismissView())
    except Exception as e:
        await interaction.response.send_message(f"Error sending position: {e}")

@tree.command(name="telemetry", description="Requests telemetry data from the Meshtastic node.")
async def telemetry(interaction: discord.Interaction):
    try:
        meshtastic_interface.sendTelemetry()
        embed = Embed(title="Telemetry", description="Telemetry request sent.", color=Color.green())
        await interaction.response.send_message(embed=embed, view=DismissView())
    except Exception as e:
        await interaction.response.send_message(f"Error requesting telemetry: {e}")

@tree.command(name="trace", description="Initiates a traceroute to the specified destination node.")
async def trace(interaction: discord.Interaction, destination: str, hoplimit: int = 10, channel_index: int = 0):
    try:
        meshtastic_interface.sendTraceRoute(destination, hoplimit, channel_index)
        embed = Embed(title="Traceroute", description=f"Traceroute request sent to {destination} with hoplimit {hoplimit} on channel {channel_index}.", color=Color.green())
        await interaction.response.send_message(embed=embed, view=DismissView())
    except Exception as e:
        await interaction.response.send_message(f"Error sending traceroute: {e}")

@tree.command(name="senddata", description="Sends custom data on the specified port (data as hex string).")
async def senddata(interaction: discord.Interaction, port: int, data: str):
    try:
        data_bytes = bytes.fromhex(data)
        meshtastic_interface.sendData(data_bytes, portNum=port)
        embed = Embed(title="Send Data", description=f"Data sent on port {port}: {data}", color=Color.green())
        await interaction.response.send_message(embed=embed, view=DismissView())
    except Exception as e:
        await interaction.response.send_message(f"Error sending data: {e}")

@tree.command(name="ping", description="Sends a heartbeat (ping) to the Meshtastic node.")
async def ping(interaction: discord.Interaction):
    try:
        meshtastic_interface.sendHeartbeat()
        embed = Embed(title="Ping", description="Heartbeat sent to Meshtastic node.", color=Color.green())
        await interaction.response.send_message(embed=embed, view=DismissView())
    except Exception as e:
        await interaction.response.send_message(f"Error sending heartbeat: {e}")

@tree.command(
    name="lora",
    description="Sends a LoRa message on a specified channel (default 1: Side Channel (encrypted))."
)
async def lora(interaction: discord.Interaction, message: str, channel: int = 1):
    try:
        meshtastic_interface.sendText(message, channelIndex=channel)
        embed = Embed(title="LoRa Message", description=f"Message sent on channel {channel}:\n{message}", color=Color.green())
        await interaction.response.send_message(embed=embed, view=DismissView())
    except Exception as e:
        await interaction.response.send_message(f"Error sending message: {e}")

@tree.command(name="message", description="Sends a direct message to a specified node.")
async def message(interaction: discord.Interaction, nodeid: str, message: str):
    try:
        meshtastic_interface.sendText(message, destinationId=nodeid, channelIndex=0)
        embed = Embed(title="Direct Message", description=f"Message sent to node {nodeid}:\n{message}", color=Color.green())
        await interaction.response.send_message(embed=embed, view=DismissView())
    except Exception as e:
        await interaction.response.send_message(f"Error sending direct message to {nodeid}: {e}")

# New /dm command for sending a direct message using recent nodes plus any favorites
@tree.command(name="dm", description="Send a direct message to one of the 10 most recent nodes plus any favorites.")
async def dm(interaction: discord.Interaction):
    try:
        nodes_data = meshtastic_interface.nodes
        if not nodes_data:
            await interaction.response.send_message("No nodes available.", ephemeral=True)
            return

        # Sort nodes by lastHeard descending.
        sorted_nodes = sorted(nodes_data.values(), key=lambda n: n.get("lastHeard", 0), reverse=True)
        recent_nodes = sorted_nodes[:10]
        # Collect favorites from all nodes.
        favorite_nodes = [node for node in nodes_data.values() if node.get("isFavorite", False)]
        # Use a dictionary keyed by node ID to avoid duplicates.
        combined = {node.get("user", {}).get("id", "N/A"): node for node in recent_nodes}
        for node in favorite_nodes:
            node_id = node.get("user", {}).get("id", "N/A")
            if node_id not in combined:
                combined[node_id] = node
        # Build the select options.
        options = []
        for node in combined.values():
            user = node.get("user", {})
            label = user.get("longName", "Unknown")
            description = f"AKA: {user.get('shortName', 'N/A')}"
            value = user.get("id", "N/A")
            options.append(discord.SelectOption(label=label, description=description, value=value))
        # Create the select menu.
        select_menu = Select(placeholder="Select a node to message", options=options, custom_id="dm_select")
        
        async def dm_select_callback(select_interaction: discord.Interaction):
            selected_id = select_interaction.data.get("values", [None])[0]
            if selected_id is None:
                await select_interaction.response.send_message("No node selected.", ephemeral=True)
                return
            modal = DMModal(selected_id)
            await select_interaction.response.send_modal(modal)
        
        select_menu.callback = dm_select_callback
        view = View()
        view.add_item(select_menu)
        await interaction.response.send_message("Select a node to send a direct message:", view=view, ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Error preparing DM command: {e}", ephemeral=True)

@tree.command(name="channels", description="Lists active channels on the Meshtastic node.")
async def channels(interaction: discord.Interaction):
    try:
        chans = meshtastic_interface.localNode.channels
        active_channels = []
        for idx, chan in enumerate(chans):
            if chan.role == channel_pb2.Channel.Role.DISABLED:
                continue
            name = chan.settings.name.strip() if chan.settings.name else "LongFast"
            active_channels.append(f"**{idx}**: {name}")
        if not active_channels:
            await interaction.response.send_message("No active channels found.")
        else:
            embed = Embed(title="Active Channels", description="\n".join(active_channels), color=Color.blurple())
            await interaction.response.send_message(embed=embed, view=DismissView())
    except Exception as e:
        await interaction.response.send_message(f"Error retrieving channels: {e}")

@tree.command(name="unattended", description="Toggle unattended mode for auto-reply using Ollama API.")
async def unattended(interaction: discord.Interaction):
    global unattended_mode
    unattended_mode = not unattended_mode
    status = f"Auto-reply: {'ON' if unattended_mode else 'OFF'}"
    await bot.change_presence(activity=discord.Game(name=status))
    await interaction.response.send_message(f"Unattended mode is now {'enabled' if unattended_mode else 'disabled'}.", ephemeral=True)

# --------------------------
# Simplified on_message Handler for Discord
# --------------------------
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    await bot.process_commands(message)

# --------------------------
# Async function to process unattended meshtastic messages
# --------------------------
async def process_unattended_meshtastic_message(node_id: str, text: str):
    key = str(node_id)
    if key not in conversation_history:
        conversation_history[key] = []
    conversation_history[key].append({"role": "user", "content": text})
    system_prompt = {
        "role": "system",
        "content": "You are Sara a human female user of a LoRa radio in Pike National Forest in Colorado. Reply to this message, keeping all responses under 125 characters."
    }
    payload = {
        "model": "llama3.2:1b",
        "messages": [system_prompt] + conversation_history[key],
        "stream": False,
        "options": {
            "max_tokens": 120
        }
    }
    try:
        print(f"[DEBUG] Sending meshtastic message to LLM for node {node_id}: {text}")
        response = requests.post("http://localhost:11434/api/chat", json=payload, timeout=250)
        response.raise_for_status()
        response_text = response.text.strip()
        try:
            data, _ = json.JSONDecoder().raw_decode(response_text)
        except Exception as json_ex:
            print(f"[DEBUG] JSON decode error for node {node_id}: {json_ex}. Response text: {response_text}")
            raise json_ex
        assistant_reply = data.get("message", {}).get("content", "").strip()
        if assistant_reply:
            conversation_history[key].append({"role": "assistant", "content": assistant_reply})
            print(f"[DEBUG] Received reply from LLM for node {node_id}: {assistant_reply}")
            meshtastic_interface.sendText(assistant_reply, destinationId=node_id, channelIndex=0)
            print(f"[DEBUG] A response to node {node_id} was sent to their message '{text}' the LLM replied '{assistant_reply}'")
            await send_meshtastic_message(DISCORD_CHANNEL_ID, f"**[Mesh Auto Reply]** to node {node_id}: {assistant_reply}")
        else:
            print(f"[DEBUG] LLM did not return a valid reply for node {node_id}.")
    except Exception as e:
        print(f"[DEBUG] Error communicating with LLM for node {node_id}: {e}")

# --------------------------
# Keep Meshtastic Connection Alive
# --------------------------
def keep_meshtastic_alive():
    try:
        while True:
            time.sleep(1)
    except Exception as e:
        print(f"Meshtastic thread error: {e}")

meshtastic_thread = threading.Thread(target=keep_meshtastic_alive, daemon=True)
meshtastic_thread.start()

# --------------------------
# Bot Event Handlers
# --------------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        await tree.sync()
        print("Slash commands synced.")
    except Exception as e:
        print(f"Error syncing commands: {e}")

# --------------------------
# Run the Bot
# --------------------------
bot.run(DISCORD_BOT_TOKEN)
