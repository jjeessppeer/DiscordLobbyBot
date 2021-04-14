import os
import random
import secrets
import asyncio
import json
import math

from datetime import datetime
import time

import discord
from discord.ext import commands
from dotenv import load_dotenv

from lobby import Lobby, PermanentLobby

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN') # Bot token
LOBBY_TIMEOUT = int(os.getenv('LOBBY_TIMEOUT')) # Inactivity timeout in seconds

bot = commands.Bot(command_prefix='!')

lobbies = {}
lobby_messages = {}

lobby_lock = asyncio.Lock()

async def chron_checkup():
    await bot.wait_until_ready()
    
    batch_size = 5 # Lobbies checked each iteration
    update_interval = 5 # Interval in which all lobbies should be checked
    
    offset_count = 0
    while not bot.is_closed():
        await lobby_lock.acquire()
        print("Chron checkup")

        offset_count += batch_size
        if offset_count >= len(lobbies):
            offset_count = 0
        if len(lobbies) < batch_size: sleep_time = 5
        else: sleep_time = math.ceil(batch_size / len(lobbies)) * update_interval

        keys = list(lobbies.keys())[offset_count:offset_count+batch_size]

        lobbies_to_remove = []
        current_time = time.time()

        for lobby_id in keys:
            lobby = lobbies[lobby_id]
            await lobby.update_lock.acquire()
            await lobby.updateMessages()
            await lobby.fetchMessages()

            # Regular lobby timeout
            if (lobby.isTimedOut()):
                lobbies_to_remove.append([lobby_id, 'Timed out.'])
            
            # Inactivity timeout
            elif current_time - lobby.last_activity > LOBBY_TIMEOUT:
                print('Removing inactive lobby')
                lobbies_to_remove.append([lobby_id, 'Inactivity timeout.'])

            # Messages removed
            elif len(lobby.messages) == 0:
                lobbies_to_remove.append([lobby_id, 'Messages removed.'])

            # Check for user timeouts
            await lobby.updateMemberTimeouts()

            lobby.update_lock.release()
            

        lobby_lock.release()


        # Clean up lobbies
        for [lobby_id, reason] in lobbies_to_remove:
            if lobby_id in lobbies:
                await lobbies[lobby_id].finalizeLobby(False, reason)
                await removeLobby(lobby_id)
        await asyncio.sleep(sleep_time - (time.time() - current_time))

async def removeLobby(lobby_hash):
    if lobby_hash not in lobbies: raise Exception("Trying to close non existant lobby")
    await lobby_lock.acquire()
    print(f'Deleting lobby {lobby_hash}')
    lobby = lobbies[lobby_hash]
    for message_id in lobbies[lobby_hash].messages:
        try:
            del lobby_messages[message_id]
        except KeyError: pass
    del lobbies[lobby_hash]
    lobby_lock.release()
    await saveLobbyDump()

async def saveLobbyDump():
    await lobby_lock.acquire()
    print('Saving lobbies to file...')
    with open('lobbies.json', 'w') as f:
        data = {}
        for lobby in lobbies.values():
            await lobby.update_lock.acquire()
            data[lobby.hash] = lobby.getSaveData()
            lobby.update_lock.release()
        json.dump(data, f, indent=2)
    lobby_lock.release()

async def loadLobbyDump():
    await lobby_lock.acquire()
    print("Loading lobbies from file...")
    global loaded_lobby_file
    await bot.wait_until_ready()
    lobby_types = {'Lobby': Lobby, 'PermanentLobby': PermanentLobby}
    with open('lobbies.json', 'r') as f:
        data = json.load(f)
        for lobby_data in data.values():
            lobby = lobby_types[lobby_data['type']](0, '', 0, -1, -1, bot)
            await lobby.update_lock.acquire()
            await lobby.loadData(lobby_data)
            await lobby.updateLobby()

            lobbies[lobby_data['hash']] = lobby
            for message_id in lobby.messages:
                lobby_messages[message_id] = lobby
            lobby.update_lock.release()
    lobby_lock.release()


@bot.command()
@commands.is_owner()
async def shutdown(context):
    await saveLobbyDump()
    await lobby_lock.acquire()
    print("Shutting down.")
    exit()

@bot.event
async def on_ready():
    print(f'Ready to go...')

@bot.command(name='lobby', help=(
    'Create a new lobby in the current channel\n'
    'Usage: "!lobby {size} {lobby_timeout} {user_timeout} {name}"\n'
    '  size:integer - Size of lobby. Once reached all members are notifierd.\n'
    '  lobby_timeout:integer - Timeout time for lobby. After {timeout} minutes the lobby is closed. If set to -1 lobby never times out.\n'
    '  reaction_timeout:integer - Reactions are removed {reaction_timeout} minutes after being applied. If set to -1 reactions never times out.\n'
    '  name:string - Name of the lobby.\n\n'
    'Creates a lobby. Join lobbies by reacting to the lobby message. Once {size} members has been reached all members will be pinged in the channels where they reacted from.'))
async def init_lobby(ctx, size: int, *args):
    if (size < 1 or size >= 1000): 
        await ctx.send("Error: Invalid lobby size. Range [1, 1000].")
        return
    if len(args) > 0:
        try: 
            timeout = int(args[0]) * 60
            if (timeout > 60*24): raise ValueError()
        except ValueError: 
            try: await ctx.send("Error: Invalid timeout value.")
            except: pass
            return
    else: 
        timeout = 30 * 60
    if len(args) > 1:
        try: 
            user_timeout = int(args[1]) * 60
            if (user_timeout > 60*24): raise ValueError()
        except ValueError:
            try: await ctx.send("Error: Invalid reaction_timeout format.")
            except: pass
            return
    else:
        user_timeout = 30 * 60
    name = ' '.join(args[2:])

    # Initialize new lobby
    lobby = Lobby(size, name, ctx.author.id, timeout, user_timeout, bot)
    if (lobby.hash in lobbies): raise Exception()
    await lobby.update_lock.acquire()
    message = await lobby.postMessage(ctx)
    if not message == None: 
        lobbies[lobby.hash] = lobby
        lobby_messages[message.id] = lobby
    lobby.update_lock.release()
    await saveLobbyDump()

@bot.command(name='permlobby', help=(
    'Create a new lobby permanent in the current channel\n'
    'Usage: "!permlobby {size} {lobby_timeout} {user_timeout} {name}"\n'
    '  size:integer - Size of lobby. Once reached all members are notifierd.\n'
    '  lobby_timeout:integer - Timeout time for lobby. After {timeout} minutes the lobby is closed. If set to -1 lobby never times out.\n'
    '  reaction_timeout:integer - Reactions are removed {reaction_timeout} minutes after being applied. If set to -1 reactions never times out.\n'
    '  name:string - Name of the lobby.\n\n'
    'Works the same way as !lobby. The exception being not closing lobby once it fills. Instead it resets the lobby so it can be used again.'))
async def init_perm_lobby(ctx, size: int, *args):
    if (size < 1 or size >= 1000): 
        await ctx.send("Error: Invalid lobby size. Range [1, 1000].")
        return
    if len(args) > 0:
        try: 
            timeout = int(args[0]) * 60
            if (timeout > 60*24): raise ValueError()
        except ValueError: 
            await ctx.send("Error: Invalid timeout datatype.")
            return
    else: 
        timeout = 30 * 60
    if len(args) > 1:
        try: 
            user_timeout = int(args[1]) * 60
            if (user_timeout > 60*24): raise ValueError()
        except ValueError:
            try: await ctx.send("Error: Invalid reaction_timeout format.")
            except: pass
            return
    else:
        user_timeout = 30 * 60
    name = ' '.join(args[2:])

    # Initialize new lobby
    lobby = PermanentLobby(size, name, ctx.author.id, timeout, user_timeout, bot)
    if (lobby.hash in lobbies): raise Exception()
    await lobby.update_lock.acquire()
    message = await lobby.postMessage(ctx)
    if not message == None:
        lobbies[lobby.hash] = lobby
        lobby_messages[message.id] = lobby
    lobby.update_lock.release()
    await saveLobbyDump()

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
    await saveLobbyDump()

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
            await removeLobby(lobby.hash)
        else:
            await saveLobbyDump()
    lobby.update_lock.release()

@bot.event
async def on_raw_reaction_remove(payload):
    if (payload.message_id not in lobby_messages): return
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


bot.loop.create_task(loadLobbyDump())
bot.loop.create_task(chron_checkup())
bot.run(TOKEN)
