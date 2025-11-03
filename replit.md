# Telegram Bot Project

## Overview
This is a Telegram bot built with Python using the python-telegram-bot library. The bot can respond to commands and echo back user messages.

## Features
- Responds to `/start`, `/help`, and `/about` commands
- Echoes back any text messages sent to it
- Simple and easy to extend with more functionality

## Architecture
- **Language**: Python 3.11
- **Main Library**: python-telegram-bot (v22.5)
- **Main File**: bot.py
- **Bot Token**: Stored securely in TELEGRAM_BOT_TOKEN environment variable

## Setup
1. Create a bot using @BotFather on Telegram
2. Get your bot token
3. Add the token to the TELEGRAM_BOT_TOKEN secret in Replit
4. Run the bot

## How to Get a Bot Token
1. Open Telegram and search for @BotFather
2. Send `/newbot` command
3. Follow the prompts to create your bot
4. BotFather will give you a token like: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`
5. Add this token to your Replit secrets

## Recent Changes
- 2025-11-03: Initial project setup with basic echo bot functionality
