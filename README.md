Meshtastic Discord Bot Bridge

Overview

Meshtastic Discord Bot Bridge is a Python application that integrates a Meshtastic LoRa-based mesh network with Discord using modern slash commands. The bot relays messages from the Meshtastic network to a designated Discord channel and enables users to send commands from Discord to the mesh network. This project leverages Discord’s Application Commands API to provide a rich, interactive experience through slash commands.

Features
	•	Relays text messages from a Meshtastic node on the primary channel to a specific Discord channel.
	•	Sends text messages over the LoRa network using slash commands.
	•	Provides direct messaging functionality to send messages to specific nodes.
	•	Retrieves and displays network node information and device configuration.
	•	Transmits positional data including latitude, longitude, and altitude.
	•	Requests telemetry data from the connected Meshtastic node.
	•	Initiates traceroute commands to trace routes between nodes.
	•	Sends custom data packets by specifying a port and hex string data.
	•	Implements heartbeat (ping) functionality to verify connectivity with the Meshtastic device.

Requirements
	•	Python 3.8 or newer.
	•	discord.py version 2.0 or later for slash command support.
	•	Meshtastic Python library for TCP communication with the device.
	•	PubSub library for message subscription and event handling.

Installation
	1.	Clone or download the repository.
	2.	Create and activate a virtual environment.
	3.	Install the required dependencies using pip.
	4.	Configure the Discord bot token, Discord channel ID, and Meshtastic hostname in the configuration section of the script.

Configuration

The primary configuration parameters are:
	•	Discord Bot Token: Authenticates the bot with Discord.
	•	Discord Channel ID: The channel where Meshtastic messages will be relayed.
	•	Meshtastic Hostname: The IP address of your Meshtastic device (using the default port 4403).

Make sure the necessary intents are enabled in your Discord developer portal, especially if additional functionality beyond slash commands is needed.

Usage

After configuring the project, run the script to start the bot. On startup, the bot will:
	•	Connect to the Meshtastic network.
	•	Log in to Discord and sync the slash commands automatically.
	•	Relay incoming Meshtastic messages to the designated Discord channel.
	•	Execute slash commands received from Discord to interact with the Meshtastic network.

Commands

The bot provides several slash commands:
	•	lora: Sends a text message over the primary LoRa channel.
	•	message: Sends a direct message to a specified node.
	•	nodes: Retrieves and displays a list of nodes currently in the mesh network.
	•	info: Retrieves device configuration and status information.
	•	position: Sends a position packet with latitude, longitude, and an optional altitude.
	•	telemetry: Requests telemetry data from the Meshtastic node.
	•	trace: Initiates a traceroute to a designated node.
	•	senddata: Sends a custom data packet on a specified port (with data provided as a hex string).
	•	ping: Sends a heartbeat (ping) to confirm connectivity with the Meshtastic device.

How It Works

The application uses a combination of asynchronous programming and threading. A dedicated background thread maintains the Meshtastic connection, while incoming messages are processed asynchronously and relayed to Discord through the bot’s event loop. The slash commands, implemented using Discord’s Application Commands API, provide users with a seamless and modern interface to interact with the LoRa network.

Troubleshooting
	•	Verify that the Meshtastic device is accessible on the network.
	•	Double-check that the Discord Bot Token and Channel ID are correctly configured.
	•	Ensure that the required Discord intents are enabled in the Discord developer portal.
	•	Consult the terminal output for any exception messages that can assist with debugging.

Contributing

Contributions are welcome. To contribute:
	•	Fork the repository.
	•	Create a feature branch.
	•	Submit pull requests with your improvements or bug fixes.
	•	Ensure that your changes adhere to the project’s coding standards and include appropriate documentation.

License

This project is licensed under the MIT License. See the LICENSE file for details.

Acknowledgments
	•	Thanks to the Meshtastic community for their ongoing support and resources.
	•	Appreciation to the developers of discord.py for their contributions to the Discord bot ecosystem.
	•	Gratitude to all contributors who help maintain and improve the project.
