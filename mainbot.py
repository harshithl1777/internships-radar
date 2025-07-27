import json
import os
import time
from datetime import datetime
import git
import schedule
import discord
from discord.ext import tasks, commands
import asyncio
from dotenv import load_dotenv
import sys

# Load environment variables
load_dotenv()

# Configuration validation
def validate_config():
    """Validate required configuration values on startup"""
    required_vars = ['DISCORD_TOKEN', 'CHANNEL_IDS']
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print(f"Error: Missing required environment variables: {', '.join(missing_vars)}")
        print("Please check your .env file or set these environment variables.")
        sys.exit(1)
    
    # Validate channel IDs format
    try:
        channel_ids = os.getenv('CHANNEL_IDS').split(',')
        for channel_id in channel_ids:
            int(channel_id.strip())
    except (ValueError, AttributeError):
        print("Error: CHANNEL_IDS must be comma-separated integers")
        sys.exit(1)
    
    print("Configuration validation passed.")

# Validate configuration on startup
validate_config()

# Constants from environment variables
REPO_URL = os.getenv('REPO_URL', 'https://github.com/cvrve/Summer2025-Internships')
LOCAL_REPO_PATH = os.getenv('LOCAL_REPO_PATH', 'Summer2025-Internships')
JSON_FILE_PATH = os.path.join(LOCAL_REPO_PATH, '.github', 'scripts', 'listings.json')
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_IDS = [id.strip() for id in os.getenv('CHANNEL_IDS').split(',')]
MAX_RETRIES = int(os.getenv('MAX_RETRIES', '3'))
CHECK_INTERVAL_MINUTES = int(os.getenv('CHECK_INTERVAL_MINUTES', '1'))

# Initialize Discord bot and global variables
intents = discord.Intents.default()
bot = commands.Bot(command_prefix='!', intents=intents)
failed_channels = set()  # Keep track of channels that have failed
channel_failure_counts = {}  # Track failure counts for each channel
message_tracking = {}  # Track sent messages for role expiration updates

def clone_or_update_repo():
    """
    The function `clone_or_update_repo` clones a repository if it doesn't exist locally or updates it if
    it already exists.
    """
    print("Cloning or updating repository...")
    if os.path.exists(LOCAL_REPO_PATH):
        try:
            repo = git.Repo(LOCAL_REPO_PATH)
            repo.remotes.origin.pull()
            print("Repository updated.")
        except git.exc.InvalidGitRepositoryError:
            os.rmdir(LOCAL_REPO_PATH)  # Remove invalid directory
            git.Repo.clone_from(REPO_URL, LOCAL_REPO_PATH)
            print("Repository cloned fresh.")
    else:
        git.Repo.clone_from(REPO_URL, LOCAL_REPO_PATH)
        print("Repository cloned fresh.")

def read_json():
    """
    The function `read_json()` reads a JSON file and returns the loaded data.
    :return: The function `read_json` is returning the data loaded from the JSON file.
    """
    print(f"Reading JSON file from {JSON_FILE_PATH}...")
    with open(JSON_FILE_PATH, 'r') as file:
        data = json.load(file)
    print(f"JSON file read successfully, {len(data)} items loaded.")
    return data

# Function to format the message
def format_message(role):
    """
    The `format_message` function generates a formatted message for a new internship posting, including
    details such as company name, role title, location, season, sponsorship, and posting date.
    
    :param role: The role dictionary containing internship information
    :return: A formatted message string for Discord
    """
    cvrve = 'cvrve'
    location_str = ', '.join(role['locations']) if role['locations'] else 'Not specified'
    return f"""
>>> # {role['company_name']} just posted a new internship!

### Role:
[{role['title']}]({role['url']})

### Location:
{location_str}

### Season:
{role['season']}

### Sponsorship: `{role['sponsorship']}`
### Posted on: {datetime.now().strftime('%B, %d')}
made by the team @ [{cvrve}](https://www.cvrve.me/)
"""

def format_deactivation_message(role):
    """
    The function `format_deactivation_message` generates a message indicating that a specific internship
    role is no longer active.
    
    :param role: The role dictionary containing internship information
    :return: A formatted deactivation message string for Discord
    """
    cvrve = 'cvrve'
    return f"""
>>> # {role['company_name']} internship is no longer active

### Role:
~~[{role['title']}](about:blank)~~ (Link disabled - position closed)

### Status: `Inactive`
### Deactivated on: {datetime.now().strftime('%B, %d')}
made by the team @ [{cvrve}](https://www.cvrve.me/)
"""

async def update_expired_role_messages(role):
    """
    Update previously sent messages for a role that has expired/been deactivated.
    
    :param role: The role dictionary containing internship information
    :return: None
    """
    role_key = f"{role['company_name']}_{role['title']}"
    
    if role_key not in message_tracking:
        print(f"No messages found to update for role: {role_key}")
        return
    
    updated_message = f"""
>>> # ❌ {role['company_name']} internship is now CLOSED

### Role:
~~[{role['title']}](about:blank)~~ (Link disabled - position closed)

### Location:
{', '.join(role['locations']) if role['locations'] else 'Not specified'}

### Season:
{role['season']}

### Status: `🔴 CLOSED`
### Closed on: {datetime.now().strftime('%B, %d')}
made by the team @ [cvrve](https://www.cvrve.me/)
"""
    
    messages_to_update = message_tracking[role_key]
    
    for msg_info in messages_to_update:
        try:
            channel = bot.get_channel(int(msg_info['channel_id']))
            if channel is None:
                channel = await bot.fetch_channel(int(msg_info['channel_id']))
            
            message = await channel.fetch_message(msg_info['message_id'])
            await message.edit(content=updated_message)
            print(f"Updated message {msg_info['message_id']} in channel {msg_info['channel_id']}")
            
        except discord.NotFound:
            print(f"Message {msg_info['message_id']} not found in channel {msg_info['channel_id']}")
        except discord.Forbidden:
            print(f"No permission to edit message {msg_info['message_id']} in channel {msg_info['channel_id']}")
        except Exception as e:
            print(f"Error updating message {msg_info['message_id']}: {e}")
    
    # Clean up tracking for this role
    del message_tracking[role_key]
    print(f"Completed updating messages for expired role: {role_key}")

def compare_roles(old_role, new_role):
    """
    The function `compare_roles` compares two dictionaries representing roles and returns a list of
    changes between them.
    
    :param old_role: The original role dictionary
    :param new_role: The updated role dictionary
    :return: List of changes between the roles
    """
    changes = []
    for key in new_role:
        if old_role.get(key) != new_role.get(key):
            changes.append(f"{key} changed from {old_role.get(key)} to {new_role.get(key)}")
    return changes

async def send_message(message, channel_id, role_key=None):
    """
    The function sends a message to a Discord channel with error handling and retry mechanism.
    
    :param message: The message content to send
    :param channel_id: The Discord channel ID
    :param role_key: Optional role key for tracking messages (company_name + title)
    :return: None
    """
    if channel_id in failed_channels:
        print(f"Skipping previously failed channel ID {channel_id}")
        return

    try:
        print(f"Sending message to channel ID {channel_id}...")
        channel = bot.get_channel(int(channel_id))
        
        if channel is None:
            print(f"Channel {channel_id} not in cache, attempting to fetch...")
            try:
                channel = await bot.fetch_channel(int(channel_id))
            except discord.NotFound:
                print(f"Channel {channel_id} not found")
                channel_failure_counts[channel_id] = channel_failure_counts.get(channel_id, 0) + 1
                if channel_failure_counts[channel_id] >= MAX_RETRIES:
                    failed_channels.add(channel_id)
                return
            except discord.Forbidden:
                print(f"No permission for channel {channel_id}")
                failed_channels.add(channel_id)  # Immediate blacklist on permission issues
                return
            except Exception as e:
                print(f"Error fetching channel {channel_id}: {e}")
                channel_failure_counts[channel_id] = channel_failure_counts.get(channel_id, 0) + 1
                if channel_failure_counts[channel_id] >= MAX_RETRIES:
                    failed_channels.add(channel_id)
                return

        sent_message = await channel.send(message)
        print(f"Successfully sent message to channel {channel_id}")
        
        # Track message for potential expiration updates
        if role_key:
            if role_key not in message_tracking:
                message_tracking[role_key] = []
            message_tracking[role_key].append({
                'channel_id': channel_id,
                'message_id': sent_message.id,
                'timestamp': datetime.now()
            })
        
        # Reset failure count on success
        if channel_id in channel_failure_counts:
            del channel_failure_counts[channel_id]
        
        await asyncio.sleep(2)  # Rate limiting delay
        
    except Exception as e:
        print(f"Error sending message to channel {channel_id}: {e}")
        channel_failure_counts[channel_id] = channel_failure_counts.get(channel_id, 0) + 1
        if channel_failure_counts[channel_id] >= MAX_RETRIES:
            print(f"Channel {channel_id} has failed {MAX_RETRIES} times, adding to failed channels")
            failed_channels.add(channel_id)

async def send_messages_to_channels(message, role_key=None):
    """
    Sends a message to multiple Discord channels concurrently with error handling.
    
    :param message: The message content to send
    :param role_key: Optional role key for tracking messages
    :return: None
    """
    tasks = []
    for channel_id in CHANNEL_IDS:
        if channel_id not in failed_channels:
            tasks.append(send_message(message, channel_id, role_key))
    
    # Wait for all messages to be sent
    await asyncio.gather(*tasks, return_exceptions=True)

def check_for_new_roles():
    """
    The function checks for new roles and deactivated roles, sending appropriate messages to Discord channels.
    """
    print("Checking for new roles...")
    clone_or_update_repo()
    
    new_data = read_json()
    
    # Compare with previous data if exists
    if os.path.exists('previous_data.json'):
        with open('previous_data.json', 'r') as file:
            old_data = json.load(file)
        print("Previous data loaded.")
    else:
        old_data = []
        print("No previous data found.")

    new_roles = []
    deactivated_roles = []

    # Create a dictionary for quick lookup of old roles
    old_roles_dict = {(role['title'], role['company_name']): role for role in old_data}

    for new_role in new_data:
        old_role = old_roles_dict.get((new_role['title'], new_role['company_name']))
        
        if old_role:
            # Check if the role was previously active and is now inactive
            if old_role['active'] and not new_role['active']:
                deactivated_roles.append(new_role)
                print(f"Role {new_role['title']} at {new_role['company_name']} is now inactive.")
        elif new_role['is_visible'] and new_role['active']:
            new_roles.append(new_role)
            print(f"New role found: {new_role['title']} at {new_role['company_name']}")

    # Handle new roles
    for role in new_roles:
        role_key = f"{role['company_name']}_{role['title']}"
        message = format_message(role)
        bot.loop.create_task(send_messages_to_channels(message, role_key))

    # Handle deactivated roles
    for role in deactivated_roles:
        # Update existing messages for this role
        bot.loop.create_task(update_expired_role_messages(role))
        # Also send a new deactivation message
        message = format_deactivation_message(role)
        bot.loop.create_task(send_messages_to_channels(message))

    # Update previous data
    with open('previous_data.json', 'w') as file:
        json.dump(new_data, file)
    print("Updated previous data with new data.")

    if not new_roles and not deactivated_roles:
        print("No updates found.")

@bot.event
async def on_ready():
    """
    Event handler for when the bot is ready and connected to Discord.
    """
    print(f'Logged in as {bot.user}')
    print(f'Bot is ready and monitoring {len(CHANNEL_IDS)} channels')
    while True:
        schedule.run_pending()
        await asyncio.sleep(1)

# Graceful shutdown handler
import signal

def signal_handler(sig, frame):
    """Handle graceful shutdown"""
    print("\nShutting down gracefully...")
    save_message_tracking()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Schedule the job with configurable interval
schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(check_for_new_roles)

# Save and load message tracking data
def save_message_tracking():
    """Save message tracking data to file"""
    try:
        # Convert datetime objects to strings for JSON serialization
        serializable_tracking = {}
        for role_key, messages in message_tracking.items():
            serializable_tracking[role_key] = []
            for msg in messages:
                msg_copy = msg.copy()
                msg_copy['timestamp'] = msg_copy['timestamp'].isoformat()
                serializable_tracking[role_key].append(msg_copy)
        
        with open('message_tracking.json', 'w') as f:
            json.dump(serializable_tracking, f, indent=2)
        print("Message tracking data saved.")
    except Exception as e:
        print(f"Error saving message tracking data: {e}")

def load_message_tracking():
    """Load message tracking data from file"""
    global message_tracking
    try:
        if os.path.exists('message_tracking.json'):
            with open('message_tracking.json', 'r') as f:
                serializable_tracking = json.load(f)
            
            # Convert timestamp strings back to datetime objects
            for role_key, messages in serializable_tracking.items():
                message_tracking[role_key] = []
                for msg in messages:
                    msg['timestamp'] = datetime.fromisoformat(msg['timestamp'])
                    message_tracking[role_key].append(msg)
            
            print(f"Loaded message tracking data for {len(message_tracking)} roles.")
    except Exception as e:
        print(f"Error loading message tracking data: {e}")

def main():
    """Main function to run the bot"""
    # Load existing message tracking data on startup
    load_message_tracking()
    
    # Run the bot
    print("Starting bot with environment configuration...")
    print(f"Monitoring {len(CHANNEL_IDS)} channels every {CHECK_INTERVAL_MINUTES} minutes")
    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        print(f"Error starting bot: {e}")
        save_message_tracking()  # Save data before exit
        sys.exit(1)

if __name__ == "__main__":
    main()