import os
import random
import secrets
import asyncio

from datetime import datetime
import time

import discord
from discord.ext import commands
from dotenv import load_dotenv

from lobby import Lobby, PermanentLobby

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
LOBBY_TIMEOUT = os.getenv('LOBBY_TIMEOUT')

bot = commands.Bot(command_prefix='!')

lobbies = {}
lobby_messages = {}

async def time_check():
    print(time.time())
    print("timecheck?")
    await bot.wait_until_ready()
    print(f"ready {bot.is_closed()}")
    while not bot.is_closed():
        # Check for lobby timeouts.
        await asyncio.sleep(1)

        # Check if lobby messages still exist.

bot.loop.create_task(time_check())

def closeLobby(lobby_hash):
    if lobby_hash not in lobbies: raise Exception("Trying to close non existant lobby")
    lobby = lobbies[lobby_hash]

    # Close normal lobby
    if type(lobby) is Lobby:
        print(f'Closing lobby {lobby_hash}')
        for message_id in lobbies[lobby_hash].messages:
            try:
                del lobby_messages[message_id]
            except KeyError: pass
        del lobbies[lobby_hash]

    # Clear perm lobby
    elif type(lobby) is PermanentLobby:
        print(f'Purged lobby {lobby_hash}')


def purgeLobby(lobby_hash):
    print(f'Purging lobby {lobby_hash}')

@bot.event
async def on_ready():
    print(f'Ready to go...')

@bot.command(name='lobby', help='Create a new lobby in the current channel\nUsage: "!lobby {size} {timeout:minutes default 30} {name}"\nCreates a lobby. Join lobbies by reacting to the lobby message. Once {size} members has been reached all members will be pinged in the channels where they reacted from.')
async def init_lobby(ctx, size: int, *args):
    if (size < 1 or size >= 1000): 
        await ctx.send("Error: Invalid lobby size. Range [1, 1000]")
        return
    name = ' '.join(args)
    lobby = Lobby(size, name, ctx.author.id)
    if (lobby.hash in lobbies): raise Exception()
    await lobby.update_lock.acquire()
    message = await lobby.postMessage(ctx)
    lobbies[lobby.hash] = lobby
    lobby_messages[message.id] = lobby
    lobby.update_lock.release()

@bot.command(name='permlobby', help='Create a new lobby in the current channel\nUsage: "!permlobby {size} {name}"\nCreates a permanent lobby. Permanent works like normal ones with the exception that they are not removed once they fill up. Instead they are only cleared.')
async def init_perm_lobby(ctx, size: int, *args):
    if (size < 1 or size >= 1000): 
        await ctx.send("Error: Invalid lobby size. Range [1, 1000]")
        return
    name = ' '.join(args)
    lobby = PermanentLobby(size, name, ctx.author.id)
    if (lobby.hash in lobbies): raise Exception()
    await lobby.update_lock.acquire()
    message = await lobby.postMessage(ctx)
    lobbies[lobby.hash] = lobby
    lobby_messages[message.id] = lobby
    lobby.update_lock.release()

@bot.command(name='clonelobby', help='Clone an existing lobby to the current channel\nUsage: "!clonelobby {id:string}"\nClones the lobby with specified id to current channel. Cloned lobbies will mirror the original lobby. Changes done to either applies to both.')
async def clone_lobby(ctx, identifier: str):
    if identifier not in lobbies:
        await ctx.send("Error: Lobby with specified identifier does not exist")
        return
    await lobbies[identifier].update_lock.acquire()
    message = await lobbies[identifier].postMessage(ctx)
    lobby_messages[message.id] = lobbies[identifier]
    lobbies[identifier].update_lock.release()

@bot.event
async def on_raw_reaction_add(payload):
    if (payload.message_id not in lobby_messages):
        print("uninteresting message.")
        return
    lobby = lobby_messages[payload.message_id]
    await lobby.update_lock.acquire()
    await lobby.updateLobby()
    if lobby.isFull():
        await lobby.finalizeLobby()
        closeLobby(lobby.hash)
    lobby.update_lock.release()

@bot.event
async def on_raw_reaction_remove(payload):
    if (payload.message_id not in lobby_messages):
        print("uninteresting message.")
        return
    lobby = lobby_messages[payload.message_id]
    await lobby.update_lock.acquire()
    await lobby.updateLobby()
    lobby.update_lock.release()

@init_lobby.error
async def clear_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument) or isinstance(error, commands.BadArgument):
        await ctx.send('Invalid command parameters. Check !help for proper usage of command.')
    elif isinstance(error, commands.MissingPermissions) or isinstance(error, discord.errors.Forbidden):
        await ctx.send(f'Bot does not have required permissions: {error}')

    # else:
    #     await ctx.send(f'Error handling command `{error}`')
    else: 
        await ctx.send('Unexpected error when handling command. Make sure permissions are set correctly. Check !help for proper use of commands.')
        raise

bot.run(TOKEN)
