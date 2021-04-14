import os
import random
import secrets
import asyncio
import json

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
loaded_lobby_file = False

lobby_lock = asyncio.Lock()



async def time_check():
    await bot.wait_until_ready()
    
    offset_count = 0
    while not bot.is_closed():
        keys = lobbies.keys()
        # TODO: dont check all lobbies each iteration. Stagger them.

        lobbies_to_remove = []

        print("Checking for timeouts")
        for lobby_id in keys:
            lobby = lobbies[lobby_id]
            await lobby.update_lock.acquire()
            await lobby.updateMessages()
            if (lobby.isTimedOut()):
                lobbies_to_remove.append([lobby_id, 'Timed out.'])
            lobby.update_lock.release()

        # for lobby_hash in timed_out_lobbies:
            
        
        # Check for lobbies without active messages
        print("Checking empty")
        for lobby_id in keys:
            lobby = lobbies[lobby_id]
            await lobby.fetchMessages()
            if len(lobby.messages) == 0:
                lobbies_to_remove.append([lobby_id, 'Messages removed.'])


        # Clean up lobbies
        for [lobby_id, reason] in lobbies_to_remove:
            if lobby_id in lobbies:
                await lobbies[lobby_id].finalizeLobby(False, reason)
                removeLobby(lobby_id)

        await saveLobbyDump()

        await asyncio.sleep(5)


async def saveLobbyDump():
    if not loaded_lobby_file: return
    await lobby_lock.acquire()
    with open('lobbies.json', 'w') as f:
        data = {}
        for lobby in lobbies.values():
            await lobby.update_lock.acquire()
            data[lobby.hash] = lobby.getSaveData()
            lobby.update_lock.release()
        json.dump(data, f, indent=2)
    lobby_lock.release()

async def loadLobbyDump():
    global loaded_lobby_file
    print("Loading saved lobbies")
    await bot.wait_until_ready()
    await lobby_lock.acquire()
    lobby_types = {'Lobby': Lobby, 'PermanentLobby': PermanentLobby}
    with open('lobbies.json', 'r') as f:
        data = json.load(f)
        for lobby_data in data.values():
            print(lobby_data)
            lobby = lobby_types[lobby_data['type']](0, '', 0, -1, bot)
            await lobby.loadData(lobby_data)
            await lobby.updateLobby()

            lobbies[lobby_data['hash']] = lobby
            for message_id in lobby.messages:
                lobby_messages[message_id] = lobby
    loaded_lobby_file = True
    lobby_lock.release()



bot.loop.create_task(time_check())
bot.loop.create_task(loadLobbyDump())

def removeLobby(lobby_hash):
    if lobby_hash not in lobbies: raise Exception("Trying to close non existant lobby")
    lobby = lobbies[lobby_hash]

    print(f'Deleting lobby {lobby_hash}')
    for message_id in lobbies[lobby_hash].messages:
        try:
            del lobby_messages[message_id]
        except KeyError: pass
    del lobbies[lobby_hash]

@bot.event
async def on_ready():
    print(f'Ready to go...')

@bot.command(name='lobby', help='Create a new lobby in the current channel\nUsage: "!lobby {size} {timeout} {name}"\n  *size:integer - Size of lobby. Once reached all members are notifierd.\n  *timeout:integer - Timeout time for lobby. After {timeout} minutes the lobby is closed. If set to -1 lobby never times out.\n  *name:string - Name of the lobby.\n\nCreates a lobby. Join lobbies by reacting to the lobby message. Once {size} members has been reached all members will be pinged in the channels where they reacted from.')
async def init_lobby(ctx, size: int, *args):
    if (size < 1 or size >= 1000): 
        await ctx.send("Error: Invalid lobby size. Range [1, 1000].")
        return
    if len(args) > 0:
        try: timeout = int(args[0]) * 60
        except ValueError: 
            await ctx.send("Error: Invalid timeout datatype.")
            return
    else: 
        timeout = 30 * 60
    name = ' '.join(args[1:])

    # Initialize new lobby
    lobby = Lobby(size, name, ctx.author.id, timeout, bot)
    if (lobby.hash in lobbies): raise Exception()
    await lobby.update_lock.acquire()
    message = await lobby.postMessage(ctx)
    if not message == None: 
        lobbies[lobby.hash] = lobby
        lobby_messages[message.id] = lobby
    lobby.update_lock.release()

@bot.command(name='permlobby', help='Create a new lobby in the current channel\nUsage: "!permlobby {size} {name}"\nCreates a permanent lobby. Permanent works like normal ones with the exception that they are not removed once they fill up. Instead they are only cleared.')
async def init_perm_lobby(ctx, size: int, *args):
    if (size < 1 or size >= 1000): 
        await ctx.send("Error: Invalid lobby size. Range [1, 1000].")
        return
    if len(args) > 0:
        try: timeout = int(args[0]) * 60
        except ValueError: 
            await ctx.send("Error: Invalid timeout datatype.")
            return
    else: 
        timeout = 30 * 60
    name = ' '.join(args[1:])

    # Initialize new lobby
    lobby = PermanentLobby(size, name, ctx.author.id, timeout, bot)
    if (lobby.hash in lobbies): raise Exception()
    await lobby.update_lock.acquire()
    message = await lobby.postMessage(ctx)
    if not message == None:
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
    if not message == None: 
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
        if type(lobby) is Lobby:
            removeLobby(lobby.hash)
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
