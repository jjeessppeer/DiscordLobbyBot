import os
import random
import secrets
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
BOT_ID = int(os.getenv('BOT_ID'))

class Lobby():
    def __init__(self, size, name, author_id):
        self.author_id = author_id
        self.size = size
        self.name = f' - {name}' if name != "" else ""

        self.update_lock = asyncio.Lock()

        self.hash = secrets.token_hex(4)
        self.messages = {}
        self.members = {}
        self.finalized = False

    def load(self, data):
        pass

    def getLobbyString(self):
        mention_str = '\n'.join([member.mention for member in self.members.values()])
        msg = (
            f'__**Lobby{self.name}**__\n'
            f'Copy with: `!clonelobby {self.hash}`\n'
            f'React to message to join lobby. Once {self.size} members are reached all members will be pinged.\n'
            'This lobby can be mirrored in multiple channels using !clonelobby.\n'
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
            except discord.errors.NotFound: pass
            except discord.errors.Forbidden: pass
        self.messages = messages_updated
    
    async def fetchMembers(self):
        self.members = {}
        for message_id in self.messages:
            for reaction in self.messages[message_id].reactions:
                async for user in reaction.users():
                    if user.id == BOT_ID: continue
                    self.members[user.id] = user
         
    async def updateLobby(self):
        if self.finalized: return

        await self.fetchMessages()
        await self.fetchMembers()
        
        lobby_string = self.getLobbyString()
        for message in self.messages.values():
            await message.edit(content=lobby_string)

    def isFull(self):
        return len(self.members) >= self.size

    async def notifyMembers(self):
        notification_messages = {}
        for message in self.messages.values():
            # Get users who reacted to each message
            users = {}
            for reaction in message.reactions:
                async for user in reaction.users():
                    if user.id == BOT_ID: continue
                    users[user.id] = user
            # Send a message in the specified channel
            content = self.getNotificationString(users)
            noti_message = await message.channel.send(content)
            notification_messages[noti_message.id] = noti_message
        return notification_messages

    async def finalizeLobby(self):
        if self.finalized: return
        self.finalized = True
        await self.notifyMembers()
        for message in self.messages.values():
            try: await message.edit(content=f'~~{message.content}~~\nLobby finished.')
            except: pass

    async def postMessage(self, ctx):
        message = await ctx.send(self.getLobbyString())
        self.messages[message.id] = message
        await message.add_reaction('✅')
        return message

class PermanentLobby(Lobby):
    def __init__(self, size, name, author_id):
        super(PermanentLobby,self).__init__(size, name, author_id)
        self.notification_messages = {}

    async def finalizeLobby(self):
        self.notification_messages = await self.notifyMembers()
        # Clear members and reactions
        for message in self.messages.values():
            for reaction in message.reactions:
                try:
                    async for user in reaction.users():
                        if user.id == BOT_ID: continue
                        try: await message.remove_reaction(reaction, user)
                        except: print("Failed to remove reactions.")
                except: print("Failed to get reactions.")
        self.members = {}

        lobby_string = self.getLobbyString()
        for message in self.messages.values():
            try: await message.edit(content=lobby_string)
            except: print("Failed to remove message")

    def getLobbyString(self):
        mention_str = '\n'.join([member.mention for member in self.members.values()])
        msg = (
            f'__**Permanent{self.name}**__\n'
            f'Copy with: `!clonelobby {self.hash}`\n'
            f'React to message to join lobby. Once {self.size} members are reached all members will be pinged.\n'
            'This lobby can be mirrored in multiple channels using !clonelobby.\n'
            'Reactions are removed after 30 minutes.\n'
            f'**Members {len(self.members)}/{self.size}:**\n'
            f'{mention_str}\n'
        )
        return msg