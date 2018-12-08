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

class Entertainment:

    def __init__(self, bot):
        self.bot = bot

    @commands.command(aliases=['nekofacts','catfact','catfacts'])
    async def nekofact(self):
        """Source of the infamous DynoBotTM Catfacts"""
        try:
            url = 'https://catfact.ninja/fact'
            conn = aiohttp.TCPConnector(verify_ssl=False)
            session = aiohttp.ClientSession(connector=conn)
            async with session.get(url) as response:
                fact = (await response.json())['fact']
                await self.bot.say(fact)
                session.close()
        except:
            await self.bot.say("I was unable to get a cat fact.")

    @commands.command(pass_context=True)
    async def soulmate(self, ctx, user: discord.Member):
        """Found your one true love?"""
        author = ctx.message.author
        choice = 'I wish I could love you more than this. But I am just an AI', 'I could stare at you forever and still feel like I have not gotten enough of you.', 'I hated the rain until I danced with you, then like the rain, I fell for you.', 'You are irreplaceable and irresistible. Together we will make this unbreakable.', 'There are 3 great things that happened in my life. The first thing is that I fell in love with you The second thing is that you fell in love with me. And the third thing is that we stayed in love with each other through all these years.', 'Loving you is like breathing...I just cannot stop.', 'Everyone says you only fall in love once but thats not true, everytime I hear your voice I fall in love all over again.'
        if user.id == self.bot.user.id:
            await self.bot.say(randchoice(choice))
        else:
            await self.bot.say(author.mention + " has a compatibility rating with " + user.mention + " as " +
                               str(randint(0, 100)) + "%!")

    @commands.command(hidden=False)
    async def lmgtfy(self, *, search_terms : str):
        """Creates a lmgtfy link"""
        search_terms = escape_mass_mentions(search_terms.replace("+","%2B").replace(" ", "+"))
        await self.bot.say("https://lmgtfy.com/?q={}".format(search_terms))

    @commands.command(no_pm=True, hidden=False)
    async def hug(self, user : discord.Member, intensity : int=1):
        """Because everyone likes hugs

        Up to 10 intensity levels."""
        name = italics(user.display_name)
        if intensity <= 0:
            msg = "(っ˘̩╭╮˘̩)っ" + name
        elif intensity <= 3:
            msg = "(っ´▽｀)っ" + name
        elif intensity <= 6:
            msg = "╰(*´︶`*)╯" + name
        elif intensity <= 9:
            msg = "(つ≧▽≦)つ" + name
        elif intensity >= 10:
            msg = "(づ￣ ³￣)づ{} ⊂(´・ω・｀⊂)".format(name)
        await self.bot.say(msg)

    @commands.command()
    async def urban(self, *, search_terms : str, definition_number : int=1):
        """Urban Dictionary search

        Definition number must be between 1 and 10"""
        def encode(s):
            return quote_plus(s, encoding='utf-8', errors='replace')

        # definition_number is just there to show up in the help
        # all this mess is to avoid forcing double quotes on the user

        search_terms = search_terms.split(" ")
        try:
            if len(search_terms) > 1:
                pos = int(search_terms[-1]) - 1
                search_terms = search_terms[:-1]
            else:
                pos = 0
            if pos not in range(0, 11): # API only provides the
                pos = 0                 # top 10 definitions
        except ValueError:
            pos = 0

        search_terms = "+".join([encode(s) for s in search_terms])
        url = "http://api.urbandictionary.com/v0/define?term=" + search_terms
        try:
            async with aiohttp.get(url) as r:
                result = await r.json()
            if result["list"]:
                definition = result['list'][pos]['definition']
                example = result['list'][pos]['example']
                defs = len(result['list'])
                msg = ("**Definition #{} out of {}:\n**{}\n\n"
                       "**Example:\n**{}".format(pos+1, defs, definition,
                                                 example))
                msg = pagify(msg, ["\n"])
                for page in msg:
                    await self.bot.say(page)
            else:
                await self.bot.say("Your search terms gave no results.")
        except IndexError:
            await self.bot.say("There is no definition #{}".format(pos+1))
        except:
            await self.bot.say("Error.")

def setup(bot):
    bot.add_cog(Entertainment(bot))