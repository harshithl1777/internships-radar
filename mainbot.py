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

BIGTECH = [
    "activision",
    "adobe",
    "affirm",
    "airbnb",
    "akuna capital",
    "alibaba",
    "amazon",
    "amd",
    "apple",
    "applied intuition",
    "asana",
    "atlassian",
    "audible",
    "aurora",
    "autodesk",
    "bitgo",
    "blackrock",
    "blackstone",
    "blizzard",
    "block",
    "bloomberg",
    "booking.com",
    "box",
    "brex",
    "bridgewater associates",
    "bytedance",
    "capital one",
    "chewy",
    "chime",
    "circle",
    "cisco",
    "citadel",
    "cloudflare",
    "coinbase",
    "confluent",
    "coursera",
    "credit karma",
    "criteo",
    "crowdstrike",
    "cruise",
    "ctc",
    "databricks",
    "datadog",
    "de shaw",
    "disney",
    "docusign",
    "doordash",
    "dropbox",
    "drw",
    "duolingo",
    "ebay",
    "electronic arts",
    "expedia",
    "faire",
    "flexport",
    "flipkart",
    "google",
    "grammarly",
    "groupon",
    "grubhub",
    "guidewire",
    "gusto",
    "hubspot",
    "hudson river trading",
    "hulu",
    "imc",
    "instabase",
    "instacart",
    "intel",
    "intuit",
    "jane street",
    "jump trading",
    "linkedin",
    "lucid",
    "lyft",
    "mapbox",
    "meta",
    "microsoft",
    "miro",
    "mongodb",
    "morgan stanley",
    "netapp",
    "netflix",
    "nextdoor",
    "niantic",
    "notion",
    "nuro",
    "nvidia",
    "okta",
    "openai",
    "optiver",
    "oracle",
    "palantir technologies",
    "palo alto networks",
    "patreon",
    "paycom",
    "paypal",
    "pinterest",
    "qualcomm",
    "qualtrics",
    "quora",
    "reddit",
    "ripple",
    "rippling",
    "rivian",
    "robinhood",
    "roblox",
    "rubrik",
    "salesforce",
    "samsara",
    "samsung",
    "scale ai",
    "sentry",
    "servicenow",
    "sig",
    "snap",
    "snowflake",
    "splunk",
    "spotify",
    "squarespace",
    "stackadapt",
    "stripe",
    "tencent",
    "tesla",
    "the trade desk",
    "tiktok",
    "tinder",
    "tripadvisor",
    "twilio",
    "twitch",
    "two sigma",
    "uber",
    "unity",
    "verkada",
    "vimeo",
    "visa",
    "vmware",
    "wayfair",
    "waymo",
    "weride",
    "whatnot",
    "wise",
    "wish",
    "workday",
    "x",
    "yahoo",
    "yelp",
    "zendesk",
    "zillow",
    "ziprecruiter",
    "zoho",
    "zoom",
    "zoox",
    "zynga",
]


# Configuration validation
def validate_config():
    """Validate required configuration values on startup"""
    required_vars = ["DISCORD_TOKEN", "CHANNEL_IDS"]
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
        channel_ids = os.getenv("CHANNEL_IDS").split(",")
        for channel_id in channel_ids:
            int(channel_id.strip())
    except (ValueError, AttributeError):
        print("Error: CHANNEL_IDS must be comma-separated integers")
        sys.exit(1)

    print("Configuration validation passed.")


# Validate configuration on startup
validate_config()

# Constants from environment variables
REPO_URL = os.getenv("REPO_URL", "https://github.com/cvrve/Summer2025-Internships")
LOCAL_REPO_PATH = os.getenv("LOCAL_REPO_PATH", "Summer2025-Internships")
JSON_FILE_PATH = os.path.join(LOCAL_REPO_PATH, ".github", "scripts", "listings.json")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_IDS = [id.strip() for id in os.getenv("CHANNEL_IDS").split(",")]
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

# Initialize Discord bot and global variables
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
failed_channels = set()  # Keep track of channels that have failed
channel_failure_counts = {}  # Track failure counts for each channel


def read_json():
    """
    The function `read_json()` reads a JSON file and returns the loaded data.
    :return: The function `read_json` is returning the data loaded from the JSON file.
    """
    print(f"Reading JSON file from {JSON_FILE_PATH}...")
    with open(JSON_FILE_PATH, "r") as file:
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
    location_str = ", ".join(role["locations"]) if role["locations"] else "Not specified"
    siren = "🚨🚨🚨" if role["company_name"].lower() in BIGTECH else ""
    return f"""
{siren} Alarm Triggered!
# {role['company_name']} just posted a new internship!

### Role:
[{role['title']}]({role['url']})

### Location:
{location_str}

### Season:
{role['season']}

### Sponsorship: `{role['sponsorship']}`
### Posted on: {datetime.now().strftime('%B, %d')}
"""


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

        await channel.send(message, allowed_mentions=discord.AllowedMentions(everyone=True))
        print(f"Successfully sent message to channel {channel_id}")

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


def async check_for_new_roles():
    """
    The function checks for new roles and deactivated roles, sending appropriate messages to Discord channels.
    """
    print("Checking for new roles...")

    new_data = read_json()

    # Compare with previous data if exists
    if os.path.exists("previous_data.json"):
        with open("previous_data.json", "r") as file:
            old_data = json.load(file)
        print("Previous data loaded.")
    else:
        old_data = []
        print("No previous data found.")

    new_roles = []
    deactivated_roles = []

    # Create a dictionary for quick lookup of old roles
    old_roles_dict = {(role["title"], role["company_name"]): role for role in old_data}

    for new_role in new_data:
        old_role = old_roles_dict.get((new_role["title"], new_role["company_name"]))

        if (
            not old_role
            and new_role["is_visible"]
            and new_role["active"]
            and new_role["company_name"].lower() in BIGTECH
        ):
            new_roles.append(new_role)
            print(f"New role found: {new_role['title']} at {new_role['company_name']}")

    # Handle new roles
    for role in new_roles:
        role_key = f"{role['company_name']}_{role['title']}"
        message = format_message(role)
        await send_messages_to_channels(message, role_key)

    # Update previous data
    with open("previous_data.json", "w") as file:
        json.dump(new_data, file)
    print("Updated previous data with new data.")

    if not new_roles and not deactivated_roles:
        print("No updates found.")


@bot.event
async def on_ready():
    """
    Event handler for when the bot is ready and connected to Discord.
    """
    print(f"Logged in as {bot.user}")
    print(f"Bot is ready and monitoring {len(CHANNEL_IDS)} channels")
    await check_for_new_roles()
    await bot.close()


# Graceful shutdown handler
import signal


def signal_handler(sig, frame):
    """Handle graceful shutdown"""
    print("\nShutting down gracefully...")
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def main():
    """Main function to run the bot"""

    # Run the bot
    print("Starting bot with environment configuration...")
    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        print(f"Error starting bot: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
