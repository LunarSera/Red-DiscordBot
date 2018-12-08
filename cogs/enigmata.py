import os, discord, random, asyncio, aiohttp, string
import datetime, time
from datetime import datetime
from discord.ext import commands
from __main__ import send_cmd_help
from random import choice as randchoice, randint
from .utils.dataIO import dataIO
from .utils.chat_formatting import escape_mass_mentions, italics, pagify
from .utils.chat_formatting import *
from .utils import checks
from urllib.parse import quote_plus
DB_VERSION = 2

class Enigmata:
    """These commands give you insight into the lore of Enigmata: Stellar War."""

    def __init__(self, bot):
        self.bot = bot
        self.lore = dataIO.load_json("data/enigmata/lore.json")
        self.images = dataIO.load_json("data/enigmata/image.index.json")
        self.session = aiohttp.ClientSession(loop=self.bot.loop)

    def __unload(self):
        self.session.close()

    async def first_word(self, msg):
        return msg.split(" ")[0].lower()

    async def get_prefix(self, server, msg):
        prefixes = self.bot.settings.get_prefixes(server)
        for p in prefixes:
            if msg.startswith(p):
                return p
        return None
		
    async def part_of_existing_command(self, alias, server):
        '''Command or alias'''
        for command in self.bot.commands:
            if alias.lower() == command.lower():
                return True
        return False

    async def make_server_folder(self, server):
        if not os.path.exists("data/enigmata/{}".format(server.id)):
            print("Creating server folder")
            os.makedirs("data/enigmata/{}".format(server.id))

    async def on_message(self, message):
        if len(message.content) < 2 or message.channel.is_private:
            return

        msg = message.content
        server = message.server
        channel = message.channel
        prefix = await self.get_prefix(server, msg)
        if not prefix:
            return
        alias = await self.first_word(msg[len(prefix):])

        if alias in self.images["server"][server.id]:
            image = self.images["server"][server.id][alias]
            await self.bot.send_typing(channel)
            await self.bot.send_file(channel, image)

    async def check_command_exists(self, command, server):
        if command in self.images["server"][server.id]:
            return True
        elif await self.part_of_existing_command(command, server):
            return True
        else:
            return False

#-----------------------------------------------------------------------------------------------------------------
    @commands.group(no_pm=True, pass_context=True)
    async def enigmata(self, ctx):
        """Enigmata Lore."""
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)

    @enigmata.command(hidden=True)
    async def story(self):
        """Says a random piece of lore from Enigmata: Stellar War"""
        await self.bot.say(randchoice(self.lore))
		
    @enigmata.command(pass_context=True)
    @checks.admin_or_permissions(manage_server=True)
    async def select(self, ctx, file=None, *, comment=None):
        """Upload a file from the bot."""

        message = ctx.message
        server = message.server

        if file == None:
            if os.listdir("data/enigmata/453668709396119562") == []:
                await self.bot.say("There is nothing saved yet. Use the save command to begin.")
                return

            msg = "Send `n/enigmata select 'filename'` to reupload.\nSend `n/enigmata delete 'filename'` to remove file from this list.\nRequires *Manage Server Permission*\n\nList of available files to upload:\n"
            for file in os.listdir("data/enigmata/453668709396119562"):
                msg += "`{}\n".format(file)[:-5] + "`"
            await self.bot.say(msg)
            return

        if "." not in file:
            for fname in os.listdir("data/enigmata/453668709396119562"):
                if fname.startswith(file):
                    file += "." + fname.partition(".")[2]
                    break

        if os.path.isfile("data/enigmata/453668709396119562/{}".format(file)) is True:
                await self.bot.upload(fp="data/enigmata/453668709396119562/{}".format(file))
        else:
            await self.bot.say(
                "That file doesn't seem to exist. Make sure it is the good name, try to add the extention (especially if two files have the same name)"
            )

    @enigmata.command(pass_context=True, no_pm=True, invoke_without_command=True)
    @checks.admin_or_permissions(manage_server=True)
    async def delete(self, ctx, cmd):
        """Removes selected image."""
        author = ctx.message.author
        server = ctx.message.server
        channel = ctx.message.channel
        cmd = cmd.lower()
        if server.id not in self.images["server"]:
            await self.bot.say("I have no images on this server!")
            return
        if cmd not in self.images["server"][server.id]:
            await self.bot.say("{} is not an image for this server!".format(cmd))
            return
        os.remove(self.images["server"][server.id][cmd])
        del self.images["server"][server.id][cmd]
        dataIO.save_json("data/enigmata/image.index.json", self.images)
        await self.bot.say("{} has been deleted from my directory.".format(cmd))

    @enigmata.command(pass_context=True, no_pm=True, invoke_without_command=True)
    async def save(self, ctx, cmd):
        """Add an image to direct upload.\n Where cmd = name of your choice."""
        author = ctx.message.author
        server = ctx.message.server
        channel = ctx.message.channel
        prefix = await self.get_prefix(server, ctx.message.content)
        msg = ctx.message
        if server.id not in self.images["server"]:
            await self.make_server_folder(server)
            self.images["server"][server.id] = {}
        if cmd is not "":
            if await self.check_command_exists(cmd, server):
                await self.bot.say("{} is already in the list, try another!".format(cmd))
                return
            else:
                await self.bot.say("{} added as the command!".format(cmd))
        await self.bot.say("Upload an image for me to use! You have 1 minute.")
        while msg is not None:
            msg = await self.bot.wait_for_message(author=author, timeout=60)
            if msg is None:
                await self.bot.say("No image uploaded then.")
                break

            if msg.attachments != []:
                filename = msg.attachments[0]["filename"][-4:]
                directory = "data/enigmata/{}{}".format(server.id, filename)
                if cmd is None:
                    cmd = filename.split(".")[0]
                cmd = cmd.lower()
                directory = "data/enigmata/{}/{}{}".format(server.id, cmd, filename)
                self.images["server"][server.id][cmd] = directory
                dataIO.save_json("data/enigmata/image.index.json", self.images)
                async with self.session.get(msg.attachments[0]["url"]) as resp:
                    test = await resp.read()
                    with open(self.images["server"][server.id][cmd], "wb") as f:
                        f.write(test)
                await self.bot.send_message(channel, "{} has been added to my files!"
                                            .format(cmd))
                break
            if msg.content.lower().strip() == "exit":
                await self.bot.say("Your changes have been saved.")
                break

def check_folder():
    if not os.path.exists("data/enigmata"):
        print("Creating data/enigmata folder")
        os.makedirs("data/enigmata")

def check_file():
    data = {"server":{}}
    f = "data/enigmata/image.index.json"
    if not dataIO.is_valid_json(f):
        print("Creating default image.index.json...")
        dataIO.save_json(f, data)

def check_file():
    lore = {"server":{}}
    f = "data/enigmata/lore.json"
    if not dataIO.is_valid_json(f):
        print("Creating default lore.json...")
        dataIO.save_json(f, lore)


def setup(bot):
    check_folder()
    check_file()
    bot.add_cog(Enigmata(bot))