import asyncio
import threading
import time
import discord
from discord import app_commands

import meshtastic.tcp_interface
from pubsub import pub

# --------------------------
# Configuration
# --------------------------
# Configure your Discord bot token and the channel ID where you want to relay messages.
DISCORD_BOT_TOKEN = "YOUR_DISCORD_KEY_HERE"
# Replace with the integer ID of your channel (e.g., 123456789012345678)
DISCORD_CHANNEL_ID = YOUR_DISCORD_CHANNEL_HERE
# The IP address for the Meshtastic TCP API (default port 4403 is used)
MESHTASTIC_HOSTNAME = "YOUR_MESHTASTIC_IP_ADDRESS_HERE"

# --------------------------
# Initialize Meshtastic Interface
# --------------------------
try:
    meshtastic_interface = meshtastic.tcp_interface.TCPInterface(hostname=MESHTASTIC_HOSTNAME)
except Exception as e:
    print(f"Error initializing Meshtastic TCP interface: {e}")
    exit(1)

# --------------------------
# Create Discord Client and Command Tree
# --------------------------
intents = discord.Intents.default()
# Slash commands do not require the message_content intent, but you might need it for other purposes.
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

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
        if text:
            sender = packet.get("fromId", "unknown node")
            full_message = f"**[Mesh]** Message from {sender}: {text}"
            # Schedule the async sending of the message on the Discord event loop
            asyncio.run_coroutine_threadsafe(
                send_meshtastic_message(DISCORD_CHANNEL_ID, full_message),
                client.loop
            )
    except Exception as ex:
        print(f"Error processing received Meshtastic message: {ex}")

async def send_meshtastic_message(channel_id, message):
    channel = client.get_channel(channel_id)
    if channel:
        await channel.send(message)
    else:
        print(f"Channel with ID {channel_id} not found.")

# Subscribe to Meshtastic messages
pub.subscribe(on_meshtastic_receive, "meshtastic.receive.text")

# --------------------------
# Discord Slash Commands
# --------------------------

@tree.command(name="lora", description="Sends a message over LoRa on the primary channel.")
async def lora(interaction: discord.Interaction, message: str):
    try:
        meshtastic_interface.sendText(message, channelIndex=0)
        await interaction.response.send_message(f"Message sent over LoRa on the primary channel: {message}")
    except Exception as e:
        await interaction.response.send_message(f"Error sending message: {e}")

@tree.command(name="message", description="Sends a direct message to a specified node.")
async def message(interaction: discord.Interaction, nodeid: str, message: str):
    try:
        meshtastic_interface.sendText(message, destinationId=nodeid, channelIndex=0)
        await interaction.response.send_message(f"Direct message sent to {nodeid}: {message}")
    except Exception as e:
        await interaction.response.send_message(f"Error sending direct message to {nodeid}: {e}")

@tree.command(name="nodes", description="Retrieves a table of nodes in the mesh network.")
async def nodes(interaction: discord.Interaction):
    try:
        nodes_str = meshtastic_interface.showNodes()
        # Discord has character limits; split if necessary.
        messages = [nodes_str[i:i+1900] for i in range(0, len(nodes_str), 1900)]
        await interaction.response.send_message("Nodes:")
        for msg in messages:
            await interaction.followup.send(f"```{msg}```")
    except Exception as e:
        await interaction.response.send_message(f"Error retrieving nodes: {e}")

@tree.command(name="info", description="Retrieves the device's configuration and status info.")
async def info(interaction: discord.Interaction):
    try:
        info_str = meshtastic_interface.showInfo()
        messages = [info_str[i:i+1900] for i in range(0, len(info_str), 1900)]
        await interaction.response.send_message("Info:")
        for msg in messages:
            await interaction.followup.send(f"```{msg}```")
    except Exception as e:
        await interaction.response.send_message(f"Error retrieving info: {e}")

@tree.command(name="position", description="Sends a position packet (latitude, longitude, [altitude]).")
async def position(interaction: discord.Interaction, latitude: float, longitude: float, altitude: int = 0):
    try:
        meshtastic_interface.sendPosition(latitude=latitude, longitude=longitude, altitude=altitude)
        await interaction.response.send_message(f"Position sent: lat={latitude}, lon={longitude}, alt={altitude}")
    except Exception as e:
        await interaction.response.send_message(f"Error sending position: {e}")

@tree.command(name="telemetry", description="Requests telemetry data from the Meshtastic node.")
async def telemetry(interaction: discord.Interaction):
    try:
        meshtastic_interface.sendTelemetry()
        await interaction.response.send_message("Telemetry request sent.")
    except Exception as e:
        await interaction.response.send_message(f"Error requesting telemetry: {e}")

@tree.command(name="trace", description="Initiates a traceroute to the specified destination node.")
async def trace(interaction: discord.Interaction, destination: str, hoplimit: int = 10, channel_index: int = 0):
    try:
        meshtastic_interface.sendTraceRoute(destination, hoplimit, channel_index)
        await interaction.response.send_message(f"Traceroute request sent to {destination} with hoplimit {hoplimit} on channel {channel_index}.")
    except Exception as e:
        await interaction.response.send_message(f"Error sending traceroute: {e}")

@tree.command(name="senddata", description="Sends custom data on the specified port (data as hex string).")
async def senddata(interaction: discord.Interaction, port: int, data: str):
    try:
        data_bytes = bytes.fromhex(data)
        meshtastic_interface.sendData(data_bytes, portNum=port)
        await interaction.response.send_message(f"Data sent on port {port}: {data}")
    except Exception as e:
        await interaction.response.send_message(f"Error sending data: {e}")

@tree.command(name="ping", description="Sends a heartbeat (ping) to the Meshtastic node.")
async def ping(interaction: discord.Interaction):
    try:
        meshtastic_interface.sendHeartbeat()
        await interaction.response.send_message("Heartbeat sent to Meshtastic node.")
    except Exception as e:
        await interaction.response.send_message(f"Error sending heartbeat: {e}")

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
# Discord Client Event Handlers
# --------------------------
@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    # Optionally, sync commands globally (or per guild for testing)
    try:
        # For global sync (may take up to an hour to update on Discord):
        await tree.sync()
        # Alternatively, for a specific guild (fast update), use:
        # guild = discord.Object(id=YOUR_GUILD_ID)
        # await tree.sync(guild=guild)
        print("Slash commands synced.")
    except Exception as e:
        print(f"Error syncing commands: {e}")

# --------------------------
# Run the Bot
# --------------------------
client.run(DISCORD_BOT_TOKEN)
