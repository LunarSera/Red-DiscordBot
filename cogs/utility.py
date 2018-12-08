import os, discord, random, asyncio, aiohttp, string, logging
import datetime, time
from datetime import datetime
from discord.ext import commands
from __main__ import send_cmd_help
from random import choice as randchoice, randint
from .utils.dataIO import dataIO
from .utils.chat_formatting import escape_mass_mentions, italics, pagify, box
from .utils.chat_formatting import *
from .utils import checks
from urllib.parse import quote_plus
DB_VERSION = 2

def get_role(ctx, role_id):
    roles = set(ctx.message.server.roles)
    for role in roles:
        if role.id == role_id:
            return role
    return None

class Utility:
    """Useful backend commands"""

    def __init__(self, bot):
        self.bot = bot
        self.new_data = False
        self.seen = dataIO.load_json('data/enigmata/seen.json')
        self.session = aiohttp.ClientSession(loop=self.bot.loop)
        self.say = dataIO.load_json("data/enigmata/say.json")

    async def data_writer(self):
        while self == self.bot.get_cog('Seen'):
            if self.new_data:
                dataIO.save_json('data/enigmata/seen.json', self.seen)
                self.new_data = False
                await asyncio.sleep(60)
            else:
                await asyncio.sleep(30)

    @commands.command(pass_context=True)
    async def ping(self,ctx):
        """Shows latency from Bot to Server."""
        channel = ctx.message.channel
        t1 = time.perf_counter()
        await self.bot.send_typing(channel)
        t2 = time.perf_counter()
        await self.bot.say("Ping: {}ms".format(round((t2-t1)*1000)))

    @commands.command(pass_context=True, no_pm=True, name='seen')
    async def _seen(self, context, username: discord.Member):
        '''Shows the last time the bot saw a user.'''
        server = context.message.server
        author = username
        timestamp_now = context.message.timestamp
        if server.id in self.seen:
            if author.id in self.seen[server.id]:
                data = self.seen[server.id][author.id]
                timestamp_then = datetime.fromtimestamp(data['TIMESTAMP'])
                timestamp = timestamp_now - timestamp_then
                days = timestamp.days
                seconds = timestamp.seconds
                hours = seconds // 3600
                seconds = seconds - (hours * 3600)
                minutes = seconds // 60
                if sum([days, hours, minutes]) < 1:
                    ts = 'just now'
                else:
                    ts = ''
                    if days == 1:
                        ts += '{} day, '.format(days)
                    elif days > 1:
                        ts += '{} days, '.format(days)
                    if hours == 1:
                        ts += '{} hour, '.format(hours)
                    elif hours > 1:
                        ts += '{} hours, '.format(hours)
                    if minutes == 1:
                        ts += '{} minute ago'.format(minutes)
                    elif minutes > 1:
                        ts += '{} minutes ago'.format(minutes)
                em = discord.Embed(color=discord.Color.green())
                avatar = author.avatar_url if author.avatar else author.default_avatar_url
                em.set_author(name='{} was seen {}'.format(author.display_name, ts), icon_url=avatar)
                await self.bot.say(embed=em)
            else:
                message = 'I haven\'t seen {} yet.'.format(author.display_name)
                await self.bot.say('{}'.format(message))
        else:
            message = 'I haven\'t seen {} yet.'.format(author.display_name)
            await self.bot.say('{}'.format(message))

    async def on_message(self, message):
        if not message.channel.is_private and self.bot.user.id != message.author.id:
            if not any(message.content.startswith(n) for n in self.bot.settings.prefixes):
                server = message.server
                author = message.author
                ts = message.timestamp.timestamp()
                data = {}
                data['TIMESTAMP'] = ts
                if server.id not in self.seen:
                    self.seen[server.id] = {}
                self.seen[server.id][author.id] = data
                self.new_data = True

    @commands.command(pass_context=True, no_pm=True, aliases=['uinfo'])
    async def userinfo(self, ctx, *, user: discord.Member=None):
        """Shows a user's information."""
        author = ctx.message.author
        server = ctx.message.server
        if not user:
            user = author
        roles = [x.name for x in user.roles if x.name != "@everyone"]
        if not roles: roles = ["None"]
        data = "```python\n"
        data += "Name: {}\n".format(str(user))
        data += "Nickname: {}\n".format(str(user.nick))
        data += "ID: {}\n".format(user.id)
        if user.game is None:
            pass
        elif user.game.url is None:
            data += "Playing: {}\n".format(str(user.game))
        else:
            data += "Streaming: {} ({})\n".format(str(user.game),(user.game.url))
        passed = (ctx.message.timestamp - user.created_at).days
        data += "Created: {} ({} days ago)\n".format(user.created_at, passed)
        passed = (ctx.message.timestamp - joined_at).days
        data += "Joined: {} ({} days ago)\n".format(joined_at, passed)
        data += "Roles: {}\n".format(", ".join(roles))
        if user.avatar_url != "":
            data += "Avatar:"
            data += "```"
            data += user.avatar_url
        else:
            data += "```"
        await self.bot.say(data)

    @commands.command(pass_context=True, no_pm=True, aliases=['sinfo'])
    async def serverinfo(self, ctx):
        """Shows information about the server."""
        server = ctx.message.server
        online = str(len([m.status for m in server.members if str(m.status) == "online" or str(m.status) == "idle"]))
        total_users = str(len(server.members))
        text_channels = len([x for x in server.channels if str(x.type) == "text"])
        voice_channels = len(server.channels) - text_channels

        data = "```python\n"
        data += "Name: {}\n".format(server.name)
        data += "ID: {}\n".format(server.id)
        data += "Region: {}\n".format(server.region)
        data += "Users: {}/{}\n".format(online, total_users)
        data += "Text channels: {}\n".format(text_channels)
        data += "Voice channels: {}\n".format(voice_channels)
        data += "Roles: {}\n".format(len(server.roles))
        passed = (ctx.message.timestamp - server.created_at).days
        data += "Created: {} ({} days ago)\n".format(server.created_at, passed)
        data += "Owner: {}\n".format(server.owner)
        if server.icon_url != "":
            data += "Icon:"
            data += "```"
            data += server.icon_url
        else:
            data += "```"
        await self.bot.say(data)
###################
        print("Testing values in data/enigmata")
        for server in self.bot.servers:
            try:
                self.say[server.id]["ROLE"]
                self.say[server.id]["USERS"]
            except:
                self.say[server.id] = {}
                self.say[server.id]["ROLE"] = None
                self.say[server.id]["USERS"] = []
        
    @commands.group(name="setsay", pass_context=True, no_pm=True, invoke_without_command=True)
    @checks.admin_or_permissions()
    async def sayset(self, ctx):
        """The 'Say' command set
add - Adds a user to have the abillity to use the say command
list - list users allowed and permited role
remove - Removes a user to have the abillity to use the say command
role - Adds a permited role to use the say command"""
        if ctx.invoked_subcommand is None:
            await self.bot.send_message(ctx.message.channel, "```Please use the say command with: \n add - Adds a **user** to have the abillity to use the say command \n remove - Removes a **user** to have the abillity to use the say command \n role - Adds a role and those with it can use the say command \n list - lists permited users and the permited role```")

    @sayset.command(name="list", pass_context=True)
    @checks.admin_or_permissions()
    async def say_list(self,ctx):
        """Lists permited users and the permitted role"""
        names = []
        for user_id in self.say[ctx.message.server.id]["USERS"]:
            names.append(discord.utils.get(self.bot.get_all_members(), id=user_id).name)
                    
        msg = ("+ Permited\n"
               "{}\n\n"
               "".format(", ".join(sorted(names))))

        for page in pagify(msg, [" "], shorten_by=16):
            await self.bot.say(box(page.lstrip(" "), lang="diff"))

        #gets the name of the role and displays it
        if self.say[ctx.message.server.id]["ROLE"] is not None:
            await self.bot.send_message(ctx.message.channel, "Permited Role: **{}**".format(get_role(ctx, self.say[ctx.message.server.id]["ROLE"]).name))
        else:
            await self.bot.send_message(ctx.message.channel, "No role has permission")
            
    @sayset.command(name="add", pass_context=True, no_pm=True)
    @checks.admin_or_permissions()
    async def say_add (self, ctx, user: discord.Member):
        """Adds a [user] to have the abillity to use the say command"""
        self.say[ctx.message.server.id]["USERS"].append(user.id)
        self.save()
        await self.bot.send_message(ctx.message.channel, "Done!")

    @sayset.command(name="remove", pass_context=True, no_pm=True)
    @checks.admin_or_permissions()
    async def say_remove (self, ctx, user: discord.Member):
        """Removes a [user] to have the abillity to use the say command"""
        try:
            self.say[ctx.message.server.id]["USERS"].remove(user.id)
            self.save()
            await self.bot.send_message(ctx.message.channel, "Done!")

        except:
            await self.bot.send_message(ctx.message.channel, "Are you sure that {} had the permision in the first place?".format(user.mention))

    @sayset.command(name="role", pass_context=True)
    @checks.admin_or_permissions()
    async def say_role(self, ctx, role_name:str):
        """Sets the permitted role"""
        role = discord.utils.get(ctx.message.server.roles, name=role_name)

        if role is not None:
            self.say[ctx.message.server.id]["ROLE"] = role.id
            self.save()
            await self.bot.send_message(ctx.message.channel, "Role added!")

        else:
            await self.bot.send_message(ctx.message.channel, "Role not found!")

    @commands.command(name="say", pass_context=True, no_pm =True)
    async def bot_say(self, ctx, *, text):
        """The bot repeats what you tell it to"""

        if '@everyone' in ctx.message.content and '@here' in ctx.message.content:
            await self.bot.send_message(ctx.message.channel, "Woh! {}, please don't do that".format(ctx.message.author.mention))
            return
    
        #IF there are no mentions such as @everyone or @here must test useing a string
        
        if ctx.message.channel.permissions_for(ctx.message.server.me).manage_messages is not True:
            await self.bot.say("This command requires the **Manage Messages** permission.")
            return
        
            #checks if they are allowed (role or permitted)         
        if ctx.message.author.id in self.say[ctx.message.server.id]["USERS"] or get_role(ctx, self.say[ctx.message.server.id]["ROLE"])  in ctx.message.author.roles:
            await self.bot.delete_message(ctx.message)
            await self.bot.send_message(ctx.message.channel, text)
        else: 
            await self.bot.say("You need to be given access to this command") 
        


    def save(self):
        dataIO.save_json("data/enigmata/say.json", self.say)

    async def server_join(self, server):
        self.say[server.id]={
            "ROLE":None,
            "USERS":[],
        }

        self.save()

def check_folder():
    if not os.path.exists('data/enigmata'):
        print('Creating data/enigmata')
        os.makdirs('data/enigmata')

def check_file():
    if not dataIO.is_valid_json("data/enigmata/say.json"):
        print("Creating empty say.json...")    
        dataIO.save_json("data/enigmata/say.json", {})
		
def check_file():
    data = {}
    data['db_version'] = DB_VERSION
    f = 'data/enigmata/seen.json'
    if not dataIO.is_valid_json(f):
        print('Creating seen.json...')
        dataIO.save_json(f, data)
    else:
        check = dataIO.load_json(f)
        if 'db_version' in check:
            if check['db_version'] < DB_VERSION:
                data = {}
                data['db_version'] = DB_VERSION
                dataIO.save_json(f, data)
                print('SEEN: Database version too old, resetting!')
        else:
            data = {}
            data['db_version'] = DB_VERSION
            dataIO.save_json(f, data)
            print('SEEN: Database version too old, resetting!')

def setup(bot):
    check_file()
    check_folder()
    n = Utility(bot)
    loop = asyncio.get_event_loop()
    loop.create_task(n.data_writer())
    bot.add_listener(n.server_join, "on_server_join")
    bot.add_cog(Utility(bot))