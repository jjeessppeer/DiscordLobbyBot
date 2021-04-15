import os
import random
import secrets
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
import time
import math
import json

load_dotenv()
BOT_ID = int(os.getenv('BOT_ID'))

class Lobby():
    def __init__(self, size, name, author_id, lobby_timeout, user_timeout, bot):
        self.author_id = author_id
        self.size = size
        self.name = f' - {name}' if name != "" else ""
        self.bot = bot

        self.update_lock = asyncio.Lock()

        self.hash = secrets.token_hex(4)
        self.messages = {}
        self.members = {}
        self.members_last_active = {}
        self.finalized = False


        self.creation_time = time.time()
        self.timeout = lobby_timeout
        self.user_timeout = user_timeout
        self.last_activity = self.creation_time


    def getSaveData(self):
        data = {
            'type': 'Lobby',
            'hash': self.hash,
            'author_id': self.author_id,
            'size': self.size,
            'name': self.name,
            'messages': [[message.id, message.channel.id] for message in self.messages.values()],
            'creation_time': self.creation_time,
            'timeout': self.timeout,
            'user_timeout': self.user_timeout,
            'members_last_active': self.members_last_active,
            'last_activity': self.last_activity
            }
        return data
    
    async def loadData(self, data):
        self.hash = data['hash']
        self.author_id = data['author_id']
        self.size = data['size']
        self.name = data['name']
        self.creation_time = data['creation_time']
        self.timeout = data['timeout']
        self.user_timeout = data['user_timeout']
        self.last_activity = data['last_activity']
        self.members_last_active = data['members_last_active']
        messages = {}
        for [message_id, channel_id] in data['messages']:
            try:
                channel = await self.bot.fetch_channel(channel_id)
                message = await channel.fetch_message(message_id)
                messages[message_id] = message
            except: pass
        self.messages = messages



    def isTimedOut(self):
        if self.timeout < 0: return False
        return time.time() - self.creation_time > self.timeout
    
    def timeRemaining(self):
        t = time.time() - self.creation_time
        t = math.floor((self.timeout - t) / 60.0) 
        t = max(0, t)
        return t

    def getLobbyString(self, add_mentions=True):
        mention_str = '\n'.join([member.mention for member in self.members.values()])
        if mention_str == '': mention_str = '...'
        if not add_mentions: mention_str = '...'
        lobby_timeout_str = f'Lobby timer: `{self.timeRemaining()} min`.\n' if self.timeout>0 else ''
        reac_timeout_str = f'Reaction timeout: `{math.floor(self.user_timeout/60)} min`.\n' if self.user_timeout>0 else ''
        msg = (
            f'__**Lobby{self.name}**__\n'
            f'Mirror this lobby with: `!clonelobby {self.hash}`\n'
            f'React to message to join lobby. Once `{self.size}` members are reached all members will be pinged.\n'
            f'{lobby_timeout_str}'
            f'{reac_timeout_str}'
            f'**Members {len(self.members)}/{self.size}:**\n'
            f'{mention_str}\n'
        )
        return msg
    
    def getNotificationString(self, users):
        mention_str = ', '.join([user.mention for user in users.values()])
        name_str = f'**{self.name}**' if self.name != '' else ''
        msg = (
            f'Lobby {name_str} `{self.hash}` is now filled.\n'
            f'{mention_str}'
        )
        return msg

    async def fetchMessages(self):
        messages_updated = {}
        for message_id in self.messages:
            try:
                msg = await self.messages[message_id].channel.fetch_message(message_id)
                messages_updated[message_id] = msg
            except: pass
        self.messages = messages_updated
    
    async def fetchMembers(self):
        members_updated = {}
        for message_id in self.messages:
            for reaction in self.messages[message_id].reactions:
                try:
                    async for user in reaction.users():
                        if user.id == BOT_ID: continue
                        members_updated[user.id] = user
                        if user.id not in self.members:
                            self.members_last_active[user.id] = time.time()
                except: pass
        if members_updated != self.members:
            self.members = members_updated
            self.last_activity = time.time()

    async def updateMemberTimeouts(self):
        if self.user_timeout < 0: return
        fetched_messages = False
        for user_id in self.members:
            if time.time() - self.members_last_active[user_id] > self.user_timeout:
                if not fetched_messages: await self.fetchMessages()

                # Clear reactions.
                for message in self.messages.values():
                    for reaction in message.reactions:
                        try:
                            await message.remove_reaction(reaction, self.members[user_id])
                        except: pass
    
    async def updateMessages(self):
        if self.finalized: return
        lobby_string = self.getLobbyString()
        for message in self.messages.values():
            try: await message.edit(content=lobby_string)
            except: pass

    async def updateLobby(self):
        if self.finalized: return

        await self.fetchMessages()
        await self.fetchMembers()
        await self.updateMessages()

    def isFull(self):
        return len(self.members) >= self.size

    async def notifyMembers(self):
        notification_messages = {}
        for message in self.messages.values():
            # Get users who reacted to each message
            users = {}
            try:
                for reaction in message.reactions:
                    async for user in reaction.users():
                        if user.id == BOT_ID: continue
                        users[user.id] = user
                # Send a message in the specified channel
                content = self.getNotificationString(users)
            
                noti_message = await message.channel.send(content)
                notification_messages[noti_message.id] = noti_message
            except: pass
        return notification_messages

    async def finalizeLobby(self, notify=True, reason='Lobby filled.'):
        if self.finalized: return
        self.finalized = True
        if notify:
            await self.notifyMembers()
        for message in self.messages.values():
            try: await message.edit(content=f'~~{message.content}~~\n{reason}')
            except: pass

    async def postMessage(self, ctx):
        try:
            message = await ctx.send(self.getLobbyString(False))
            await message.add_reaction('✅')
            self.messages[message.id] = message
        except:
            return None
        return message

class PermanentLobby(Lobby):
    def __init__(self, size, name, author_id, lobby_timeout, user_timeout, bot):
        super(PermanentLobby,self).__init__(size, name, author_id, lobby_timeout, user_timeout, bot)
        self.notification_messages = {}
        self.type = 'PermanentLobby'
        self.notification_post_time = -1
    
    def getSaveData(self):
        data = Lobby.getSaveData(self)
        data['notifications'] = [[message.id, message.channel.id] for message in self.notification_messages.values()]
        data['type'] = 'PermanentLobby'
        return data
    
    async def loadData(self, data):
        await Lobby.loadData(self, data)
        notification_messages = {}
        for [message_id, channel_id] in data['notifications']:
            try:
                channel = await self.bot.fetch_channel(channel_id)
                message = await channel.fetch_message(message_id)
                notification_messages[message_id] = message
            except: pass
        self.notification_messages = notification_messages

    async def purgeNotifications(self):
        for message in self.notification_messages.values():
            try: await message.delete()
            except: pass
        self.notification_messages = {}

    async def resetLobby(self):
        # Clear reactions.
        for message in self.messages.values():
            for reaction in message.reactions:
                try:
                    async for user in reaction.users():
                        if user.id == BOT_ID: continue
                        try: await message.remove_reaction(reaction, user)
                        except: pass
                except: pass

        # Clear members.
        self.members = {}

        # Reset messages.
        lobby_string = self.getLobbyString()
        for message in self.messages.values():
            try: await message.edit(content=lobby_string)
            except: pass

    async def finalizeLobby(self, notify=True, reason='Lobby filled.'):
        if notify:
            await self.purgeNotifications()
            self.notification_messages = await self.notifyMembers()
        if reason == 'Lobby filled.':
            await self.resetLobby()
        else:
            await Lobby.finalizeLobby(self, False, reason)

    def getLobbyString(self, add_mentions=True):
        mention_str = '\n'.join([member.mention for member in self.members.values()])
        if mention_str == '': mention_str = '...'
        if not add_mentions: mention_str = '...'
        lobby_timeout_str = f'Lobby timer: `{self.timeRemaining()} min`.\n' if self.timeout>0 else ''
        reac_timeout_str = f'Reaction timeout: `{math.floor(self.user_timeout/60)} min`.\n' if self.user_timeout>0 else ''
        msg = (
            f'__**Permanent lobby{self.name}**__\n'
            f'Mirror this lobby with: `!clonelobby {self.hash}`\n'
            f'React to message to join lobby. Once `{self.size}` members are reached all members will be pinged.\n'
            f'{lobby_timeout_str}'
            f'{reac_timeout_str}'
            f'**Members {len(self.members)}/{self.size}:**\n'
            f'{mention_str}\n'
        )
        return msg