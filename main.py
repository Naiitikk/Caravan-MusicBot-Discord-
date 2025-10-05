import discord
import os
from discord.ext import commands
import yt_dlp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import asyncio
from collections import deque
from flask import Flask

# Load Opus library for voice support
if not discord.opus.is_loaded():
    # Try different opus library paths
    opus_libs = ['libopus.so.0', 'libopus.so', 'opus']
    for lib in opus_libs:
        try:
            discord.opus.load_opus(lib)
            break
        except OSError:
            continue
    
    if not discord.opus.is_loaded():
        print("Warning: Could not load opus library. Voice features may not work properly.")

# Initialize Flask app
flask_app = Flask(__name__)

# Flask health check route
@flask_app.route('/health')
def health_check():
    return "I'm alive!", 200

# Define root route
@flask_app.route('/')
def home():
    return "Welcome to the Music Bot API!", 200

# Discord bot setup continues...
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
# Spotify 
SPOTIFY_CLIENT_ID = 'your_client_id'
SPOTIFY_CLIENT_SECRET = 'your_client_secret'
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET
))
# Queue system
music_queues = {}

class MusicQueue:
    def __init__(self):
        self.queue = deque()
        self.current = None
        self.is_playing = False

    def add_song(self, song_info):
        self.queue.append(song_info)

    def get_next(self):
        if self.queue:
            return self.queue.popleft()
        return None

    def clear(self):
        self.queue.clear()
        self.current = None

    def get_queue_list(self):
        return list(self.queue)

ydl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'noplaylist': True,
    'extractaudio': False,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'no_warnings': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
}

def get_queue(guild_id):
    if guild_id not in music_queues:
        music_queues[guild_id] = MusicQueue()
    return music_queues[guild_id]

async def play_next(ctx):
    queue = get_queue(ctx.guild.id)

    if not queue.queue:
        queue.is_playing = False
        # Clear channel topic when no music is playing
        try:
            await ctx.channel.edit(topic="🎵 No music playing")
        except discord.Forbidden:
            pass  # Bot doesn't have permission to edit channel topic
        await ctx.send("🎵 Queue is empty!")
        return

    next_song = queue.get_next()
    queue.current = next_song
    queue.is_playing = True

    # Download from YouTube using yt-dlp
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch:{next_song['search_query']}", download=False)['entries'][0]
        url = info['url']

    def after_playing(error):
        if error:
            print(f'Player error: {error}')
        asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)

    ffmpeg_options = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn'
    }
    source = discord.FFmpegPCMAudio(url, **ffmpeg_options)
    ctx.voice_client.play(source, after=after_playing)

    # Update channel topic with currently playing song
    try:
        await ctx.channel.edit(topic=f"🎵 Now Playing: {info['title']}")
    except discord.Forbidden:
        pass  # Bot doesn't have permission to edit channel topic

    # Create simple now playing embed
    embed = discord.Embed(
        title="🎵 Now Playing",
        description=f"**{info['title']}**",
        color=0x00ff41
    )
    embed.add_field(name="Requested by", value=next_song['requester'], inline=True)
    embed.add_field(name="Duration", value=f"{info.get('duration', 'Unknown')}s", inline=True)

    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    activity = discord.Activity(type=discord.ActivityType.listening, name="!help | Cutiepie")
    await bot.change_presence(activity=activity)
    print(f"✅ Logged in as {bot.user.name}")

@bot.command()
async def join(ctx):
    if ctx.author.voice:
        await ctx.author.voice.channel.connect()

        embed = discord.Embed(
            title="🎧 Connected",
            description=f"Joined **{ctx.author.voice.channel.name}**",
            color=0x00ff41
        )

        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Connection Failed",
            description="Please join a voice channel first!",
            color=0xff0000
        )
        await ctx.send(embed=embed)

@bot.command()
async def play(ctx, *, query):
    if not ctx.author.voice:
        await ctx.send("❌ Join a voice channel first.")
        return

    if ctx.voice_client is None:
        await ctx.invoke(bot.get_command("join"))

    queue = get_queue(ctx.guild.id)

    # Detect Spotify link
    if "open.spotify.com" in query:
        try:
            if "track" in query:
                track_id = query.split("/")[-1].split("?")[0]
                track = sp.track(track_id)
                search_query = f"{track['name']} {track['artists'][0]['name']}"
                display_title = f"{track['name']} by {track['artists'][0]['name']}"
            else:
                await ctx.send("⚠️ Only individual track links are supported for now.")
                return
        except Exception as e:
            await ctx.send("❌ Failed to fetch Spotify track.")
            print(e)
            return
    else:
        search_query = query
        display_title = query

    song_info = {
        'search_query': search_query,
        'title': display_title,
        'requester': ctx.author.name
    }

    queue.add_song(song_info)

    if not queue.is_playing:
        embed = discord.Embed(
            title="▶️ Playing",
            description=f"**{display_title}**",
            color=0x00ff41
        )
        embed.add_field(name="Requested by", value=ctx.author.name, inline=True)

        await ctx.send(embed=embed)
        await play_next(ctx)
    else:
        embed = discord.Embed(
            title="📝 Added to Queue",
            description=f"**{display_title}**",
            color=0x00ff41
        )
        embed.add_field(name="Position", value=f"#{len(queue.get_queue_list()) + 1}", inline=True)
        embed.add_field(name="Requested by", value=ctx.author.name, inline=True)

        await ctx.send(embed=embed)

@bot.command()
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()

        embed = discord.Embed(
            title="⏭️ Track Skipped",
            description="Moving to next song...",
            color=0x00ff41
        )

        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Skip Failed",
            description="No music playing to skip",
            color=0xff0000
        )
        await ctx.send(embed=embed)

@bot.command()
async def queue(ctx):
    queue = get_queue(ctx.guild.id)

    if not queue.current and not queue.queue:
        await ctx.send("📭 Queue is empty.")
        return

    embed = discord.Embed(title="🎵 Music Queue", color=0x00ff41)

    if queue.current:
        embed.add_field(
            name="🎵 Currently Playing",
            value=f"**{queue.current['title']}**\nRequested by: {queue.current['requester']}",
            inline=False
        )

    if queue.queue:
        queue_list = queue.get_queue_list()
        queue_text = ""
        for i, song in enumerate(queue_list[:10], 1):  # Show max 10 songs
            queue_text += f"{i}. **{song['title']}** - {song['requester']}\n"

        if len(queue_list) > 10:
            queue_text += f"\n... and {len(queue_list) - 10} more songs"

        embed.add_field(name="📋 Up Next", value=queue_text, inline=False)
    else:
        embed.add_field(name="📋 Up Next", value="No songs in queue", inline=False)

    await ctx.send(embed=embed)

@bot.command()
async def clear(ctx):
    queue = get_queue(ctx.guild.id)
    queue.clear()
    if ctx.voice_client:
        ctx.voice_client.stop()
    await ctx.send("🗑️ Queue cleared!")

@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="🎵 Music Bot Commands",
        description="Available commands:",
        color=0x00ff41
    )

    embed.add_field(
        name="Basic Commands",
        value="`!join` - Join voice channel\n`!leave` - Leave voice channel\n`!play <song>` - Play music\n`!skip` - Skip current song\n`!queue` - Show queue\n`!clear` - Clear queue\n`!stop` - Stop playback",
        inline=False
    )

    embed.add_field(
        name="Supported Sources",
        value="• YouTube links and searches\n• Spotify track links",
        inline=False
    )
    await ctx.send(embed=embed)

@bot.command()
async def leave(ctx):
    if ctx.voice_client:
        queue = get_queue(ctx.guild.id)
        queue.clear()
        await ctx.voice_client.disconnect()
        await ctx.send("👋 Bye ! See you soon cutie ")
    else:
        await ctx.send("❌ I'm not in a voice channel.")

@bot.command()
async def stop(ctx):
    if ctx.voice_client:
        queue = get_queue(ctx.guild.id)
        queue.clear()
        ctx.voice_client.stop()
        # Clear channel topic when stopping
        try:
            await ctx.channel.edit(topic="🎵 No music playing")
        except discord.Forbidden:
            pass  # Bot doesn't have permission to edit channel topic
        await ctx.send("⏹️ I'Have Stopped and cleared queue.")

# Run the bot (replace with your actual token)
if __name__ == '__main__':
    # Run the Flask app in a separate thread
    from threading import Thread
    def run_flask():
        flask_app.run(host='0.0.0.0', port=5000)
    Thread(target=run_flask).start()
    # Start the Discord bot using your token directly
    bot.run("MTM5NzUwMTU1MzgzMjg4NjMwMw.GtCuya.8bOm-rV5bLCfcflWNOOPgxXV_LgNEJ_DiOEKvA")