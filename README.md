![MeshCore Banner](images/meshcore-bg.png)

# MeshCore for Home Assistant

This is a custom Home Assistant integration for MeshCore mesh radio nodes. It allows you to monitor and control MeshCore nodes via USB, BLE, or TCP connections.

> :warning: **Work in Progress**: This integration is under active development. BLE connection method hasn't been thoroughly tested yet.

Core integration is powered by [mccli.py](https://github.com/fdlamotte/mccli/blob/main/mccli.py) from fdlamotte.

## Features

- Connect to MeshCore nodes via USB, BLE, or TCP
- Monitor node status, signal strength, battery levels, and more
- View messages received by the mesh network
- Send messages to other nodes in the network
- Automatically discover nodes in the mesh network and create sensors for them
- Track and monitor repeater nodes with detailed statistics
- Configurable update intervals for different data types (messages, device info, repeaters)

## Installation

### HACS Installation (Recommended)

1. Make sure you have [HACS](https://hacs.xyz/) installed
2. Add this repository as a custom repository in HACS:
   - Go to HACS > Integrations
   - Click on the three dots in the top right corner
   - Select "Custom repositories"
   - Add the URL of this repository
   - Select "Integration" as the category
3. Click "Install" on the MeshCore integration

### Manual Installation

1. Copy the `custom_components/meshcore` directory to your Home Assistant `custom_components` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** > **Devices & Services**
2. Click **+ Add Integration** and search for "MeshCore"
3. Follow the setup wizard:
   - Select the connection type (USB, BLE, or TCP)
   - For USB: Select the USB port and set the baud rate (default: 115200)
   - For BLE: Select your MeshCore device from the discovered devices or enter the address manually
   - For TCP: Enter the hostname/IP and port of your MeshCore device
   - Configure update intervals for different data types:
     - Messages interval: How often to poll for new messages (default: 10 seconds)
     - Device info interval: How often to update device statistics (default: 60 seconds)
     - Repeater update interval: How often to poll repeater nodes (default: 300 seconds)

## Available Sensors

For the local node:
- **Node Status**: Shows if the node is online or offline
- **Battery Voltage**: Battery voltage in volts
- **Battery Percentage**: Battery level (percentage)
- **Node Count**: Number of nodes in the mesh network (including the local node)
- **TX Power**: Transmission power in dBm
- **Latitude/Longitude**: Node location (if available)
- **Frequency**: Radio frequency in MHz
- **Bandwidth**: Radio bandwidth in kHz
- **Spreading Factor**: Radio spreading factor

For remote nodes (automatically created for each node in the network):
- **MeshCore Contacts**: Diagnostic sensor showing all contacts with their details
- **Contact Status**: Status sensor for each contact ("fresh" or "stale" based on last seen time)
- Contact details are included as attributes (name, type, public key, last seen, etc.)

For message tracking:
- **Channel Messages**: Binary sensors for tracking messages on channels 0-3
- **Contact Messages**: Binary sensors for tracking messages from specific contacts

For repeater nodes:
- **Battery Voltage**: Battery voltage in volts
- **Battery Percentage**: Estimated battery level percentage
- **Uptime**: How long the repeater has been running (in minutes)
- **Airtime**: Total radio airtime used by the repeater (in minutes)
- **Messages Sent/Received**: Count of messages handled by the repeater
- **TX Queue Length**: Number of messages in transmission queue
- **Free Queue Length**: Number of free slots in queue
- **Sent/Received Flood Messages**: Count of broadcast messages
- **Sent/Received Direct Messages**: Count of direct messages
- **Full Events**: Count of queue full events
- **Direct/Flood Duplicates**: Count of duplicate messages

## Services

### Send Message

Send a message to a specific node in the mesh network.

Service: `meshcore.send_message`

| Field | Type | Description |
| ----- | ---- | ----------- |
| `node_id` | string | The ID of the node to send the message to (first 8 chars of public key) |
| `message` | string | The message text to send |

Example:
```yaml
service: meshcore.send_message
data:
  node_id: "a1b2c3d4"
  message: "Hello from Home Assistant!"
```

## Automations

### Forward New Messages to Push Notifications
```yaml
alias: Meshcore Forward to Push
description: "Forwards messages from any channel to a push notification"
triggers:
  - trigger: event
    event_type: meshcore_message
conditions:
  - condition: template
    value_template: "{{ trigger.event.data.message_type == 'channel'}}"
actions:
  - action: notify.notify
    data:
      message: >-
        Meshcore Message {{ trigger.event.data.channel_display }} from {{
        trigger.event.data.sender_name }}: {{ trigger.event.data.message }}
mode: single
```

## Troubleshooting

### Connection Issues

- **USB Connection**: Make sure the device is properly connected and the correct port is selected. Try a different baud rate if the default doesn't work.
- **BLE Connection**: Ensure Bluetooth is enabled on your Home Assistant host. Try moving closer to the device if signal strength is low. **Note: BLE pairing over Home Assistant Bluetooth proxy is not currently working until MeshCore supports disabling the PIN requirement.**
- **TCP Connection**: Verify the hostname/IP and port are correct and that there are no firewalls blocking the connection.

### Repeater Issues

- If repeaters aren't appearing, check that your node has correct time synchronization
- Verify the public key used for repeater login is correct
- Try increasing the repeater update interval if connections are unreliable
- Check the Home Assistant logs for detailed error messages related to repeater connections

### Integration Not Working

- Check the Home Assistant logs for error messages related to the MeshCore integration
- Verify that your MeshCore device is working correctly (try using the MeshCore CLI directly)
- Make sure you have the required permissions to access the device (especially for USB devices)
- Try adjusting the update intervals if you're experiencing performance issues

## Support and Development

- Report issues on GitHub
- Contributions are welcome via pull requests

## Requirements

- Home Assistant (version 2023.8.0 or newer)
- MeshCore node with firmware that supports API commands
- For BLE: Bluetooth adapter on the Home Assistant host (direct connection only; proxy connections don't work with PIN pairing)
- For USB: USB port on the Home Assistant host

## License

This project is licensed under the MIT License - see the LICENSE file for details.
